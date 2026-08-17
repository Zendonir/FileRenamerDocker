"""Abgleich erkannter Dateien mit TMDB/TVDB und Berechnung des Zielpfads."""
import asyncio
import difflib
import re
from pathlib import Path

import httpx

from . import logs, naming, parser
from .providers import TMDB, TVDB

log = logs.get("matcher")


TMDB_ANIMATION_GENRE = 16
ANIME_GENRE_NAMES = {"anime", "animation"}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def detect_anime(path: str, guess: dict, candidate: dict | None, settings: dict) -> bool:
    """Heuristik: Anime oder normale Serie?

    Ausschlaggebend ist der Pfad (eindeutiger Nutzerwille), danach typische
    Fansub-Merkmale und schließlich japanische Herkunft plus Animations-Genre.
    """
    if settings.get("anime_detection") == "off":
        return False

    haystack = path.lower()
    for keyword in settings.get("anime_keywords", []):
        if keyword.lower() in haystack:
            return True

    if candidate:
        language = (candidate.get("original_language") or "").lower()
        countries = {c.upper() for c in candidate.get("origin_country") or []}
        genres = {str(g).lower() for g in candidate.get("genres") or []}
        genre_ids = set(candidate.get("genre_ids") or [])
        japanese = language in {"ja", "jpn"} or bool(countries & {"JP", "JPN"})
        animated = bool(genres & ANIME_GENRE_NAMES) or TMDB_ANIMATION_GENRE in genre_ids
        if japanese and (animated or "anime" in genres):
            return True

    return False


def category_of(path: str, guess: dict, candidate: dict | None, settings: dict) -> str:
    """Liefert 'movie', 'series' oder 'anime'."""
    if guess.get("type") != "episode":
        return "movie"
    return "anime" if detect_anime(path, guess, candidate, settings) else "series"


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

    def provider_for(self, category: str) -> str:
        """Welche Datenbank ist für diese Kategorie zuständig?"""
        if category == "movie":
            return "tmdb"
        key = "anime_provider" if category == "anime" else "series_provider"
        return self.settings.get(key, "tvdb")

    async def search(self, client, kind: str, query: str, year: int | None,
                     provider: str | None = None) -> list[dict]:
        category = "movie" if kind == "movie" else ("anime" if kind == "anime" else "series")
        if category == "movie":
            return await self.tmdb.search_movie(client, query, year)
        name = provider or self.provider_for(category)
        source = self.tvdb if name == "tvdb" else self.tmdb
        return await source.search_series(client, query, year)

    async def _episode_info(self, client, provider: str, series_id: int,
                            season: int | None, ep: int, absolute: bool = False):
        key = (provider, series_id, season, ep, absolute)
        if key in self._episode_cache:
            return self._episode_cache[key]
        source = self.tvdb if provider == "tvdb" else self.tmdb
        try:
            if absolute and provider == "tvdb":
                info = await source.episode_by_absolute(client, series_id, ep)
            elif season is None:
                # Ohne Staffelangabe bleibt nur Staffel 1 als Annahme.
                info = await source.episode(client, series_id, 1, ep)
            else:
                info = await source.episode(client, series_id, season, ep)
        except (httpx.HTTPError, RuntimeError):
            info = None
        self._episode_cache[key] = info
        return info

    async def episodes_for(self, client, category: str, provider: str, series_id: int,
                           guess: dict) -> list[dict]:
        """Lädt die Episodendaten passend zur Zählweise der Kategorie."""
        numbers = guess.get("episodes") or []
        if not numbers:
            return []
        # Anime ohne Staffelangabe werden absolut gezählt.
        absolute = (category == "anime" and self.settings.get("anime_absolute", True)
                    and guess.get("season") is None)
        found = [await self._episode_info(client, provider, series_id,
                                          guess.get("season"), ep, absolute)
                 for ep in numbers]
        if absolute and not any(found):
            # Kein Treffer über die absolute Liste: normale Zählung als Rückfall.
            found = [await self._episode_info(client, provider, series_id, 1, ep)
                     for ep in numbers]
        return found

    def destination(self, guess: dict, match: dict, src: Path,
                    episodes: list[dict] | None = None, category: str = "movie") -> str:
        """Berechnet den absoluten Zielpfad anhand des Schemas der Kategorie."""
        is_series = category in ("series", "anime")
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
                # Bei absoluter Zählung liefert die Datenbank Staffel und Episode nach.
                if guess.get("season") is None and episodes[0]:
                    info["season"] = episodes[0].get("season")
                    resolved = [e.get("episode") for e in episodes if e and e.get("episode")]
                    if resolved:
                        info["episodes"] = resolved
                        info["episode"] = resolved[0]
            else:
                info["episode_title"] = guess.get("episode_title")
            if info.get("absolute") is None and guess.get("season") is None:
                # Ohne Datenbanktreffer bleibt die Nummer aus dem Dateinamen.
                info["absolute"] = (guess.get("episodes") or [None])[0]

        template = self.settings[f"{category}_format"]
        target = self.settings[f"{category}_target"]
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
            "category": "movie",
            "error": None,
        }
        if not guess.get("title"):
            result["error"] = "Kein Titel aus dem Dateinamen erkennbar."
            log.warning("Nicht analysierbar: %s", src)
            return result

        # Erste Einschätzung noch ohne Datenbank – sie bestimmt, welche Quelle gefragt wird.
        category = category_of(str(src), guess, None, self.settings)
        result["category"] = category

        try:
            candidates = await self.search(client, category, guess["title"], guess.get("year"))
        except (httpx.HTTPError, RuntimeError) as exc:
            result["error"] = str(exc)
            log.error("Datenbankabfrage fehlgeschlagen für '%s': %s", guess["title"], exc)
            return result

        if not candidates:
            result["error"] = "Keine Treffer bei der Datenbank."
            log.warning("Keine Treffer für '%s' (%s)", guess["title"], src.name)
            return result

        for candidate in candidates:
            candidate["confidence"] = confidence(guess["title"], guess.get("year"), candidate)
        candidates.sort(key=lambda c: (c["confidence"], c.get("popularity", 0)), reverse=True)
        result["candidates"] = candidates

        best = candidates[0]
        result["match"] = best
        result["confidence"] = best["confidence"]

        # Zweite Einschätzung: jetzt mit Sprache und Genre aus der Datenbank.
        if category != "movie":
            category = category_of(str(src), guess, best, self.settings)
            result["category"] = category

        episodes = None
        if category != "movie":
            episodes = await self.episodes_for(client, category, best["provider"], best["id"], guess)

        try:
            result["dest"] = self.destination(guess, best, src, episodes, category)
        except ValueError as exc:
            result["error"] = str(exc)
            log.error("Zielpfad für %s nicht berechenbar: %s", src.name, exc)
            return result

        threshold = float(self.settings.get("min_confidence", 0.7))
        result["status"] = "matched" if best["confidence"] >= threshold else "review"
        log.info("%s [%s]: '%s' -> %s (%s, %d %%)", src.name, category, guess["title"],
                 best["title"], best["provider"].upper(), round(best["confidence"] * 100))
        if result["status"] == "review":
            log.warning("Unsicherer Treffer, bitte prüfen: %s", src.name)
        return result

    async def process(self, entries: list[dict], concurrency: int = 5) -> list[dict]:
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def run(entry):
                async with semaphore:
                    return await self.process_file(client, entry)
            return list(await asyncio.gather(*(run(e) for e in entries)))
