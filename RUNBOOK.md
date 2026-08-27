# RUNBOOK – Betrieb des ip³ Leitstands

Für den Bürorechner, auf dem der Leitstand läuft. Wird mit jeder Phase aktuell gehalten.
Stand: Phase 0.

## 1. Überblick

| Was | Wert |
|---|---|
| Host | _eintragen (siehe docs/OFFENE-PUNKTE.md)_ |
| Adresse | `https://leitstand.ip3.local` |
| Anwendung | ein Prozess (`ip3-leitstand server`), liefert API **und** Oberfläche |
| Reverse Proxy | Caddy mit TLS aus interner Zertifizierungsstelle, `deploy/Caddyfile` |
| Ports | 443 nach außen (nur Büro-Netz), 8000 nur lokal |
| Datenbank | `daten\leitstand.sqlite3` – **lokal auf dem Host, niemals in OneDrive** |
| Backup-Ziel | OneDrive-Ordner `04_Backup`, 30 Generationen, nächtlich 01:30 |
| Protokolle | `logs\leitstand.log` (Anwendung), `logs\dienst-*.log` (Dienst) |
| Testinstanz | Port 8010, eigene Datenbankkopie, `deploy/Caddyfile.testinstanz` |

**Warum die Datenbank nicht in OneDrive gehört:** SQLite sichert gleichzeitige Zugriffe über
Dateisperren ab, die eine Ordnersynchronisation nicht kennt. Die Datei wird dabei früher oder
später beschädigt. Der Leitstand verweigert deshalb den Start, wenn der Datenbankpfad nach
einem Sync-Ordner aussieht. Die **Sicherungen** liegen sehr wohl in OneDrive – dort wird nur
gelesen und geschrieben, nicht gleichzeitig gearbeitet.

## 2. Installation

Ausführlich für Windows: `deploy/windows/NSSM-Einrichtung.md`. Für Linux:
`deploy/systemd/ip3-leitstand.service`.

Kurzfassung:

1. Voraussetzungen: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 22 (nur zum Bauen),
   Caddy, unter Windows zusätzlich NSSM.
2. Repository auf den Host holen, Verzeichnisse `daten\` und `logs\` anlegen.
3. `config.example.toml` nach `config.toml` kopieren und ausfüllen: Pfade, Firmenstammdaten,
   Backup-Ziel. `.env.example` nach `.env` kopieren und einen Sitzungsschlüssel erzeugen:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
4. Backend einrichten:
   ```
   cd backend
   uv sync --frozen
   uv run alembic upgrade head
   uv run ip3-leitstand seed
   ```
   Das ausgegebene Passwort notieren – es erscheint nur einmal.
5. Oberfläche bauen:
   ```
   cd frontend
   npm ci
   npm run build
   ```
   Danach in `config.toml` unter `[pfade]` den Eintrag `frontend` auf `frontend/dist` setzen.
6. Dienste einrichten (NSSM oder systemd), Caddy starten, `caddy trust` ausführen.
7. Das Wurzelzertifikat der Caddy-Zertifizierungsstelle auf **jedem** Arbeitsplatz importieren.
   Ohne diesen Schritt zeigt der Browser eine Warnung, und Nutzer lernen, Warnungen
   wegzuklicken.
8. Anmelden, Passwort wechseln, Datenstand auf der Startseite prüfen.
8a. Konten für die übrigen Nutzer anlegen – solange es keine Nutzerverwaltung in der Oberfläche
   gibt, läuft das über die Kommandozeile:
   ```
   uv run ip3-leitstand nutzer-anlegen michael@ip3-energie.de "Michael Bäumler" --rolle admin
   uv run ip3-leitstand nutzer-anlegen buchhaltung@ip3-energie.de "Vorname Name" --rolle buchhaltung
   uv run ip3-leitstand nutzer-anlegen monteur@ip3-energie.de "Vorname Name" --rolle team
   ```
   Jedes ausgegebene Startpasswort einmal weitergeben; es muss bei der ersten Anmeldung
   gewechselt werden. Vorhandene Konten zeigt `ip3-leitstand nutzer-liste`.
9. `ip3-leitstand backup` **als Dienstkonto** ausführen und nachsehen, ob die Datei im
   Zielordner ankommt.

## 3. Start und Stopp

Reihenfolge: erst der Leitstand, dann Caddy. Umgekehrt zeigt Caddy kurzzeitig einen Fehler.

**Windows**

```powershell
nssm start ip3-leitstand
nssm start ip3-caddy

