"""Ausführen der Dateiaktionen inkl. Verlauf und Undo."""
import os
import shutil
import time
from pathlib import Path

from . import config


class ActionError(RuntimeError):
    pass


def _unique(dest: Path, overwrite: bool) -> Path:
    if not dest.exists() or overwrite:
        return dest
    stem, suffix = dest.stem, dest.suffix
    for i in range(1, 1000):
        candidate = dest.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    raise ActionError(f"Kein freier Zielname für {dest}")


def _same_device(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False


def transfer(src: Path, dest: Path, action: str, overwrite: bool = False) -> Path:
    """Führt eine einzelne Datei-Operation aus und gibt den tatsächlichen Zielpfad zurück."""
    if not src.is_file():
        raise ActionError(f"Quelle existiert nicht: {src}")
    if action == "test":
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest, overwrite)
    if dest.exists() and overwrite:
        dest.unlink()

    if action == "move":
        shutil.move(str(src), str(dest))
    elif action == "copy":
        shutil.copy2(str(src), str(dest))
    elif action == "hardlink":
        if not _same_device(src, dest.parent):
            raise ActionError("Hardlink nicht möglich: Quelle und Ziel liegen auf verschiedenen Volumes.")
        os.link(str(src), str(dest))
    elif action == "symlink":
        os.symlink(str(src), str(dest))
    else:
        raise ActionError(f"Unbekannte Aktion: {action}")
    return dest


def cleanup_dirs(paths: set[Path], stop_at: set[Path]) -> list[str]:
    """Räumt leere Quellordner auf, ohne die konfigurierten Wurzeln zu löschen."""
    removed = []
    stop = {p.resolve() for p in stop_at}
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        current = path
        while current.is_dir() and current.resolve() not in stop:
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
                removed.append(str(current))
                current = current.parent
            except OSError:
                break
    return removed


def apply(items: list[dict], action: str, overwrite: bool, clean_empty: bool,
          roots: list[str]) -> dict:
    """Verarbeitet eine Liste von {src, dest}-Paaren."""
    results = []
    history = []
    source_dirs: set[Path] = set()

    for item in items:
        src = Path(item["src"])
        dest = Path(item["dest"])
        try:
            final = transfer(src, dest, action, overwrite)
            source_dirs.add(src.parent)
            results.append({"src": str(src), "dest": str(final), "ok": True, "error": None})
            if action != "test":
                history.append({
                    "time": time.time(),
                    "action": action,
                    "src": str(src),
                    "dest": str(final),
                    "undone": False,
                })
        except (ActionError, OSError) as exc:
            results.append({"src": str(src), "dest": str(dest), "ok": False, "error": str(exc)})

    removed = []
    if clean_empty and action == "move":
        removed = cleanup_dirs(source_dirs, {Path(r) for r in roots})
    if history:
        config.append_history(history)

    return {
        "results": results,
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "removed_dirs": removed,
    }


def undo(entry_times: list[float]) -> dict:
    """Macht zuvor ausgeführte Operationen rückgängig (Move/Copy/Link)."""
    history = config.load_history()
    wanted = set(entry_times)
    results = []

    for entry in history:
        if entry["time"] not in wanted or entry.get("undone"):
            continue
        src, dest = Path(entry["src"]), Path(entry["dest"])
        try:
            if not dest.exists():
                raise ActionError(f"Ziel nicht mehr vorhanden: {dest}")
            if entry["action"] == "move":
                if src.exists():
                    raise ActionError(f"Quelle existiert bereits: {src}")
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(src))
            else:
                dest.unlink()
            entry["undone"] = True
            results.append({"dest": str(dest), "ok": True, "error": None})
        except (ActionError, OSError) as exc:
            results.append({"dest": str(dest), "ok": False, "error": str(exc)})

    config.replace_history(history)
    return {"results": results, "ok": sum(1 for r in results if r["ok"])}
