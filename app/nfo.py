"""Begleitende NFO-Dateien für Kodi, Jellyfin und Emby."""
from pathlib import Path
from xml.etree import ElementTree as ET

from . import logs

log = logs.get("nfo")


def _text(parent: ET.Element, tag: str, value) -> None:
    if value in (None, "", []):
        return
    ET.SubElement(parent, tag).text = str(value)


def build(item: dict) -> str | None:
    """Erzeugt den NFO-Inhalt passend zur Kategorie."""
    match = item.get("match") or {}
    guess = item.get("guess") or {}
    category = item.get("category", "movie")

    if category == "movie":
        root = ET.Element("movie")
        _text(root, "title", match.get("title"))
        _text(root, "originaltitle", match.get("original_title"))
        _text(root, "year", match.get("year"))
        _text(root, "set", match.get("collection"))
    else:
        root = ET.Element("episodedetails")
        _text(root, "title", guess.get("episode_title") or match.get("title"))
        _text(root, "showtitle", match.get("title"))
        _text(root, "season", guess.get("season"))
        episodes = guess.get("episodes") or []
        _text(root, "episode", episodes[0] if episodes else None)
        _text(root, "aired", guess.get("air_date"))

    for genre in match.get("genres") or []:
        _text(root, "genre", genre)
    if match.get("rating"):
        _text(root, "rating", round(float(match["rating"]), 1))

    ids = ET.SubElement(root, "uniqueid")
    ids.set("type", match.get("provider", "tmdb"))
    ids.set("default", "true")
    ids.text = str(match.get("id", ""))
    if match.get("imdb_id"):
        imdb = ET.SubElement(root, "uniqueid")
        imdb.set("type", "imdb")
        imdb.text = match["imdb_id"]

    if not match.get("id"):
        return None
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n' + \
        ET.tostring(root, encoding="unicode")


def write(item: dict, dest: str) -> str | None:
    """Legt die NFO neben die Zieldatei. Fehler sind nie fatal."""
    content = build(item)
    if not content:
        return None
    path = Path(dest).with_suffix(".nfo")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        return str(path)
    except OSError as exc:
        log.error("NFO nicht schreibbar: %s (%s)", path, exc)
        return None
