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
- **Erkennung in drei Stufen** – Dateiname, dann Ordnername, dann eingebettete
  Container-Metadaten; ausgewertet werden Titel, Jahr, Staffel, Episode, Auflösung,
  Codec und Release-Gruppe
- **Abgleich** mit TMDB/TVDB inkl. Trefferqualität in Prozent; Serien wahlweise über TVDB oder TMDB
- **Manuelle Korrektur**: pro Datei den richtigen Treffer suchen und auswählen; Zielpfad direkt editierbar
- **Drei getrennte Kategorien** – Filme, Serien und Anime, jeweils mit eigenem Zielordner
  und eigenem Namensschema; Anime werden automatisch erkannt und sind manuell umschaltbar
- **Schema-Editor mit Bubbles** – Bausteine anklicken, per Maus umsortieren, Live-Vorschau
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

1. **Einstellungen**: API-Keys, Quellordner, Zielordner je Kategorie, die drei
   Namensschemata im Bubble-Editor, Anime-Erkennung und Standardaktion.
2. **Umbenennen → Scannen & Zuordnen**: Dateien werden analysiert und abgeglichen.
   Farbcodierung: grün = sicher erkannt, gelb = bitte prüfen, rot = kein Treffer.
3. Bei gelb/rot auf **Treffer wählen** klicken und den richtigen Eintrag suchen.
   Zielpfade lassen sich zusätzlich direkt im Feld anpassen, und über das Auswahlfeld
   daneben schaltest du die Kategorie um, falls ein Anime als Serie erkannt wurde.
   Die Chips oben rechts filtern die Liste nach Film, Serie oder Anime.
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

## Wie der Titel erkannt wird

Die Erkennung läuft in drei Stufen. Jede Stufe kommt nur dran, wenn die vorherige
nichts Brauchbares geliefert hat:

**1. Der Dateiname** – der Normalfall. `Dark.S02E05.German.1080p.WEB.h264-GRP.mkv`
ergibt Titel, Staffel, Episode, Auflösung, Quelle, Codec und Release-Gruppe in einem
Rutsch. Der Ordner wird dabei bewusst ignoriert, damit ein gut benanntes File nicht
vom Ordner überstimmt wird.

**2. Der Ordnername** – wenn der Dateiname nichts hergibt. Als nichtssagend gelten
reine Nummern (`01.mkv`), DVD-Rip-Namen (`VTS_01_1.mkv`), Hash-Namen
(`a3f9c2b81e4d77aa.mkv`) und Allerweltsnamen (`video.mkv`, `untitled.mkv`).
Dabei gilt:

- **Staffelordner werden übersprungen**, liefern aber die Staffelnummer:
  `Breaking Bad (2008)/Season 03/01.mkv` → Breaking Bad, S03E01. Erkannt werden
  `Season 3`, `Staffel 3`, `S03` sowie `Specials`, `Extras`, `Disc 1`, `CD2`, `Subs`.
- **Sammelordner werden übersprungen** – aus `Downloads`, `complete`, `Torrents`,
  `Serien`, `Filme` oder `Anime` wird nie ein Titel; die Suche geht eine Ebene höher.
- **Der Quellordner selbst zählt nie**, sonst hieße jeder Film nach dem Downloadordner.
- Ziffern aus einem Müll-Dateinamen werden **nicht** als Episode missverstanden:
  `Der Pate (1972)/VTS_01_1.mkv` bleibt ein Film und wird nicht zu Episode 1.

**3. Eingebettete Metadaten** – zuletzt die Tags im Container selbst, gelesen aus
MKV/WebM (Matroska-Tags und Segment-Titel) und MP4/M4V/MOV (iTunes-Atome). Ausgewertet
werden Serientitel, Episodentitel, Staffel, Episode und Erscheinungsjahr. Das rettet
Dateien, die weder im Namen noch im Ordner etwas verraten.

Das Auslesen läuft **ohne ffmpeg** – die Container werden direkt gelesen, es werden nur
die Kopf-Bytes angefasst. Das spart rund 250 MB Image-Größe gegenüber einer
ffmpeg-Installation.

Unabhängig davon füllen die Metadaten immer **Lücken**: Steht der Titel im Dateinamen,
fehlen aber Staffel und Episode, werden sie aus den Tags ergänzt.

