"""Dauerhafter Antwort-Cache (SQLite) für Datenbankabfragen.

Ein zweiter Scan derselben Serie kommt damit ohne einen einzigen API-Aufruf aus.
"""
import json
import sqlite3
import threading
import time

from .config import CONFIG_DIR

DB_FILE = CONFIG_DIR / "cache.sqlite"
DEFAULT_TTL = 14 * 24 * 3600      # Serien- und Filmdaten ändern sich selten.

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS entries ("
            " key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL)"
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON entries(created)")
        _conn.commit()
    return _conn


def get(key: str, ttl: int = DEFAULT_TTL):
    """Liefert den Wert oder None, wenn er fehlt oder zu alt ist."""
    try:
        with _lock:
            row = _connect().execute(
                "SELECT value, created FROM entries WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        if time.time() - row[1] > ttl:
            return None
        return json.loads(row[0])
    except (sqlite3.Error, ValueError):
        return None


def put(key: str, value) -> None:
    try:
        with _lock:
            conn = _connect()
            conn.execute(
                "INSERT OR REPLACE INTO entries (key, value, created) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), time.time()),
            )
            conn.commit()
    except (sqlite3.Error, TypeError, ValueError):
        pass       # Ein defekter Cache darf den Scan nie aufhalten.


def clear() -> int:
    """Leert den Cache und liefert die Anzahl entfernter Einträge."""
    try:
        with _lock:
            conn = _connect()
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            conn.execute("DELETE FROM entries")
            conn.commit()
            return count
    except sqlite3.Error:
        return 0


def stats() -> dict:
    try:
        with _lock:
            conn = _connect()
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            oldest = conn.execute("SELECT MIN(created) FROM entries").fetchone()[0]
        return {"entries": count, "oldest": oldest, "file": str(DB_FILE)}
    except sqlite3.Error:
        return {"entries": 0, "oldest": None, "file": str(DB_FILE)}
