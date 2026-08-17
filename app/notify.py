"""Benachrichtigt Medienserver, wenn neue Dateien einsortiert wurden."""
import httpx

from . import logs

log = logs.get("notify")


async def _post(client: httpx.AsyncClient, url: str, **kwargs) -> bool:
    try:
        response = await client.request(kwargs.pop("method", "POST"), url, timeout=15, **kwargs)
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.error("Benachrichtigung an %s fehlgeschlagen: %s", url.split("?")[0], exc)
        return False


async def notify_all(settings: dict, summary: dict) -> dict:
    """Ruft Plex, Jellyfin und freie Webhooks auf. Fehler brechen nichts ab."""
    results = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        plex, token = settings.get("plex_url", "").rstrip("/"), settings.get("plex_token", "")
        if plex and token:
            # Ohne Section-Angabe aktualisiert Plex alle Bibliotheken.
            results["plex"] = await _post(
                client, f"{plex}/library/sections/all/refresh",
                method="GET", params={"X-Plex-Token": token})

        jelly = settings.get("jellyfin_url", "").rstrip("/")
        jelly_token = settings.get("jellyfin_token", "")
        if jelly and jelly_token:
            results["jellyfin"] = await _post(
                client, f"{jelly}/Library/Refresh",
                headers={"X-Emby-Token": jelly_token})

        for url in settings.get("webhook_urls", []):
            if url:
                results[url] = await _post(client, url, json=summary)

    if results:
        log.info("Medienserver benachrichtigt: %s",
                 ", ".join(f"{k}={'ok' if v else 'Fehler'}" for k, v in results.items()))
    return results
