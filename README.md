# Media Renamer

Ein Docker-Container zum Umbenennen und Einsortieren von Filmen und Serien –
**vollständig über ein Webinterface steuerbar**, ohne Desktop-GUI und ohne CLI.
Metadaten kommen von **TMDB** (Filme + Serien) und **TheTVDB** (Serien).

## Warum kein FileBot im Image?

FileBot ist proprietär und lizenzpflichtig; es darf nicht in ein eigenes Image
gepackt und weitergegeben werden. Dieses Projekt bildet den für dich relevanten
Funktionsumfang eigenständig nach: Erkennung aus dem Dateinamen, Datenbank-Abgleich,
Namensschema mit Platzhaltern, Vorschau vor der Ausführung und Verschieben ans Ziel.

## Funktionen

- **Scan** rekursiv über beliebig viele Quellordner, Sample- und Kleinstdateien werden übersprungen
- **Erkennung** von Titel, Jahr, Staffel, Episode, Auflösung, Codec, Release-Gruppe (via `guessit`)
- **Abgleich** mit TMDB/TVDB inkl. Trefferqualität in Prozent; Serien wahlweise über TVDB oder TMDB
- **Manuelle Korrektur**: pro Datei den richtigen Treffer suchen und auswählen; Zielpfad direkt editierbar
- **Namensschema** mit FileBot-ähnlichen Platzhaltern und Live-Vorschau in den Einstellungen
- **Aktionen**: Verschieben, Kopieren, Hardlink, Symlink oder Trockenlauf („Nur testen“)
- **Mehrteilige Episoden** (`S01E01E02`), Untertitel-Dateien mit Sprachkürzel, Teil-/CD-Nummern
- **Verlauf mit Undo** – jede Operation lässt sich einzeln zurücknehmen, mit Suche und Filter
- **Log im Webinterface** – alle Aktionen und Fehler live mitlesen, filtern und herunterladen
- **Leere Quellordner** werden nach dem Verschieben optional aufgeräumt
- **PUID/PGID**, damit verschobene Dateien dem richtigen Benutzer gehören

## Schnellstart

```bash
git clone https://github.com/Zendonir/FileRenamerDocker.git
cd FileRenamerDocker
# In docker-compose.yml den Pfad unter volumes auf dein Medien-Verzeichnis anpassen
docker compose up -d --build
```

Danach `http://<server-ip>:8080` öffnen.

### Ohne Compose

```bash
docker build -t media-renamer .
docker run -d --name media-renamer -p 8080:8080 \
  -e PUID=1000 -e PGID=1000 -e TZ=Europe/Berlin \
  -v /pfad/zu/config:/config \
  -v /pfad/zu/medien:/data \
  media-renamer
```

### API-Keys

| Dienst | Wo bekommen | Hinweis |
|---|---|---|
| TMDB | https://www.themoviedb.org/settings/api | v3-Key oder v4-Read-Access-Token, beides wird erkannt |
| TVDB | https://thetvdb.com/api-information | v4-Key; nur nötig, wenn TVDB als Serien-Quelle gewählt ist |

Keys entweder im Webinterface unter **Einstellungen** eintragen (landen in
`/config/settings.json`) oder als `TMDB_API_KEY` / `TVDB_API_KEY` per Umgebungsvariable.

## Volumes

| Pfad | Zweck |
|---|---|
| `/config` | Einstellungen, Verlauf und Logdateien (`/config/logs/`) |
| `/data` | Medien – Quelle und Ziel |

**Wichtig:** Quelle und Ziel sollten unter **einem** Mount liegen (z. B. beides unter
`/data`). Sonst wird beim Verschieben über Volume-Grenzen kopiert statt umbenannt, und
Hardlinks funktionieren gar nicht.

## Ablauf im Webinterface

1. **Einstellungen**: API-Keys, Quellordner, Zielordner, Namensschema, Standardaktion.
2. **Umbenennen → Scannen & Zuordnen**: Dateien werden analysiert und abgeglichen.
   Farbcodierung: grün = sicher erkannt, gelb = bitte prüfen, rot = kein Treffer.
3. Bei gelb/rot auf **Treffer wählen** klicken und den richtigen Eintrag suchen.
   Zielpfade lassen sich zusätzlich direkt im Feld anpassen.
4. Dateien anhaken, Aktion wählen, **Übernehmen**. Mit „Nur testen“ passiert nichts
   auf der Platte – ideal für den ersten Durchlauf.
5. **Verlauf**: Falls etwas schiefging, Einträge anhaken und rückgängig machen.
6. **Log**: Zeigt, was genau passiert ist – hilfreich, wenn eine Datei falsch
   zugeordnet wurde oder eine Aktion fehlschlug.

## Log und Rückgängigmachen

Für falsch benannte Dateien gibt es zwei getrennte Werkzeuge:

**Tab „Verlauf“** – die Liste aller ausgeführten Operationen, jede einzeln zurücknehmbar:

