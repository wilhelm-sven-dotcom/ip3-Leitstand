# ip³ Leitstand

Projekt- und Finanz-Cockpit der ip³ Energietechnik GmbH. Ersetzt die verteilte Excel-Landschaft aus
Auftragsliste, Umsatzplanung, Abschlagsverfolgung und Nachkalkulation durch eine zentrale Anwendung
mit eigener Datenhaltung: Projektverwaltung mit Zahlungsplan, Umsatz-Ist und Forecast, Fakturierung
im ip³-Corporate-Design (inklusive E-Rechnung und GoBD-Festschreibung), Nachkalkulation je Projekt,
Firmen-Cockpit und Anlagenregister.

Die Anwendung läuft auf einem Rechner im Büro und wird im Firmennetz über den Browser genutzt.
Alle Daten bleiben lokal beziehungsweise im Firmen-OneDrive.

## Dokumentation

| Datei | Inhalt |
|---|---|
| [PLAN.md](PLAN.md) | Verbindliche Bauvorlage: Architektur, Datenmodell, Geschäftsregeln, Phasenplan |
| [CLAUDE.md](CLAUDE.md) | Arbeitsregeln und Befehle für die Entwicklung |
| [RUNBOOK.md](RUNBOOK.md) | Betrieb: Installation, Start und Stopp, Update, Backup, Restore, Störungen |
| [docs/AUF-DEN-EIGENEN-RECHNER.md](docs/AUF-DEN-EIGENEN-RECHNER.md) | Den Leitstand mit Demodaten auf dem eigenen Mac oder Windows-Rechner ansehen (ohne Server, zum Wegwerfen) |
| [NUTZERHANDBUCH.md](NUTZERHANDBUCH.md) | Bedienung je Rolle |
| [VERFAHRENSDOKU.md](VERFAHRENSDOKU.md) | Verfahrensdokumentation nach GoBD (Grundgerüst, Abstimmung mit dem Steuerberater offen) |
| [CHANGELOG.md](CHANGELOG.md) | Was in welcher Phase entstanden ist |
| [docs/OFFENE-PUNKTE.md](docs/OFFENE-PUNKTE.md) | Rückfragen und getroffene Zwischenentscheidungen |
| [design/README.md](design/README.md) | Designsystem, Komponentenschnitt, Screen-Mockups |

## Stand

**Phase 7 vollständig – Unterlagen und eigene Anlagen.** Der Doku-Scan liest nachts die
Projektordner und hält fest, welche Mappe unvollständig ist; am Entwurf einer Schlussrechnung
steht, was fehlt, und das Festschreiben verlangt dann eine ausdrückliche Bestätigung – gesperrt
wird nicht, denn der Scan sieht nur Dateinamen. Das Vergütungs-Controlling stellt der Abrechnung
des Netzbetreibers gegenüber, was aus den hinterlegten Sätzen zu erwarten wäre: eine
Kontrollrechnung, keine Buchung. Damit ist der Phasenplan aus PLAN §7 gebaut.

**Phase 7 – Kapazität und Angebotspipeline.** Zwei Ansichten, die dieselbe Frage von zwei
Seiten stellen: reicht es? Die Kapazität stellt den Sollstunden aus der Kalkulation die
Wochenstunden der Mannschaft gegenüber, Woche für Woche, und sagt dazu, was an der Antwort
unsicher ist – unverplante Projekte, fehlende Sollstunden, Namen aus TimeTac ohne
Mitarbeiterdatensatz. Die Pipeline zeigt, was angeboten ist, roh und mit der Wahrscheinlichkeit
gewichtet: **Angebote, keine Aufträge**, deshalb getrennt vom Forecast und nie darin.

**Phase 6 – Service, Anlagen und Fristen.** Was nach dem Bau kommt, hat jetzt einen Ort. Wechselt
ein Projekt auf „abgeschlossen", entsteht daraus eine Anlage samt Gewährleistungsfrist: vier Jahre
nach VOB, fünf nach BGB, gerechnet ab der Abnahme. Der Fristenwächter leitet die Frist zur
MaStR-Registrierung aus dem Inbetriebnahmedatum ab und hakt sie ab, sobald die Nummer im Register
steht; was überfällig ist oder demnächst abläuft, steht auf der Startseite. Verschickt wird
nichts. Dazu das Anlagenregister mit Servicehistorie, die Liste der Anlagen ohne Wartungsvertrag
und Serviceaufträge als eigener Projekttyp.

Davor gebaut: Phase 1 (Übernahme der Bestandsdaten, Projekte, Termine, Zahlungsplan), Phase 2
(Umsatz und Forecast), Phase 3 (Fakturierung bis zur festgeschriebenen Schlussrechnung mit
E-Rechnung), Phase 4 (Ist-Kosten aus DATEV, TimeTac und Stückliste, Nachkalkulation je Projekt)
und Phase 5 (Firmen-Cockpit mit Deckungsbeitrag, Fixkostenblock, Break-even und Zahlungslage).
Einzelheiten im [CHANGELOG](CHANGELOG.md).

## Schnellstart für die Entwicklung

Voraussetzungen: Python 3.11+ mit [uv](https://docs.astral.sh/uv/), Node 22.

```bash
# Backend
cd backend
uv sync
cp ../config.example.toml ../config.toml     # Pfade und Firmenstammdaten eintragen
cp ../.env.example ../.env                   # Geheimnisse eintragen
uv run alembic upgrade head
uv run ip3-leitstand seed --demodaten
uv run ip3-leitstand server                  # API auf http://127.0.0.1:8000

# Frontend (zweites Terminal)
cd frontend
npm ci
npm run dev                                  # Oberfläche auf http://localhost:5173
```

Erstanmeldung mit dem beim Seed angelegten Administrator; das Passwort muss beim ersten Anmelden
gewechselt werden. Die Ausgabe des Seed-Befehls nennt die Zugangsdaten.

Für den Betrieb auf dem Bürorechner gilt das [RUNBOOK](RUNBOOK.md), nicht dieser Schnellstart.
