"""Liest Titel-Metadaten direkt aus den Containern (MKV/WebM und MP4/M4V/MOV).

Bewusst ohne ffmpeg: es würde das Image um ein Vielfaches aufblähen, obwohl nur
wenige Kopf-Bytes gebraucht werden. Gelesen wird ausschließlich der Header-Bereich.
"""
import struct
from pathlib import Path

from . import logs

log = logs.get("metadata")

MAX_SCAN = 8 * 1024 * 1024        # so weit wird höchstens in die Datei gesehen
MAX_STRING = 300

# --- Matroska (EBML) ---------------------------------------------------------
EBML_SEGMENT = 0x18538067
EBML_INFO = 0x1549A966
EBML_TITLE = 0x7BA9
EBML_TAGS = 0x1254C367
EBML_TAG = 0x7373
EBML_TARGETS = 0x63C0
EBML_TARGET_TYPE_VALUE = 0x68CA
EBML_SIMPLE_TAG = 0x67C8
EBML_TAG_NAME = 0x45A3
EBML_TAG_STRING = 0x4487
# Container, in die hineingelaufen wird, statt sie zu überspringen.
EBML_CONTAINERS = {EBML_SEGMENT, EBML_INFO, EBML_TAGS, EBML_TAG, EBML_TARGETS, EBML_SIMPLE_TAG}

# Matroska-Zielebenen: 70 = Serie/Sammlung, 60 = Staffel, 50 = Film/Episode.
LEVEL_COLLECTION, LEVEL_SEASON, LEVEL_EPISODE = 70, 60, 50


def _read_vint(handle, keep_marker: bool):
    """Liest eine EBML-Zahl variabler Länge."""
    first = handle.read(1)
    if not first:
        return None, 0
    value = first[0]
    if value == 0:
        return None, 1
    length = 1
    mask = 0x80
    while not value & mask:
        mask >>= 1
        length += 1
    rest = handle.read(length - 1)
    if len(rest) != length - 1:
        return None, length
    number = value if keep_marker else value & (mask - 1)
    for byte in rest:
        number = (number << 8) | byte
    return number, length


def _read_mkv(handle, end: int, depth: int, out: dict) -> None:
    while handle.tell() < end and depth < 8:
        start = handle.tell()
        element_id, _ = _read_vint(handle, keep_marker=True)
        if element_id is None:
            return
        size, _ = _read_vint(handle, keep_marker=False)
        if size is None:
            return
        body = handle.tell()
        # Unbekannte Größe (Live-Streams): bis zum Ende weiterlesen.
        unknown = size >= 0x00FFFFFFFFFFFFFF
        stop = end if unknown else min(body + size, end)
        if stop <= start:
            return

        if element_id in EBML_CONTAINERS:
            _read_mkv(handle, stop, depth + 1, out)
        elif element_id == EBML_TITLE:
            out.setdefault("segment_title", _text(handle.read(min(size, MAX_STRING))))
        elif element_id == EBML_TARGET_TYPE_VALUE:
            out["_level"] = int.from_bytes(handle.read(min(size, 8)), "big")
        elif element_id == EBML_TAG_NAME:
            out["_name"] = (_text(handle.read(min(size, MAX_STRING))) or "").upper()
        elif element_id == EBML_TAG_STRING:
            value = _text(handle.read(min(size, MAX_STRING)))
            name, level = out.get("_name"), out.get("_level", LEVEL_EPISODE)
            if name and value:
                out.setdefault("tags", []).append((level, name, value))
        handle.seek(stop)


