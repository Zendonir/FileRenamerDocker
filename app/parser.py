"""Dateinamen-Analyse in Stufen.

Reihenfolge der Erkennung:
  1. der Dateiname selbst,
  2. bei nichtssagendem Dateinamen der Ordnername,
  3. zuletzt die im Container eingebetteten Metadaten.

Fehlende Einzelangaben (Staffel, Episode, Jahr, Episodentitel) werden am Ende
aus den Metadaten ergänzt, egal welche Stufe den Titel geliefert hat.
"""
import re
from pathlib import Path

from guessit import guessit

from . import metadata

# Ordnernamen, die keinen Serientitel tragen und deshalb übersprungen werden.
STRUCTURE_DIRS = re.compile(
    r"^(season|staffel|series|s)\s*\d+$|^(specials?|extras?|bonus|subs?|untertitel|"
    r"sample|disc|disk|cd|dvd|bd)\s*\d*$|^\d{1,3}$",
    re.IGNORECASE,
)

# Titel, die zwar erkannt werden, aber nichts aussagen.
GENERIC_TITLES = {
    "video", "videos", "movie", "movies", "film", "filme", "episode", "folge",
    "untitled", "unknown", "new", "output", "index", "title", "default", "clip",
    "stream", "track", "media", "temp", "download", "encode", "rip", "full",
    "part", "teil", "disc", "disk", "main", "playback", "vts", "vob", "avseq",
}

# Staffelnummer aus einem Strukturordner ("Season 03", "Staffel 2", "S03").
SEASON_DIR = re.compile(r"^(?:season|staffel|series|s)\s*[_.-]?\s*(\d{1,3})$", re.IGNORECASE)

# Dateinamen ohne Titel, deren Zahl trotzdem verlässlich die Episode ist.
EPISODE_ONLY_NAME = re.compile(
    r"^(?:"
    r"s\s*\d{1,2}\s*[ex]\s*\d{1,3}"      # S01E02
    r"|\d{1,2}\s*x\s*\d{1,3}"            # 1x02
    r"|(?:e|ep|episode|folge|teil)\s*\d{1,4}"
    r"|\d{1,4}(?:\s*v\d)?"               # 03, 03v2
    r")$",
    re.IGNORECASE,
)

# Sammel- und Ablageordner: tragen nie einen Titel, es wird weiter nach oben gesucht.
GENERIC_FOLDERS = GENERIC_TITLES | {
    "downloads", "download", "incoming", "complete", "completed", "fertig",
    "torrents", "torrent", "usenet", "nzb", "seedbox", "watch", "ablage",
    "plex", "jellyfin", "emby", "kodi", "medien", "mediathek",
    "filme", "serien", "movies", "series", "shows", "tv", "tvshows", "anime",
    "kinder", "dokus", "dokumentationen", "neu", "unsortiert", "sonstiges",
    "misc", "tmp", "sortieren", "input", "output", "quelle", "ziel",
}

MEANINGLESS = re.compile(
    r"^[\W_]*$"                      # nur Sonderzeichen
    r"|^[a-f0-9]{8,}$"               # Hash-artige Namen
    r"|^vts[\W_]*\d*[\W_]*\d*$"      # DVD-Rips: VTS_01_1
    r"|^(video|title|movie|episode|folge|track|part|teil)[\W_]*\d*$",
    re.IGNORECASE,
)


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _join(value):
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value is not None else None


def is_meaningful(title: str | None) -> bool:
    """Trägt dieser Titel überhaupt Information?"""
    if not title:
        return False
    cleaned = re.sub(r"[\W_]+", " ", title).strip()
    if len(cleaned) < 2:
        return False
    if cleaned.isdigit():
        return False
    if cleaned.lower() in GENERIC_TITLES:
        return False
    return not MEANINGLESS.match(title.strip())


def _normalize(guess: dict) -> dict:
    """Bringt eine guessit-Ausgabe in unsere Struktur."""
    seasons = guess.get("season")
    episodes = guess.get("episode")
    if isinstance(seasons, list):
        seasons = seasons[0]
    episode_list = episodes if isinstance(episodes, list) else ([episodes] if episodes is not None else [])

    kind = guess.get("type", "movie")
    if episode_list or seasons is not None:
        kind = "episode"

    languages = guess.get("language")
    return {
        "type": "episode" if kind == "episode" else "movie",
        "title": guess.get("title"),
        "year": guess.get("year"),
        "season": seasons,
        "episodes": episode_list,
        "episode_title": guess.get("episode_title"),
        "part": _first(guess.get("part")) or _first(guess.get("cd")),
        "source": _join(guess.get("source")),
        "resolution": guess.get("screen_size"),
        "video_codec": _join(guess.get("video_codec")),
        "audio_codec": _join(guess.get("audio_codec")),
        "release_group": guess.get("release_group"),
        "languages": [str(x) for x in languages] if isinstance(languages, list)
        else ([str(languages)] if languages else []),
        "subtitle_language": str(guess["subtitle_language"]) if guess.get("subtitle_language") else None,
        "container": guess.get("container"),
    }


