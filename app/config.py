"""Persistente Konfiguration (JSON in /config)."""
import json
import os
import threading
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
CONFIG_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "history.json"

DEFAULTS = {
    "tmdb_api_key": os.environ.get("TMDB_API_KEY", ""),
    "tvdb_api_key": os.environ.get("TVDB_API_KEY", ""),
    "language": os.environ.get("LANGUAGE", "de-DE"),
    "series_provider": "tvdb",          # tvdb | tmdb
    "source_dirs": ["/data/input"],
    "movie_target": "/data/movies",
    "series_target": "/data/series",
    "anime_target": "/data/anime",
    "movie_format": "{n} ({y})/{n} ({y}){' CD'+pi}{' '+vf}",
    "series_format": "{n}/Season {s.pad(2)}/{n} - {s00e00} - {t}",
    "anime_format": "{n}/{n} - {abs.pad(3)|s00e00} - {t}",
    "anime_detection": "auto",           # auto | off
    "anime_keywords": ["anime", "subsplease", "erai-raws", "horriblesubs", "judas", "ember"],
    "anime_provider": "tvdb",            # Datenquelle speziell für Anime
    "anime_absolute": True,              # absolute Episodennummer bevorzugen
    "action": "move",                    # move | copy | hardlink | symlink | test
    "min_confidence": 0.7,
    "extensions": [
        ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts",
        ".mpg", ".mpeg", ".flv", ".webm", ".iso",
    ],
    "subtitle_extensions": [".srt", ".sub", ".ass", ".ssa", ".idx", ".sup"],
    "min_size_mb": 50,
    "use_folder_names": True,        # Ordnername, wenn der Dateiname nichts hergibt
    "use_embedded_metadata": True,   # Container-Tags als letzte Quelle und Lückenfüller
    "clean_empty_dirs": True,
    "overwrite": False,

    # Abgleich mit der bestehenden Bibliothek
    "check_library": True,
    "duplicate_action": "skip",      # skip | replace_if_better | always

    # Automatikbetrieb
    "auto_enabled": False,
    "auto_interval_minutes": 60,
    "auto_min_confidence": 0.9,      # nur sehr sichere Treffer laufen unbeaufsichtigt
    "auto_categories": ["movie", "series", "anime"],
    "auto_quiet_seconds": 120,       # Datei muss so lange unverändert sein

    # Benachrichtigung der Medienserver nach getaner Arbeit
    "webhook_urls": [],
    "plex_url": "",
    "plex_token": "",
    "jellyfin_url": "",
    "jellyfin_token": "",

    # Begleitdateien
    "write_nfo": False,
    "download_artwork": False,

    # Dateinamen
    "ascii_only": False,             # Umlaute umschreiben (ae, oe, ue, ss)
    "windows_safe": True,            # Punkte/Leerzeichen am Ende vermeiden

    # Zugang
    "auth_enabled": False,
    "auth_user": "admin",
    "auth_password_hash": "",
}

_lock = threading.Lock()


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    _ensure_dir()
    data = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            data.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except (OSError, ValueError):
            pass
    # Env-Variablen gewinnen nur, wenn in der Datei nichts gesetzt ist.
    for key in ("tmdb_api_key", "tvdb_api_key"):
        if not data.get(key) and DEFAULTS[key]:
            data[key] = DEFAULTS[key]
    return data


def save(patch: dict) -> dict:
    with _lock:
        data = load()
        for key, value in patch.items():
            if key in DEFAULTS:
                data[key] = value
        _ensure_dir()
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        # Die Datei enthält API-Keys und ggf. einen Passwort-Hash.
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass
        return data


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            return []
    return []


def append_history(entries: list) -> None:
    with _lock:
        history = load_history()
        history = (entries + history)[:2000]
        _ensure_dir()
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), "utf-8")


def replace_history(history: list) -> None:
    with _lock:
        _ensure_dir()
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), "utf-8")
