"""Gemeinsame HTTP-Logik der Datenbank-Anbindungen: Wiederholversuche und Cache."""
import asyncio

import httpx

from .. import cache, logs

log = logs.get("http")

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4


async def request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Führt eine Anfrage aus und wiederholt sie bei Rate-Limit oder Serverfehler.

    Bei 429 wird der vom Dienst genannte Retry-After-Wert respektiert, sonst
    wird die Wartezeit verdoppelt (1s, 2s, 4s).
    """
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS - 1:
                raise
            await asyncio.sleep(2 ** attempt)
            continue

        if response.status_code not in RETRY_STATUS or attempt == MAX_ATTEMPTS - 1:
            return response

        delay = 2 ** attempt
        if response.status_code == 429:
            header = response.headers.get("retry-after")
            if header:
                try:
                    delay = min(float(header), 60)
                except ValueError:
                    pass
            log.warning("Rate-Limit erreicht, warte %.0fs und versuche es erneut.", delay)
        else:
            log.warning("Antwort %s von %s, neuer Versuch in %ss.",
                        response.status_code, url.split("?")[0], delay)
        await asyncio.sleep(delay)

    if last_error:
        raise last_error
    return response


async def cached_json(client: httpx.AsyncClient, key: str, url: str, *,
                      use_cache: bool = True, **kwargs) -> dict:
    """GET mit Wiederholversuchen und dauerhaftem Cache."""
    if use_cache:
        hit = cache.get(key)
        if hit is not None:
            return hit
    response = await request(client, "GET", url, **kwargs)
    response.raise_for_status()
    data = response.json()
    if use_cache:
        cache.put(key, data)
    return data
