"""Dateinamen-Analyse auf Basis von guessit."""
from pathlib import Path

from guessit import guessit


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _join(value):
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value is not None else None


def parse(path: str) -> dict:
    """Liefert normalisierte Metadaten aus Dateiname und Ordnerstruktur."""
    p = Path(path)
    # Ordnername mitgeben: liefert bei "Serie/Season 01/01.mkv" deutlich bessere Treffer.
    hint = str(Path(p.parent.name) / p.name)
    guess = dict(guessit(hint))
    if not guess.get("title"):
        guess = dict(guessit(p.name))

    seasons = guess.get("season")
    episodes = guess.get("episode")
    if isinstance(seasons, list):
        seasons = seasons[0]
    episode_list = episodes if isinstance(episodes, list) else ([episodes] if episodes is not None else [])

    kind = guess.get("type", "movie")
    if episode_list or seasons is not None:
        kind = "episode"

    return {
        "type": "episode" if kind == "episode" else "movie",
        "title": guess.get("title"),
        "year": guess.get("year"),
        "season": seasons,
        "episodes": episode_list,
        "episode_title": guess.get("episode_title"),
        "part": _first(guess.get("part")) or _first(guess.get("cd")),
        "source": _join(guess.get("source")),
        "resolution": guess.get("screen_size"),
        "video_codec": _join(guess.get("video_codec")),
        "audio_codec": _join(guess.get("audio_codec")),
        "release_group": guess.get("release_group"),
        "languages": [str(x) for x in guess.get("language", [])] if isinstance(guess.get("language"), list)
        else ([str(guess["language"])] if guess.get("language") else []),
        "subtitle_language": str(guess["subtitle_language"]) if guess.get("subtitle_language") else None,
        "container": guess.get("container"),
    }
