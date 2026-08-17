import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import parser  # noqa: E402

ROOTS = ["/data/input"]


def parse(path, **kw):
    kw.setdefault("roots", ROOTS)
    kw.setdefault("use_metadata", False)
    return parser.parse(path, **kw)


# --- Stufe 1: Dateiname ------------------------------------------------------

def test_filename_wins_over_folder():
    """Der Dateiname ist aussagekräftig – der Ordner darf nicht dazwischenfunken."""
    guess = parse("/data/input/Irgendein Downloadordner/Der.Pate.1972.1080p.mkv")
    assert guess["title_source"] == "filename"
    assert "Pate" in guess["title"]
    assert guess["year"] == 1972


def test_series_from_filename():
    guess = parse("/data/input/Dark/Staffel 2/Dark.S02E05.German.1080p.mkv")
    assert guess["title_source"] == "filename"
    assert guess["title"] == "Dark"
    assert guess["season"] == 2 and guess["episodes"] == [5]


# --- Stufe 2: Ordnername -----------------------------------------------------

@pytest.mark.parametrize("filename", ["01.mkv", "S01E01.mkv", "episode 1.mkv", "video.mkv"])
def test_folder_used_when_filename_is_empty(filename):
    guess = parse(f"/data/input/Breaking Bad (2008)/Season 01/{filename}")
    assert guess["title_source"] == "folder"
    assert guess["title"] == "Breaking Bad"


def test_season_folder_is_skipped_for_title():
    guess = parse("/data/input/Dark/Staffel 2/01.mkv")
    assert guess["title"] == "Dark"


def test_episode_number_survives_folder_fallback():
    guess = parse("/data/input/Breaking Bad/Season 01/03.mkv")
    assert guess["episodes"] == [3]
    assert guess["title"] == "Breaking Bad"


def test_dvd_rip_names_use_folder():
    guess = parse("/data/input/Der Pate (1972)/VTS_01_1.mkv")
    assert guess["title_source"] == "folder"
    assert "Pate" in guess["title"]
    assert guess["year"] == 1972


def test_dvd_rip_digits_are_not_an_episode():
    """VTS_01_1 ist Container-Kram – daraus darf keine Episode 1 werden."""
    guess = parse("/data/input/Der Pate (1972)/VTS_01_1.mkv")
    assert guess["episodes"] == []
    assert guess["type"] == "movie"


def test_season_comes_from_season_folder():
    """Der Staffelordner liefert die Nummer, auch wenn er nicht den Titel trägt."""
    guess = parse("/data/input/Breaking Bad (2008)/Season 03/01.mkv")
    assert guess["title"] == "Breaking Bad"
    assert guess["season"] == 3
    assert guess["episodes"] == [1]
    assert guess["type"] == "episode"


def test_german_season_folder():
    guess = parse("/data/input/Dark/Staffel 2/05.mkv")
    assert guess["season"] == 2 and guess["episodes"] == [5]


@pytest.mark.parametrize("folder", [
    "Downloads", "complete", "Torrents", "Serien", "Filme", "Anime", "unsortiert", "tv",
])
def test_generic_folders_are_never_the_title(folder):
    """Ein Sammelordner darf nicht zum Serientitel werden."""
    guess = parse(f"/data/input/{folder}/video.mkv")
    assert guess["title"] is None


def test_search_continues_above_generic_folder():
    guess = parse("/data/input/Downloads/Inception (2010)/Season 01/01.mkv")
    assert guess["title"] == "Inception"


@pytest.mark.parametrize("stem,expected", [
    ("01", True), ("003", True), ("S01E02", True), ("1x02", True),
    ("E05", True), ("Folge 7", True), ("03v2", True),
    ("VTS_01_1", False), ("a3f9c2b81e4d77aa", False), ("video", False),
    ("AVSEQ01", False), ("title00", False),
])
def test_episode_number_detection(stem, expected):
    assert parser.carries_episode_number(stem) is expected


def test_hash_filename_uses_folder():
    guess = parse("/data/input/Inception (2010)/a3f9c2b81e4d77aa.mkv")
    assert guess["title_source"] == "folder"
    assert guess["title"] == "Inception"


def test_source_root_is_never_the_title():
    """Liegt die Datei direkt im Quellordner, darf dessen Name nicht als Titel dienen."""
    guess = parse("/data/input/video.mkv")
    assert guess["title"] is None


def test_folder_fallback_can_be_disabled():
    guess = parse("/data/input/Breaking Bad/Season 01/01.mkv", use_folder=False)
    assert guess["title"] is None


# --- Bewertung der Aussagekraft ---------------------------------------------

@pytest.mark.parametrize("title", ["Dark", "Der Pate", "9", "12 Monkeys", "V"])
def test_meaningful_titles(title):
    assert parser.is_meaningful(title) is (len(title.strip()) >= 2)


@pytest.mark.parametrize("title", [
    None, "", "   ", "video", "Movie", "untitled", "01", "137", "___",
    "VTS_01_1", "a3f9c2b81e4d77aa", "episode 5", "Teil 2",
])
def test_meaningless_titles(title):
    assert parser.is_meaningful(title) is False


def test_structure_folders_are_recognized():
    for name in ["Season 01", "Staffel 2", "S03", "Specials", "Extras", "Disc 1", "CD2", "Subs"]:
        folder = Path(f"/data/input/Serie/{name}/x.mkv")
        assert parser.title_folder(folder, ROOTS).name == "Serie", name
