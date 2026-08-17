#!/bin/sh
set -e

# Läuft der Container als root, wechseln wir auf PUID/PGID – so gehören
# verschobene Dateien dem gleichen Benutzer wie im übrigen Media-Stack.
if [ "$(id -u)" = "0" ]; then
    if ! getent group "$PGID" >/dev/null 2>&1; then
        groupadd -g "$PGID" renamer 2>/dev/null || addgroup -g "$PGID" renamer 2>/dev/null || true
    fi
    if ! getent passwd "$PUID" >/dev/null 2>&1; then
        useradd -u "$PUID" -g "$PGID" -M -s /sbin/nologin renamer 2>/dev/null || true
    fi
    chown -R "$PUID:$PGID" /config 2>/dev/null || true
    exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
