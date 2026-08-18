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
- **Mehrteilige Episoden** (`S01E01E02`), Teil-/CD-Nummern
- **Untertitel folgen ihrem Video** – gleicher Treffer, gleicher Zielname, ohne eigene Abfrage
- **Sammelzuweisung**: einen Treffer mit einem Klick auf alle Episoden einer Serie anwenden
- **Bibliotheks-Abgleich** – erkennt vorhandene Fassungen und überspringt oder ersetzt sie
  je nach Qualität (Auflösung, Quelle, HDR, Größe)
- **Automatikbetrieb** – scannt in festem Takt und verschiebt sicher Erkanntes selbst;
  laufende Downloads werden erkannt und bleiben liegen
- **Plex, Jellyfin und Webhooks** werden nach getaner Arbeit benachrichtigt
- **NFO-Dateien, Poster und Hintergrundbilder** für Kodi/Jellyfin/Emby – rein
  optional und standardmäßig aus
- **Verlauf mit Undo** – jede Operation lässt sich einzeln zurücknehmen, mit Suche und Filter
- **Log im Webinterface** – alle Aktionen und Fehler live mitlesen, filtern und herunterladen
- **Zugangsschutz** per Passwort, **Antwort-Cache** für schnelle Wiederholungsläufe
- **Tastaturbedienung** der Ergebnisliste; Scan abbrechbar und neustartfest gespeichert
- **Leere Quell- und Zielordner** werden aufgeräumt (auch beim Rückgängigmachen)
- **PUID/PGID** und Images für **amd64 und arm64**

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

## Betrieb auf TrueNAS

Getestete Vorgehensweise für **TrueNAS SCALE** (ab Version 24.10, „Apps → Custom App“
mit Docker-Compose):

```yaml
services:
  media-renamer:
    image: ghcr.io/zendonir/filerenamerdocker:latest
    container_name: media-renamer
    ports:
      - "8080:8080"
    environment:
      PUID: 568             # der Benutzer "apps" auf TrueNAS SCALE
      PGID: 568
      TZ: Europe/Berlin
      AUTH_PASSWORD: "dein-passwort"     # richtet den Zugangsschutz beim ersten Start ein
    volumes:
      - /mnt/tank/appdata/media-renamer:/config
      - /mnt/tank/media:/data            # enthält input, movies, series, anime
    restart: unless-stopped
```

Worauf es auf TrueNAS besonders ankommt:

- **Ein Dataset für alles.** Quelle und Ziel müssen im selben Dataset liegen (hier
  `/mnt/tank/media`), sonst kopiert ZFS beim Verschieben die kompletten Dateien statt
  sie nur umzuhängen – bei 20 GB pro Film ein spürbarer Unterschied. Hardlinks
  funktionieren über Dataset-Grenzen gar nicht.
- **PUID/PGID auf 568 setzen** – das ist der `apps`-Benutzer von SCALE. Sonst gehören
  die verschobenen Dateien root und Plex oder Jellyfin kommen nicht mehr heran.
- **ACLs beachten.** Nutzt dein Dataset NFSv4-ACLs, muss der `apps`-Benutzer dort
  Schreibrechte haben (Datasets → Edit Permissions). Andernfalls scheitert das
  Verschieben mit „Permission denied“, gut sichtbar im Log-Tab.
- **Snapshots.** Läuft im Ziel-Dataset eine Snapshot-Aufgabe, belegen ersetzte
  Fassungen weiterhin Platz, bis der Snapshot ausläuft – das ist normal, aber gut
  zu wissen, wenn „Ersetzen, wenn besser“ aktiv ist.
- **Automatikbetrieb statt Cron.** Der Zeitplan steckt in der App selbst; du brauchst
  keine TrueNAS-Cron-Aufgabe.

Läuft neben dem Renamer ein Plex oder Jellyfin auf demselben TrueNAS, trage dessen
Adresse unter „Medienserver benachrichtigen“ ein (z. B. `http://localhost:32400`,
wenn beide im Host-Netz liegen, sonst die IP des NAS). Nach jedem Lauf wird die
Bibliothek dann automatisch aktualisiert.

