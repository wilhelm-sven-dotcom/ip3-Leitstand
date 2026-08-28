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

**Phase 4 – Ist-Kosten und Nachkalkulation.** Der Leitstand weiß jetzt auch, was ein Projekt
gekostet hat. Drei Ist-Quellen laufen zusammen: die DATEV-Kostenträgerauswertung (Schlüssel
KOST2 = Projektnummer), die TimeTac-Stunden mal Verrechnungssatz als kalkulatorische
Eigenleistung und die bewertete Stückliste aus dem Kalkulationsblatt. Dagegen stehen Erlös und
Sollwerte; heraus kommt die Marge in € und Prozent mit Ampel gegen die Sollmarge. Jeder
Importlauf ersetzt seinen Zeitraum, ein nachgelieferter Monat ist damit der Normalfall.

Davor gebaut: Phase 1 (Übernahme der Bestandsdaten, Projekte, Termine, Zahlungsplan), Phase 2
(Umsatz und Forecast mit Jahresverlauf und Auftragsbestand) und Phase 3 (Fakturierung von der
Auftragsbestätigung bis zur festgeschriebenen Schlussrechnung mit E-Rechnung). Einzelheiten im
[CHANGELOG](CHANGELOG.md).

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