nssm stop ip3-caddy
nssm stop ip3-leitstand
nssm status ip3-leitstand
```

**Linux**

```bash
sudo systemctl start ip3-leitstand caddy
sudo systemctl stop caddy ip3-leitstand
sudo systemctl status ip3-leitstand
sudo journalctl -u ip3-leitstand -f
```

**Gesundheitsprüfung** – ohne Anmeldung abrufbar:

```
https://leitstand.ip3.local/api/gesundheit
```

Erwartet: `{"status": "bereit", "version": "...", "datenbank": "erreichbar"}`.

## 4. Alltag: Protokolle und Datenstand

* **Datenstand auf der Startseite** ist die erste Anlaufstelle. Dort steht, wann die Sicherung
  zuletzt lief. Ein roter Punkt bedeutet: der letzte Lauf ist gescheitert oder länger her als
  erwartet. Wer `admin.jobs` hat, kann einen Lauf direkt auslösen.
* **`logs\leitstand.log`** enthält die Anwendungsmeldungen, zehn Generationen à 10 MB.
  Beim Lesen die Datei nicht offen halten – auf Windows scheitert sonst das Rollen.
* **Vorgangsnummer:** Meldet der Leitstand einen unerwarteten Fehler, nennt er eine
  achtstellige Nummer. Mit ihr findet sich der vollständige Eintrag im Protokoll.

## 5. Update über die Testinstanz

Nie direkt auf der Produktivinstanz (PLAN §2). Der Ablauf:

**Testinstanz vorbereiten**

1. Sicherung ziehen: `ip3-leitstand backup`
2. Die jüngste Sicherung in das Datenverzeichnis der Testinstanz kopieren.
3. Dort den neuen Stand einspielen:
   ```
   git pull
   cd backend && uv sync --frozen && uv run alembic upgrade head
   cd ../frontend && npm ci && npm run build
   cd ../backend && uv run pytest
   ```
4. Testinstanz starten (Port 8010) und die **Abnahmeliste** (Abschnitt 10) durchgehen.

**Produktivinstanz aktualisieren** – erst wenn die Testinstanz sauber ist:

1. Nutzer informieren.
2. `ip3-leitstand backup`
3. Dienst stoppen: `nssm stop ip3-leitstand` bzw. `systemctl stop ip3-leitstand`
4. `git pull`, `uv sync --frozen`, `alembic upgrade head`, `npm ci && npm run build`
5. Dienst starten, Gesundheitsprüfung abrufen, Abnahmeliste kurz durchgehen.

**Zurück auf den alten Stand**

Dienst stoppen, `alembic downgrade <vorherige Revision>`, alten Stand auschecken, Dienst
starten. Führt eine Migration Daten zusammen oder verwirft Spalten, ist der Restore
(Abschnitt 7) der sicherere Weg.

## 6. Backup

* **Wann:** nächtlich um 01:30 Ortszeit, konfigurierbar unter `[jobs] backup_uhrzeit`.
* **Wohin:** `[pfade] backup`, üblicherweise der OneDrive-Ordner `04_Backup`.
* **Wie viele:** 30 Generationen (`[jobs] backup_generationen`). Ältere werden gelöscht –
  ausschließlich Dateien mit dem Namensmuster `leitstand_JJJJMMTT-HHMMSS.sqlite3`. Andere
  Dateien im Ordner bleibt der Leitstand unangetastet.
* **Was genau:** eine in sich geschlossene Kopie der Datenbank (`VACUUM INTO`), erzeugt auch
  während gearbeitet wird. Sie hat **keine** Begleitdateien `-wal` und `-shm`; für den Restore
  genügt diese eine Datei.
* **Prüfung:** jede Sicherung wird direkt nach dem Schreiben auf Integrität geprüft. Ein
  Fehler erscheint als Warnung im Datenstand.
* **Von Hand auslösen:** `ip3-leitstand backup` oder auf der Startseite „Jetzt ausführen".
* **Nachsehen, dass es lief:** Datenstand auf der Startseite; dort steht das Alter der
  jüngsten erfolgreichen Sicherung.

Die Rechnungs-PDFs und -XMLs liegen ab Phase 3 ohnehin im OneDrive und werden dort
mitgesichert.

## 7. Restore Schritt für Schritt

Ruhig lesen, dann handeln. Die Reihenfolge ist wichtig: die vorhandene Datenbank wird
**beiseitegelegt, nicht gelöscht** – falls die Sicherung unbrauchbar ist, ist sie die einzige
verbleibende Quelle.

1. **Nutzer informieren** und den Dienst stoppen:
   ```
   nssm stop ip3-leitstand          # Windows
   sudo systemctl stop ip3-leitstand   # Linux
   ```

2. **Vorhandene Datenbank beiseitelegen** (umbenennen, nicht löschen), samt Begleitdateien:
   ```
   cd D:\ip3-leitstand\daten
   rename leitstand.sqlite3      leitstand.sqlite3.vor-restore-2026-08-27
   rename leitstand.sqlite3-wal  leitstand.sqlite3-wal.vor-restore-2026-08-27
   rename leitstand.sqlite3-shm  leitstand.sqlite3-shm.vor-restore-2026-08-27
   ```
   Die beiden letzten gibt es möglicherweise nicht – das ist in Ordnung.

3. **Gewünschte Sicherung wählen.** Die Dateinamen tragen Datum und Uhrzeit in Ortszeit:
   `leitstand_20260827-013000.sqlite3`. Im Zweifel die jüngste.

4. **Sicherung kopieren und umbenennen:**
   ```
   copy "C:\...\04_Backup\leitstand_20260827-013000.sqlite3" "D:\ip3-leitstand\daten\leitstand.sqlite3"
   ```
   Kopieren, nicht verschieben: die Sicherung bleibt im Backup-Ordner.

5. **Prüfen, bevor der Dienst wieder läuft:**
   ```
   cd D:\ip3-leitstand\backend
   uv run ip3-leitstand pruefen
   ```
   Der Befehl nennt Größe, Integrität, Tabellen mit Zeilenzahlen und den Schemastand. Zeigt er
   einen Integritätsfehler: **nicht starten**, sondern die nächstältere Sicherung versuchen.

6. **Schemastand angleichen**, wenn der Befehl eine ältere Revision meldet als erwartet:
   ```
   uv run ip3-leitstand schema
   ```

7. **Dienst starten** und Gesundheitsprüfung abrufen.

8. **Stichprobe:** anmelden, Datenstand ansehen, einen bekannten Datensatz aufrufen. Ab
   Phase 3 zusätzlich: die letzte Rechnungsnummer je Kreis mit dem Rechnungsordner vergleichen.

9. **Vermerken:** Datum, verwendete Sicherung, Ergebnis in `VERFAHRENSDOKU.md`, Abschnitt 7.
   Eine Rückspielung ohne Vermerk fehlt später in der Nachweiskette.

10. **Nacharbeit:** Alles, was nach dem Zeitpunkt der Sicherung passiert ist, fehlt jetzt. Ab
    Phase 3 heißt das insbesondere: Rechnungen, die nach der Sicherung festgeschrieben wurden,
    sind in der Datenbank nicht mehr vorhanden – die PDFs liegen aber im Rechnungsordner. Diese
    Belege müssen von Hand nachgetragen werden, damit die Nummernkreise lückenlos bleiben. Vor
    dem Nachtragen mit dem Steuerberater sprechen.

Die beiseitegelegte Datei erst löschen, wenn der Leitstand einige Tage einwandfrei läuft.

## 8. Störungen

| Anzeichen | Ursache und Vorgehen |
|---|---|
| Dienst startet nicht | `logs\dienst-fehler.log` bzw. `journalctl -u ip3-leitstand` lesen. Konfigurationsfehler erscheinen dort im Klartext samt nächstem Schritt. |
| „Die Datenbank soll unter … liegen. Der Ordner … deutet auf eine Ordnersynchronisation hin" | Der Datenbankpfad zeigt in einen Sync-Ordner. In `config.toml` unter `[pfade] datenbank` auf ein lokales Verzeichnis setzen. |
| Zertifikatswarnung im Browser | Das Wurzelzertifikat der Caddy-Zertifizierungsstelle fehlt auf dem Arbeitsplatz (Abschnitt 2, Schritt 7). |
| „Datenbank ist gesperrt" | Ein Vorgang hält eine Schreibsperre. Meist ein hängender Import; Protokoll prüfen. Tritt es wiederholt auf: läuft der Dienst versehentlich zweimal? |
| Oberfläche zeigt einen alten Stand | Browser-Cache. Die `index.html` wird mit `no-store` ausgeliefert, ein Neuladen mit Strg+F5 genügt. Tritt es nach jedem Update auf, prüfen, ob Caddy zwischenspeichert. |
| Datenstand zeigt „noch nie gelaufen" | Der Zeitplan läuft nicht: Backup-Ziel gesetzt? Dienst neu gestartet? Einmal von Hand auslösen und die Meldung lesen. |
| Sicherung schlägt jede Nacht fehl | Meist Rechte: das Dienstkonto erreicht den OneDrive-Ordner nicht (siehe `deploy/windows/NSSM-Einrichtung.md`, Hinweis am Anfang). |
| Nutzer ist ausgesperrt | Nach fünf Fehlversuchen 15 Minuten Wartezeit; die Sperre läuft von selbst ab. Passwort vergessen: `uv run ip3-leitstand passwort-setzen <e-mail>` – der Nutzer muss es bei der nächsten Anmeldung wechseln. |
| Mitarbeiter scheidet aus | `uv run ip3-leitstand nutzer-deaktivieren <e-mail>` – offene Sitzungen enden sofort. Das Konto bleibt bestehen, weil das Änderungsprotokoll darauf verweist (PLAN §5). Rückgängig mit `--aktivieren`. |
| Mehrere Sicherungen je Nacht | Der Dienst läuft mit mehreren Arbeitsprozessen. Der Leitstand ist für genau einen gedacht; Startparameter prüfen. |

## 9. Bestandsdaten übernehmen (einmalig, Phase 1)

Die Übernahme liest die beiden Excel-Dateien und schreibt Kunden, Projekte, Meilensteine und
Zahlungsplan in die Datenbank. **Sie läuft genau einmal.** Ein zweiter Lauf wird abgewiesen, weil
er alles doppelt anlegen würde; die Prüfung sitzt in der Datenbank, nicht in der Oberfläche.

### Vorbereitung

1. Beide Dateien in den Migrationsordner legen, unter genau diesen Namen:
   * `Offene_Auftraege_2025.xlsx` (die Auftragsliste mit den Abschlägen)
   * `Teambesprechung_NEU.xlsx` (die Projektliste)
   Der Ordner steht in `config.toml` unter `[pfade] migration`.
2. **Sicherung ziehen** (`ip3-leitstand backup`) – der Rückweg für den Fall, dass die
   Zuordnungen doch nicht stimmen.
3. Die Dateien vorher **nicht** aufräumen. Der Import kommt mit den Eigenheiten zurecht und
   protokolliert jede, die er nicht sicher lesen konnte.

### Ablauf

```bash
# 1. Nur ansehen, nichts schreiben: Kontrollsummen und Befunde
uv run ip3-leitstand migration-analysieren --ausfuehrlich

