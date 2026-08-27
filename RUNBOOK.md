# RUNBOOK – Betrieb des ip³ Leitstands

Für den Bürorechner, auf dem die Anwendung läuft. Wird mit jeder Phase aktuell gehalten.
Stand: Phase 0.

> Vollständig gefüllt wird dieses Runbook am Ende von Phase 0 (Auslieferung und Deploy-Vorlagen).
> Die Gliederung steht bereits, damit während der Umsetzung nichts vergessen wird.

## 1. Überblick

| Was | Wert |
|---|---|
| Host | _noch festzulegen (siehe docs/OFFENE-PUNKTE.md)_ |
| Anwendung | ein Uvicorn-Prozess als Dienst, liefert API und Oberfläche |
| Reverse Proxy | Caddy mit TLS (interne CA) |
| Datenbank | SQLite, lokal auf dem Host – nicht in OneDrive |
| Backup-Ziel | OneDrive-Ordner `04_Backup`, 30 Generationen |
| Testinstanz | zweite Instanz mit Backup-Kopie der Datenbank; Updates laufen erst dort |

## 2. Installation

_folgt am Ende von Phase 0_

## 3. Start und Stopp

_folgt am Ende von Phase 0_

## 4. Alltag: Logs und Systemstatus

_folgt am Ende von Phase 0_

## 5. Update über die Testinstanz

_folgt am Ende von Phase 0_

## 6. Backup

_folgt am Ende von Phase 0_

## 7. Restore Schritt für Schritt

_folgt am Ende von Phase 0 – ein Restore wird vor der Freigabe der Phase einmal geprobt_

## 8. Störungen

_folgt am Ende von Phase 0_

## 9. Abnahmeliste

_folgt am Ende von Phase 0_

## 10. Was in späteren Phasen dazukommt

- **Vor Phase 3:** WeasyPrint braucht auf Windows die GTK/Pango-Bibliotheken – rechtzeitig beschaffen.
- **Vor Phase 4:** TimeTac-Zugangsdaten, DATEV-Exportpfade im OneDrive.