Im Webinterface zeigt ein Badge an, woher der Titel stammt – 📁 **aus Ordner** oder
🏷️ **aus Metadaten**; ohne Badge kam er aus dem Dateinamen. Im Log steht dieselbe
Information als eigene Zeile. Beide Zusatzstufen lassen sich in den Einstellungen
einzeln abschalten.

## Kategorien: Film, Serie, Anime

Jede Datei landet in genau einer von drei Kategorien, und jede Kategorie hat ihren
**eigenen Zielordner und ihr eigenes Namensschema**:

| Kategorie | Zielordner | Standardschema |
|---|---|---|
| 🎬 Film | `/data/movies` | `{n} ({y})/{n} ({y}){' CD'+pi}{' '+vf}` |
| 📺 Serie | `/data/series` | `{n}/Season {s.pad(2)}/{n} - {s00e00} - {t}` |
| 🎌 Anime | `/data/anime` | `{n}/{n} - {abs.pad(3)|s00e00} - {t}` |

### Anime-Erkennung

Ob eine Serie ein Anime ist, entscheidet der Container in dieser Reihenfolge:

1. **Pfad-Schlüsselwörter** – liegt die Datei unter `.../Anime/...` oder stammt sie von
   einer typischen Fansub-Gruppe (`[SubsPlease]`, `[Erai-raws]` …), gilt das als
   eindeutiger Wunsch und schlägt alles andere. Die Liste ist in den Einstellungen frei
   editierbar.
2. **Herkunft und Genre aus der Datenbank** – japanische Originalsprache bzw. Herkunftsland
   **in Kombination mit** dem Animations-Genre.

Diese Kombination ist bewusst gewählt: Die Simpsons sind animiert, aber kein Anime;
Shōgun ist japanisch, aber kein Anime. Beide Fälle sind durch Tests abgedeckt.

Die Erkennung lässt sich komplett abschalten (dann ist alles „Serie“). Unabhängig davon
kannst du **die Kategorie jeder einzelnen Datei im Umbenennen-Tab per Auswahlfeld
umschalten** – Zielpfad und Schema werden sofort neu berechnet.

Das Anime-Schema nutzt standardmäßig die **absolute Episodennummer** (`{abs}`), weil
Fansubs so zählen (`Serie - 137`). Findet die Datenbank dazu nichts, fällt das
Standardschema per `{abs.pad(3)|s00e00}` automatisch auf `S01E12` zurück. Über die
Einstellung „Absolute Episodennummer bevorzugen“ steuerst du das Verhalten; die
Datenquelle für Anime (TVDB oder TMDB) ist getrennt von der für normale Serien wählbar.

## Namensschema-Editor

Unter **Einstellungen → Namensschema** gibt es je einen Editor für Filme, Serien und
Anime. Das Schema wird dort nicht getippt, sondern aus **Bubbles** zusammengesetzt:

- **Anklicken** eines Bausteins in der Palette hängt ihn hinten an. Die Palette zeigt
  nur, was zur Kategorie passt – Staffel und Episode tauchen beim Film-Schema nicht auf.
- **Verschieben** per Maus (Drag & Drop) sortiert die Bubbles um; eine farbige Kante
  zeigt an, wo die Bubble landet.
- **✕** auf einer Bubble entfernt sie.
- **Textbausteine** sind direkt beschreibbar – für Trennzeichen wie ` - ` oder Klammern.
- **`/`** ist eine eigene Bubble und trennt Ordnerebenen.
- Die **Live-Vorschau** darunter zeigt bei jeder Änderung sofort den fertigen Dateinamen
  an einem Beispiel der jeweiligen Kategorie.
- Über **Als Text bearbeiten** lässt sich das Schema weiterhin direkt tippen – beide
  Ansichten bleiben synchron.

Ergibt z. B. `Der Pate (1972)/Der Pate (1972) 1080p.mkv`,
`Dark/Season 02/Dark - S02E05 - Lost.mkv` und
`Frieren/Frieren - 012 - Ende der Reise.mkv`.

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
| `{e00}` | Episode `02` | | `{id}` | Datenbank-ID |

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
| `POST /api/category` | Kategorie einer Datei umschalten (Film/Serie/Anime) |
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