# 2. Übernahme über die Oberfläche: Importe & Daten → Bestandsdaten übernehmen
#    Dort werden die offenen Zuordnungen entschieden (siehe unten).
```

Die Zuordnung von Hand ist der eigentliche Arbeitsschritt: die Auftragsliste kennt Kunden nur als
Freitext (`Kunde, Ort - Rechnungsart`), die Projektliste führt Projekte. Was eindeutig
zusammenpasst, ordnet der Leitstand selbst zu; der Rest steht in der Maske, nach Betrag sortiert –
die größten Posten zuerst, weil dort eine Fehlzuordnung am meisten kostet. Je Kunde gibt es drei
Möglichkeiten: einen Vorschlag bestätigen, über die Suche ein anderes Projekt wählen oder ein
eigenes Projekt anlegen.

**Hilfreich beim Entscheiden:** die Summe der Auftragszeilen eines Kunden entspricht bei den
meisten Projekten auf den Euro dem AB-Wert genau eines Projekts der Teamliste. Steht in der
Auswahlliste ein Projekt mit genau diesem Wert, ist es das richtige. Beim Abnahmelauf traf das
bei 15 von 24 offenen Kunden zu; die übrigen 9 haben in der Teamliste kein Gegenstück und
bekommen ein eigenes Projekt.

Die Übernahme selbst läuft in **einer** Transaktion: entweder alles oder nichts. Bricht sie ab,
steht die Datenbank unverändert da – auch das Importprotokoll ist dann leer.

### Danach

| Schritt | Warum |
|---|---|
| Beide Excel-Dateien schreibgeschützt setzen | Ab hier ist der Leitstand führend. Zwei Wahrheiten über denselben Auftrag sind der Anfang jeder Abweichung. |
| Menü **Projekte → Projektleiter zuordnen** durchgehen | Die Teamliste führt Vornamen, keine Konten. Erst mit der Zuordnung wirkt eine eingeschränkte Sichtbarkeit. |
| Importprotokoll lesen (Startseite → Datenstand, oder `importlaeufe`) | Dort stehen die Befunde: unlesbare Beträge, abgeleitete Gewerke, Projekte ohne Auftragsjahr. |
| Projekte mit unvollständigem Zahlungsplan ansehen | Die Auftragsliste führt nur die **offenen** Positionen. Bei Altprojekten fehlt der in früheren Jahren berechnete Teil; die Differenz wird ausgewiesen und nicht durch eine erfundene Position geschlossen. |
| Anlagenart je Projekt prüfen | Aufdach, Speicher und Ladestation leitet der Import aus den Anlagendaten ab. Ob eine Anlage auf einer **Freifläche** steht, sagt keine Spalte – das ist in der Projektmaske nachzutragen. |

### Erwartete Zahlen (Abnahmelauf vom 27.08.2026)

| Größe | Wert |
|---|---|
| Kunden | 484 (475 aus der Teamliste, 9 nur in der Auftragsliste) |
| Projekte | 539 (530 + 9 neu angelegte) |
| Meilensteine | 5.848 |
| Zahlungsplanpositionen | 280 mit 3.826.937,38 € netto |
| davon als „gestellt" markiert | 150 mit 862.152,24 € |
| Auftragswert gesamt | 18.085.904,86 € über 500 Projekte mit Wert |

Weichen diese Zahlen bei einem echten Lauf ab, sind die Quelldateien inzwischen andere – das ist
kein Fehler, aber ein Grund, die Kontrollsummen in der Maske vor der Übernahme zu lesen.

## 10. Abnahmeliste

Nach Installation und nach jedem Update auf der Testinstanz durchgehen. Dauert wenige Minuten
und fängt genau die Fehler, die niemand im Protokoll sucht.

| # | Schritt | Erwartet |
|---|---|---|
| 1 | `https://.../api/gesundheit` aufrufen | `status: bereit`, `datenbank: erreichbar` |
| 2 | Startseite aufrufen, ohne angemeldet zu sein | Anmeldeseite in Navy mit Zeichen 3, keine Zertifikatswarnung |
| 3 | Mit falschem Passwort anmelden | „E-Mail-Adresse oder Passwort stimmt nicht." – keine Auskunft darüber, was falsch war |
| 4 | Fünfmal falsch anmelden, dann richtig | Sperre mit Wartezeit in Minuten; auch das richtige Passwort wird abgelehnt |
| 5 | Nach Ablauf der Sperre richtig anmelden | Startseite erscheint, Begrüßung mit Vornamen |
| 6 | Bei einem neuen Konto anmelden | Passwortwechsel wird verlangt und lässt sich nicht umgehen |
| 7 | Startseite ansehen | Datenstand sichtbar, Sicherung mit Alter, spätere Läufe als „kommt später" |
| 8 | „Jetzt ausführen" bei der Sicherung (als Administrator) | Neue Datei im Backup-Ordner, Datenstand zeigt „vor wenigen Minuten" |
| 9 | Als Nutzer der Rolle `team` anmelden | Menüpunkte für Nachkalkulation und Cockpit fehlen – nicht ausgegraut, sondern nicht vorhanden |
| 10 | Tiefe Adresse direkt aufrufen, z. B. `/passwort` | Seite erscheint, keine Fehlermeldung des Servers |
| 11 | Unbekannten API-Pfad aufrufen, z. B. `/api/gibtesnicht` | JSON-Fehlerkörper, keine HTML-Seite |
| 12 | Abmelden, dann zurück-Taste im Browser | Anmeldeseite, keine Daten mehr sichtbar |
| 13 | Restore nach Abschnitt 7 proben (nur bei Installation) | Prüfbefehl meldet Integrität in Ordnung, Anmeldung funktioniert, Daten sind da |
| 14 | Projektliste öffnen, Jahr und Gewerk filtern, „poellath" suchen | Trefferzahl und Auftragsvolumen ändern sich mit dem Filter; die Suche findet Pöllath auch ohne Umlaut |
| 15 | Ein Projekt öffnen, Termin auf „erledigt" setzen, speichern, Seite neu laden | Der Termin steht noch da; das Änderungsprotokoll hat **einen** Eintrag für den Vorgang |
| 16 | Dasselbe Projekt in zwei Browser-Tabs öffnen, in beiden speichern | Der zweite Tab bekommt eine Konfliktmeldung mit Zeitpunkt; die erste Änderung bleibt erhalten |
| 17 | Als Rolle `team` die Projektliste öffnen | Keine Spalte „Auftragswert", kein Auftragsvolumen in der Kopfzeile, kein Knopf „Neues Projekt" |
| 18 | Als Rolle `team` `/api/projekte/<nr>` direkt aufrufen | `ab_wert_netto: null`, `zahlungsplan: []` – die Werte fehlen in der Antwort, nicht nur in der Anzeige |
| 19 | Bei einer migriert-gestellten Zahlungsplanposition den Betrag ändern | Meldung mit dem Weg zur Rücknahme; nach der Rücknahme ist die Position bearbeitbar, beides steht im Änderungsprotokoll |

## 11. Was in späteren Phasen dazukommt

* **Vor Phase 3:** WeasyPrint braucht auf Windows die GTK/Pango-Bibliotheken. Rechtzeitig
  beschaffen, sonst blockiert es die Fakturierung.
* **Vor Phase 3:** Ordner `01_Rechnungen` einrichten und Schreibrechte für das Dienstkonto
  prüfen.
* **Vor Phase 4:** TimeTac-Zugangsdaten, DATEV-Exportpfade im OneDrive (`02_DATEV`),
  Kalkulationsordner (`03_Kalkulation`).
* **Ab Phase 3** kommen zur Abnahmeliste die Kernabläufe hinzu: Abschlag stellen,
  festschreiben, stornieren.
