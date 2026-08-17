"""Abgleich erkannter Dateien mit TMDB/TVDB und Berechnung des Zielpfads."""
import asyncio
import difflib
import re
from pathlib import Path

import httpx

from . import naming, parser
from .providers import TMDB, TVDB


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def confidence(guess_title: str, guess_year: int | None, candidate: dict) -> float:
    """Bewertet einen Treffer anhand von Titelähnlichkeit und Jahr."""
    score = difflib.SequenceMatcher(
        None, _normalize(guess_title), _normalize(candidate.get("title"))
    ).ratio()
    if candidate.get("original_title"):
        score = max(score, difflib.SequenceMatcher(
            None, _normalize(guess_title), _normalize(candidate["original_title"])
        ).ratio())
    if guess_year and candidate.get("year"):
        diff = abs(guess_year - candidate["year"])
        score = score * (1.0 if diff == 0 else 0.9 if diff == 1 else 0.7)
    elif guess_year and not candidate.get("year"):
        score *= 0.95
    return round(min(score, 1.0), 3)


class Matcher:
    def __init__(self, settings: dict):
        self.settings = settings
        self.language = settings.get("language", "de-DE")
        self._tmdb = None
        self._tvdb = None
        self._series_cache: dict = {}
        self._episode_cache: dict = {}

    @property
    def tmdb(self) -> TMDB:
        if self._tmdb is None:
            self._tmdb = TMDB(self.settings.get("tmdb_api_key", ""), self.language)
        return self._tmdb

    @property
    def tvdb(self) -> TVDB:
        if self._tvdb is None:
            self._tvdb = TVDB(self.settings.get("tvdb_api_key", ""), self.language)
        return self._tvdb

    def series_provider(self):
        return self.tvdb if self.settings.get("series_provider") == "tvdb" else self.tmdb

    async def search(self, client, kind: str, query: str, year: int | None,
                     provider: str | None = None) -> list[dict]:
        if kind == "movie":
            return await self.tmdb.search_movie(client, query, year)
        source = self.tvdb if (provider or self.settings.get("series_provider")) == "tvdb" else self.tmdb
        return await source.search_series(client, query, year)

    async def _episode_info(self, client, provider: str, series_id: int, season: int, ep: int):
        key = (provider, series_id, season, ep)
        if key in self._episode_cache:
            return self._episode_cache[key]
        source = self.tvdb if provider == "tvdb" else self.tmdb
        try:
            info = await source.episode(client, series_id, season, ep)
        except (httpx.HTTPError, RuntimeError):
            info = None
        self._episode_cache[key] = info
        return info

    def destination(self, guess: dict, match: dict, src: Path,
                    episodes: list[dict] | None = None) -> str:
        """Berechnet den absoluten Zielpfad für eine Datei."""
        is_series = guess["type"] == "episode"
        info = {
            "name": match.get("title"),
            "year": match.get("year"),
            "provider_id": match.get("id"),
            "imdb_id": match.get("imdb_id"),
            "collection": match.get("collection"),
            "resolution": guess.get("resolution"),
            "video_codec": guess.get("video_codec"),
            "audio_codec": guess.get("audio_codec"),
            "source": guess.get("source"),
            "release_group": guess.get("release_group"),
            "part": guess.get("part"),
            "languages": guess.get("languages"),
            "extension": src.suffix,
        }
        if is_series:
            info["season"] = guess.get("season")
            info["episodes"] = guess.get("episodes")
            info["episode"] = (guess.get("episodes") or [None])[0]
            if episodes:
                titles = [e["title"] for e in episodes if e and e.get("title")]
                info["episode_title"] = " & ".join(titles) if titles else guess.get("episode_title")
                info["absolute"] = episodes[0].get("absolute") if episodes[0] else None
                info["air_date"] = episodes[0].get("air_date") if episodes[0] else None
            else:
                info["episode_title"] = guess.get("episode_title")

        template = self.settings["series_format"] if is_series else self.settings["movie_format"]
        target = self.settings["series_target"] if is_series else self.settings["movie_target"]
        relative = naming.format_path(template, info)
        suffix = src.suffix.lower()
        if guess.get("subtitle_language"):
            suffix = f".{guess['subtitle_language']}{suffix}"
        return str(Path(target) / (relative + suffix))

    async def process_file(self, client, entry: dict) -> dict:
        """Analysiert eine Datei und liefert Vorschlag + Alternativen."""
        src = Path(entry["path"])
        guess = parser.parse(str(src))
        result = {
            "src": str(src),
            "name": src.name,
            "size": entry.get("size"),
            "is_subtitle": entry.get("is_subtitle", False),
            "guess": guess,
            "candidates": [],
            "match": None,
            "confidence": 0.0,
            "dest": None,
            "status": "unmatched",
            "error": None,
        }
        if not guess.get("title"):
            result["error"] = "Kein Titel aus dem Dateinamen erkennbar."
            return result

        try:
            candidates = await self.search(client, guess["type"], guess["title"], guess.get("year"))
        except (httpx.HTTPError, RuntimeError) as exc:
            result["error"] = str(exc)
            return result

        if not candidates:
            result["error"] = "Keine Treffer bei der Datenbank."
            return result

        for candidate in candidates:
            candidate["confidence"] = confidence(guess["title"], guess.get("year"), candidate)
        candidates.sort(key=lambda c: (c["confidence"], c.get("popularity", 0)), reverse=True)
        result["candidates"] = candidates

        best = candidates[0]
        result["match"] = best
        result["confidence"] = best["confidence"]

        episodes = None
        if guess["type"] == "episode" and guess.get("season") is not None:
            episodes = [
                await self._episode_info(client, best["provider"], best["id"], guess["season"], ep)
                for ep in (guess.get("episodes") or [])
            ]

        try:
            result["dest"] = self.destination(guess, best, src, episodes)
        except ValueError as exc:
            result["error"] = str(exc)
            return result

        threshold = float(self.settings.get("min_confidence", 0.7))
        result["status"] = "matched" if best["confidence"] >= threshold else "review"
        return result

    async def process(self, entries: list[dict], concurrency: int = 5) -> list[dict]:
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def run(entry):
                async with semaphore:
                    return await self.process_file(client, entry)
            return list(await asyncio.gather(*(run(e) for e in entries)))
