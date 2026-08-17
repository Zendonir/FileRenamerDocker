import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import naming, parser


def test_movie_format():
    info = {"name": "Der Pate", "year": 1972, "resolution": "1080p", "extension": ".mkv"}
    assert naming.format_path("{n} ({y})/{n} ({y}){' '+vf}", info) == "Der Pate (1972)/Der Pate (1972) 1080p"


def test_movie_format_drops_missing_optional():
    info = {"name": "Der Pate", "year": 1972, "extension": ".mkv"}
    assert naming.format_path("{n} ({y})/{n} ({y}){' '+vf}", info) == "Der Pate (1972)/Der Pate (1972)"


def test_series_format():
    info = {"name": "Dark", "season": 2, "episodes": [5], "episode": 5, "episode_title": "Lost"}
    assert naming.format_path("{n}/Season {s.pad(2)}/{n} - {s00e00} - {t}", info) == \
        "Dark/Season 02/Dark - S02E05 - Lost"


def test_multi_episode():
    info = {"name": "Dark", "season": 1, "episodes": [1, 2], "episode": 1, "episode_title": "A & B"}
    assert "S01E01E02" in naming.format_path("{n} - {s00e00} - {t}", info)


def test_fallback_chain():
    info = {"name": "Dark", "season": 1, "episodes": [3], "episode": 3}
    assert naming.format_path("{t|n}", info) == "Dark"


def test_sanitize_removes_invalid_chars():
    info = {"name": 'Ka:Pow?/Boom', "year": 2000}
    assert naming.format_path("{n} ({y})", info) == "KaPowBoom (2000)"


def test_parse_series():
    guess = parser.parse("/data/input/Dark.S02E05.German.1080p.BluRay.x264-GROUP.mkv")
    assert guess["type"] == "episode"
    assert guess["season"] == 2
    assert guess["episodes"] == [5]
    assert guess["resolution"] == "1080p"


def test_parse_movie():
    guess = parser.parse("/data/input/Der.Pate.1972.German.1080p.BluRay.x264.mkv")
    assert guess["type"] == "movie"
    assert guess["year"] == 1972
    assert "Pate" in guess["title"]
