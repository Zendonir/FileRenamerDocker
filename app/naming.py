"""Format-Engine für Zielpfade (FileBot-ähnliche Platzhalter).

Unterstützte Ausdrücke innerhalb von {...}:
  {n}              Wert einsetzen, leer wenn nicht vorhanden
  {s.pad(2)}       Zahl links mit Nullen auffüllen
  {'CD '+pi}       Literale werden nur ausgegeben, wenn alle Variablen gefüllt sind
  {n|t}            Fallback: erster gefüllter Wert gewinnt
"""
import re

INVALID = r'[<>:"/\\|?*\x00-\x1f]'
RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_TOKEN = re.compile(r"\{([^{}]*)\}")
_PAD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.pad\((\d+)\)$")


TRANSLITERATE = {
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
    "à": "a", "á": "a", "â": "a", "ã": "a", "å": "a", "æ": "ae",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ç": "c", "ñ": "n",
    "ì": "i", "í": "i", "î": "i", "ï": "i", "ø": "o", "ò": "o", "ó": "o", "ô": "o",
    "ù": "u", "ú": "u", "û": "u", "ý": "y", "š": "s", "ž": "z", "–": "-", "—": "-",
    "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
}


def to_ascii(text: str) -> str:
    """Schreibt Umlaute und Sonderzeichen aus – für SMB-Freigaben an alte Clients."""
    out = "".join(TRANSLITERATE.get(char, char) for char in text)
    return out.encode("ascii", "ignore").decode("ascii")


def sanitize(name: str, replacement: str = "", ascii_only: bool = False,
             windows_safe: bool = True) -> str:
    """Entfernt für Dateisysteme unzulässige Zeichen aus einem Pfadsegment."""
    cleaned = re.sub(INVALID, replacement, name)
    if ascii_only:
        cleaned = to_ascii(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if windows_safe:
        # Windows und SMB stolpern über Punkte und Leerzeichen am Ende.
        cleaned = cleaned.rstrip(". ")
    else:
        cleaned = cleaned.strip(".")
    if cleaned.upper() in RESERVED or cleaned.split(".")[0].upper() in RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:200].strip()


def _resolve(name: str, ctx: dict):
    value = ctx.get(name)
    if value is None or value == "" or value == []:
        return None
    return value


def _eval_part(part: str, ctx: dict):
    part = part.strip()
    if not part:
        return None
    if part.startswith("'") and part.endswith("'") and len(part) >= 2:
        return part[1:-1]
    pad = _PAD.match(part)
    if pad:
        value = _resolve(pad.group(1), ctx)
        if value is None:
            return None
        try:
            return str(int(value)).zfill(int(pad.group(2)))
        except (TypeError, ValueError):
            return str(value)
    value = _resolve(part, ctx)
    return None if value is None else str(value)


def _eval_expr(expr: str, ctx: dict) -> str:
    # Fallback-Kette: {n|t} -> erster gefüllter Wert
    for alternative in expr.split("|"):
        parts = [p for p in alternative.split("+")]
        values = [_eval_part(p, ctx) for p in parts]
        literals_only = all(p.strip().startswith("'") for p in parts)
        # Ein Verbund fällt komplett weg, sobald eine Variable darin leer ist.
        if any(v is None for v in values) and not literals_only:
            continue
        result = "".join(v for v in values if v is not None)
        if result:
            return result
    return ""


def _episode_tokens(ctx: dict) -> dict:
    season = ctx.get("s")
    episodes = ctx.get("_episodes") or ([ctx["e"]] if ctx.get("e") is not None else [])
    tokens = {}
    if episodes:
        try:
            nums = [int(e) for e in episodes]
        except (TypeError, ValueError):
            nums = []
        if nums:
            s_part = f"S{int(season):02d}" if season is not None else ""
            tokens["s00e00"] = s_part + "".join(f"E{n:02d}" for n in nums)
            tokens["e00"] = "-".join(f"{n:02d}" for n in nums)
            tokens["sxe"] = f"{int(season)}x" + "-".join(f"{n:02d}" for n in nums) if season is not None else ""
    return tokens


def build_context(info: dict) -> dict:
    """Baut die Platzhalter-Tabelle aus Metadaten + erkannten Release-Infos."""
    ctx = {
        "n": info.get("name"),
        "y": info.get("year"),
        "s": info.get("season"),
        "e": info.get("episode"),
        "t": info.get("episode_title"),
        "_episodes": info.get("episodes"),
        "abs": info.get("absolute"),
        "airdate": info.get("air_date"),
        "vf": info.get("resolution"),
        "vc": info.get("video_codec"),
        "ac": info.get("audio_codec"),
        "source": info.get("source"),
        "group": info.get("release_group"),
        "pi": info.get("part"),
        "collection": info.get("collection"),
        "imdb": info.get("imdb_id"),
        "id": info.get("provider_id"),
        "lang": ", ".join(info.get("languages") or []) or None,
        "ext": (info.get("extension") or "").lstrip("."),
    }
    ctx.update(_episode_tokens(ctx))
    return {k: v for k, v in ctx.items() if v is not None and v != ""}


def format_path(template: str, info: dict, ascii_only: bool = False,
                windows_safe: bool = True) -> str:
    """Rendert ein Template zu einem relativen Pfad (ohne Dateiendung)."""
    ctx = build_context(info)
    # Nur das Template selbst darf Ordnergrenzen setzen — Werte aus den
    # Metadaten dürfen keine zusätzlichen Pfadebenen erzeugen.
    rendered = _TOKEN.sub(
        lambda m: _eval_expr(m.group(1), ctx).replace("/", "").replace("\\", ""),
        template,
    )
    segments = [sanitize(seg, ascii_only=ascii_only, windows_safe=windows_safe)
                for seg in rendered.split("/")]
    segments = [seg for seg in segments if seg]
    if not segments:
        raise ValueError("Format ergibt einen leeren Pfad.")
    return "/".join(segments)
