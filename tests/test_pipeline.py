"""Durchlauf der gesamten Kette mit einer nachgebildeten Datenbank."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import scanner
from app.matcher import Matcher

SERIES = {"provider": "tvdb", "id": 1, "title": "Dark", "year": 2017,
          "original_language": "de", "origin_country": ["DE"], "genre_ids": [18],
          "popularity": 10}


class FakeMatcher(Matcher):
    """Matcher ohne Netz – zählt zugleich die Abfragen."""

    def __init__(self, settings):
        super().__init__(settings)
        self.searches = []
        self.episode_calls = 0

    async def search(self, client, kind, query, year, provider=None):
        self.searches.append(query)
        return [dict(SERIES)]

    async def episodes_for(self, client, category, provider, series_id, guess):
        self.episode_calls += 1
        numbers = guess.get("episodes") or []
        return [{"title": f"Folge {n}", "air_date": "2019-06-21", "absolute": n,
                 "season": guess.get("season") or 1, "episode": n} for n in numbers]


def settings_for(tmp_path, **extra):
    return {
        "source_dirs": [str(tmp_path / "in")],
        "movie_target": str(tmp_path / "out" / "movies"),
        "series_target": str(tmp_path / "out" / "series"),
        "anime_target": str(tmp_path / "out" / "anime"),
        "movie_format": "{n} ({y})/{n} ({y})",
        "series_format": "{n}/Season {s.pad(2)}/{n} - {s00e00} - {t}",
        "anime_format": "{n}/{n} - {abs.pad(3)|s00e00} - {t}",
        "extensions": [".mkv"], "subtitle_extensions": [".srt"],
        "min_size_mb": 0, "min_confidence": 0.7, "language": "de-DE",
        "series_provider": "tvdb", "anime_provider": "tvdb", "anime_detection": "auto",
        "anime_keywords": ["anime"], "anime_absolute": True,
        "use_folder_names": True, "use_embedded_metadata": False,
        "check_library": True, "ascii_only": False, "windows_safe": True,
        **extra,
    }


def build(tmp_path, files):
    for rel, size in files.items():
        path = tmp_path / "in" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
    return scanner.scan([str(tmp_path / "in")], [".mkv"], 0, True, [".srt"])


def run(matcher, entries):
    return asyncio.run(matcher.process(entries))


def test_subtitle_follows_video_and_costs_no_query(tmp_path):
    entries = build(tmp_path, {
        "Dark/Staffel 2/Dark.S02E05.German.1080p.mkv": 2048,
        "Dark/Staffel 2/Dark.S02E05.German.de.srt": 64,
    })
    matcher = FakeMatcher(settings_for(tmp_path))
    items = run(matcher, entries)

    sub = next(i for i in items if i["is_subtitle"])
    video = next(i for i in items if not i["is_subtitle"])
    assert video["dest"].endswith("Dark/Season 02/Dark - S02E05 - Folge 5.mkv")
    assert sub["dest"].endswith("Dark/Season 02/Dark - S02E05 - Folge 5.de.srt")
    assert sub["linked_to"] == video["src"]
    # Genau eine Suche: der Untertitel hat keine ausgelöst.
    assert matcher.searches == ["Dark"]


def test_orphan_subtitle_still_gets_its_own_query(tmp_path):
    entries = build(tmp_path, {"Dark.S02E05.German.de.srt": 64})
    matcher = FakeMatcher(settings_for(tmp_path))
    items = run(matcher, entries)
    assert matcher.searches == ["Dark"]        # ohne Video wird doch gefragt
    assert items[0]["dest"] is not None


def test_existing_better_version_is_detected(tmp_path):
    target = tmp_path / "out" / "series" / "Dark" / "Season 02"
    target.mkdir(parents=True)
    (target / "Dark - S02E05 - Folge 5 2160p.mkv").write_bytes(b"\0" * 9000)

    entries = build(tmp_path, {"Dark.S02E05.German.720p.mkv": 1000})
    items = run(FakeMatcher(settings_for(tmp_path)), entries)

    assert items[0]["existing"] is not None
    assert items[0]["existing"]["verdict"] == "worse"


def test_new_version_recognised_as_better(tmp_path):
    target = tmp_path / "out" / "series" / "Dark" / "Season 02"
    target.mkdir(parents=True)
    (target / "Dark - S02E05 - Folge 5 720p.mkv").write_bytes(b"\0" * 500)

    entries = build(tmp_path, {"Dark.S02E05.German.1080p.BluRay.mkv": 9000})
    items = run(FakeMatcher(settings_for(tmp_path)), entries)
    assert items[0]["existing"]["verdict"] == "better"


def test_empty_library_reports_nothing(tmp_path):
    entries = build(tmp_path, {"Dark.S02E05.German.1080p.mkv": 1000})
    items = run(FakeMatcher(settings_for(tmp_path)), entries)
    assert items[0]["existing"] is None


def test_library_check_can_be_disabled(tmp_path):
    target = tmp_path / "out" / "series" / "Dark" / "Season 02"
    target.mkdir(parents=True)
    (target / "Dark - S02E05 - Folge 5 2160p.mkv").write_bytes(b"\0" * 9000)
    entries = build(tmp_path, {"Dark.S02E05.German.720p.mkv": 1000})
    items = run(FakeMatcher(settings_for(tmp_path, check_library=False)), entries)
    assert items[0]["existing"] is None


def test_ascii_option_reaches_the_destination(tmp_path):
    entries = build(tmp_path, {"Dark.S02E05.German.1080p.mkv": 1000})
    matcher = FakeMatcher(settings_for(tmp_path, ascii_only=True))
    matcher.searches = []

    async def german_titles(client, category, provider, series_id, guess):
        return [{"title": "Grüße", "air_date": None, "absolute": 5,
                 "season": 2, "episode": 5}]

    matcher.episodes_for = german_titles
    items = run(matcher, entries)
    assert items[0]["dest"].endswith("Gruesse.mkv")


def test_cancelled_scan_returns_placeholders(tmp_path):
    entries = build(tmp_path, {"a.mkv": 100, "b.mkv": 100})
    matcher = FakeMatcher(settings_for(tmp_path))

    async def go():
        return await matcher.process(entries, is_cancelled=lambda: True)

    items = asyncio.run(go())
    assert len(items) == 2
    assert all(i["status"] == "unmatched" for i in items)
    assert matcher.searches == []           # keine einzige Abfrage


@pytest.mark.parametrize("name,expected_folder", [
    ("Dark.S02E05.German.1080p.mkv", "series"),
    ("Anime/Dark.S02E05.1080p.mkv", "anime"),
])
def test_category_decides_the_target_folder(tmp_path, name, expected_folder):
    entries = build(tmp_path, {name: 1000})
    items = run(FakeMatcher(settings_for(tmp_path)), entries)
    assert f"/out/{expected_folder}/" in items[0]["dest"]