## Volumes

| Pfad | Zweck |
|---|---|
| `/config` | Einstellungen, Verlauf, Logdateien (`/config/logs/`), Cache und letzter Scan |
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
| `GET /api/scan` | Letzter Lauf – überlebt einen Neustart |
| `POST /api/scan/{id}/cancel` | Laufenden Scan abbrechen |
| `GET /api/group/{id}?src=…` | Alle Dateien desselben erkannten Titels |
| `GET /api/auto`, `POST /api/auto/run` | Automatik: Status und Sofortlauf (`?dry_run=true`) |
| `POST /api/login`, `POST /api/logout` | Anmeldung |
| `GET/DELETE /api/cache` | Cache-Statistik und Leeren |
| `POST /api/notify-test` | Verbindung zu Plex/Jellyfin/Webhooks prüfen |

Die Antwort von `POST /api/apply` enthält bei eingeschalteten Optionen zusätzlich
`nfo_written` und `artwork_written` mit der Anzahl geschriebener Begleitdateien.
| `POST /api/preview-format` | Namensschema testen |

## Automatikbetrieb

Unter **Einstellungen → Automatikbetrieb** aktivierbar. Der Container scannt dann selbst
im eingestellten Takt und verschiebt, was sicher erkannt wurde:

- Es wird nur verschoben, was die **eigene, höhere Schwelle** erreicht (Standard 0,9).
  Alles darunter bleibt liegen und wartet auf deine Durchsicht im Webinterface.
- **Laufende Downloads werden erkannt**: Eine Datei muss eine einstellbare Zeit lang
  unverändert sein (Standard 120 s), sonst wird sie übersprungen und beim nächsten
  Lauf erneut geprüft.
- Nach getaner Arbeit werden **Plex, Jellyfin und deine Webhooks** benachrichtigt.
- Über **„Automatik testen"** siehst du gefahrlos, was passieren würde, ohne dass eine
  Datei angefasst wird. **„Jetzt automatisch verarbeiten"** startet einen Lauf sofort.

Die Leiste oben im Umbenennen-Tab zeigt jederzeit Status, letzten und nächsten Lauf.

## Duplikate und Bibliotheks-Abgleich

Vor dem Verschieben prüft der Renamer, ob am Ziel bereits eine Fassung derselben
Episode oder desselben Films liegt, und vergleicht die Qualität: zuerst die Auflösung,
dann die Quelle (Blu-ray schlägt WEB schlägt HDTV), dann HDR, zuletzt die Dateigröße.
Das Ergebnis steht als Badge an der Datei. Drei Verhaltensweisen stehen zur Wahl:

| Einstellung | Verhalten |
|---|---|
| **Überspringen** (Standard) | Vorhandenes bleibt unangetastet, die neue Datei bleibt liegen |
| **Ersetzen, wenn besser** | Nur eine echte Verbesserung ersetzt die alte Fassung, die dann gelöscht wird |
| **Trotzdem verschieben** | Beide Fassungen bleiben nebeneinander bestehen |

## Begleitdateien: NFO, Poster, Hintergrundbilder

**Beide Funktionen sind optional und ab Werk ausgeschaltet.** Ohne Häkchen unter
„Einstellungen → Begleitdateien" wird ausschließlich die Mediendatei selbst angefasst –
es entsteht keine einzige Zusatzdatei und es geht keine Anfrage nach draußen.

**NFO-Dateien** (`write_nfo`) legen neben jede Datei eine XML-Datei im Kodi-Format:
Titel, Jahr, Genres, Bewertung und die Datenbank-IDs (TMDB/TVDB und, wenn bekannt,
IMDb). Filme bekommen `<movie>`, Episoden `<episodedetails>` mit Serientitel, Staffel,
Episode und Erstausstrahlung.

**Poster und Hintergrundbilder** (`download_artwork`) sind über einen **Hauptschalter**
und vier Einzelschalter steuerbar:

