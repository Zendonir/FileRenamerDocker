import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import library, naming, nfo

GB = 1024 ** 3
VIDEO_EXT = {".mkv", ".mp4", ".avi"}


def guess(resolution=None, source=None):
    return {"resolution": resolution, "source": source, "video_codec": "H.264"}


# --- Qualitätsvergleich ------------------------------------------------------

def test_higher_resolution_wins():
    assert library.quality_score(guess("1080p")) > library.quality_score(guess("720p"))


def test_bluray_beats_web_at_same_resolution():
    assert library.quality_score(guess("1080p", "bluray")) > \
        library.quality_score(guess("1080p", "web"))


def test_size_only_breaks_ties():
    small = library.quality_score(guess("1080p", "bluray"), 4 * GB)
    large = library.quality_score(guess("1080p", "bluray"), 9 * GB)
    assert large > small


def test_2160p_beats_1080p_even_when_smaller():
    assert library.quality_score(guess("2160p"), 3 * GB) > \
        library.quality_score(guess("1080p"), 40 * GB)


# --- Vergleich mit einer konkreten Datei ------------------------------------

def make(path: Path, size_mb: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * (size_mb * 1024 * 1024))
    return path


def test_new_file_is_better(tmp_path):
    old = make(tmp_path / "Dark - S01E01 - Pilot 720p.mkv", 2)
    verdict = library.compare(guess("1080p", "bluray"), 900 * 1024 * 1024,
                              "neu 1080p.mkv", old, guess("720p", "web"))
    assert verdict == "better"


def test_new_file_is_worse(tmp_path):
    old = make(tmp_path / "Dark - S01E01 - Pilot 1080p.mkv", 2)
    verdict = library.compare(guess("720p", "web"), 100 * 1024 * 1024,
                              "neu 720p.mkv", old, guess("1080p", "bluray"))
    assert verdict == "worse"


def test_same_quality_and_size_is_equal(tmp_path):
    old = make(tmp_path / "Dark - S01E01 - Pilot 1080p.mkv", 10)
    verdict = library.compare(guess("1080p", "bluray"), 10 * 1024 * 1024,
                              "neu.mkv", old, guess("1080p", "bluray"))
    assert verdict == "equal"


# --- Auffinden vorhandener Fassungen ----------------------------------------

def test_finds_same_episode_in_other_quality(tmp_path):
    make(tmp_path / "Dark - S01E01 - Pilot 720p.mkv")
    dest = tmp_path / "Dark - S01E01 - Pilot 1080p.mkv"
    found = library.find_existing(str(dest), VIDEO_EXT)
    assert [f.name for f in found] == ["Dark - S01E01 - Pilot 720p.mkv"]


def test_other_episodes_are_not_matched(tmp_path):
    make(tmp_path / "Dark - S01E02 - Dunkel 720p.mkv")
    dest = tmp_path / "Dark - S01E01 - Pilot 1080p.mkv"
    assert library.find_existing(str(dest), VIDEO_EXT) == []


def test_subtitles_are_not_counted_as_existing(tmp_path):
    (tmp_path / "Dark - S01E01 - Pilot.de.srt").write_text("x")
    dest = tmp_path / "Dark - S01E01 - Pilot 1080p.mkv"
    assert library.find_existing(str(dest), VIDEO_EXT) == []


def test_missing_target_folder_is_no_error(tmp_path):
    assert library.find_existing(str(tmp_path / "gibtsnicht" / "x.mkv"), VIDEO_EXT) == []


# --- Umlaut-Umschrift und Windows-sichere Namen -----------------------------

def test_ascii_transliteration():
    info = {"name": "Grüße aus Köln", "year": 2020}
    assert naming.format_path("{n} ({y})", info, ascii_only=True) == "Gruesse aus Koeln (2020)"


def test_umlauts_stay_by_default():
    info = {"name": "Grüße aus Köln", "year": 2020}
    assert naming.format_path("{n} ({y})", info) == "Grüße aus Köln (2020)"


def test_windows_safe_strips_trailing_dot():
    info = {"name": "Star Trek Nemesis."}
    assert naming.format_path("{n}", info, windows_safe=True) == "Star Trek Nemesis"


def test_reserved_device_name_is_escaped():
    assert naming.sanitize("CON") == "_CON"
    assert naming.sanitize("con.mkv") == "_con.mkv"


# --- NFO ---------------------------------------------------------------------

def test_movie_nfo(tmp_path):
    item = {"category": "movie", "guess": {},
            "match": {"provider": "tmdb", "id": 238, "title": "Der Pate",
                      "year": 1972, "imdb_id": "tt0068646", "genres": ["Drama"]}}
    path = nfo.write(item, str(tmp_path / "Der Pate (1972).mkv"))
    content = Path(path).read_text("utf-8")
    assert path.endswith("Der Pate (1972).nfo")
    assert "<title>Der Pate</title>" in content
    assert '<uniqueid type="imdb">tt0068646</uniqueid>' in content


def test_episode_nfo(tmp_path):
    item = {"category": "series",
            "guess": {"season": 2, "episodes": [5], "episode_title": "Lost"},
            "match": {"provider": "tvdb", "id": 326472, "title": "Dark"}}
    content = Path(nfo.write(item, str(tmp_path / "x.mkv"))).read_text("utf-8")
    assert "<episodedetails>" in content
    assert "<showtitle>Dark</showtitle>" in content
    assert "<season>2</season>" in content and "<episode>5</episode>" in content


def test_nfo_without_match_is_skipped(tmp_path):
    assert nfo.write({"category": "movie", "guess": {}, "match": None},
                     str(tmp_path / "x.mkv")) is None
