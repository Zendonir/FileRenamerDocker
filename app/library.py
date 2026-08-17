"""Abgleich mit der bestehenden Bibliothek: schon vorhanden, besser oder schlechter?"""
import re
from pathlib import Path

# Grobe Rangfolge; höher gewinnt. Bewusst einfach gehalten – die Auflösung
# entscheidet zuerst, Quelle und Dateigröße brechen Gleichstände.
RESOLUTION_RANK = {
    "480p": 1, "576p": 2, "720p": 3, "1080i": 4, "1080p": 5,
    "1440p": 6, "2160p": 7, "4k": 7, "4320p": 8,
}
SOURCE_RANK = {
    "cam": 0, "telesync": 1, "ts": 1, "screener": 2, "dvd": 3, "hdtv": 4,
    "web": 5, "webrip": 5, "web-dl": 6, "webdl": 6, "bluray": 7, "blu-ray": 7,
    "remux": 8, "ultra hd blu-ray": 9,
}
HDR_MARKERS = ("hdr", "dolby vision", "dv", "hdr10")


def _rank(table: dict, value: str | None) -> int:
    if not value:
        return 0
    key = str(value).strip().lower()
    return table.get(key, 0)


def quality_score(guess: dict, size: int = 0, path: str = "") -> tuple:
    """Vergleichbare Kennzahl einer Datei – größer ist besser."""
    haystack = f"{path} {guess.get('source') or ''}".lower()
    return (
        _rank(RESOLUTION_RANK, guess.get("resolution")),
        _rank(SOURCE_RANK, guess.get("source")),
        1 if any(marker in haystack for marker in HDR_MARKERS) else 0,
        size,
    )


def describe(guess: dict) -> str:
    parts = [guess.get("resolution"), guess.get("source"), guess.get("video_codec")]
    return " ".join(str(p) for p in parts if p) or "unbekannte Qualität"


def _same_episode_pattern(dest: Path) -> re.Pattern:
    """Findet Dateien derselben Episode bzw. desselben Films im Zielordner."""
    stem = dest.stem
    # Alles ab der Auflösung/Qualitätsangabe abschneiden, damit
    # "Serie - S01E02 - Titel 1080p" und "... 720p" zusammenfinden.
    core = re.split(r"\s*[\[\(]?\b(480p|576p|720p|1080[ip]|2160p|4k)\b", stem, maxsplit=1)[0]
    return re.compile(re.escape(core.strip()) + r".*", re.IGNORECASE)


def find_existing(dest: str, video_extensions: set[str]) -> list[Path]:
    """Sucht im Zielordner nach bereits vorhandenen Fassungen derselben Datei."""
    dest_path = Path(dest)
    folder = dest_path.parent
    if not folder.is_dir():
        return []
    pattern = _same_episode_pattern(dest_path)
    found = []
    for child in folder.iterdir():
        try:
            if not child.is_file() or child.suffix.lower() not in video_extensions:
                continue
        except OSError:
            continue
        if child.resolve() == dest_path.resolve():
            continue
        if pattern.match(child.stem):
            found.append(child)
    return found


def compare(new_guess: dict, new_size: int, new_path: str,
            existing: Path, existing_guess: dict) -> str:
    """'better', 'worse' oder 'equal' aus Sicht der neuen Datei."""
    try:
        existing_size = existing.stat().st_size
    except OSError:
        existing_size = 0
    new_score = quality_score(new_guess, new_size, new_path)
    old_score = quality_score(existing_guess, existing_size, str(existing))
    if new_score[:3] == old_score[:3]:
        # Gleiche Qualitätsmerkmale: erst ein deutlicher Größenunterschied zählt.
        if abs(new_size - existing_size) < max(existing_size * 0.05, 50 * 1024 * 1024):
            return "equal"
    return "better" if new_score > old_score else "worse"