- Verschobene Dateien wandern exakt an den ursprünglichen Ort zurück, inklusive Ordner.
- Kopien, Hard- und Symlinks werden am Ziel wieder entfernt; die Quelle bleibt unangetastet.
- Suchfeld und Filter („nur aktive“ / „nur rückgängig gemachte“) helfen, einen einzelnen
  Eintrag unter tausenden zu finden – du musst also nicht einen ganzen Lauf zurücknehmen,
  um eine falsch benannte Datei zu korrigieren.
- Bereits zurückgenommene Einträge bleiben grau sichtbar stehen, damit nachvollziehbar
  bleibt, was passiert ist.
- Gespeichert in `/config/history.json`, überlebt Container-Neustarts (max. 2000 Einträge).

**Tab „Log“** – das laufende Protokoll:

- Erfasst Scans, Datenbank-Treffer samt Trefferqualität, manuelle Zuweisungen, jede
  Datei-Operation mit Quell- und Zielpfad, Fehler und jedes Rückgängigmachen.
- Filter nach Level (Debug/Info/Warnung/Fehler) und Volltextsuche über alle Zeilen.
- Aktualisiert sich alle 4 Sekunden automatisch – ein laufender Scan ist live mitlesbar.
- **Logdatei herunterladen** liefert `/config/logs/renamer.log` als Textdatei.
- Die Datei rotiert bei 5 MB und behält 5 Generationen (`renamer.log.1` … `.5`), läuft
  also nicht voll. Sie liegt unter `/config` und übersteht Neustarts; die Ansicht im
  Browser zeigt die letzten 2000 Zeilen seit dem Start.

Wenn also eine Datei falsch umbenannt wurde: im **Log** nachsehen, welcher Treffer
gewählt wurde, dann im **Verlauf** genau diesen Eintrag suchen und zurücknehmen.
Danach die Datei erneut scannen und über **Treffer wählen** korrekt zuordnen.

## Namensschema

Standard:

```
Filme:   {n} ({y})/{n} ({y}){' CD'+pi}{' '+vf}
Serien:  {n}/Season {s.pad(2)}/{n} - {s00e00} - {t}
```

ergibt z. B. `Der Pate (1972)/Der Pate (1972) 1080p.mkv` und
`Dark/Season 02/Dark - S02E05 - Lost.mkv`.

| Platzhalter | Bedeutung | | Platzhalter | Bedeutung |
|---|---|---|---|---|
| `{n}` | Titel | | `{s00e00}` | `S01E02` |
| `{y}` | Jahr | | `{sxe}` | `1x02` |
| `{s}` | Staffel | | `{abs}` | absolute Episodennummer |
| `{e}` | Episode | | `{airdate}` | Erstausstrahlung |
| `{t}` | Episodentitel | | `{vf}` | Auflösung |
| `{vc}` | Video-Codec | | `{ac}` | Audio-Codec |
| `{source}` | Quelle (BluRay …) | | `{group}` | Release-Gruppe |
| `{pi}` | Teil-/CD-Nummer | | `{collection}` | Filmreihe |
| `{imdb}` | IMDb-ID | | `{lang}` | Sprachen |

Regeln:

- `{s.pad(2)}` füllt links mit Nullen auf.
- `{' CD'+pi}` gibt den Text **nur** aus, wenn `pi` gefüllt ist – sonst fällt der
  ganze Ausdruck weg. So bleiben keine leeren Klammern oder Bindestriche stehen.
- `{t|n}` nimmt den ersten gefüllten Wert.
- `/` im Template trennt Ordnerebenen; `/` innerhalb eines Titels wird entfernt,
  erzeugt also keine ungewollte Unterebene.

Die Live-Vorschau in den Einstellungen zeigt das Ergebnis sofort.

## API

Das Webinterface nutzt eine reguläre REST-API, die sich auch skripten lässt:

| Endpoint | Zweck |
|---|---|
| `GET /api/health` | Status und ob Keys hinterlegt sind |
| `GET/POST /api/settings` | Einstellungen lesen/schreiben |
| `POST /api/scan` → `GET /api/scan/{id}` | Scan starten, Fortschritt abfragen |
| `POST /api/search` | Datenbanksuche |
| `POST /api/select` | Treffer manuell zuweisen |
| `POST /api/apply` | Aktion ausführen |
| `GET /api/history`, `POST /api/undo` | Verlauf und Rücknahme |
| `GET /api/logs` | Log-Zeilen, gefiltert nach `level` und `q` |
| `GET /api/logs/download` | Vollständige Logdatei als Text |
| `POST /api/preview-format` | Namensschema testen |

## Sicherheit

Die Anwendung hat **keine Authentifizierung** und kann Dateien im gemounteten
Verzeichnis verschieben und löschen. Betreibe sie nur im lokalen Netz oder hinter
einem Reverse-Proxy mit Zugriffsschutz.

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests -q
CONFIG_DIR=./config .venv/bin/uvicorn app.main:app --reload --port 8080
```

## Lizenz

MIT. Metadaten stammen von TMDB und TheTVDB; deren Nutzungsbedingungen gelten für
die jeweiligen API-Keys.
