# Übergabe an die IT

Diese Datei ist für die Person geschrieben, die den ip³ Leitstand einrichtet und betreibt und
das Projekt noch nie gesehen hat. Sie beantwortet vier Fragen: **was das ist, warum es das
gibt, wie es auf den Host kommt und was daran angebunden wird.**

Der Bau ist abgeschlossen – alle sieben Phasen aus [PLAN §7](../PLAN.md) sind fertig, die
Testsuite ist grün. Was noch fehlt, ist keine Software mehr, sondern Einrichtung.

| | |
|---|---|
| Auftraggeber | ip³ Energietechnik GmbH, Brandweg 1, 92637 Theisseil |
| Ansprechpartner fachlich | Sven Wilhelm (Geschäftsführung) |
| Quelltext | GitHub, privat – Zugang erteilt Sven |
| Nutzerzahl | vier bis sechs, alle im Firmennetz |
| Geschätzter Einrichtungsaufwand | ein halber bis ein Tag, wenn der Host bereitsteht; dazu je Arbeitsplatz ~10 Minuten für das Wurzelzertifikat |

---

## In drei Sätzen

Der Leitstand ist eine selbst entwickelte Web-Anwendung, die Projekte, Rechnungen und Zahlen
der Firma an einer Stelle führt. Sie besteht aus **einem** Python-Prozess mit einer
SQLite-Datenbank, davor Caddy als Reverse Proxy mit TLS; die Oberfläche wird als statische
Dateien vom selben Prozess ausgeliefert. Sie läuft komplett im Haus – keine Cloud, kein
externer Dienst, kein Konto irgendwo.

## Warum es das gibt

ip³ plant und baut Photovoltaik-Anlagen und Batteriespeicher, von Aufdach bis Freifläche. Die Steuerung
lief bisher über zwei gewachsene Excel-Dateien, einen Ordner voll Rechnungs-PDFs und
Kopfwissen. Konkret heißt das:

* Ob ein Abschlag gestellt wurde, stand in einer anderen Datei als der Zahlungsplan.
* Der Umsatz-Forecast war eine Momentaufnahme, die niemand ohne halben Tag Arbeit erneuern
  konnte.
* Ob ein Projekt Geld verdient hat, wusste man erst, wenn die Kanzlei gebucht hatte – und dann
  nur als Summe über alles, nicht je Projekt.
* Fristen (Gewährleistung, Registrierung im Marktstammdatenregister) hingen an Erinnerung.

Der Leitstand ersetzt das durch eine Datenhaltung, aus der sich all das ableiten lässt:
Projektverwaltung mit Zahlungsplan, Umsatz-Ist und Forecast, Fakturierung im
Corporate Design bis zur GoBD-konformen Festschreibung mit E-Rechnung, Nachkalkulation je
Projekt (Soll aus dem Kalkulationsblatt gegen Ist aus Buchhaltung, Stückliste und Stunden),
ein Firmen-Cockpit und ein Anlagenregister mit Fristenwächter.

**Warum das für die Einrichtung wichtig ist:** aus dem Zweck folgen die Randbedingungen. Es
hängen Rechnungen daran, also gilt GoBD – festgeschriebene Belege sind per
Datenbank-Trigger unveränderbar, und die Sicherung ist keine Nettigkeit. Es hängen
Personenstunden daran, also gilt die DSGVO. Und es ist das einzige System, in dem manche Zahl
existiert, also ist ein Restore, der noch nie geprobt wurde, eine Vermutung.

---

## Wie es aufgebaut ist

| Ebene | Technik |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic; Paketverwaltung `uv` |
| Datenbank | SQLite im WAL-Modus, **lokal auf dem Host** |
| Frontend | React 19 + Vite + TypeScript, wird gebaut und als statische Dateien vom Backend ausgeliefert |
| Hintergrundläufe | APScheduler **im Anwendungsprozess**, nicht im Taskplaner |
| Reverse Proxy | Caddy mit TLS, `deploy/Caddyfile` |
| Dienst | ein Uvicorn-Prozess, `deploy/systemd/` bzw. `deploy/windows/` |
| Ports | 443 nach außen (nur Büro-Netz), 8000 nur lokal gebunden |

Node ist ausschließlich Bauwerkzeug für die Oberfläche; im Betrieb läuft kein Node.

### Datenflüsse

Die Anwendung **schreibt** nur an zwei Stellen: in die eigene Datenbank und in den
Rechnungs-Ausgabeordner. Alles andere wird **ausschließlich gelesen**. Wer wissen will, was
passiert, wenn der Leitstand ausfällt: es fehlt eine Auswertung, es gehen keine Quelldaten
verloren.

