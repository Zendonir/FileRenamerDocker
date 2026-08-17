"""FastAPI-Backend für den Medien-Renamer."""
import asyncio
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, naming, renamer, scanner
from .matcher import Matcher

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Media Renamer", version="1.0.0")

# Laufende und abgeschlossene Scan-Jobs (Prozess-lokal, bewusst nicht persistiert).
JOBS: dict[str, dict] = {}


class Settings(BaseModel):
    tmdb_api_key: str | None = None
    tvdb_api_key: str | None = None
    language: str | None = None
    series_provider: str | None = None
    source_dirs: list[str] | None = None
    movie_target: str | None = None
    series_target: str | None = None
    movie_format: str | None = None
    series_format: str | None = None
    action: str | None = None
    min_confidence: float | None = None
    extensions: list[str] | None = None
    subtitle_extensions: list[str] | None = None
    min_size_mb: int | None = None
    clean_empty_dirs: bool | None = None
    overwrite: bool | None = None


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
    kind: str = "movie"


class ApplyItem(BaseModel):
    src: str
    dest: str


class ApplyRequest(BaseModel):
    items: list[ApplyItem] = Field(default_factory=list)
    action: str | None = None


class UndoRequest(BaseModel):
    times: list[float]


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
    }


@app.post("/api/settings")
async def post_settings(payload: Settings):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Maskierte Keys nicht zurückschreiben.
    for key in ("tmdb_api_key", "tvdb_api_key"):
        if patch.get(key) == "***":
            patch.pop(key)
    config.save(patch)
    return await get_settings()


@app.get("/api/browse")
async def browse(path: str = "/"):
    return scanner.browse(path)


@app.post("/api/preview-format")
async def preview_format(payload: dict):
    """Testet ein Format-Template mit Beispieldaten."""
    kind = payload.get("kind", "movie")
    template = payload.get("template", "")
    sample = {
        "name": "Beispiel Serie" if kind == "series" else "Beispiel Film",
        "year": 2021,
        "season": 2,
        "episodes": [5],
        "episode": 5,
        "episode_title": "Die Rückkehr",
        "resolution": "1080p",
        "video_codec": "H.264",
        "audio_codec": "DTS",
        "source": "Blu-ray",
        "release_group": "GROUP",
        "extension": ".mkv",
    }
    try:
        return {"preview": naming.format_path(template, sample) + ".mkv"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _run_scan(job_id: str, source_dirs: list[str], include_subtitles: bool):
    job = JOBS[job_id]
    settings = config.load()
    try:
        entries = scanner.scan(
            source_dirs,
            settings["extensions"],
            settings["min_size_mb"],
            include_subtitles,
            settings["subtitle_extensions"],
        )
        job["total"] = len(entries)
        if not entries:
            job["status"] = "done"
            return

        matcher = Matcher(settings)
        async with httpx.AsyncClient() as client:
            semaphore = asyncio.Semaphore(5)

            async def run(entry):
                async with semaphore:
                    item = await matcher.process_file(client, entry)
                    job["items"].append(item)
                    job["done"] = len(job["items"])
                    return item

            await asyncio.gather(*(run(e) for e in entries))
        job["status"] = "done"
    except Exception as exc:  # Job-Fehler landen sichtbar im Webinterface.
        job["status"] = "error"
        job["error"] = str(exc)


@app.post("/api/scan")
async def start_scan(payload: ScanRequest):
    settings = config.load()
    if not settings.get("tmdb_api_key") and not settings.get("tvdb_api_key"):
        raise HTTPException(status_code=400, detail="Bitte zuerst einen TMDB- oder TVDB-API-Key hinterlegen.")
    source_dirs = payload.source_dirs or settings["source_dirs"]
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"id": job_id, "status": "running", "total": 0, "done": 0,
                    "items": [], "error": None}
    # Ältere Jobs verwerfen, damit der Speicher nicht unbegrenzt wächst.
    for old in list(JOBS)[:-20]:
        JOBS.pop(old, None)
    asyncio.create_task(_run_scan(job_id, source_dirs, payload.include_subtitles))
    return {"job_id": job_id}


@app.get("/api/scan/{job_id}")
async def scan_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job unbekannt.")
    return job


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
    """Weist einer Datei manuell einen Treffer zu und berechnet den Zielpfad neu."""
    job = JOBS.get(payload.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job unbekannt.")
    item = next((i for i in job["items"] if i["src"] == payload.src), None)
    if not item:
        raise HTTPException(status_code=404, detail="Datei im Job nicht gefunden.")

    settings = config.load()
    matcher = Matcher(settings)
    guess = dict(item["guess"])
    guess["type"] = "episode" if payload.kind == "series" else "movie"

    async with httpx.AsyncClient() as client:
        source = matcher.tvdb if payload.provider == "tvdb" else matcher.tmdb
        try:
            if guess["type"] == "episode":
                match = await source.series_details(client, payload.id)
                episodes = None
                if guess.get("season") is not None:
                    episodes = [
                        await matcher._episode_info(client, payload.provider, payload.id,
                                                    guess["season"], ep)
                        for ep in (guess.get("episodes") or [])
                    ]
            else:
                match = await matcher.tmdb.movie_details(client, payload.id)
                episodes = None
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    item["guess"] = guess
    item["match"] = match
    item["confidence"] = 1.0
    item["status"] = "matched"
    item["error"] = None
    try:
        item["dest"] = matcher.destination(guess, match, Path(payload.src), episodes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@app.post("/api/apply")
async def apply(payload: ApplyRequest):
    settings = config.load()
    action = payload.action or settings["action"]
    if not payload.items:
        raise HTTPException(status_code=400, detail="Keine Dateien ausgewählt.")
    return await asyncio.to_thread(
        renamer.apply,
        [i.model_dump() for i in payload.items],
        action,
        settings["overwrite"],
        settings["clean_empty_dirs"],
        settings["source_dirs"],
    )


@app.get("/api/history")
async def history(limit: int = 200):
    return {"entries": config.load_history()[:limit]}


@app.post("/api/undo")
async def undo(payload: UndoRequest):
    return await asyncio.to_thread(renamer.undo, payload.times)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
