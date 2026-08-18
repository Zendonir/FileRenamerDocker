"""Abgleich erkannter Dateien mit TMDB/TVDB und Berechnung des Zielpfads."""
import asyncio
import difflib
import re
from pathlib import Path

import httpx

from . import library, logs, naming, parser
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


def _common_prefix(a: str, b: str) -> int:
    length = 0
    for x, y in zip(a, b, strict=False):   # kürzere Zeichenkette begrenzt
        if x != y:
            break
        length += 1
    return length


def _subtitle_score(sub_stem: str, sub_guess: dict, video_stem: str, video_guess: dict):
    """Wie gut passt ein Untertitel zu einer Videodatei? None heißt: gar nicht.

    Dateinamen weichen fast immer ab ("...German.de.srt" gegen
    "...German.1080p.mkv"), deshalb zählt zuerst die erkannte Episode.
    """
    same_episode = bool(
        sub_guess.get("episodes")
        and sub_guess.get("episodes") == video_guess.get("episodes")
        and sub_guess.get("season") == video_guess.get("season")
    )
    same_title = bool(
        sub_guess.get("title") and video_guess.get("title")
        and _normalize(sub_guess["title"]) == _normalize(video_guess["title"])
    )
    prefix = _common_prefix(sub_stem, video_stem)

    if same_episode and same_title:
        return (3, prefix)
    if same_episode or (same_title and not video_guess.get("episodes")):
        return (2, prefix)
    if sub_stem == video_stem or sub_stem.startswith(video_stem):
        return (1, prefix)
    # Reine Namensähnlichkeit reicht nur, wenn sie deutlich ist.
    if prefix >= max(6, len(video_stem) // 2):
        return (0, prefix)
    return None


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
        relative = naming.format_path(
            template, info,
            ascii_only=self.settings.get("ascii_only", False),
            windows_safe=self.settings.get("windows_safe", True),
        )
        suffix = src.suffix.lower()
        if guess.get("subtitle_language"):
            suffix = f".{guess['subtitle_language']}{suffix}"
        return str(Path(target) / (relative + suffix))

    async def process_file(self, client, entry: dict) -> dict:
        """Analysiert eine Datei und liefert Vorschlag + Alternativen."""
        src = Path(entry["path"])
        guess = parser.parse(
            str(src),
            roots=self.settings.get("source_dirs"),
            use_folder=self.settings.get("use_folder_names", True),
            use_metadata=self.settings.get("use_embedded_metadata", True),
        )
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
            "title_source": guess.get("title_source"),
            "thumb_url": None,
            "error": None,
        }
        if not guess.get("title"):
            result["error"] = "Kein Titel erkennbar – weder aus Dateiname, Ordner noch Metadaten."
            log.warning("Nicht analysierbar: %s", src)
            return result
        if guess.get("title_source") != "filename":
            log.info("Titel für %s stammt aus %s: '%s'", src.name,
                     {"folder": "dem Ordnernamen", "metadata": "den Metadaten"}
                     .get(guess["title_source"], guess["title_source"]), guess["title"])

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
            if episodes and episodes[0]:
                result["thumb_url"] = episodes[0].get("thumb_url")

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
        self.check_library(result)
        return result

    # --- Abgleich mit der bestehenden Bibliothek -----------------------------

    def check_library(self, item: dict) -> None:
        """Vermerkt, ob am Ziel bereits eine Fassung liegt und wie sie sich vergleicht."""
        item["existing"] = None
        if not item.get("dest") or not self.settings.get("check_library", True):
            return
        extensions = {e.lower() for e in self.settings.get("extensions", [])}
        found = library.find_existing(item["dest"], extensions)
        if not found:
            return

        current = found[0]
        existing_guess = parser.parse(str(current), use_folder=False, use_metadata=False)
        verdict = library.compare(item["guess"], item.get("size") or 0,
                                  item["src"], current, existing_guess)
        item["existing"] = {
            "path": str(current),
            "verdict": verdict,
            "quality": library.describe(existing_guess),
            "new_quality": library.describe(item["guess"]),
        }
        if verdict == "better":
            log.info("%s ist besser als die vorhandene Fassung (%s vs. %s).",
                     Path(item["src"]).name, item["existing"]["new_quality"],
                     item["existing"]["quality"])
        else:
            log.info("%s liegt bereits in der Bibliothek (%s, vorhanden: %s).",
                     Path(item["src"]).name, verdict, item["existing"]["quality"])

    # --- Untertitel an ihre Videodatei koppeln ------------------------------

    @staticmethod
    def attach_subtitles(items: list[dict]) -> None:
        """Untertitel erben Treffer und Ziel der gleichnamigen Videodatei.

        Das spart nicht nur Abfragen – es verhindert vor allem, dass ein
        Untertitel bei einer anderen Serie landet als sein Video.
        """
        videos = {}
        for item in items:
            if item.get("is_subtitle") or not item.get("dest"):
                continue
            src = Path(item["src"])
            videos.setdefault(src.parent, []).append((src.stem.lower(), item))

        for item in items:
            if not item.get("is_subtitle"):
                continue
            src = Path(item["src"])
            stem = src.stem.lower()
            best_video, best_score = None, None
            for video_stem, video in videos.get(src.parent, []):
                score = _subtitle_score(stem, item.get("guess") or {},
                                        video_stem, video.get("guess") or {})
                if score and (best_score is None or score > best_score):
                    best_video, best_score = video, score
            if not best_video:
                continue

            video = best_video
            language = item["guess"].get("subtitle_language")
            suffix = f".{language}{src.suffix.lower()}" if language else src.suffix.lower()
            item["match"] = video["match"]
            item["category"] = video["category"]
            item["confidence"] = video["confidence"]
            item["status"] = video["status"]
            item["error"] = None
            item["linked_to"] = video["src"]
            item["dest"] = str(Path(video["dest"]).with_suffix("")) + suffix
            log.info("Untertitel %s folgt der Videodatei %s.", src.name, Path(video["src"]).name)

    async def process(self, entries: list[dict], concurrency: int = 5,
                      on_progress=None, is_cancelled=None) -> list[dict]:
        """Erst die Videos, dann die Untertitel – die hängen sich meist einfach an."""
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def run(entry):
                async with semaphore:
                    if is_cancelled and is_cancelled():
                        return self.placeholder(entry)
                    item = await self.process_file(client, entry)
                    if on_progress:
                        on_progress(item)
                    return item

            videos = [e for e in entries if not e.get("is_subtitle")]
            subtitles = [e for e in entries if e.get("is_subtitle")]
            items = list(await asyncio.gather(*(run(e) for e in videos)))

            pending = [self.placeholder(e) for e in subtitles]
            items.extend(pending)
            self.attach_subtitles(items)

            # Nur Untertitel ohne passendes Video brauchen eine eigene Abfrage.
            orphans = [e for e in subtitles
                       if not next(i for i in pending if i["src"] == e["path"]).get("linked_to")]
            if orphans:
                resolved = await asyncio.gather(*(run(e) for e in orphans))
                by_src = {i["src"]: i for i in resolved}
                items = [by_src.get(i["src"], i) for i in items]
        return items

    def placeholder(self, entry: dict) -> dict:
        """Eintrag ohne Datenbankabfrage – für Untertitel und abgebrochene Läufe."""
        src = Path(entry["path"])
        is_subtitle = entry.get("is_subtitle", False)
        return {
            "src": str(src), "name": src.name, "size": entry.get("size"),
            "is_subtitle": is_subtitle, "guess": parser.parse(
                str(src),
                roots=self.settings.get("source_dirs"),
                use_folder=self.settings.get("use_folder_names", True),
                use_metadata=False),
            "candidates": [], "match": None, "confidence": 0.0, "dest": None,
            "status": "unmatched", "category": "movie", "title_source": None,
            "existing": None, "linked_to": None,
            "error": "Kein zugehöriges Video gefunden." if is_subtitle else "Abgebrochen.",
        }
