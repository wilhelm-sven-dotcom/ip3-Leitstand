# Den Leitstand auf dem eigenen PC ansehen

Diese Anleitung bringt den Leitstand auf einen normalen Windows-Rechner – zum Anschauen, nicht
zum Betreiben. Rund 30 Minuten, davon das meiste Wartezeit beim Herunterladen.

**Was dabei entsteht:** eine vollständige Anwendung mit erfundenen Demodaten, die nur auf diesem
einen Rechner läuft. Kein Server, kein Netz, keine echten Firmendaten. Zum Wegwerfen: der Ordner
kann hinterher gelöscht werden, es bleibt nichts zurück.

**Was das *nicht* ist:** der spätere Betrieb. Wie der Leitstand als Dienst mit Autostart, TLS und
nächtlicher Sicherung eingerichtet wird, steht in [`../RUNBOOK.md`](../RUNBOOK.md) und
[`../deploy/windows/NSSM-Einrichtung.md`](../deploy/windows/NSSM-Einrichtung.md). Die Entscheidung,
**wo** er am Ende läuft (Bürorechner oder gemieteter Server), muss jetzt noch nicht fallen.

---

## Schritt 1: Drei Programme installieren

Alle drei über PowerShell, das auf jedem Windows liegt. **Windows-Taste → „PowerShell" tippen →
Enter.** Administratorrechte sind nicht nötig.

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id astral-sh.uv -e
```

| Programm | Wofür |
|---|---|
| **Git** | holt den Quelltext von GitHub |
| **Node** | baut die Oberfläche einmal zusammen |
| **uv** | bringt Python mit und richtet das Backend ein – Python muss **nicht** getrennt installiert werden |

Falls `winget` nicht bekannt ist: die drei von <https://git-scm.com>, <https://nodejs.org>
(LTS-Version) und <https://docs.astral.sh/uv/> herunterladen und normal installieren.

**Danach PowerShell einmal schließen und neu öffnen.** Sonst kennt das Fenster die neuen Befehle
noch nicht. Zur Kontrolle:

```powershell
git --version
node --version
uv --version
```

Drei Versionsnummern = fertig. Kommt „wird nicht erkannt", ist das Fenster noch das alte.

---

## Schritt 2: Quelltext holen

```powershell
mkdir C:\ip3-probe
cd C:\ip3-probe
git clone -b claude/new-session-9oqvjg https://github.com/wilhelm-sven-dotcom/ip3-Leitstand.git
cd ip3-Leitstand
```

Beim ersten Mal fragt Git nach der GitHub-Anmeldung – ein Browserfenster geht auf, dort mit dem
GitHub-Konto anmelden. Das Repository ist privat, ohne Anmeldung geht es nicht.

> **`-b claude/new-session-9oqvjg` ist wichtig.** Die Arbeit liegt auf diesem Zweig, nicht auf dem
> Hauptzweig. Ohne den Schalter landet ein älterer Stand auf der Platte.

---

## Schritt 3: Konfiguration anlegen

Zwei kleine Textdateien, beide direkt in `C:\ip3-probe\ip3-Leitstand`. Beide Blöcke einfach ins
PowerShell-Fenster kopieren – sie schreiben die Dateien selbst:

```powershell
@'
[app]
umgebung = "entwicklung"

[pfade]
datenbank = 'C:\ip3-probe\daten\leitstand.sqlite3'
logs      = 'C:\ip3-probe\logs'
backup    = 'C:\ip3-probe\04_Backup'
rechnungen = 'C:\ip3-probe\01_Rechnungen'
datev      = 'C:\ip3-probe\02_DATEV'
kalkulation = 'C:\ip3-probe\03_Kalkulation'
frontend  = 'C:\ip3-probe\ip3-Leitstand\frontend\dist'

[sitzung]
cookie_secure = false
'@ | Set-Content -Encoding UTF8 config.toml

