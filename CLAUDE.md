# CLAUDE.md – Arbeitsregeln ip³ Leitstand

Projekt- und Finanz-Cockpit der ip³ Energietechnik GmbH. Die verbindliche Bauvorlage ist
**[PLAN.md](PLAN.md)** – dort stehen Datenmodell (§5), Geschäftsregeln (§6), Phasenplan (§7) und
Corporate Design (§11). Diese Datei fasst nur zusammen, was bei jeder Änderung gilt; Details
werden bei Bedarf in PLAN.md nachgelesen, nicht hier gespiegelt.

## Stack

| Ebene | Technik |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, APScheduler, pydantic-settings; Paketverwaltung `uv` |
| Datenbank | SQLite (WAL, `busy_timeout`, Fremdschlüssel an), lokal auf dem Host – **niemals in einem Sync-Ordner** |
| Frontend | React 19, Vite, TypeScript, React Router, TanStack Query; eigene Komponenten nach `design/`, keine UI-Bibliothek |
| API-Vertrag | OpenAPI → `openapi-typescript`/`openapi-fetch`; generierter Client, kein handgeschriebener Fetch-Code |
| Betrieb | ein Uvicorn-Prozess als Dienst, Caddy davor mit TLS; Frontend-Build wird vom Backend ausgeliefert |

## Verzeichnisse

```
backend/    FastAPI-Anwendung, Migrationen, Tests
frontend/   React-Oberfläche (Vite)
design/     Designsystem und Screen-Mockups (Claude Design) – Vorlage, wird nicht importiert
assets/cd/  Corporate-Design-Assets: Schriften, Logos, Zeichen 3
deploy/      Caddyfile, systemd-Unit, Windows-Dienst-Anleitung
docs/       Berechtigungskatalog (generiert), offene Punkte
```

## Regeln, die immer gelten

1. **Phasen der Reihe nach** (PLAN §7). Jede Phase endet mit lauffähiger App, grüner `pytest`-Suite
   und einem Eintrag in `CHANGELOG.md`.
2. **Berechtigungen ausschließlich serverseitig.** Jede Route prüft über `benoetigt('ressource.aktion')`
   gegen Berechtigungsschlüssel, nie gegen Rollennamen. Das Frontend blendet nur zusätzlich aus.
   Der Regressionstest in `backend/tests/test_rbac.py` verlangt für **jede** schreibende `/api`-Route
   eine solche Abhängigkeit – seine Ausnahmeliste darf nur mit Begründung wachsen.
3. **Geldbeträge sind Integer in Cent.** Kein Gleitkomma, Umrechnung nur in der Anzeige.
   Umsatzsteuer wird je Steuersatz auf die Nettosumme des Belegs gerundet (PLAN §6.11).
4. **Zeitstempel in UTC** speichern (`UtcDateTime`, naive Werte werden abgewiesen), Anzeige und
   Monatszuordnung in Europe/Berlin.
5. **Nichts löschen, was Bezüge hat.** Belege und Stammdaten wechseln den Status
   (`inaktiv`, `storniert`), Nutzer werden nur deaktiviert. Festgeschriebene Belege sind per
   Datenbank-Trigger unveränderbar.
6. **Optimistic Locking** in allen Bearbeitungsmasken: Speichern mit veraltetem Stand ergibt eine
   Konfliktmeldung, kein stilles Überschreiben.
7. **Jede schreibende Aktion in `audit_log`.** Passwörter, Hashes und Token erscheinen dort nie.
8. **Fehlerpfade zählen zur Funktion.** Fehlerhafte Importdatei, nicht erreichbare Schnittstelle,
   Speicherkonflikt, fehlende Berechtigung: verständliche deutsche Meldung mit nächstem Schritt,
   niemals ein Stacktrace in der Antwort. Fehlerkörper: `{code, meldung, naechster_schritt}`.
9. **Sprache:** Oberfläche, Fachkommentare, Commit-Nachrichten und Dokumentation auf Deutsch.
   Feldnamen deutsch in `snake_case`.
10. **Abhängigkeiten sparsam** und erst in der Phase, in der sie gebraucht werden. Keine Cloud-Dienste,
    alle Daten bleiben lokal bzw. im Firmen-OneDrive. Versionen über Lockfiles gepinnt.
11. **Corporate Design ist verbindlich** (PLAN §11, `design/README.md`): Farben nur aus den Tokens,
    kein Grün, keine Verläufe, Zahlen in Space Grotesk mit Tabellenziffern, deutsche Zahlenformate
    (`1.250,00 €`, `5.695 kWp`) mit geschütztem Leerzeichen vor der Einheit.
12. **Bei buchführungs- oder steuerrelevanten Unklarheiten nachfragen**, nicht annehmen.
    Rein technische Detailfragen werden entschieden und die Annahme im Code kommentiert;
    offene Rückfragen sammelt `docs/OFFENE-PUNKTE.md`.

## Häufige Befehle

```bash
# Backend
cd backend
uv sync                                  # Abhängigkeiten
uv run alembic upgrade head              # Schema anlegen/aktualisieren
uv run ip3-leitstand seed --demodaten    # Stammdaten + Demodaten (nur Entwicklung)
uv run ip3-leitstand server              # API auf :8000
uv run pytest                            # Testsuite
uv run ruff check . && uv run ruff format --check .

# Frontend
cd frontend
npm ci
npm run api                              # OpenAPI-Client neu generieren (nach API-Änderungen!)
npm run dev                              # Vite auf :5173, /api wird auf :8000 gespiegelt
npm run typecheck && npm test && npm run build
```

Nach jeder Änderung an API-Routen oder Schemas `npm run api` laufen lassen – sonst schlägt der
Frische-Test der OpenAPI-Spezifikation fehl.

## Was nicht passiert

Kein ERP, keine Lagerbuchhaltung, keine BWA, keine DATEV-Direktschnittstelle, kein automatischer
Mail- oder Mahnversand, keine Mobile-App (PLAN §12). Die Anwendung schreibt nur in die eigene
Datenbank und in den Rechnungs-Ausgabeordner; alle externen Quellen werden ausschließlich gelesen.
