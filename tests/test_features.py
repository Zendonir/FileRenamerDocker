import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import auth, cache, renamer, scheduler
from app.matcher import Matcher
from app.providers import http as provider_http

SETTINGS = {"movie_format": "{n} ({y})", "series_format": "{n}/{s00e00}",
            "anime_format": "{n}/{abs}", "movie_target": "/m", "series_target": "/s",
            "anime_target": "/a", "extensions": [".mkv"], "check_library": False}


# --- Untertitel folgen ihrem Video ------------------------------------------

def video(src, dest, **kw):
    return {"src": src, "name": Path(src).name, "is_subtitle": False, "dest": dest,
            "match": {"provider": "tvdb", "id": 1, "title": "Dark"}, "category": "series",
            "confidence": 1.0, "status": "matched", "guess": {}, **kw}


def subtitle(src, language=None):
    return {"src": src, "name": Path(src).name, "is_subtitle": True, "dest": None,
            "match": None, "category": "movie", "confidence": 0.0, "status": "unmatched",
            "guess": {"subtitle_language": language}, "linked_to": None,
            "error": "Kein zugehöriges Video gefunden."}


def test_subtitle_inherits_video_match():
    items = [
        video("/in/Dark.S02E05.mkv", "/s/Dark/Season 02/Dark - S02E05 - Lost.mkv"),
        subtitle("/in/Dark.S02E05.de.srt", "de"),
    ]
    Matcher.attach_subtitles(items)
    sub = items[1]
    assert sub["status"] == "matched"
    assert sub["linked_to"] == "/in/Dark.S02E05.mkv"
    assert sub["dest"] == "/s/Dark/Season 02/Dark - S02E05 - Lost.de.srt"


def test_subtitle_without_language_keeps_plain_suffix():
    items = [video("/in/Film.mkv", "/m/Film (2020).mkv"), subtitle("/in/Film.srt")]
    Matcher.attach_subtitles(items)
    assert items[1]["dest"] == "/m/Film (2020).srt"


def test_subtitle_picks_the_longest_matching_video():
    """'Serie.S01E01.HD.srt' gehört zu 'Serie.S01E01.HD.mkv', nicht zu 'Serie.S01E01.mkv'."""
    items = [
        video("/in/Serie.S01E01.mkv", "/s/A.mkv"),
        video("/in/Serie.S01E01.HD.mkv", "/s/B.mkv"),
        subtitle("/in/Serie.S01E01.HD.srt"),
    ]
    Matcher.attach_subtitles(items)
    assert items[2]["linked_to"] == "/in/Serie.S01E01.HD.mkv"


def test_subtitle_in_other_folder_stays_unlinked():
    items = [video("/in/a/Film.mkv", "/m/Film.mkv"), subtitle("/in/b/Film.srt")]
    Matcher.attach_subtitles(items)
    assert items[1]["linked_to"] is None
    assert items[1]["status"] == "unmatched"


def test_orphan_subtitle_keeps_its_error():
    items = [subtitle("/in/Allein.srt")]
    Matcher.attach_subtitles(items)
    assert items[0]["error"] == "Kein zugehöriges Video gefunden."


# --- Passwörter und Sitzungen -----------------------------------------------

def test_password_roundtrip():
    stored = auth.hash_password("geheim123")
    assert auth.verify_password("geheim123", stored)
    assert not auth.verify_password("falsch", stored)


def test_hash_is_salted():
    assert auth.hash_password("x") != auth.hash_password("x")


def test_broken_hash_never_verifies():
    for junk in ["", "kaputt", "md5$a$b", "pbkdf2$nurzwei"]:
        assert auth.verify_password("x", junk) is False


def test_session_lifecycle():
    token = auth.create_session()
    assert auth.valid_session(token)
    auth.drop_session(token)
    assert not auth.valid_session(token)
    assert not auth.valid_session("erfunden")


def test_expired_session_is_rejected():
    token = auth.create_session()
    auth._sessions[token] = time.time() - 1
    assert not auth.valid_session(token)


# --- Cache -------------------------------------------------------------------

def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_FILE", tmp_path / "c.sqlite")
    monkeypatch.setattr(cache, "_conn", None)
    cache.put("k", {"a": 1})
    assert cache.get("k") == {"a": 1}
    assert cache.get("fehlt") is None


