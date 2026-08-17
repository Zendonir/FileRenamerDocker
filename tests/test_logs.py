import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import logs  # noqa: E402


def setup_module():
    logs.setup()


def test_entries_are_newest_first():
    log = logs.get("test")
    log.info("erster Eintrag")
    log.info("zweiter Eintrag")
    entries = logs.entries(level="INFO")["entries"]
    assert entries[0]["message"] == "zweiter Eintrag"


def test_level_filter_hides_info():
    log = logs.get("test")
    log.info("harmlose Info")
    log.error("echter Fehler")
    messages = [e["message"] for e in logs.entries(level="ERROR")["entries"]]
    assert "echter Fehler" in messages
    assert "harmlose Info" not in messages


def test_query_filter_is_case_insensitive():
    logs.get("test").warning("Datei NICHT gefunden")
    messages = [e["message"] for e in logs.entries(level="DEBUG", query="nicht gefunden")["entries"]]
    assert messages and all("NICHT gefunden" in m for m in messages)


def test_after_id_returns_only_newer_lines():
    log = logs.get("test")
    log.info("alt")
    last = logs.entries(level="DEBUG")["last_id"]
    log.info("neu")
    entries = logs.entries(level="DEBUG", after_id=last)["entries"]
    assert [e["message"] for e in entries] == ["neu"]


def test_buffer_is_bounded():
    log = logs.get("test")
    for i in range(logs.BUFFER_SIZE + 50):
        log.debug("Zeile %d", i)
    assert logs.entries(level="DEBUG")["total"] <= logs.BUFFER_SIZE