```
              ┌──────────────────────────────────────────┐
Browser       │  HOST (ein Rechner im Büro)              │
im Büro-Netz  │                                          │
   │          │   Caddy :443 ──► ip3-leitstand :8000     │
   └──HTTPS──►│                        │                 │
              │                        ├─► leitstand.sqlite3   (lokal, KEIN Sync)
              │                        │                 │
              │                        ├─► logs/         │
              └────────────────────────┼─────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
   nur lesen                      schreiben                      nur lesen
        │                              │                              │
  02_DATEV (CSV)              01_Rechnungen (PDF/XML)         TimeTac REST-API
  03_Kalkulation (XLSX)       04_Backup (nächtlich)           api.timetac.com
  05_Projekte (Scan)
  Angebots-Tool (XLSX/CSV)
  Netzbetreiber-Abrechnung
```

---

## Was angebunden wird

| Quelle | Richtung | Form | Wie oft |
|---|---|---|---|
| **TimeTac** | nur lesen | REST-API v3, OAuth2 Client Credentials | nächtlich, laufender + voriger Monat |
| **DATEV** | nur lesen | drei CSV-Exporte der Kanzlei in `02_DATEV` | monatlich, dateibasiert |
| **Kalkulationsblätter** | nur lesen | Excel je Projekt in `03_Kalkulation`, Dateiname beginnt mit der Projektnummer | nächtlicher Scan |
| **Projektordner** | nur lesen | ein Ordner je Projekt in `05_Projekte`, Nummer im Namen | nächtlicher Scan |
| **Angebots-Tool** | nur lesen | eine Liste als `.xlsx` oder `.csv` | bei Bedarf |
| **Netzbetreiber-Abrechnung** | nur lesen | `.csv` oder `.xlsx`, **kein PDF** | monatlich |
| **Rechnungsausgang** | **schreiben** | PDF und ZUGFeRD-XML nach `01_Rechnungen` | bei jeder Festschreibung |
| **Sicherung** | **schreiben** | `VACUUM INTO` nach `04_Backup`, 30 Generationen | nächtlich 01:30 |

Es gibt **keine** DATEV-Direktschnittstelle und keinen Mail- oder Mahnversand. Die
Spaltennamen aller Importe stehen in der `config.toml`, nicht im Code – wenn ein echter Export
anders heißt als vorbelegt, wird das dort nachgezogen, ohne Programmänderung.

### Netzwerk

* **Einmalig ausgehend**: HTTPS zu GitHub, PyPI und dem npm-Registry für Installation und
  Updates.
* **Dauerhaft ausgehend**: HTTPS zu `api.timetac.com`. Sonst nichts.
* **Eingehend**: 443 aus dem Büro-Netz. `deploy/windows/firewall-regel.ps1` schränkt das ein.
* Kein Zugriff aus dem Internet, kein VPN-Bedarf, kein Portforwarding.
* **Nicht der Leitstand, aber derselbe Host:** der OneDrive-Client braucht eigenen
  ausgehenden Verkehr. Ohne ihn sind die gelesenen Ordner leer und die Sicherung landet
  nur lokal.

---

## Sechs Regeln, die nicht verhandelbar sind

Jede davon hat einen Grund, und jede ist schon irgendwo einmal schiefgegangen.

**1. Die Datenbank gehört nicht in einen Sync-Ordner.** SQLite sichert gleichzeitige Zugriffe
über Dateisperren ab, die OneDrive nicht kennt – die Datei wird früher oder später beschädigt.
Der Leitstand verweigert deshalb den Start, wenn der Pfad nach einem Sync-Ordner aussieht.
Die *Sicherungen* liegen sehr wohl in OneDrive; dort wird nur geschrieben, nicht gleichzeitig
gearbeitet.

**2. Genau ein Arbeitsprozess.** Der Zeitplan der nächtlichen Läufe steckt im Prozess. Mit
mehreren liefe die Sicherung mehrfach und die Importe würden Kosten doppelt zählen. Der
Startbefehl trägt darum kein `--workers`; die Anwendung warnt im Protokoll, wenn sie Anzeichen
für mehrere Prozesse findet.

**3. Das Dienstkonto muss den Backup-Ordner erreichen.** Unter Windows ist das die häufigste
Ursache für eine Sicherung, die jede Nacht scheitert: ein Dienst unter `LocalSystem` sieht das
OneDrive des angemeldeten Nutzers nicht. Deshalb `ip3-leitstand backup` einmal **als
Dienstkonto** ausführen und nachsehen, ob die Datei ankommt.