def test_cache_respects_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_FILE", tmp_path / "c.sqlite")
    monkeypatch.setattr(cache, "_conn", None)
    cache.put("k", "wert")
    assert cache.get("k", ttl=0) is None       # sofort abgelaufen
    assert cache.get("k", ttl=3600) == "wert"


def test_cache_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_FILE", tmp_path / "c.sqlite")
    monkeypatch.setattr(cache, "_conn", None)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.clear() == 2
    assert cache.get("a") is None


# --- Wiederholversuche bei Rate-Limit ---------------------------------------

def _no_sleep(monkeypatch):
    """Wartezeiten im Test überspringen, ohne asyncio.sleep selbst zu zerstören."""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(provider_http.asyncio, "sleep", lambda *_: real_sleep(0))

def test_retry_on_429(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if len(calls) < 3:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"ok": True})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider_http.request(client, "GET", "https://x/test")

    _no_sleep(monkeypatch)
    response = asyncio.run(run())
    assert response.status_code == 200
    assert len(calls) == 3


def test_gives_up_after_max_attempts(monkeypatch):
    async def handler(request):
        return httpx.Response(503)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider_http.request(client, "GET", "https://x/test")

    _no_sleep(monkeypatch)
    assert asyncio.run(run()).status_code == 503


def test_no_retry_on_404(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(1)
        return httpx.Response(404)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await provider_http.request(client, "GET", "https://x/test")

    asyncio.run(run())
    assert len(calls) == 1


# --- Duplikat-Entscheidung ---------------------------------------------------

@pytest.mark.parametrize("mode,verdict,expected", [
    ("skip", "better", "skip"),
    ("skip", "worse", "skip"),
    ("replace_if_better", "better", "replace"),
    ("replace_if_better", "worse", "skip"),
    ("replace_if_better", "equal", "skip"),
    ("always", "worse", "keep_both"),
])
def test_duplicate_decision(mode, verdict, expected):
    assert renamer._duplicate_decision({"verdict": verdict}, mode) == expected


def test_apply_skips_existing(tmp_path):
    src = tmp_path / "neu.mkv"
    src.write_bytes(b"x")
    item = {"src": str(src), "dest": str(tmp_path / "ziel" / "Film.mkv"),
            "existing": {"verdict": "worse", "quality": "1080p",
                         "path": str(tmp_path / "alt.mkv")}}
    result = renamer.apply([item], "move", False, False, [str(tmp_path)], "skip")
    assert result["skipped"] == 1 and result["ok"] == 0
    assert src.exists()          # Quelle bleibt unangetastet


def test_apply_replaces_worse_version(tmp_path):
    old = tmp_path / "ziel" / "Film 720p.mkv"
    old.parent.mkdir()
    old.write_bytes(b"alt")
    src = tmp_path / "neu.mkv"
    src.write_bytes(b"neu")
    item = {"src": str(src), "dest": str(tmp_path / "ziel" / "Film 1080p.mkv"),
            "existing": {"verdict": "better", "quality": "720p", "path": str(old)}}
    result = renamer.apply([item], "move", False, False, [str(tmp_path)], "replace_if_better")
    assert result["ok"] == 1
    assert not old.exists()      # alte Fassung wurde entfernt


# --- Undo räumt den Zielordner auf ------------------------------------------

def test_undo_removes_empty_target_dir(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "HISTORY_FILE", tmp_path / "cfg" / "history.json")
    src = tmp_path / "quelle" / "film.mkv"
    src.parent.mkdir()
    src.write_bytes(b"x")
    target = tmp_path / "ziel"
    dest = target / "Film (2020)" / "Film (2020).mkv"

    renamer.apply([{"src": str(src), "dest": str(dest)}], "move", False, False,
                  [str(tmp_path / "quelle")])
    assert dest.exists()

    entry = config.load_history()[0]
    result = renamer.undo([entry["time"]], [str(target)])
    assert result["ok"] == 1
    assert src.exists()
    assert not dest.parent.exists()      # der leere Zielordner ist weg
    assert target.exists()               # der Zielordner selbst bleibt


# --- Automatiklauf -----------------------------------------------------------

def test_settled_file_detection(tmp_path):
    f = tmp_path / "x.mkv"
    f.write_bytes(b"x")
    assert scheduler.is_settled(str(f), 0) is True
    assert scheduler.is_settled(str(f), 3600) is False
    assert scheduler.is_settled(str(tmp_path / "weg.mkv"), 0) is False