mkdir C:\ip3-probe\daten, C:\ip3-probe\logs, C:\ip3-probe\04_Backup, `
      C:\ip3-probe\01_Rechnungen, C:\ip3-probe\02_DATEV, C:\ip3-probe\03_Kalkulation
```

Zwei Zeilen verdienen eine Erklärung:

* **`cookie_secure = false`** erlaubt die Anmeldung über `http://` ohne Verschlüsselung. Für den
  Betrieb wäre das falsch – deshalb **verweigert der Leitstand den Start**, wenn `umgebung` auf
  `produktion` steht und dieser Schalter aus ist. Auf dem eigenen Rechner, wo nichts das Gerät
  verlässt, ist er in Ordnung.
* **`datenbank`** liegt bewusst unter `C:\ip3-probe\` und **nicht** in OneDrive. SQLite und
  Ordnersynchronisation zerstören sich gegenseitig; der Leitstand erkennt einen Sync-Pfad und
  startet dann gar nicht erst.

Die zweite Datei, `.env`, enthält später die Geheimnisse (TimeTac-Zugang). Zum Anschauen wird sie
noch nicht gebraucht – aber sie gleich anzulegen erspart später einen Schritt:

```powershell
Copy-Item .env.example .env
```

> **Beide Dateien bleiben auf diesem Rechner.** `config.toml` und `.env` sind in `.gitignore`
> eingetragen und wandern nie nach GitHub. Genau deshalb gehören Zugangsdaten dort hinein und
> nicht in eine Datei, die eingecheckt wird.

---

## Schritt 4: Backend einrichten

```powershell
cd C:\ip3-probe\ip3-Leitstand\backend
uv sync
uv run alembic upgrade head
uv run ip3-leitstand seed --demodaten
```

Der erste Befehl dauert am längsten – er lädt Python und die Bibliotheken. Die drei Befehle
bedeuten der Reihe nach: Abhängigkeiten holen, Datenbank anlegen, Grunddaten und Demoprojekte
einspielen.

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

```powershell
cd C:\ip3-probe\ip3-Leitstand\frontend
npm ci
npm run build
```

Das entsteht einmal und liegt danach in `frontend\dist` – genau dort, wohin `config.toml` in
Schritt 3 zeigt. Der Leitstand liefert die Oberfläche dann selbst aus; ein zweites Programm
läuft nicht.

---

## Schritt 6: Starten

```powershell
cd C:\ip3-probe\ip3-Leitstand\backend
uv run ip3-leitstand server
```

Wenn `Application startup complete` erscheint, im Browser **<http://localhost:8000>** aufrufen und
mit E-Mail und Startpasswort anmelden. Es folgt sofort die Passwortänderung.

**Das Fenster bleibt offen, solange der Leitstand läuft.** Beenden mit `Strg+C`. Erneut starten:
dasselbe Kommando – Daten und Passwort bleiben erhalten.

---

## Schritt 7: Damit Zahlen dastehen

Nach der Anmeldung sind fünf Demoprojekte da, aber die **Nachkalkulation** ist noch leer: es gibt
weder Sollwerte noch Ist-Kosten. Dafür liegen im Repository vorbereitete Beispieldateien
(erfunden, siehe [`../vorlagen/beispiele/LIESMICH.md`](../vorlagen/beispiele/LIESMICH.md)).

Ein **zweites** PowerShell-Fenster öffnen – das erste läuft ja weiter:

```powershell
cd C:\ip3-probe\ip3-Leitstand
Copy-Item vorlagen\beispiele\*.xlsx C:\ip3-probe\03_Kalkulation\
Copy-Item vorlagen\beispiele\kostentraeger_2026-07.csv C:\ip3-probe\02_DATEV\
```

Dann im Browser auf **Importe & Daten**: bei „Kalkulationsblätter" und bei „DATEV" jeweils die
Vorschau ansehen und übernehmen. Die Stunden kommen im Regelbetrieb über die
TimeTac-Schnittstelle; solange die Zugangsdaten nicht eingetragen sind, tut es die Beispieldatei:

```powershell
cd C:\ip3-probe\ip3-Leitstand\backend
uv run ip3-leitstand timetac-csv ..\vorlagen\beispiele\timetac_2026-07.csv
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

