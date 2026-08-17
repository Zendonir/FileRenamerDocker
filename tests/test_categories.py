import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import naming  # noqa: E402
from app.matcher import category_of, detect_anime  # noqa: E402

SETTINGS = {
    "anime_detection": "auto",
    "anime_keywords": ["anime", "subsplease"],
}
EPISODE = {"type": "episode"}
MOVIE = {"type": "movie"}


def test_movie_stays_movie_even_in_anime_folder():
    assert category_of("/data/anime/Akira.1988.mkv", MOVIE, None, SETTINGS) == "movie"


def test_path_keyword_marks_anime():
    assert category_of("/data/anime/Naruto/01.mkv", EPISODE, None, SETTINGS) == "anime"


def test_fansub_group_marks_anime():
    path = "/data/input/[SubsPlease] Frieren - 12 (1080p).mkv"
    assert category_of(path, EPISODE, None, SETTINGS) == "anime"


def test_plain_series_is_not_anime():
    candidate = {"original_language": "en", "genre_ids": [18], "origin_country": ["US"]}
    assert category_of("/data/input/Dark.S01E01.mkv", EPISODE, candidate, SETTINGS) == "series"


def test_japanese_animation_is_anime():
    candidate = {"original_language": "ja", "genre_ids": [16], "origin_country": ["JP"]}
    assert category_of("/data/input/Shingeki.S01E03.mkv", EPISODE, candidate, SETTINGS) == "anime"


def test_japanese_liveaction_is_not_anime():
    candidate = {"original_language": "ja", "genre_ids": [18], "origin_country": ["JP"]}
    assert category_of("/data/input/Shogun.S01E01.mkv", EPISODE, candidate, SETTINGS) == "series"


def test_western_cartoon_is_not_anime():
    candidate = {"original_language": "en", "genre_ids": [16], "origin_country": ["US"]}
    assert category_of("/data/input/Simpsons.S05E01.mkv", EPISODE, candidate, SETTINGS) == "series"


def test_tvdb_genre_names_are_understood():
    candidate = {"original_language": "jpn", "genres": ["Anime", "Action"], "origin_country": ["JP"]}
    assert detect_anime("/x/y.mkv", EPISODE, candidate, SETTINGS) is True


def test_detection_can_be_disabled():
    off = {**SETTINGS, "anime_detection": "off"}
    candidate = {"original_language": "ja", "genre_ids": [16], "origin_country": ["JP"]}
    assert category_of("/data/anime/x.mkv", EPISODE, candidate, off) == "series"


def test_anime_absolute_format():
    info = {"name": "Frieren", "absolute": 12, "episode_title": "Ende der Reise",
            "season": 1, "episodes": [12]}
    assert naming.format_path("{n}/{n} - {abs.pad(3)|s00e00} - {t}", info) == \
        "Frieren/Frieren - 012 - Ende der Reise"


def test_anime_format_falls_back_to_season_episode():
    info = {"name": "Frieren", "season": 1, "episodes": [12], "episode": 12,
            "episode_title": "Ende der Reise"}
    assert naming.format_path("{n}/{n} - {abs.pad(3)|s00e00} - {t}", info) == \
        "Frieren/Frieren - S01E12 - Ende der Reise"