**4. TLS ist nicht optional.** Die Anmeldung läuft über ein Cookie. Ohne TLS geht es
unverschlüsselt durchs Firmennetz. Caddy erzeugt mit `tls internal` ein eigenes Zertifikat –
dessen Wurzelzertifikat muss auf **jedem** Arbeitsplatz installiert werden. Nutzer, die
Browserwarnungen wegklicken, klicken auch die nächste weg.

**5. Geheimnisse nur in die `.env` auf dem Host.** Sitzungsschlüssel und TimeTac-Zugang gehören
ausschließlich dorthin – nie in die `config.toml`, nie ins Repository. Beide Dateien sind
ignoriert und bleiben auf dem Host.

**6. Der Leitstand legt keine Ordner an.** Absicht: ein Werkzeug, das ungefragt Verzeichnisse
im Firmen-OneDrive anlegt, wäre schlimmer als eines, das sie vermisst. Fehlt einer, sagt die
Bereitschaftsprüfung welcher und wofür.

---

## Der Weg auf den Host

Der vollständige Ablauf steht in **[INBETRIEBNAHME.md](INBETRIEBNAHME.md)** – neun Schritte,
jeder mit Befehlen. Hier die Kurzfassung:

| # | Schritt | Ergebnis |
|---|---|---|
| 0 | GitHub-Zugang von Sven, Repository klonen | Quelltext auf dem Host |
| 1 | `git`, `node 22`, `uv`, Caddy installieren; **auf Windows zusätzlich GTK-Runtime** | Voraussetzungen |
| 2 | Die sechs Ordner anlegen und Rechte setzen | Ablage |
| 3 | `config.toml` und `.env` aus den Beispieldateien füllen | Konfiguration |
| 4 | `uv run ip3-leitstand schema` und `seed` (**ohne** `--demodaten`) | Datenbank + Administrator |
| 5 | `npm ci && npm run build`, dann `[pfade] frontend` auf `frontend/dist` | Oberfläche |
| 6 | Dienst einrichten, Caddy starten, `caddy trust`, Wurzelzertifikat verteilen | erreichbar über HTTPS |
| 7 | Datenquellen einzeln anschließen und prüfen | Importe laufen |
| 8 | Autostart prüfen, **eine Sicherung testweise zurückspielen** | betriebsbereit |
| 9 | Nutzer anlegen (`admin`, `buchhaltung`, `team`) | Übergabe an die Anwender |

### Der Befehl, der den Stand feststellt

```bash
cd backend && uv run ip3-leitstand bereitschaft
```

Er ändert nichts. Er prüft Konfiguration, Datenbank, Ordner (mit einem echten Schreibtest, weil
`os.access` unter Windows und bei ACLs lügt), die Grafikbibliotheken für das Rechnungs-PDF, die
Verrechnungssätze und den Datenstand – und nennt zu jedem offenen Punkt den nächsten Schritt.
Rückgabewert 1 nur, wenn etwas den Start verhindert. Nach jedem Schritt oben lohnt ein Lauf.

### Zwei Hosts zur Wahl – die Entscheidung steht noch aus

| | Rechner im Büro (Windows) | Gemieteter Linux-Server |
|---|---|---|
| Dienst | NSSM, `deploy/windows/` | systemd, `deploy/systemd/` |
| Rechnungs-PDF | **GTK-Runtime nachinstallieren**, sonst kein PDF | liegt in der Regel vor |
| OneDrive | direkt eingebunden | Zugriff muss eingerichtet werden |
| Läuft um 01:30 | nur wenn der Rechner an bleibt | immer |
| Daten verlassen das Haus | nein | ja, zum Rechenzentrum |

Der nächtliche Lauf braucht einen Rechner, der um 01:30 Uhr läuft. Auf einem Bürorechner, der
abends ausgeht, holt der Leitstand einen verpassten Lauf beim nächsten Start **einmal** nach –
er stapelt sie nicht. Eine Empfehlung zur Hardware gibt es nicht zu treffen: vier bis sechs
Nutzer und einige tausend Datensätze sind für SQLite unkritisch.

---

## Betrieb danach

Alles Weitere steht im **[RUNBOOK](../RUNBOOK.md)**: Start und Stopp, Protokolle, Update über
die Testinstanz, Sicherung, Restore Schritt für Schritt, Störungen.

Drei Dinge, die den Betrieb tragen:

* **Der Systemstatus auf der Startseite** zeigt jeden nächtlichen Lauf mit seinem Alter.
  Stille Job-Ausfälle darf es nicht geben – ein Lauf, der als „noch nicht eingerichtet"
  dasteht, ist besser als einer, der unbemerkt fehlt.
