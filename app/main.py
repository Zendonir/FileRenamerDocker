"""FastAPI-Backend für den Medien-Renamer."""
import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, cache, config, logs, naming, nfo, notify, renamer, scanner, scheduler
from .matcher import Matcher

STATIC_DIR = Path(__file__).parent / "static"

logs.setup()
log = logs.get("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("Media Renamer gestartet. Logdatei: %s", logs.LOG_FILE)
    auth.bootstrap()
    task = asyncio.create_task(scheduler.loop())
    yield
    task.cancel()
    log.info("Media Renamer wird beendet.")


app = FastAPI(title="Media Renamer", version="2.0.0", lifespan=lifespan)
app.middleware("http")(auth.middleware)

# Laufende und abgeschlossene Scan-Jobs; der letzte Lauf wird zusätzlich auf Platte gesichert.
JOBS: dict[str, dict] = {}
TASKS: dict[str, asyncio.Task] = {}


class Settings(BaseModel):
    tmdb_api_key: str | None = None
    tvdb_api_key: str | None = None
    language: str | None = None
    series_provider: str | None = None
    anime_provider: str | None = None
    anime_detection: str | None = None
    anime_keywords: list[str] | None = None
    anime_absolute: bool | None = None
    source_dirs: list[str] | None = None
    movie_target: str | None = None
    series_target: str | None = None
    anime_target: str | None = None
    movie_format: str | None = None
    series_format: str | None = None
    anime_format: str | None = None
    action: str | None = None
    min_confidence: float | None = None
    extensions: list[str] | None = None
    subtitle_extensions: list[str] | None = None
    min_size_mb: int | None = None
    use_folder_names: bool | None = None
    use_embedded_metadata: bool | None = None
    clean_empty_dirs: bool | None = None
    overwrite: bool | None = None
    check_library: bool | None = None
    duplicate_action: str | None = None
    auto_enabled: bool | None = None
    auto_interval_minutes: int | None = None
    auto_min_confidence: float | None = None
    auto_categories: list[str] | None = None
    auto_quiet_seconds: int | None = None
    webhook_urls: list[str] | None = None
    plex_url: str | None = None
    plex_token: str | None = None
    jellyfin_url: str | None = None
    jellyfin_token: str | None = None
    write_nfo: bool | None = None
    ascii_only: bool | None = None
    windows_safe: bool | None = None
    auth_enabled: bool | None = None
    auth_user: str | None = None
    auth_password: str | None = None


class ScanRequest(BaseModel):
    source_dirs: list[str] | None = None
    include_subtitles: bool = True


class SearchRequest(BaseModel):
    kind: str = "movie"
    query: str
    year: int | None = None
    provider: str | None = None


class SelectRequest(BaseModel):
    job_id: str
    src: str
    provider: str
    id: int
    kind: str = "movie"                  # movie | series | anime
    srcs: list[str] | None = None        # gesetzt: Zuweisung für mehrere Dateien


class CategoryRequest(BaseModel):
    job_id: str
    src: str
    category: str                # movie | series | anime


class ApplyItem(BaseModel):
    src: str
    dest: str


class ApplyRequest(BaseModel):
    items: list[ApplyItem] = Field(default_factory=list)
    action: str | None = None


class UndoRequest(BaseModel):
    times: list[float]


class LoginRequest(BaseModel):
    user: str
    password: str


LAST_SCAN_FILE = config.CONFIG_DIR / "last_scan.json"


def _save_job(job: dict) -> None:
    """Sichert den Lauf, damit ein Neustart die Durchsicht nicht vernichtet."""
    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LAST_SCAN_FILE.write_text(json.dumps(job, ensure_ascii=False), "utf-8")
    except (OSError, TypeError, ValueError) as exc:
        log.debug("Scan konnte nicht gesichert werden: %s", exc)


def _load_job() -> dict | None:
    try:
        if LAST_SCAN_FILE.exists():
            return json.loads(LAST_SCAN_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _find_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job:
        return job
    stored = _load_job()
    if stored and stored.get("id") == job_id:
        JOBS[job_id] = stored        # zurück in den Speicher holen, damit Änderungen greifen
        return stored
    raise HTTPException(status_code=404, detail="Job unbekannt.")


@app.get("/api/logs")
async def get_logs(level: str = "INFO", q: str = "", limit: int = 300,
                   after_id: int | None = None):
    """Log-Zeilen für die Web-Ansicht, neueste zuerst."""
    return logs.entries(level=level, query=q, limit=limit, after_id=after_id)


@app.get("/api/logs/download", response_class=PlainTextResponse)
async def download_logs(lines: int = 5000):
    """Rohes Logfile-Ende zum Herunterladen bzw. für Support-Anfragen."""
    return PlainTextResponse(
        logs.tail_file(lines),
        headers={"Content-Disposition": 'attachment; filename="renamer.log"'},
    )


@app.get("/api/health")
async def health():
    settings = config.load()
    return {
        "status": "ok",
        "tmdb_configured": bool(settings.get("tmdb_api_key")),
        "tvdb_configured": bool(settings.get("tvdb_api_key")),
    }


@app.get("/api/settings")
async def get_settings():
    settings = config.load()
    return {
        **settings,
        "tmdb_api_key": "***" if settings.get("tmdb_api_key") else "",
        "tvdb_api_key": "***" if settings.get("tvdb_api_key") else "",
        "plex_token": "***" if settings.get("plex_token") else "",
        "jellyfin_token": "***" if settings.get("jellyfin_token") else "",
        "auth_password_hash": "",
        "auth_configured": bool(settings.get("auth_password_hash")),
    }


@app.post("/api/settings")
async def post_settings(payload: Settings):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Maskierte Keys nicht zurückschreiben.
    for key in ("tmdb_api_key", "tvdb_api_key", "plex_token", "jellyfin_token"):
        if patch.get(key) == "***":
            patch.pop(key)
    # Klartext-Passwort nie speichern, nur den Hash.
    password = patch.pop("auth_password", None)
    if password:
        patch["auth_password_hash"] = auth.hash_password(password)
    config.save(patch)
    changed = [k for k in patch if k not in ("tmdb_api_key", "tvdb_api_key")]
    log.info("Einstellungen geändert: %s", ", ".join(changed) or "API-Keys")
    return await get_settings()


@app.get("/api/browse")
async def browse(path: str = "/"):
    return scanner.browse(path)


@app.post("/api/preview-format")
async def preview_format(payload: dict):
    """Testet ein Format-Template mit Beispieldaten."""
    kind = payload.get("kind", "movie")
    template = payload.get("template", "")
    samples = {
        "movie": {
            "name": "Der Pate", "year": 1972, "collection": "Der Pate Reihe",
            "imdb_id": "tt0068646", "part": None,
        },
        "series": {
            "name": "Dark", "year": 2017, "season": 2, "episodes": [5], "episode": 5,
            "episode_title": "Lost", "absolute": 13, "air_date": "2019-06-21",
        },
        "anime": {
            "name": "Shingeki no Kyojin", "year": 2013, "season": 1, "episodes": [3],
            "episode": 3, "episode_title": "Nacht der Abschlussfeier", "absolute": 3,
            "air_date": "2013-04-21",
        },
    }
    sample = {
        **samples.get(kind, samples["movie"]),
        "resolution": "1080p", "video_codec": "H.264", "audio_codec": "DTS",
        "source": "Blu-ray", "release_group": "GROUP", "languages": ["de", "ja"],
        "extension": ".mkv",
    }
    try:
        return {"preview": naming.format_path(template, sample) + ".mkv"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _run_scan(job_id: str, source_dirs: list[str], include_subtitles: bool):
    job = JOBS[job_id]
    settings = config.load()
    log.info("Scan gestartet in: %s", ", ".join(source_dirs))
    try:
        entries = scanner.scan(
            source_dirs,
            settings["extensions"],
            settings["min_size_mb"],
            include_subtitles,
            settings["subtitle_extensions"],
        )
        job["total"] = len(entries)
        log.info("Scan: %d Datei(en) gefunden.", len(entries))
        if not entries:
            job["status"] = "done"
            log.warning("Keine passenden Dateien gefunden — Quellordner und Endungen prüfen.")
            return

        matcher = Matcher(settings)

        def progress(item):
            job["done"] += 1
            job["current"] = item["name"]

        job["items"] = await matcher.process(
            entries,
            on_progress=progress,
            is_cancelled=lambda: job.get("cancel", False),
        )
        job["done"] = len(job["items"])
        job["status"] = "cancelled" if job.get("cancel") else "done"
        counts = {s: sum(1 for i in job["items"] if i["status"] == s)
                  for s in ("matched", "review", "unmatched")}
        log.info("Scan beendet: %d erkannt, %d zu prüfen, %d ohne Treffer.",
                 counts["matched"], counts["review"], counts["unmatched"])
    except Exception as exc:  # Job-Fehler landen sichtbar im Webinterface.
        job["status"] = "error"
        job["error"] = str(exc)
        log.exception("Scan abgebrochen: %s", exc)
    finally:
        job["finished"] = time.time()
        _save_job(job)


@app.post("/api/scan")
async def start_scan(payload: ScanRequest):
    settings = config.load()
    if not settings.get("tmdb_api_key") and not settings.get("tvdb_api_key"):
        raise HTTPException(status_code=400, detail="Bitte zuerst einen TMDB- oder TVDB-API-Key hinterlegen.")
    source_dirs = payload.source_dirs or settings["source_dirs"]
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"id": job_id, "status": "running", "total": 0, "done": 0,
                    "items": [], "error": None, "cancel": False, "current": None,
                    "started": time.time(), "finished": None}
    # Ältere Jobs verwerfen, damit der Speicher nicht unbegrenzt wächst.
    for old in list(JOBS)[:-20]:
        JOBS.pop(old, None)
    # Referenz außerhalb des Jobs halten: der Job wird als JSON ausgeliefert,
    # ein Task-Objekt darin würde die Serialisierung sprengen.
    task = asyncio.create_task(_run_scan(job_id, source_dirs, payload.include_subtitles))
    TASKS[job_id] = task
    task.add_done_callback(lambda _: TASKS.pop(job_id, None))
    return {"job_id": job_id}


@app.get("/api/scan/{job_id}")
async def scan_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        # Nach einem Neustart liegt nur noch der zuletzt gespeicherte Lauf vor.
        stored = _load_job()
        if stored and stored.get("id") == job_id:
            return stored
        raise HTTPException(status_code=404, detail="Job unbekannt.")
    return job


@app.post("/api/scan/{job_id}/cancel")
async def cancel_scan(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job unbekannt.")
    job["cancel"] = True
    log.warning("Scan wurde abgebrochen.")
    return {"status": "cancelling"}


@app.get("/api/scan")
async def last_scan():
    """Der zuletzt abgeschlossene Lauf – überlebt einen Neustart des Containers."""
    running = next((j for j in reversed(list(JOBS.values())) if j["status"] == "running"), None)
    if running:
        return running
    for job in reversed(list(JOBS.values())):
        return job
    stored = _load_job()
    if stored:
        return stored
    raise HTTPException(status_code=404, detail="Noch kein Scan vorhanden.")


@app.post("/api/search")
async def search(payload: SearchRequest):
    matcher = Matcher(config.load())
    try:
        async with httpx.AsyncClient() as client:
            results = await matcher.search(client, payload.kind, payload.query,
                                           payload.year, payload.provider)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"results": results}


@app.post("/api/select")
async def select(payload: SelectRequest):
    """Weist einen Treffer zu – wahlweise einer Datei oder gleich einer ganzen Serie."""
    job = _find_job(payload.job_id)
    wanted = set(payload.srcs) if payload.srcs else {payload.src}
    items = [i for i in job["items"] if i["src"] in wanted]
    if not items:
        raise HTTPException(status_code=404, detail="Datei im Job nicht gefunden.")

    category = payload.kind if payload.kind in ("movie", "series", "anime") else "movie"
    settings = config.load()
    matcher = Matcher(settings)

    async with httpx.AsyncClient() as client:
        source = matcher.tvdb if payload.provider == "tvdb" else matcher.tmdb
        try:
            if category == "movie":
                match = await matcher.tmdb.movie_details(client, payload.id)
            else:
                match = await source.series_details(client, payload.id)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        updated, failed = [], []
        for item in items:
            guess = dict(item["guess"])
            guess["type"] = "movie" if category == "movie" else "episode"
            episodes = None
            if category != "movie":
                try:
                    episodes = await matcher.episodes_for(client, category, payload.provider,
                                                          payload.id, guess)
                except (httpx.HTTPError, RuntimeError) as exc:
                    failed.append({"src": item["src"], "error": str(exc)})
                    continue
            try:
                dest = matcher.destination(guess, match, Path(item["src"]), episodes, category)
            except ValueError as exc:
                failed.append({"src": item["src"], "error": str(exc)})
                continue
            item.update({"guess": guess, "match": match, "confidence": 1.0,
                         "status": "matched", "category": category, "error": None,
                         "dest": dest})
            matcher.check_library(item)
            updated.append(item)

    # Untertitel im selben Job ziehen automatisch nach.
    Matcher(settings).attach_subtitles(job["items"])
    _save_job(job)
    log.info("Manuell zugewiesen: %d Datei(en) [%s] -> '%s' (%s #%s)",
             len(updated), category, match.get("title"), payload.provider, payload.id)
    if failed:
        log.warning("Zuweisung fehlgeschlagen für %d Datei(en).", len(failed))
    return {"items": updated, "failed": failed, "item": updated[0] if updated else None}


@app.get("/api/group/{job_id}")
async def group(job_id: str, src: str):
    """Alle Dateien des Jobs, die zum selben erkannten Titel gehören."""
    job = _find_job(job_id)
    item = next((i for i in job["items"] if i["src"] == src), None)
    if not item:
        raise HTTPException(status_code=404, detail="Datei im Job nicht gefunden.")
    title = _normalize_title(item["guess"].get("title"))
    if not title:
        return {"srcs": [src], "title": None}
    same = [i["src"] for i in job["items"]
            if not i.get("is_subtitle")
            and _normalize_title(i["guess"].get("title")) == title]
    return {"srcs": same, "title": item["guess"].get("title")}


def _normalize_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


@app.post("/api/category")
async def set_category(payload: CategoryRequest):
    """Kategorie einer Datei umschalten (z. B. Serie -> Anime) und Ziel neu berechnen."""
    if payload.category not in ("movie", "series", "anime"):
        raise HTTPException(status_code=400, detail="Unbekannte Kategorie.")
    job = _find_job(payload.job_id)
    item = next((i for i in job["items"] if i["src"] == payload.src), None)
    if not item:
        raise HTTPException(status_code=404, detail="Datei im Job nicht gefunden.")
    if not item.get("match"):
        raise HTTPException(status_code=400, detail="Erst einen Treffer zuweisen.")

    matcher = Matcher(config.load())
    guess = dict(item["guess"])
    guess["type"] = "movie" if payload.category == "movie" else "episode"
    match = item["match"]

    episodes = None
    if payload.category != "movie":
        async with httpx.AsyncClient() as client:
            try:
                episodes = await matcher.episodes_for(
                    client, payload.category, match.get("provider", "tvdb"), match["id"], guess)
            except (httpx.HTTPError, RuntimeError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

    item["guess"] = guess
    item["category"] = payload.category
    try:
        item["dest"] = matcher.destination(guess, match, Path(payload.src),
                                           episodes, payload.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("Kategorie geändert: %s -> %s", Path(payload.src).name, payload.category)
    return item


@app.post("/api/apply")
async def apply(payload: ApplyRequest):
    settings = config.load()
    action = payload.action or settings["action"]
    if not payload.items:
        raise HTTPException(status_code=400, detail="Keine Dateien ausgewählt.")
    # Die Bibliotheks-Info steckt im letzten Scan, nicht in der Anfrage.
    known = {i["src"]: i for job in JOBS.values() for i in job.get("items", [])}
    items = []
    for entry in payload.items:
        data = entry.model_dump()
        source = known.get(data["src"])
        if source:
            data["existing"] = source.get("existing")
        items.append(data)

    result = await asyncio.to_thread(
        renamer.apply, items, action, settings["overwrite"],
        settings["clean_empty_dirs"], settings["source_dirs"],
        settings.get("duplicate_action", "skip"),
    )

    if settings.get("write_nfo") and action != "test":
        written = 0
        for entry in result["results"]:
            item = known.get(entry["src"])
            if entry["ok"] and item and not item.get("is_subtitle") and nfo.write(item, entry["dest"]):
                written += 1
        result["nfo_written"] = written

    if result["ok"] and action != "test":
        await notify.notify_all(settings, {"applied": result["ok"], "action": action})
    return result


@app.post("/api/login")
async def login(payload: LoginRequest, request: Request):
    settings = config.load()
    stored = settings.get("auth_password_hash", "")
    ok = (payload.user == settings.get("auth_user", "admin")
          and stored and auth.verify_password(payload.password, stored))
    if not ok:
        log.warning("Fehlgeschlagener Anmeldeversuch für Benutzer '%s'.", payload.user)
        raise HTTPException(status_code=401, detail="Benutzer oder Passwort falsch.")
    token = auth.create_session()
    response = JSONResponse({"status": "ok"})
    response.set_cookie(auth.COOKIE, token, **auth.cookie_kwargs(request))
    log.info("Anmeldung erfolgreich: %s", payload.user)
    return response


@app.post("/api/logout")
async def logout(request: Request):
    auth.drop_session(request.cookies.get(auth.COOKIE))
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(auth.COOKIE, path="/")
    return response


@app.get("/login")
async def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/api/auto")
async def auto_status():
    settings = config.load()
    return {
        **scheduler.STATE,
        "enabled": settings.get("auto_enabled", False),
        "interval_minutes": settings.get("auto_interval_minutes", 60),
    }


@app.post("/api/auto/run")
async def auto_run(dry_run: bool = False):
    """Startet einen Automatiklauf sofort, unabhängig vom Zeitplan."""
    if scheduler.STATE.get("running"):
        raise HTTPException(status_code=409, detail="Es läuft bereits ein Automatiklauf.")
    return await scheduler.run_once(dry_run=dry_run)


@app.post("/api/notify-test")
async def notify_test():
    """Prüft die Verbindung zu Plex, Jellyfin und den Webhooks."""
    return await notify.notify_all(config.load(), {"test": True})


@app.get("/api/cache")
async def cache_stats():
    return cache.stats()


@app.delete("/api/cache")
async def cache_clear():
    count = cache.clear()
    log.info("Cache geleert: %d Einträge entfernt.", count)
    return {"cleared": count}


@app.get("/api/history")
async def history(limit: int = 200):
    return {"entries": config.load_history()[:limit]}


@app.post("/api/undo")
async def undo(payload: UndoRequest):
    settings = config.load()
    targets = [settings[k] for k in ("movie_target", "series_target", "anime_target")]
    return await asyncio.to_thread(renamer.undo, payload.times, targets)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