def _text(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8").strip("\x00").strip() or None
    except UnicodeDecodeError:
        return None


def read_mkv(path: Path) -> dict:
    result: dict = {}
    with path.open("rb") as handle:
        if handle.read(4) != b"\x1a\x45\xdf\xa3":
            return {}
        handle.seek(0)
        _read_mkv(handle, min(path.stat().st_size, MAX_SCAN), 0, result)

    info: dict = {}
    for level, name, value in result.get("tags", []):
        if name == "TITLE" and level >= LEVEL_COLLECTION:
            info.setdefault("show", value)
        elif name == "TITLE" and level <= LEVEL_EPISODE:
            info.setdefault("title", value)
        elif name == "PART_NUMBER" and level == LEVEL_SEASON:
            info.setdefault("season", _int(value))
        elif name == "PART_NUMBER" and level <= LEVEL_EPISODE:
            info.setdefault("episode", _int(value))
        elif name in ("DATE_RELEASED", "DATE_RECORDED") and value[:4].isdigit():
            info.setdefault("year", int(value[:4]))
    if result.get("segment_title"):
        info.setdefault("title", result["segment_title"])
    return info


# --- MP4 / M4V / MOV ---------------------------------------------------------
MP4_CONTAINERS = {b"moov", b"udta", b"meta", b"ilst"}
MP4_KEYS = {
    b"\xa9nam": "title",
    b"tvsh": "show",
    b"tvsn": "season",
    b"tves": "episode",
    b"\xa9day": "year",
    b"tven": "episode_id",
}


def _read_mp4(handle, end: int, depth: int, out: dict) -> None:
    while handle.tell() < end and depth < 8:
        header = handle.read(8)
        if len(header) < 8:
            return
        size = struct.unpack(">I", header[:4])[0]
        kind = header[4:8]
        body = handle.tell()
        if size == 1:                     # 64-Bit-Größe
            extended = handle.read(8)
            if len(extended) < 8:
                return
            size = struct.unpack(">Q", extended)[0] - 8
            body = handle.tell()
        elif size == 0:                   # bis Dateiende
            size = end - body + 8
        stop = min(body + size - 8, end)
        if stop <= body:
            return

        if kind in MP4_CONTAINERS:
            # 'meta' hat vor den Unter-Atomen 4 Byte Version/Flags.
            if kind == b"meta":
                handle.read(4)
            _read_mp4(handle, stop, depth + 1, out)
        elif kind in MP4_KEYS:
            out[MP4_KEYS[kind]] = _read_mp4_value(handle, stop)
        handle.seek(stop)


def _read_mp4_value(handle, stop: int):
    """Liest den 'data'-Unterblock eines iTunes-Metadaten-Atoms."""
    header = handle.read(8)
    if len(header) < 8 or header[4:8] != b"data":
        return None
    size = struct.unpack(">I", header[:4])[0]
    flags = handle.read(8)                # 4 Byte Typ + 4 Byte Locale
    if len(flags) < 8:
        return None
    payload = handle.read(min(max(size - 16, 0), MAX_STRING))
    data_type = struct.unpack(">I", flags[:4])[0]
    if data_type == 1:                    # UTF-8
        return _text(payload)
    if data_type == 21 and payload:       # Ganzzahl
        return int.from_bytes(payload[:4] if len(payload) >= 4 else payload, "big")
    return _text(payload)


def read_mp4(path: Path) -> dict:
    raw: dict = {}
    with path.open("rb") as handle:
        if handle.read(8)[4:8] != b"ftyp":
            return {}
        handle.seek(0)
        _read_mp4(handle, min(path.stat().st_size, MAX_SCAN), 0, raw)

    info = {}
    for key in ("title", "show"):
        if isinstance(raw.get(key), str):
            info[key] = raw[key]
    for key in ("season", "episode"):
        value = _int(raw.get(key))
        if value:
            info[key] = value
    year = raw.get("year")
    if isinstance(year, str) and year[:4].isdigit():
        info["year"] = int(year[:4])
    elif isinstance(year, int) and 1880 < year < 2200:
        info["year"] = year
    return info


def _int(value):
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


READERS = {
    ".mkv": read_mkv, ".webm": read_mkv,
    ".mp4": read_mp4, ".m4v": read_mp4, ".mov": read_mp4,
}


def read(path: str | Path) -> dict:
    """Liefert die eingebetteten Metadaten oder {} – Fehler sind nie fatal."""
    path = Path(path)
    reader = READERS.get(path.suffix.lower())
    if not reader:
        return {}
    try:
        info = reader(path)
    except (OSError, ValueError, struct.error, RecursionError) as exc:
        log.debug("Metadaten aus %s nicht lesbar: %s", path.name, exc)
        return {}
    if info:
        log.debug("Metadaten aus %s: %s", path.name, info)
    return info