| Schalter | Steuert |
|---|---|
| `download_artwork` | **Hauptschalter.** Aus = kein einziger Bildabruf, egal was darunter steht |
| `artwork_poster` | Poster der Serie bzw. des Films |
| `artwork_fanart` | Hintergrundbild |
| `artwork_season` | Staffelposter (beide Ablagen) |
| `artwork_thumb` | Episodenbild |

Die vier Einzelschalter stehen ab Werk auf „an", wirken aber nur, wenn der
Hauptschalter gesetzt ist – wer also einfach nur Bilder will, setzt ein Häkchen und
bekommt alles. Wer etwa nur Poster mag, schaltet die übrigen drei ab. Im Webinterface
sind die Einzelschalter ausgegraut, solange der Hauptschalter aus ist.

Abgelegt wird nach den Konventionen, die Kodi, Jellyfin und Emby verstehen:

| Was | Wohin |
|---|---|
| Film mit eigenem Ordner | `poster.jpg`, `fanart.jpg` im Filmordner |
| Film direkt im Zielordner | `<Dateiname>-poster.jpg`, `<Dateiname>-fanart.jpg` |
| Serie | `poster.jpg`, `fanart.jpg` im Serienordner |
| Staffel | `seasonXX-poster.jpg` im Serienordner **und** `poster.jpg` im Staffelordner |
| Episode | `<Dateiname>-thumb.jpg` neben der Episode |

Das Staffelposter wird bewusst doppelt abgelegt: Kodi sucht es im Serienordner,
Jellyfin im Staffelordner. Zwei kleine Dateien sparen die Entscheidung.

Weitere Eigenschaften:

- **Vorhandene Bilder bleiben unangetastet** – schon abgelegte oder selbst gewählte
  Poster werden nie überschrieben.
- Die Bild-URLs werden **nur bei eingeschaltetem Artwork** nachgeladen und landen im
  Cache; ein zweiter Lauf derselben Serie kostet keine weitere Abfrage.
- Antworten, die kein Bild sind (etwa eine HTML-Fehlerseite), werden verworfen;
  Bilder über 20 MB ebenfalls. Ein fehlgeschlagener Download bricht nie den Lauf ab,
  sondern erscheint als Zeile im Log.
- Untertitel bekommen keine Begleitdateien.

Beides greift sowohl beim manuellen **Übernehmen** als auch im **Automatikbetrieb**.

## Untertitel

Untertitel lösen **keine eigene Datenbankabfrage** mehr aus, sondern übernehmen Treffer
und Zielnamen der zugehörigen Videodatei – erkannt über die Episode, nicht über den
Dateinamen. `Dark.S02E05.German.de.srt` findet so auch dann zu
`Dark.S02E05.German.1080p.mkv`, wenn die Namen nicht identisch sind. Das Sprachkürzel
bleibt erhalten (`… - S02E05 - Lost.de.srt`). Nur Untertitel ohne passendes Video
werden noch einzeln nachgeschlagen.

## Sicherheit

- **Zugangsschutz**: Unter „Einstellungen → Zugang" lässt sich eine Anmeldung
  einschalten. Das Passwort wird als PBKDF2-Hash mit zufälligem Salt gespeichert,
  nie im Klartext. Alternativ setzt `AUTH_PASSWORD` beim ersten Start automatisch
  einen Zugang ein – praktisch für TrueNAS, wo die App gleich geschützt starten soll.
- `settings.json` enthält API-Keys und den Passwort-Hash und wird mit Rechten
  **600** geschrieben.
- Ohne aktivierten Zugangsschutz ist die Anwendung **offen** und kann Dateien
  verschieben und löschen. Betreibe sie dann nur im lokalen Netz.
- Für Zugriff von außen gehört ein Reverse-Proxy mit HTTPS davor. Das
  Sitzungs-Cookie setzt das `Secure`-Flag automatisch, sobald die Verbindung
  über HTTPS läuft (auch hinter einem Proxy mit `X-Forwarded-Proto`).

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests -q
CONFIG_DIR=./config .venv/bin/uvicorn app.main:app --reload --port 8080
```

## Lizenz

MIT. Metadaten stammen von TMDB und TheTVDB; deren Nutzungsbedingungen gelten für
die jeweiligen API-Keys.