* **Updates laufen erst auf der Testinstanz** (Port 8010, eigene Datenbankkopie,
  `deploy/Caddyfile.testinstanz`), dann auf der Produktivinstanz.
* **Protokolle** in `logs/`, mit Rotation. Jede schreibende Aktion steht zusätzlich im
  `audit_log` in der Datenbank – ohne Passwörter, Hashes oder Token.

### Berechtigungen

Drei Rollen: `admin`, `buchhaltung`, `team`. Geprüft wird **serverseitig** in jeder Route gegen
Berechtigungsschlüssel, nie gegen Rollennamen; die Oberfläche blendet nur zusätzlich aus. Die
vollständige Matrix steht in [BERECHTIGUNGEN.md](BERECHTIGUNGEN.md) – die Datei wird aus dem
Katalog im Code erzeugt und ist damit nie veraltet.

Eine Regel ist fachlich wichtig: **Beträge sind dem Team entzogen.** Auftragswerte, Margen,
Cockpit und Angebotssummen sieht die Rolle `team` nicht, Stunden und Termine schon.

### Datenschutz

Der Leitstand verarbeitet Personenstunden aus TimeTac. Zweck ist **Kostenrechnung, ausdrücklich
keine Leistungskontrolle**. Er ist ins Verzeichnis der Verarbeitungstätigkeiten nach Art. 30
DSGVO aufzunehmen; das ist noch offen und liegt bei ip³, nicht bei der IT.

---

## Was die IT von ip³ braucht

Ohne diese Zulieferungen läuft die Einrichtung nicht zu Ende. Sie liegen alle bei ip³:

| Was | Blockiert |
|---|---|
| Entscheidung, auf welchem Host er läuft | Schritt 1 und 6 |
| Zugangsdaten TimeTac (Client-ID, Secret, Kontoname) | TimeTac-Anbindung |
| Antwort der Kanzlei: Kontenrahmen SKR03/SKR04, KOST2, drei Monatsexporte | DATEV-Import |
| Bankverbindung, HRB, Steuernummer | erste echte Rechnung (§ 14 UStG) |
| Vier Verrechnungssätze bestätigen | Nachkalkulation |
| Anschriften und Privat/Gewerbe-Kennzeichen der Bestandskunden | Festschreibung, E-Rechnung |
| Je eine Beispieldatei: Angebots-Tool, Netzbetreiber-Abrechnung | Phase-7-Funktionen |
| Wurzelzertifikat auf allen Arbeitsplätzen ausrollen dürfen | Schritt 6 |

Der vollständige Stand mit Begründung steht in [OFFENE-PUNKTE.md](OFFENE-PUNKTE.md).

---

## Was der Leitstand nicht tut

Damit klar ist, wo die Grenze liegt: kein ERP, keine Lagerbuchhaltung, keine BWA, keine
DATEV-Direktschnittstelle, kein automatischer Mail- oder Mahnversand, keine Mobile-App, kein
SSO. Er ersetzt die Buchhaltung nicht – er liest sie.

---

## Wegweiser durch die Dokumentation

Alles liegt im Repository. Reihenfolge zum Lesen:

| Datei | Antwortet auf |
|---|---|
| **diese Datei** | Was ist das, warum, was muss ich tun? |
| [INBETRIEBNAHME.md](INBETRIEBNAHME.md) | Der Weg zum Echtbetrieb, Schritt für Schritt |
| [RUNBOOK.md](../RUNBOOK.md) | Betrieb: Start, Update, Sicherung, Restore, Störungen |
| [AUF-DEN-EIGENEN-RECHNER.md](AUF-DEN-EIGENEN-RECHNER.md) | Zum Ansehen auf einem beliebigen Rechner, mit Demodaten, zum Wegwerfen |
| [PLAN.md](../PLAN.md) | Architekturentscheidungen mit Begründung, Datenmodell, Geschäftsregeln |
| [BERECHTIGUNGEN.md](BERECHTIGUNGEN.md) | Wer darf was (erzeugt) |
| [NUTZERHANDBUCH.md](../NUTZERHANDBUCH.md) | Bedienung je Rolle – für die Anwenderschulung |
| [VERFAHRENSDOKU.md](../VERFAHRENSDOKU.md) | Verfahrensdokumentation nach GoBD |
| [CHANGELOG.md](../CHANGELOG.md) | Was in welcher Phase entstanden ist |

**Zum Kennenlernen ohne Risiko:** `AUF-DEN-EIGENEN-RECHNER.md` beschreibt eine
Probeinstallation mit Demodaten auf einem beliebigen Mac- oder Windows-Rechner. Eine Stunde,
ohne Server, ohne echte Daten – danach ist klar, worum es geht.
