"""Optionales Herunterladen von Postern, Hintergrundbildern und Episodenbildern.

Die Dateinamen folgen den Konventionen, die Kodi, Jellyfin und Emby lesen.
Standardmäßig ist die Funktion abgeschaltet; ohne sie wird nichts geladen.
"""
from pathlib import Path

import httpx

from . import logs

log = logs.get("artwork")

MAX_BYTES = 20 * 1024 * 1024          # ein Poster ist nie größer
ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _show_folder(dest: Path, target: str) -> Path | None:
    """Der Serienordner unterhalb des Zielordners, falls es einen gibt."""
    try:
        parts = dest.relative_to(Path(target)).parts
    except ValueError:
        return None
    return Path(target) / parts[0] if len(parts) >= 2 else None


def targets(item: dict, dest: str, settings: dict) -> list[tuple[str, Path]]:
    """Liefert Paare aus Bild-URL und Zieldatei – ohne etwas herunterzuladen."""
    match = item.get("match") or {}
    category = item.get("category", "movie")
    dest_path = Path(dest)
    plan: list[tuple[str, Path]] = []

    if category == "movie":
        folder = dest_path.parent
        target_root = Path(settings.get("movie_target", ""))
        # Liegt der Film in einem eigenen Ordner, gehören die Bilder dorthin.
        own_folder = folder != target_root
        if match.get("poster_url"):
            plan.append((match["poster_url"],
                         folder / ("poster.jpg" if own_folder else f"{dest_path.stem}-poster.jpg")))
        if match.get("fanart_url"):
            plan.append((match["fanart_url"],
                         folder / ("fanart.jpg" if own_folder else f"{dest_path.stem}-fanart.jpg")))
        return plan

    target_root = settings.get(f"{category}_target", "")
    show = _show_folder(dest_path, target_root)
    if show:
        if match.get("poster_url"):
            plan.append((match["poster_url"], show / "poster.jpg"))
        if match.get("fanart_url"):
            plan.append((match["fanart_url"], show / "fanart.jpg"))

        season = (item.get("guess") or {}).get("season")
        poster = (match.get("season_posters") or {}).get(season) \
            or (match.get("season_posters") or {}).get(str(season))
        if poster is not None and season is not None:
            # Kodi erwartet die Staffelposter im Serienordner, Jellyfin im Staffelordner.
            plan.append((poster, show / f"season{int(season):02d}-poster.jpg"))
            if dest_path.parent != show:
                plan.append((poster, dest_path.parent / "poster.jpg"))

    if item.get("thumb_url"):
        plan.append((item["thumb_url"], dest_path.with_suffix("").with_name(
            dest_path.stem + "-thumb.jpg")))
    return plan


async def download_one(client: httpx.AsyncClient, url: str, path: Path,
                       overwrite: bool = False) -> bool:
    """Lädt ein einzelnes Bild. Fehler werden protokolliert, nie geworfen."""
    if path.exists() and not overwrite:
        return False
    try:
        response = await client.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            log.warning("Kein Bild unter %s (%s) – übersprungen.", url, content_type)
            return False
        data = response.content
        if len(data) > MAX_BYTES:
            log.warning("Bild zu groß (%.1f MB), übersprungen: %s", len(data) / 1024 / 1024, url)
            return False
        if not data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return True
    except (httpx.HTTPError, OSError) as exc:
        log.error("Bild nicht ladbar (%s): %s", path.name, exc)
        return False


async def enrich(items: list[dict], settings: dict) -> None:
    """Holt die Bild-URLs nach – Suchergebnisse enthalten sie noch nicht.

    Läuft nur bei eingeschaltetem Artwork und dank Cache je Serie nur einmal.
    """
    from .matcher import Matcher  # lokal, um einen Import-Kreis zu vermeiden

    matcher = Matcher(settings)
    fetched: dict[tuple, dict] = {}
    async with httpx.AsyncClient() as client:
        for item in items:
            match = item.get("match") or {}
            if not match.get("id") or "poster_url" in match:
                continue
            key = (match.get("provider"), match["id"], item.get("category"))
            if key not in fetched:
                try:
                    if item.get("category") == "movie":
                        details = await matcher.tmdb.movie_details(client, match["id"])
                    else:
                        source = matcher.tvdb if match.get("provider") == "tvdb" else matcher.tmdb
                        details = await source.series_details(client, match["id"])
                except (httpx.HTTPError, RuntimeError) as exc:
                    log.error("Bilddaten zu '%s' nicht abrufbar: %s", match.get("title"), exc)
                    details = {}
                fetched[key] = details
            for field in ("poster_url", "fanart_url", "season_posters"):
                if fetched[key].get(field) is not None:
                    match[field] = fetched[key][field]
            match.setdefault("poster_url", None)      # nicht erneut nachschlagen


async def download(items: list[dict], destinations: dict, settings: dict) -> int:
    """Lädt die Bilder für alle erfolgreich verschobenen Dateien."""
    if not settings.get("download_artwork"):
        return 0

    relevant = [i for i in items
                if destinations.get(i["src"]) and not i.get("is_subtitle") and i.get("match")]
    if not relevant:
        return 0
    await enrich(relevant, settings)

    plan: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for item in items:
        dest = destinations.get(item["src"])
        if not dest or item.get("is_subtitle") or not item.get("match"):
            continue
        for url, path in targets(item, dest, settings):
            if path not in seen:
                seen.add(path)
                plan.append((url, path))

    if not plan:
        return 0

    written = 0
    async with httpx.AsyncClient() as client:
        for url, path in plan:
            if await download_one(client, url, path):
                written += 1
    if written:
        log.info("%d Bilddatei(en) abgelegt.", written)
    return written
