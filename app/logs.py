"""Logging: rotierende Datei in /config/logs plus Ringpuffer für das Webinterface."""
import logging
import logging.handlers
from collections import deque

from .config import CONFIG_DIR

LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "renamer.log"
BUFFER_SIZE = 2000

LOGGER = logging.getLogger("renamer")

# Ringpuffer, damit die Log-Ansicht ohne Dateizugriff antworten kann.
_buffer: deque = deque(maxlen=BUFFER_SIZE)
_counter = {"n": 0}


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _counter["n"] += 1
        _buffer.append({
            "id": _counter["n"],
            "time": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })


def setup(level: str = "INFO") -> logging.Logger:
    if LOGGER.handlers:
        return LOGGER
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        LOGGER.addHandler(file_handler)
    except OSError:
        # Kein beschreibbares /config: Konsole und Puffer reichen aus.
        pass

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.setLevel(getattr(logging, level.upper(), logging.INFO))
    LOGGER.addHandler(stream)

    buffer_handler = BufferHandler()
    buffer_handler.setLevel(logging.DEBUG)
    LOGGER.addHandler(buffer_handler)
    return LOGGER


def get(name: str) -> logging.Logger:
    return LOGGER.getChild(name)


def entries(level: str | None = None, query: str | None = None,
            limit: int = 300, after_id: int | None = None) -> dict:
    """Liefert Log-Zeilen, neueste zuerst, optional gefiltert."""
    order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    minimum = order.get((level or "").upper(), 0)
    needle = (query or "").lower()

    items = [
        e for e in _buffer
        if order.get(e["level"], 0) >= minimum
        and (not needle or needle in e["message"].lower())
        and (after_id is None or e["id"] > after_id)
    ]
    items.reverse()
    return {
        "entries": items[:limit],
        "total": len(_buffer),
        "last_id": _counter["n"],
        "file": str(LOG_FILE),
    }


def tail_file(lines: int = 2000) -> str:
    """Liest das Ende der Logdatei — überlebt im Gegensatz zum Puffer einen Neustart."""
    if not LOG_FILE.exists():
        return ""
    try:
        with LOG_FILE.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=lines))
    except OSError as exc:
        return f"Logdatei nicht lesbar: {exc}"
