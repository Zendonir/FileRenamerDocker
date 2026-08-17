"""Optionaler Zugangsschutz per Passwort und Sitzungs-Cookie."""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import config, logs

log = logs.get("auth")

COOKIE = "renamer_session"
SESSION_HOURS = 24 * 14

# Offene Pfade: Login, Statik und der Health-Check für Docker.
PUBLIC_PATHS = {"/api/login", "/api/health", "/login", "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/",)

_sessions: dict[str, float] = {}


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2 mit zufälligem Salt – Format: pbkdf2$<salt>$<hex>."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, _ = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_HOURS * 3600
    # Abgelaufene Sitzungen aufräumen.
    for old, expiry in list(_sessions.items()):
        if expiry < time.time():
            _sessions.pop(old, None)
    return token


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    expiry = _sessions.get(token)
    if not expiry:
        return False
    if expiry < time.time():
        _sessions.pop(token, None)
        return False
    return True


def drop_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


def enabled(settings: dict | None = None) -> bool:
    settings = settings or config.load()
    return bool(settings.get("auth_enabled") and settings.get("auth_password_hash"))


async def middleware(request: Request, call_next):
    """Blockt alles außer Login und Statik, solange keine Sitzung besteht."""
    path = request.url.path
    if not enabled() or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)

    if valid_session(request.cookies.get(COOKIE)):
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)
    return RedirectResponse("/login", status_code=302)


def cookie_kwargs(request: Request) -> dict:
    """Secure-Flag nur bei HTTPS, sonst lehnt der Browser das Cookie ab."""
    secure = request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto", "").startswith("https")
    return {"httponly": True, "samesite": "lax", "secure": secure,
            "max_age": SESSION_HOURS * 3600, "path": "/"}


def bootstrap() -> None:
    """Startpasswort aus der Umgebung übernehmen (praktisch für TrueNAS)."""
    password = os.environ.get("AUTH_PASSWORD")
    if not password:
        return
    settings = config.load()
    if settings.get("auth_password_hash"):
        return
    config.save({
        "auth_enabled": True,
        "auth_user": os.environ.get("AUTH_USER", "admin"),
        "auth_password_hash": hash_password(password),
    })
    log.info("Zugangsschutz aus der Umgebungsvariable AUTH_PASSWORD eingerichtet.")
