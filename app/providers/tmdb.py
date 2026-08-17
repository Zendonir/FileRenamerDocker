"""TMDB-Anbindung (Filme + Serien)."""
import json

import httpx

from . import http

BASE = "https://api.themoviedb.org/3"


class TMDBError(RuntimeError):
    pass


class TMDB:
    def __init__(self, api_key: str, language: str = "de-DE"):
        if not api_key:
            raise TMDBError("Kein TMDB API-Key konfiguriert.")
        self.api_key = api_key
        self.language = language
        # v4 Read-Access-Token (JWT) und klassischer v3-Key werden beide unterstützt.
        self._bearer = api_key.count(".") == 2 and len(api_key) > 100

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self._bearer else {}

    def _params(self, extra: dict | None = None) -> dict:
        params = {"language": self.language}
        if not self._bearer:
            params["api_key"] = self.api_key
        if extra:
            params.update(extra)
        return params

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
        full = self._params(params)
        # Der Key gehört nicht in den Cache-Schlüssel, die Sprache schon.
        key = "tmdb:" + path + ":" + json.dumps(
            {k: v for k, v in full.items() if k != "api_key"}, sort_keys=True)
        try:
            return await http.cached_json(
                client, key, f"{BASE}{path}",
                params=full, headers=self._headers(), timeout=30)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise TMDBError("TMDB: API-Key ungültig.") from exc
            raise

    async def search_movie(self, client, query: str, year: int | None = None) -> list[dict]:
        params = {"query": query, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        data = await self._get(client, "/search/movie", params)
        results = data.get("results") or []
        if not results and year:
            data = await self._get(client, "/search/movie", {"query": query, "include_adult": "false"})
            results = data.get("results") or []
        return [
            {
                "provider": "tmdb",
                "id": m["id"],
                "title": m.get("title") or m.get("original_title") or "",
                "original_title": m.get("original_title"),
                "year": int(m["release_date"][:4]) if m.get("release_date") else None,
                "overview": m.get("overview"),
                "poster": f"https://image.tmdb.org/t/p/w185{m['poster_path']}" if m.get("poster_path") else None,
                "popularity": m.get("popularity", 0),
            }
            for m in results[:12]
        ]

    async def search_series(self, client, query: str, year: int | None = None) -> list[dict]:
        params = {"query": query}
        if year:
            params["first_air_date_year"] = str(year)
        data = await self._get(client, "/search/tv", params)
        results = data.get("results") or []
        if not results and year:
            data = await self._get(client, "/search/tv", {"query": query})
            results = data.get("results") or []
        return [
            {
                "provider": "tmdb",
                "id": s["id"],
                "title": s.get("name") or s.get("original_name") or "",
                "original_title": s.get("original_name"),
                "year": int(s["first_air_date"][:4]) if s.get("first_air_date") else None,
                "overview": s.get("overview"),
                "poster": f"https://image.tmdb.org/t/p/w185{s['poster_path']}" if s.get("poster_path") else None,
                "popularity": s.get("popularity", 0),
                "original_language": s.get("original_language"),
                "genre_ids": s.get("genre_ids", []),
                "origin_country": s.get("origin_country", []),
            }
            for s in results[:12]
        ]

    async def movie_details(self, client, movie_id: int) -> dict:
        m = await self._get(client, f"/movie/{movie_id}")
        return {
            "provider": "tmdb",
            "id": m["id"],
            "title": m.get("title") or m.get("original_title"),
            "original_title": m.get("original_title"),
            "year": int(m["release_date"][:4]) if m.get("release_date") else None,
            "imdb_id": m.get("imdb_id"),
            "collection": (m.get("belongs_to_collection") or {}).get("name"),
            "genres": [g["name"] for g in m.get("genres", [])],
            "rating": m.get("vote_average"),
        }

    async def episode(self, client, series_id: int, season: int, episode: int) -> dict | None:
        try:
            e = await self._get(client, f"/tv/{series_id}/season/{season}/episode/{episode}")
        except httpx.HTTPStatusError:
            return None
        return {
            "title": e.get("name"),
            "air_date": e.get("air_date"),
            "absolute": None,
            "season": e.get("season_number", season),
            "episode": e.get("episode_number", episode),
        }

    async def series_details(self, client, series_id: int) -> dict:
        s = await self._get(client, f"/tv/{series_id}")
        return {
            "provider": "tmdb",
            "id": s["id"],
            "title": s.get("name") or s.get("original_name"),
            "original_title": s.get("original_name"),
            "year": int(s["first_air_date"][:4]) if s.get("first_air_date") else None,
            "genres": [g["name"] for g in s.get("genres", [])],
            "rating": s.get("vote_average"),
            "original_language": s.get("original_language"),
            "origin_country": s.get("origin_country", []),
        }
