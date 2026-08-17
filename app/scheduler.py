"""Automatikbetrieb: scannt in festem Takt und verschiebt sichere Treffer selbst."""
import asyncio
import time
from pathlib import Path

from . import config, logs, nfo, notify, renamer, scanner
from .matcher import Matcher

log = logs.get("auto")

STATE = {
    "running": False,
    "last_run": None,
    "next_run": None,
    "last_result": None,
    "active": False,
}


def is_settled(path: str, quiet_seconds: int) -> bool:
    """Ist die Datei fertig geschrieben (bzw. der Download abgeschlossen)?"""
    try:
        stat = Path(path).stat()
    except OSError:
        return False
    return (time.time() - stat.st_mtime) >= quiet_seconds


async def run_once(settings: dict | None = None, dry_run: bool = False) -> dict:
    """Ein vollständiger Automatiklauf. Liefert eine Zusammenfassung."""
    settings = settings or config.load()
    summary = {"scanned": 0, "applied": 0, "skipped": 0, "failed": 0,
               "waiting": 0, "review": 0, "time": time.time()}

    entries = scanner.scan(
        settings["source_dirs"], settings["extensions"], settings["min_size_mb"],
        True, settings["subtitle_extensions"],
    )
    summary["scanned"] = len(entries)
    if not entries:
        log.info("Automatiklauf: keine Dateien gefunden.")
        STATE["last_result"] = summary
        return summary

    # Dateien, die gerade noch geschrieben werden, bleiben liegen.
    quiet = int(settings.get("auto_quiet_seconds", 120))
    ready = [e for e in entries if is_settled(e["path"], quiet)]
    summary["waiting"] = len(entries) - len(ready)
    if summary["waiting"]:
        log.info("Automatiklauf: %d Datei(en) werden noch geschrieben, warte.", summary["waiting"])
    if not ready:
        STATE["last_result"] = summary
        return summary

    items = await Matcher(settings).process(ready)

    threshold = float(settings.get("auto_min_confidence", 0.9))
    categories = set(settings.get("auto_categories", ["movie", "series", "anime"]))
    chosen, held = [], []
    for item in items:
        if not item.get("dest") or item.get("status") == "unmatched":
            held.append(item)
        elif item["confidence"] < threshold or item.get("category") not in categories:
            held.append(item)
        else:
            chosen.append(item)
    summary["review"] = len(held)

    if not chosen:
        log.info("Automatiklauf: nichts sicher genug erkannt (%d zur Durchsicht).", len(held))
        STATE["last_result"] = summary
        return summary

    if dry_run:
        summary["applied"] = len(chosen)
        log.info("Testlauf: %d Datei(en) wären verarbeitet worden.", len(chosen))
        STATE["last_result"] = summary
        return summary

    result = await asyncio.to_thread(
        renamer.apply, chosen, settings["action"], settings["overwrite"],
        settings["clean_empty_dirs"], settings["source_dirs"],
        settings.get("duplicate_action", "skip"),
    )
    summary["applied"] = result["ok"]
    summary["failed"] = result["failed"]
    summary["skipped"] = result.get("skipped", 0)

    if settings.get("write_nfo"):
        done = {r["src"]: r["dest"] for r in result["results"] if r["ok"]}
        for item in chosen:
            if item["src"] in done and not item.get("is_subtitle"):
                nfo.write(item, done[item["src"]])

    log.info("Automatiklauf beendet: %d verschoben, %d übersprungen, %d Fehler, "
             "%d zur Durchsicht.", summary["applied"], summary["skipped"],
             summary["failed"], summary["review"])

    if summary["applied"]:
        await notify.notify_all(settings, summary)

    STATE["last_result"] = summary
    return summary


async def loop() -> None:
    """Hintergrundschleife; liest die Einstellungen bei jedem Durchgang neu."""
    STATE["active"] = True
    log.info("Automatikbetrieb gestartet.")
    try:
        while True:
            settings = config.load()
            if not settings.get("auto_enabled"):
                STATE["next_run"] = None
                await asyncio.sleep(30)
                continue

            interval = max(int(settings.get("auto_interval_minutes", 60)), 5) * 60
            STATE["running"] = True
            try:
                await run_once(settings)
            except Exception as exc:            # Ein Fehler darf die Schleife nie beenden.
                log.exception("Automatiklauf fehlgeschlagen: %s", exc)
            finally:
                STATE["running"] = False
                STATE["last_run"] = time.time()
                STATE["next_run"] = time.time() + interval

            # In kleinen Schritten warten, damit Änderungen schnell greifen.
            remaining = interval
            while remaining > 0:
                await asyncio.sleep(min(30, remaining))
                remaining -= 30
                if not config.load().get("auto_enabled"):
                    break
    except asyncio.CancelledError:
        log.info("Automatikbetrieb beendet.")
        raise
    finally:
        STATE["active"] = False
