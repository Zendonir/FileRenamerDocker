"""TheTVDB v4 Anbindung (Serien)."""
import json
import time

import httpx

from .. import cache
from . import http

BASE = "https://api4.thetvdb.com/v4"


class TVDBError(RuntimeError):
    pass


class TVDB:
    def __init__(self, api_key: str, language: str = "de-DE"):
        if not api_key:
            raise TVDBError("Kein TVDB API-Key konfiguriert.")
        self.api_key = api_key
        # TVDB erwartet 3-stellige Sprachcodes.
        self.language = {"de": "deu", "en": "eng", "fr": "fra", "es": "spa", "it": "ita",
                         "nl": "nld", "pt": "por", "pl": "pol"}.get(language.split("-")[0], "eng")
        self._token = None
        self._token_exp = 0.0

    async def _auth(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        r = await http.request(client, "POST", f"{BASE}/login",
                               json={"apikey": self.api_key}, timeout=30)
        if r.status_code == 401:
            raise TVDBError("TVDB: API-Key ungültig.")
        r.raise_for_status()
        self._token = r.json()["data"]["token"]
        self._token_exp = time.time() + 24 * 3600  # Token gilt 30 Tage, wir erneuern täglich.
        return self._token

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
        key = f"tvdb:{self.language}:{path}:" + json.dumps(params or {}, sort_keys=True)
        # Vorab prüfen, damit ein Treffer nicht erst einen Login auslöst.
        hit = cache.get(key)
        if hit is not None:
            return hit
        token = await self._auth(client)
        data = await http.cached_json(
            client, key, f"{BASE}{path}", params=params,
            headers={"Authorization": f"Bearer {token}"}, timeout=30)
        return data

    def _translate(self, item: dict) -> str:
        trans = item.get("translations") or {}
        name_trans = trans.get("nameTranslations") if isinstance(trans, dict) else None
        if isinstance(name_trans, dict) and name_trans.get(self.language):
            return name_trans[self.language]
        return item.get("name") or ""

    async def search_series(self, client, query: str, year: int | None = None) -> list[dict]:
        params = {"query": query, "type": "series", "limit": 12}
        if year:
            params["year"] = str(year)
        data = await self._get(client, "/search", params)
        results = data.get("data") or []
        if not results and year:
            data = await self._get(client, "/search", {"query": query, "type": "series", "limit": 12})
            results = data.get("data") or []
        out = []
        for s in results:
            first_aired = s.get("first_air_time") or s.get("firstAired") or ""
            out.append({
                "provider": "tvdb",
                "id": int(str(s.get("tvdb_id") or s.get("id", "")).replace("series-", "") or 0),
                "title": self._translate(s) or s.get("name") or "",
                "original_title": s.get("name"),
                "year": int(first_aired[:4]) if first_aired[:4].isdigit() else None,
                "overview": (s.get("overviews") or {}).get(self.language) or s.get("overview"),
                "poster": s.get("image_url") or s.get("image"),
                "popularity": 0,
                "original_language": s.get("primary_language"),
                "origin_country": [s["country"]] if s.get("country") else [],
                "genres": s.get("genres") or [],
            })
        return [s for s in out if s["id"]]

    async def series_details(self, client, series_id: int) -> dict:
        data = (await self._get(client, f"/series/{series_id}/extended"))["data"]
        first = data.get("firstAired") or ""
        return {
            "provider": "tvdb",
            "id": series_id,
            "title": data.get("name"),
            "original_title": data.get("name"),
            "year": int(first[:4]) if first[:4].isdigit() else None,
            "genres": [g["name"] for g in data.get("genres", [])],
            "rating": data.get("score"),
            "original_language": data.get("originalLanguage"),
            "origin_country": [data["originalCountry"]] if data.get("originalCountry") else [],
        }

    async def episode(self, client, series_id: int, season: int, episode: int) -> dict | None:
        return await self._lookup(client, series_id, "default",
                                  {"season": season, "episodeNumber": episode, "page": 0})

    async def episode_by_absolute(self, client, series_id: int, absolute: int) -> dict | None:
        """Episode über die absolute Nummer – bei Anime die übliche Zählweise."""
        return await self._lookup(client, series_id, "absolute",
                                  {"episodeNumber": absolute, "page": 0})

    async def _lookup(self, client, series_id: int, order: str, params: dict) -> dict | None:
        try:
            data = await self._get(client, f"/series/{series_id}/episodes/{order}", params)
        except httpx.HTTPStatusError:
            return None
        entries = (data.get("data") or {}).get("episodes") or []
        if not entries:
            return None
        e = entries[0]
        season = e.get("seasonNumber")
        episode = e.get("number")
        title = e.get("name")
        # Übersetzten Episodentitel nachladen, wenn vorhanden.
        try:
            tr = await self._get(client, f"/episodes/{e['id']}/translations/{self.language}")
            if (tr.get("data") or {}).get("name"):
                title = tr["data"]["name"]
        except httpx.HTTPStatusError:
            pass
        return {
            "title": title,
            "air_date": e.get("aired"),
            "absolute": e.get("absoluteNumber"),
            "season": season,
            "episode": episode,
        }