def carries_episode_number(stem: str) -> bool:
    """Ist die Zahl in einem titellosen Dateinamen wirklich die Episodennummer?

    "03.mkv" und "S01E02.mkv" ja – "VTS_01_1.mkv" oder ein Hash-Name nein, dort
    sind die Ziffern Container-Kram und keine Episode.
    """
    normalized = re.sub(r"[\W_]+", " ", stem).strip()
    return bool(EPISODE_ONLY_NAME.match(normalized))


def season_from_path(path: Path, roots: list[str] | None = None) -> int | None:
    """Staffelnummer aus einem übergeordneten Staffelordner."""
    stop = {Path(r).resolve() for r in (roots or [])}
    for folder in path.resolve().parents:
        if folder in stop or folder == folder.parent:
            return None
        match = SEASON_DIR.match(folder.name.strip())
        if match:
            return int(match.group(1))
        if not STRUCTURE_DIRS.match(folder.name.strip()):
            return None
    return None


def title_folder(path: Path, roots: list[str] | None = None) -> Path | None:
    """Nächster Ordner oberhalb der Datei, der einen echten Titel tragen kann.

    Staffel-, Disc- und Extras-Ordner werden übersprungen; die Quellordner selbst
    gelten nie als Titel, sonst hieße jeder Film nach dem Downloadverzeichnis.
    """
    stop = {Path(r).resolve() for r in (roots or [])}
    for folder in path.resolve().parents:
        if folder in stop or folder == folder.parent:
            return None
        name = folder.name.strip()
        if STRUCTURE_DIRS.match(name) or name.lower() in GENERIC_FOLDERS:
            continue        # Staffel- oder Sammelordner: eine Ebene höher weitersuchen
        return folder
    return None


def parse(path: str, roots: list[str] | None = None, use_folder: bool = True,
          use_metadata: bool = True) -> dict:
    """Analysiert eine Datei stufenweise und vermerkt die genutzte Quelle."""
    file_path = Path(path)

    # Stufe 1: der Dateiname.
    guess = _normalize(dict(guessit(file_path.name)))
    guess["title_source"] = "filename"
    guess["title_candidates"] = {}
    if guess.get("title"):
        guess["title_candidates"]["filename"] = guess["title"]

    # Aus einem nichtssagenden Dateinamen dürfen keine Zahlen als Episode
    # durchrutschen – "VTS_01_1" ist kein Episode 1.
    if not is_meaningful(guess.get("title")) and not carries_episode_number(file_path.stem):
        guess["episodes"] = []
        guess["season"] = None
        guess["type"] = "movie"

    # Stufe 2: der Ordnername, wenn der Dateiname nichts hergibt.
    if use_folder and not is_meaningful(guess.get("title")):
        # Die Staffel steht oft im übersprungenen Strukturordner ("Season 03").
        if guess.get("season") is None:
            season = season_from_path(file_path, roots)
            if season is not None:
                guess["season"] = season
                guess["type"] = "episode"
        folder = title_folder(file_path, roots)
        if folder is not None:
            # Nur der Ordnername – sonst schleppt guessit die Zahlen des
            # verworfenen Dateinamens wieder als Episode ein.
            from_folder = _normalize(dict(guessit(folder.name)))
            candidate = from_folder.get("title")
            guess["title_candidates"]["folder"] = candidate
            if is_meaningful(candidate):
                guess["title"] = candidate
                guess["title_source"] = "folder"
                # Der Ordner trägt oft auch Jahr und Staffel – nur Lücken füllen.
                for key in ("year", "season"):
                    if guess.get(key) is None and from_folder.get(key) is not None:
                        guess[key] = from_folder[key]
                if guess.get("season") is not None:
                    guess["type"] = "episode"

    # Stufe 3: eingebettete Metadaten – als letzte Titelquelle und als Lückenfüller.
    if use_metadata:
        tags = metadata.read(file_path)
        if tags:
            embedded = tags.get("show") or tags.get("title")
            guess["title_candidates"]["metadata"] = embedded
            if not is_meaningful(guess.get("title")) and is_meaningful(embedded):
                guess["title"] = embedded
                guess["title_source"] = "metadata"
            if guess.get("season") is None and tags.get("season"):
                guess["season"] = tags["season"]
            if not guess.get("episodes") and tags.get("episode"):
                guess["episodes"] = [tags["episode"]]
            if guess.get("year") is None and tags.get("year"):
                guess["year"] = tags["year"]
            if not guess.get("episode_title") and tags.get("show") and tags.get("title"):
                guess["episode_title"] = tags["title"]
            if tags.get("show") or guess.get("season") is not None or guess.get("episodes"):
                guess["type"] = "episode"

    if not is_meaningful(guess.get("title")):
        guess["title"] = None
    return guess
