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

**Phase 5 – Firmen-Cockpit.** Der Leitstand rechnet jetzt auch auf Firmenebene: Umsatz minus
variable Kosten ergibt den Deckungsbeitrag, minus Fixkosten die Über- oder Unterdeckung, kumuliert
über das Jahr. Dazu Break-even-Monatsumsatz, die Reichweite des Auftragsbestands und ein
Umschalter zwischen gestelltem und bezahltem Umsatz. Die Fixkosten kommen aus der Summen- und
Saldenliste der Kanzlei, für Zukunftsmonate aus der eigenen Planung; der Zahlungsstatus
ausschließlich aus der Liste offener Posten. Ausdrücklich eine Steuerungssicht, keine
handelsrechtliche BWA.

Davor gebaut: Phase 1 (Übernahme der Bestandsdaten, Projekte, Termine, Zahlungsplan), Phase 2
(Umsatz und Forecast), Phase 3 (Fakturierung bis zur festgeschriebenen Schlussrechnung mit
E-Rechnung) und Phase 4 (Ist-Kosten aus DATEV, TimeTac und Stückliste, Nachkalkulation je
Projekt). Einzelheiten im [CHANGELOG](CHANGELOG.md).

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
