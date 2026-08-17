"""TheTVDB v4 Anbindung (Serien)."""
import time

import httpx

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
        r = await client.post(f"{BASE}/login", json={"apikey": self.api_key}, timeout=30)
        if r.status_code == 401:
            raise TVDBError("TVDB: API-Key ungültig.")
        r.raise_for_status()
        self._token = r.json()["data"]["token"]
        self._token_exp = time.time() + 24 * 3600  # Token gilt 30 Tage, wir erneuern täglich.
        return self._token

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
        token = await self._auth(client)
        r = await client.get(f"{BASE}{path}", params=params,
                             headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        return r.json()

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
        }

    async def episode(self, client, series_id: int, season: int, episode: int) -> dict | None:
        params = {"season": season, "episodeNumber": episode, "page": 0}
        try:
            data = await self._get(client, f"/series/{series_id}/episodes/default", params)
        except httpx.HTTPStatusError:
            return None
        entries = (data.get("data") or {}).get("episodes") or []
        if not entries:
            return None
        e = entries[0]
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
            "season": e.get("seasonNumber", season),
            "episode": e.get("number", episode),
        }
