"""Prüft die Container-Leser gegen selbst gebaute MKV- und MP4-Strukturen."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import metadata, parser  # noqa: E402


# --- Hilfsfunktionen zum Bauen echter Container-Bytes ------------------------

def ebml_size(length: int) -> bytes:
    """8-Byte-Längenangabe (Markerbit 0x01 plus 7 Datenbytes)."""
    return b"\x01" + length.to_bytes(7, "big")


def ebml(element_id: bytes, payload: bytes) -> bytes:
    return element_id + ebml_size(len(payload)) + payload


def simple_tag(name: str, value: str) -> bytes:
    return ebml(b"\x67\xc8",
                ebml(b"\x45\xa3", name.encode()) + ebml(b"\x44\x87", value.encode()))


def mkv_file(path: Path, segment_title=None, tags=()):
    header = ebml(b"\x1a\x45\xdf\xa3", b"\x42\x86" + ebml_size(1) + b"\x01")
    body = b""
    if segment_title:
        body += ebml(b"\x15\x49\xa9\x66", ebml(b"\x7b\xa9", segment_title.encode()))
    for level, entries in tags:
        targets = ebml(b"\x63\xc0", ebml(b"\x68\xca", bytes([level])))
        simple = b"".join(simple_tag(n, v) for n, v in entries)
        body += ebml(b"\x12\x54\xc3\x67", ebml(b"\x73\x73", targets + simple))
    path.write_bytes(header + ebml(b"\x18\x53\x80\x67", body))


def atom(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def data_atom(value, numeric=False) -> bytes:
    if numeric:
        payload = struct.pack(">I", 21) + b"\x00" * 4 + struct.pack(">I", value)
    else:
        payload = struct.pack(">I", 1) + b"\x00" * 4 + str(value).encode()
    return atom(b"data", payload)


def mp4_file(path: Path, **fields):
    keys = {"title": b"\xa9nam", "show": b"tvsh", "season": b"tvsn",
            "episode": b"tves", "year": b"\xa9day"}
    ilst = b"".join(
        atom(keys[k], data_atom(v, numeric=k in ("season", "episode")))
        for k, v in fields.items()
    )
    meta = atom(b"meta", b"\x00" * 4 + atom(b"ilst", ilst))
    moov = atom(b"moov", atom(b"udta", meta))
    path.write_bytes(atom(b"ftyp", b"isom" + b"\x00" * 8) + moov)


# --- Matroska ---------------------------------------------------------------

def test_mkv_segment_title(tmp_path):
    f = tmp_path / "a.mkv"
    mkv_file(f, segment_title="Der Pate")
    assert metadata.read(f)["title"] == "Der Pate"


def test_mkv_series_tags(tmp_path):
    f = tmp_path / "b.mkv"
    mkv_file(f, tags=[
        (70, [("TITLE", "Breaking Bad")]),
        (60, [("PART_NUMBER", "3")]),
        (50, [("TITLE", "Sonnenaufgang"), ("PART_NUMBER", "7")]),
    ])
    info = metadata.read(f)
    assert info["show"] == "Breaking Bad"
    assert info["season"] == 3
    assert info["episode"] == 7
    assert info["title"] == "Sonnenaufgang"


def test_mkv_release_year(tmp_path):
    f = tmp_path / "c.mkv"
    mkv_file(f, tags=[(50, [("TITLE", "Inception"), ("DATE_RELEASED", "2010-07-16")])])
    assert metadata.read(f)["year"] == 2010


def test_mkv_umlauts_survive(tmp_path):
    f = tmp_path / "d.mkv"
    mkv_file(f, segment_title="Der Schuh des Manitu – Grüße")
    assert metadata.read(f)["title"] == "Der Schuh des Manitu – Grüße"


# --- MP4 --------------------------------------------------------------------

def test_mp4_movie_title(tmp_path):
    f = tmp_path / "a.mp4"
    mp4_file(f, title="Inception", year="2010-07-16")
    info = metadata.read(f)
    assert info["title"] == "Inception"
    assert info["year"] == 2010


def test_mp4_series_fields(tmp_path):
    f = tmp_path / "b.m4v"
    mp4_file(f, show="Dark", season=2, episode=5, title="Lost")
    info = metadata.read(f)
    assert info == {"title": "Lost", "show": "Dark", "season": 2, "episode": 5}


# --- Robustheit -------------------------------------------------------------

def test_garbage_file_is_ignored(tmp_path):
    f = tmp_path / "x.mkv"
    f.write_bytes(b"\x00\x01\x02 kein container")
    assert metadata.read(f) == {}


def test_empty_file_is_ignored(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"")
    assert metadata.read(f) == {}


def test_truncated_file_is_ignored(tmp_path):
    f = tmp_path / "x.mkv"
    full = tmp_path / "full.mkv"
    mkv_file(full, segment_title="Abgeschnitten")
    f.write_bytes(full.read_bytes()[:20])
    assert metadata.read(f) == {}


def test_unsupported_extension_is_skipped(tmp_path):
    f = tmp_path / "x.avi"
    f.write_bytes(b"RIFF....AVI ")
    assert metadata.read(f) == {}


# --- Zusammenspiel mit dem Parser -------------------------------------------

def test_metadata_is_last_resort_for_title(tmp_path):
    root = tmp_path / "input"
    (root / "Downloads").mkdir(parents=True)
    f = root / "Downloads" / "video.mkv"
    mkv_file(f, tags=[(70, [("TITLE", "Breaking Bad")]), (60, [("PART_NUMBER", "2")]),
                      (50, [("TITLE", "Grilled"), ("PART_NUMBER", "2")])])
    guess = parser.parse(str(f), roots=[str(root)])
    assert guess["title_source"] == "metadata"
    assert guess["title"] == "Breaking Bad"
    assert guess["season"] == 2 and guess["episodes"] == [2]
    assert guess["type"] == "episode"


def test_filename_beats_metadata(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    f = root / "Dark.S02E05.1080p.mkv"
    mkv_file(f, segment_title="Voellig anderer Titel")
    guess = parser.parse(str(f), roots=[str(root)])
    assert guess["title_source"] == "filename"
    assert guess["title"] == "Dark"


def test_folder_beats_metadata(tmp_path):
    root = tmp_path / "input"
    (root / "Breaking Bad").mkdir(parents=True)
    f = root / "Breaking Bad" / "01.mkv"
    mkv_file(f, segment_title="Irgendein Encoder-Titel")
    guess = parser.parse(str(f), roots=[str(root)])
    assert guess["title_source"] == "folder"
    assert guess["title"] == "Breaking Bad"


def test_metadata_fills_gaps_without_taking_over(tmp_path):
    """Titel aus dem Dateinamen, fehlende Staffel/Episode aus den Metadaten."""
    root = tmp_path / "input"
    root.mkdir()
    f = root / "Dark German 1080p.mkv"
    mkv_file(f, tags=[(70, [("TITLE", "Dark")]), (60, [("PART_NUMBER", "2")]),
                      (50, [("PART_NUMBER", "5")])])
    guess = parser.parse(str(f), roots=[str(root)])
    assert guess["title_source"] == "filename"
    assert guess["title"] == "Dark"
    assert guess["season"] == 2 and guess["episodes"] == [5]


def test_metadata_can_be_disabled(tmp_path):
    root = tmp_path / "input"
    root.mkdir()
    f = root / "video.mkv"
    mkv_file(f, segment_title="Breaking Bad")
    assert parser.parse(str(f), roots=[str(root)], use_metadata=False)["title"] is None