**Läuft sofort:** Projekte, Kunden, Zahlungsplan, Meilensteine, Nachträge, Umsatzauswertung,
Auftragsbestand, Nachkalkulation, alle Importe, Systemstatus, Rechte und Rollen.

**Läuft nicht ohne Zusatzinstallation: die Rechnungs-PDFs.** Der Satz der Belege braucht die
Grafikbibliotheken GTK/Pango, die es unter Windows nicht von Haus aus gibt. Ein Klick auf
„PDF-Vorschau" endet deshalb mit „Im Leitstand ist ein unerwarteter Fehler aufgetreten" und einer
Vorgangsnummer. Alles andere an der Fakturierung – Beleg anlegen, Positionen, Steueraufteilung,
Absetzung der Abschläge, Festschreibung – arbeitet normal. Für den späteren Betrieb wird GTK auf
dem Rechner nachinstalliert, der die Rechnungen erzeugt; für den ersten Blick lohnt das nicht.

**Nicht in dieser Probe:** die echten Firmendaten. Der Probelauf hat Demodaten. Die Übernahme der
539 Bestandsprojekte aus den beiden Excel-Dateien ist ein eigener, einmaliger Vorgang auf dem
Rechner, der den Leitstand später wirklich betreibt (`ip3-leitstand migration-uebernehmen`,
beschrieben im RUNBOOK) – sie gehört nicht in einen Wegwerf-Ordner.

---

## Wenn etwas klemmt

| Was auf dem Bildschirm steht | Was zu tun ist |
|---|---|
| `uv : Die Benennung "uv" wurde nicht als Name eines Cmdlet ... erkannt` | PowerShell schließen und neu öffnen. Die Installation trägt den Pfad erst für neue Fenster ein. |
| `fatal: repository not found` beim Klonen | Die GitHub-Anmeldung ist nicht durchgelaufen. `git clone` erneut ausführen und im Browserfenster anmelden. |
| Beim Start: eine Meldung über **Ordnersynchronisation** | Der Datenbankpfad zeigt in einen OneDrive- oder Dropbox-Ordner. In `config.toml` unter `[pfade]` auf einen lokalen Pfad ändern (z. B. `C:\ip3-probe\daten\`). |
| Anmeldung schlägt fehl, die Seite lädt neu | In `config.toml` fehlt `cookie_secure = false` unter `[sitzung]`. Ohne diesen Eintrag verwirft der Browser das Sitzungs-Cookie auf `http://`. |
| Startpasswort verloren | `uv run ip3-leitstand passwort-setzen s.wilhelm@ip3-energie.de` im Ordner `backend` – setzt ein neues und zeigt es an. |
| `Port 8000 wird bereits verwendet` | Ein anderer Leitstand läuft noch. Das alte Fenster mit `Strg+C` beenden, oder in `config.toml` unter `[app]` `port = 8010` setzen und `http://localhost:8010` aufrufen. |
| Statt der Oberfläche steht `{"code":"nicht_gefunden","meldung":"Die Adresse gibt es nicht."…}` da | `npm run build` fehlt, oder `frontend` in `config.toml` zeigt woanders hin. Der Pfad muss auf den Ordner `frontend\dist` zeigen. |

Bleibt es unklar: die Meldung aus dem PowerShell-Fenster kopieren. Der Leitstand schreibt zu jedem
unerwarteten Fehler eine Vorgangsnummer, mit der sich der Eintrag in `C:\ip3-probe\logs` finden
lässt.

---

## Aufräumen

```powershell
Remove-Item -Recurse -Force C:\ip3-probe
```

Mehr ist nicht nötig: es wurde nichts in die Registry geschrieben, kein Dienst eingerichtet und
außerhalb dieses Ordners nichts angelegt. Git, Node und uv dürfen stehen bleiben – sie werden für
den späteren Betrieb ohnehin gebraucht.
