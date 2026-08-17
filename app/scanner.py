"""Dateisystem-Scan und Verzeichnis-Browser."""
import os
from pathlib import Path

SAMPLE_MARKERS = ("sample", "trailer", "rarbg.com", "etrg")


def is_sample(path: Path, min_size_mb: int) -> bool:
    name = path.name.lower()
    if any(marker in name for marker in SAMPLE_MARKERS) and path.stat().st_size < 400 * 1024 * 1024:
        return True
    return path.stat().st_size < min_size_mb * 1024 * 1024


def scan(roots: list[str], extensions: list[str], min_size_mb: int = 50,
         include_subtitles: bool = True, subtitle_extensions: list[str] | None = None) -> list[dict]:
    """Sucht rekursiv nach Medien-Dateien in den angegebenen Wurzelverzeichnissen."""
    exts = {e.lower() for e in extensions}
    sub_exts = {e.lower() for e in (subtitle_extensions or [])} if include_subtitles else set()
    found: list[dict] = []
    seen: set[str] = set()

    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in sorted(filenames):
                path = Path(dirpath) / filename
                suffix = path.suffix.lower()
                if suffix not in exts and suffix not in sub_exts:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                real = str(path.resolve())
                if real in seen:
                    continue
                seen.add(real)
                is_sub = suffix in sub_exts
                if not is_sub and is_sample(path, min_size_mb):
                    continue
                found.append({
                    "path": str(path),
                    "name": path.name,
                    "size": stat.st_size,
                    "root": str(base),
                    "is_subtitle": is_sub,
                })
    return found


def browse(path: str) -> dict:
    """Listet Unterverzeichnisse für den Verzeichnis-Picker im Webinterface."""
    p = Path(path or "/")
    if not p.is_dir():
        p = Path("/")
    entries = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if child.name.startswith("."):
                continue
            try:
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child)})
            except OSError:
                continue
    except PermissionError:
        pass
    return {
        "path": str(p),
        "parent": str(p.parent) if str(p) != "/" else None,
        "dirs": entries,
    }
