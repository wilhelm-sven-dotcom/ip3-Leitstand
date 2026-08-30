# Den Leitstand auf dem eigenen Rechner ansehen

Diese Anleitung bringt den Leitstand auf einen normalen Arbeitsrechner – zum Anschauen, nicht zum
Betreiben. Rund 30 Minuten, davon das meiste Wartezeit beim Herunterladen.

**Geschrieben für den Mac.** Die Befehle für Windows stehen gesammelt im
[letzten Abschnitt](#auf-einem-windows-rechner); nur drei der sieben Schritte unterscheiden sich.

**Was dabei entsteht:** eine vollständige Anwendung mit erfundenen Demodaten, die nur auf diesem
einen Rechner läuft. Kein Server, kein Netz, keine echten Firmendaten. Zum Wegwerfen: der Ordner
kann hinterher gelöscht werden, es bleibt nichts zurück.

**Was das *nicht* ist:** der spätere Betrieb. Wie der Leitstand als Dienst mit Autostart, TLS und
nächtlicher Sicherung eingerichtet wird, steht in [`../RUNBOOK.md`](../RUNBOOK.md). Die
Entscheidung, **wo** er am Ende läuft, muss jetzt noch nicht fallen.

---

## Schritt 1: Vier Pakete installieren

Alles läuft im **Terminal** (Command-Taste + Leertaste, „Terminal" tippen, Enter).

Falls Homebrew noch nicht installiert ist – das ist der Paketverwalter, über den alles Weitere
kommt:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

> **Beim Passwort erscheint nichts – das ist so gewollt.** Gefragt ist das **Anmeldepasswort
> dieses Macs**, nicht das von GitHub und nicht die Apple-ID. Während des Tippens bleibt die
> Zeile leer: keine Punkte, keine Sternchen, der Cursor rührt sich nicht. Blind eintippen und
> Enter drücken.
>
> Kommt `Sorry, try again`, stimmt das Passwort nicht. Meist ist die Feststelltaste an oder die
> Tastaturbelegung eine andere als gedacht – auf der deutschen sind `y` und `z` vertauscht, das
> `@` liegt auf Alt+L. Nach drei Fehlversuchen bricht `sudo` ab und der Installer steigt aus.
> Dabei geht nichts kaputt: denselben Befehl noch einmal ausführen.

Der Installer sagt am Ende, welche zwei Zeilen noch in die Datei `~/.zprofile` gehören – diese
Zeilen ausführen, sonst kennt das Terminal `brew` nicht. Danach:

```bash
brew install git node uv pango
```

| Paket | Wofür |
|---|---|
| **git** | holt den Quelltext von GitHub |
| **node** | baut die Oberfläche einmal zusammen |
| **uv** | bringt Python mit und richtet das Backend ein – Python muss **nicht** getrennt installiert werden |
| **pango** | Textsatz für die Rechnungs-PDFs (zieht cairo und die übrigen Grafikbibliotheken mit) |

Zur Kontrolle:

```bash
git --version && node --version && uv --version
```

Drei Versionsnummern = fertig.

> **`pango` ist der Grund, warum der Mac hier im Vorteil ist.** Unter Windows fehlen diese
> Bibliotheken und die Rechnungs-PDFs bleiben tot; auf dem Mac sind sie eine Zeile weit weg, und
> die Fakturierung lässt sich vollständig ausprobieren.

---

## Schritt 2: Quelltext holen

```bash
mkdir -p ~/ip3-probe && cd ~/ip3-probe
git clone -b claude/new-session-9oqvjg https://github.com/wilhelm-sven-dotcom/ip3-Leitstand.git
cd ip3-Leitstand
```

Beim ersten Mal fragt Git nach der GitHub-Anmeldung. Das Repository ist privat, ohne Anmeldung
geht es nicht. Kommt keine Abfrage, sondern gleich `Authentication failed`, hilft der
GitHub-eigene Weg: `brew install gh && gh auth login`, danach `git clone` erneut.

> **`-b claude/new-session-9oqvjg` ist wichtig.** Die Arbeit liegt auf diesem Zweig, nicht auf dem
> Hauptzweig. Ohne den Schalter landet ein älterer Stand auf der Platte.

---

## Schritt 3: Konfiguration anlegen

Zwei kleine Textdateien, beide direkt in `~/ip3-probe/ip3-Leitstand`. Der Block schreibt sie
selbst – einfach kopieren und einfügen:

```bash
cat > config.toml <<EOF
[app]
umgebung = "entwicklung"

[pfade]
datenbank   = "$HOME/ip3-probe/daten/leitstand.sqlite3"
logs        = "$HOME/ip3-probe/logs"
backup      = "$HOME/ip3-probe/04_Backup"
rechnungen  = "$HOME/ip3-probe/01_Rechnungen"
datev       = "$HOME/ip3-probe/02_DATEV"
kalkulation = "$HOME/ip3-probe/03_Kalkulation"
frontend    = "$HOME/ip3-probe/ip3-Leitstand/frontend/dist"

[sitzung]
cookie_secure = false
EOF

mkdir -p ~/ip3-probe/{daten,logs,04_Backup,01_Rechnungen,02_DATEV,03_Kalkulation}
cp .env.example .env
```

Drei Dinge verdienen eine Erklärung:

* **`cookie_secure = false`** erlaubt die Anmeldung über `http://` ohne Verschlüsselung. Für den
  Betrieb wäre das falsch – deshalb **verweigert der Leitstand den Start**, wenn `umgebung` auf
  `produktion` steht und dieser Schalter aus ist. Auf dem eigenen Rechner, wo nichts das Gerät
  verlässt, ist er in Ordnung.
* **`$HOME` wird beim Einfügen ersetzt**, es steht danach der echte Pfad in der Datei. Wer den
  Block von Hand abtippt, schreibt gleich `/Users/<name>/…`.
* **Der Ordner liegt bewusst direkt im Benutzerverzeichnis** und nicht unter „Dokumente" oder auf
  dem Schreibtisch. Wer den synchronisierten Dokumentenordner benutzt, legt die Datenbank in
  iCloud – und SQLite und Ordnersynchronisation zerstören sich gegenseitig. Der Leitstand erkennt
  das inzwischen auch in der macOS-Schreibweise (`~/Library/Mobile Documents/…`) und startet dann
  gar nicht erst.

> **Beide Dateien bleiben auf diesem Rechner.** `config.toml` und `.env` stehen in `.gitignore`
> und wandern nie nach GitHub. Genau deshalb gehören Zugangsdaten – später der TimeTac-Zugang –
> dort hinein und nicht in eine Datei, die eingecheckt wird.

---

## Schritt 4: Backend einrichten

```bash
cd ~/ip3-probe/ip3-Leitstand/backend
uv sync
uv run alembic upgrade head
uv run ip3-leitstand seed --demodaten
```

Der erste Befehl dauert am längsten – er lädt Python und die Bibliotheken. Die drei bedeuten der
Reihe nach: Abhängigkeiten holen, Datenbank anlegen, Grunddaten und Demoprojekte einspielen.

Am Ende steht das Startpasswort auf dem Bildschirm:

```
Zugangsdaten für die erste Anmeldung:
  E-Mail:   s.wilhelm@ip3-energie.de
  Passwort: jmjpMVKsuG5zNPRo
```

**Dieses Passwort erscheint nur einmal.** Notieren. Es muss bei der ersten Anmeldung gewechselt
werden – der Leitstand lässt vorher nichts anderes zu.

---

## Schritt 5: Oberfläche bauen

```bash
cd ~/ip3-probe/ip3-Leitstand/frontend
npm ci
npm run build
```

Das entsteht einmal und liegt danach in `frontend/dist` – genau dort, wohin `config.toml` in
Schritt 3 zeigt. Der Leitstand liefert die Oberfläche dann selbst aus; ein zweites Programm läuft
nicht.

---

## Schritt 6: Starten

```bash
cd ~/ip3-probe/ip3-Leitstand/backend
uv run ip3-leitstand server
```

Wenn `Application startup complete` erscheint, im Browser **<http://localhost:8000>** aufrufen und
mit E-Mail und Startpasswort anmelden. Es folgt sofort die Passwortänderung.

**Das Fenster bleibt offen, solange der Leitstand läuft.** Beenden mit `Ctrl+C` (nicht
Command+C). Erneut starten: dasselbe Kommando – Daten und Passwort bleiben erhalten.

Beim Start stehen zwei gelbe `WARNING`-Zeilen im Protokoll: **TimeTac-Zugangsdaten fehlen** und
**Firmenstammdaten unvollständig**. Beides ist bei einer Probeinstallation richtig so – die
Zugangsdaten sind nicht eingetragen und die Bankverbindung steht bewusst nicht im Repository. Der
Leitstand läuft trotzdem; er sagt nur, was für den Echtbetrieb noch fehlt.

---

## Schritt 7: Damit Zahlen dastehen

Nach der Anmeldung sind fünf Demoprojekte da, aber die **Nachkalkulation** ist noch leer: es gibt
weder Sollwerte noch Ist-Kosten. Dafür liegen im Repository vorbereitete Beispieldateien
(erfunden, siehe [`../vorlagen/beispiele/LIESMICH.md`](../vorlagen/beispiele/LIESMICH.md)).

Ein **zweites** Terminalfenster öffnen (Command+N) – das erste läuft ja weiter:

```bash
cd ~/ip3-probe/ip3-Leitstand
cp vorlagen/beispiele/*.xlsx ~/ip3-probe/03_Kalkulation/
cp vorlagen/beispiele/kostentraeger_2026-07.csv ~/ip3-probe/02_DATEV/
```

Dann im Browser auf **Importe & Daten**: bei „Kalkulationsblätter" und bei „DATEV" jeweils die
Vorschau ansehen und übernehmen. Die Stunden kommen im Regelbetrieb über die
TimeTac-Schnittstelle; solange die Zugangsdaten nicht eingetragen sind, tut es die Beispieldatei:

```bash
cd ~/ip3-probe/ip3-Leitstand/backend
uv run ip3-leitstand timetac-csv ../vorlagen/beispiele/timetac_2026-07.csv
```

Danach steht unter **Nachkalkulation** bei Projekt 26001:

| | |
|---|---|
| Erlös | 367.500,00 € |
| Ist DATEV | 124.055,20 € |
| Ist Stunden | 3.363,75 € (51,75 h) |
| Ist Lager | 0,00 € – noch nicht gezählt |
| **Marge** | **240.081,05 € = 65,3 %** |

Die 65 % sind zu schön, und der Leitstand sagt es auch: ein Hinweis am Projekt meldet, dass vier
Lagerpositionen noch nicht gezählt sind und die Marge deshalb besser aussieht, als sie ist. Wer im
Reiter **Mengen-Ist bestätigen** die Mengen übernimmt, sieht die Lagerentnahme dazukommen
(32.997,00 €) und die Marge auf 56,3 % fallen. Genau dafür ist die Maske da.

**Bei den Importen ist Rot erwartet, nicht kaputt.** Der DATEV-Lauf endet mit „Warnung" und nennt
drei nicht übernommene Zeilen: ein Erlöskonto (8400), eine Buchung ohne Kostenträger (die
Hallenmiete) und einen Kostenträger, zu dem es kein Projekt gibt. So soll es sein – die
Beispieldatei enthält diese Fälle absichtlich, damit sichtbar wird, was der Leitstand aussortiert
und warum. Dasselbe beim TimeTac-Bericht mit der internen Besprechung und dem Mitarbeiter ohne
hinterlegten Stundensatz.

---

## Was funktioniert und was nicht

**Läuft:** Projekte, Kunden, Zahlungsplan, Meilensteine, Nachträge, Umsatzauswertung,
Auftragsbestand, Nachkalkulation, alle Importe, Systemstatus, Rechte und Rollen – und mit `pango`
aus Schritt 1 auch die **Rechnungs-PDFs** samt E-Rechnung im ip³-Corporate-Design.

**Nicht in dieser Probe:** die echten Firmendaten. Der Probelauf hat Demodaten. Die Übernahme der
539 Bestandsprojekte aus den beiden Excel-Dateien ist ein eigener, einmaliger Vorgang auf dem
Rechner, der den Leitstand später wirklich betreibt (`ip3-leitstand migration-uebernehmen`,
beschrieben im RUNBOOK) – sie gehört nicht in einen Wegwerf-Ordner.

---

## Wenn etwas klemmt

| Was auf dem Bildschirm steht | Was zu tun ist |
|---|---|
| `Sorry, try again` beim Homebrew-Installer | Das Anmeldepasswort dieses Macs stimmt nicht. Beim Tippen erscheint bewusst nichts – blind eingeben. Feststelltaste prüfen, und daran denken, dass auf der deutschen Tastatur `y` und `z` vertauscht sind. Nach drei Fehlversuchen bricht der Installer ab; den Befehl einfach erneut ausführen. Kommt danach `is not in the sudoers file`, ist dieses Konto kein Administrator (Systemeinstellungen → Benutzer & Gruppen). |
| Homebrew scheidet aus (Konto ohne Administratorrechte) | Notlösung: `uv` lässt sich ohne Administratorrechte nach `~/.local/bin` installieren – `curl -LsSf https://astral.sh/uv/install.sh \| sh`. `git` bringen die Xcode-Kommandozeilenwerkzeuge mit (`xcode-select --install`), `node` gibt es als Archiv von nodejs.org zum Auspacken ins Benutzerverzeichnis. Ohne `pango` bleiben die Rechnungs-PDFs allerdings tot – wie unter Windows. |
| `zsh: command not found: brew` | Homebrew ist installiert, aber nicht im Pfad. Die zwei Zeilen ausführen, die der Installer am Ende genannt hat, oder Terminal schließen und neu öffnen. |
| `zsh: command not found: uv` (nach `brew install`) | Terminal schließen und neu öffnen. |
| `fatal: could not read Username` oder `Authentication failed` | Die GitHub-Anmeldung fehlt. `brew install gh && gh auth login`, danach `git clone` erneut. |
| Beim Start: eine Meldung über **Ordnersynchronisation** | Der Datenbankpfad liegt in iCloud, Dropbox oder OneDrive. In `config.toml` unter `[pfade]` auf `~/ip3-probe/daten/` ändern. |
| Anmeldung schlägt fehl, die Seite lädt neu | In `config.toml` fehlt `cookie_secure = false` unter `[sitzung]`. Ohne diesen Eintrag verwirft der Browser das Sitzungs-Cookie auf `http://`. |
| Startpasswort verloren | `uv run ip3-leitstand passwort-setzen s.wilhelm@ip3-energie.de` im Ordner `backend` – setzt ein neues und zeigt es an. |
| `address already in use` auf Port 8000 | Ein anderer Leitstand läuft noch. Altes Fenster mit `Ctrl+C` beenden, oder in `config.toml` unter `[app]` `port = 8010` setzen und `http://localhost:8010` aufrufen. |
| `{"code":"nicht_gefunden", …}` statt der Oberfläche | `npm run build` fehlt, oder `frontend` in `config.toml` zeigt woanders hin. Der Pfad muss auf `frontend/dist` zeigen. |
| Beim PDF: `cannot load library 'libgobject-2.0.0.dylib'` | WeasyPrint findet die Homebrew-Bibliotheken nicht. Auf Apple Silicon liegen sie in `/opt/homebrew/lib`, das nicht im Standard-Suchpfad steht. Den Leitstand dann so starten: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run ip3-leitstand server` |

Bleibt es unklar: die Meldung aus dem Terminal kopieren. Der Leitstand schreibt zu jedem
unerwarteten Fehler eine Vorgangsnummer, mit der sich der Eintrag in `~/ip3-probe/logs` finden
lässt.

---

## Aufräumen

```bash
rm -rf ~/ip3-probe
```

Mehr ist nicht nötig: außerhalb dieses Ordners wurde nichts angelegt, kein Dienst eingerichtet,
nichts in die Systemeinstellungen geschrieben. Homebrew, git, node und uv dürfen stehen bleiben –
sie werden für den späteren Betrieb ohnehin gebraucht.

---

## Auf einem Windows-Rechner

Vier der sieben Schritte sind identisch: **4 (Backend), 5 (Oberfläche), 6 (Starten)** und die
Importe im Browser. Es unterscheiden sich nur die Installation, die Pfadschreibweise und die
Kopierbefehle. Alles läuft in **PowerShell** (Windows-Taste → „PowerShell" → Enter),
Administratorrechte sind nicht nötig.

**Schritt 1 – Installation:**

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id astral-sh.uv -e
```

Danach PowerShell einmal schließen und neu öffnen, sonst kennt das Fenster die neuen Befehle
nicht. Ein Gegenstück zu `brew install pango` gibt es nicht: **die Rechnungs-PDFs laufen unter
Windows erst, wenn GTK/Pango getrennt installiert ist.** Bis dahin endet „PDF-Vorschau" mit „Im
Leitstand ist ein unerwarteter Fehler aufgetreten" und einer Vorgangsnummer; alles andere an der
Fakturierung – Beleg anlegen, Positionen, Steueraufteilung, Absetzung der Abschläge,
Festschreibung – arbeitet normal.

**Schritt 2 – Quelltext:**

```powershell
mkdir C:\ip3-probe
cd C:\ip3-probe
git clone -b claude/new-session-9oqvjg https://github.com/wilhelm-sven-dotcom/ip3-Leitstand.git
cd ip3-Leitstand
```

**Schritt 3 – Konfiguration:**

```powershell
@'
[app]
umgebung = "entwicklung"

[pfade]
datenbank   = 'C:\ip3-probe\daten\leitstand.sqlite3'
logs        = 'C:\ip3-probe\logs'
backup      = 'C:\ip3-probe\04_Backup'
rechnungen  = 'C:\ip3-probe\01_Rechnungen'
datev       = 'C:\ip3-probe\02_DATEV'
kalkulation = 'C:\ip3-probe\03_Kalkulation'
frontend    = 'C:\ip3-probe\ip3-Leitstand\frontend\dist'

[sitzung]
cookie_secure = false
'@ | Set-Content -Encoding UTF8 config.toml

mkdir C:\ip3-probe\daten, C:\ip3-probe\logs, C:\ip3-probe\04_Backup, `
      C:\ip3-probe\01_Rechnungen, C:\ip3-probe\02_DATEV, C:\ip3-probe\03_Kalkulation

Copy-Item .env.example .env
```

**Schritt 7 – Beispieldateien:**

```powershell
cd C:\ip3-probe\ip3-Leitstand
Copy-Item vorlagen\beispiele\*.xlsx C:\ip3-probe\03_Kalkulation\
Copy-Item vorlagen\beispiele\kostentraeger_2026-07.csv C:\ip3-probe\02_DATEV\
```

**Aufräumen:** `Remove-Item -Recurse -Force C:\ip3-probe`

In der Fehlertabelle oben gelten sinngemäß dieselben Zeilen; statt `zsh: command not found` heißt
es dort `Die Benennung "uv" wurde nicht … erkannt`, und die Lösung ist dieselbe: PowerShell
schließen und neu öffnen.
