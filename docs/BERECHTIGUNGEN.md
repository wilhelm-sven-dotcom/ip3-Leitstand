# Berechtigungen

**Diese Datei wird erzeugt.** Sie entsteht aus `backend/app/sicherheit/katalog.py`
beim Ausführen von `ip3-leitstand berechtigungen-doku`. Änderungen hier gehen verloren.

Berechtigungen sind Schlüssel nach dem Muster `ressource.aktion`. Jede Route und jede
Aktion prüft gegen diese Schlüssel, nie gegen Rollennamen (PLAN §4). Der
Sichtbarkeits-Scope `eigene` beschränkt auf Datensätze, bei denen der Nutzer als
Projektleiter eingetragen ist.

## Rollen

| Rolle | Beschreibung |
|---|---|
| `admin` | Geschäftsführung: alle Berechtigungen inklusive Konfiguration, Fixkosten, Nutzerverwaltung und Stornofreigabe |
| `buchhaltung` | Kunden, Projekte und Zahlungsplan pflegen, Fakturierung inklusive Festschreibung, Importe ausführen |
| `team` | Lesender Zugriff auf Projekte und Termine ohne Beträge, ohne Nachkalkulation, ohne Firmen-Cockpit |

## Berechtigungen je Rolle

| Berechtigung | Bedeutung | Ab Phase | admin | buchhaltung | team |
|---|---|---|---|---|---|
| `admin.jobs` | Hintergrundläufe von Hand starten | 0 | ja | – | – |
| `admin.konfiguration` | Konfiguration ansehen und ändern | 0 | ja | – | – |
| `admin.nutzer` | Nutzer und Rollen verwalten | 0 | ja | – | – |
| `angebote.lesen` | Angebotspipeline ansehen | 7 | ja | – | – |
| `angebote.schreiben` | Angebote pflegen und einlesen | 7 | ja | – | – |
| `anlagen.lesen` | Anlagenregister und Fristen ansehen | 6 | ja | ja | ja |
| `anlagen.schreiben` | Anlagen, Serviceaufträge und Fristen pflegen | 6 | ja | – | – |
| `cockpit.lesen` | Firmen-Cockpit ansehen | 5 | ja | – | – |
| `importe.ausfuehren` | Importe starten (DATEV, TimeTac, Migration) | 1 | ja | ja | – |
| `kapazitaet.lesen` | Wochenauslastung und Mannschaft ansehen | 7 | ja | ja | ja |
| `kapazitaet.schreiben` | Mitarbeiter und Wochenstunden pflegen | 7 | ja | – | – |
| `kunden.lesen` | Kunden und Ansprechpartner ansehen | 1 | ja | ja | ja |
| `kunden.schreiben` | Kunden und Ansprechpartner pflegen | 1 | ja | ja | – |
| `meilensteine.schreiben` | Termine und Status pflegen | 1 | ja | ja | – |
| `nachkalkulation.lesen` | Nachkalkulation und Margen ansehen | 4 | ja | – | – |
| `projekte.lesen` | Projekte und Termine ansehen | 1 | ja | ja | ja |
| `projekte.schreiben` | Projekte anlegen und bearbeiten | 1 | ja | ja | – |
| `projekte.werte_lesen` | Auftragswerte und Zahlungsplanbeträge ansehen | 1 | ja | ja | – |
| `rechnungen.erstellen` | Belege als Entwurf erstellen | 3 | ja | ja | – |
| `rechnungen.festschreiben` | Belege festschreiben (Nummer, Hash, Sperre) | 3 | ja | ja | – |
| `rechnungen.lesen` | Belege ansehen | 3 | ja | ja | – |
| `rechnungen.stornieren` | Belege stornieren und Gutschriften | 3 | ja | – | – |
| `stammdaten.schreiben` | Fixkosten und Kontenzuordnung pflegen | 5 | ja | – | – |
| `systemstatus.lesen` | Datenstand und Hintergrundläufe ansehen | 0 | ja | ja | ja |
| `umsatz.lesen` | Umsatz, Forecast und Auftragsbestand ansehen | 2 | ja | ja | – |
| `zahlungsplan.schreiben` | Zahlungsplan und Nachträge pflegen | 1 | ja | ja | – |

## Hinweise

- `projekte.werte_lesen` ist von `projekte.lesen` getrennt, damit Mitarbeiter
  Projektdaten und Termine sehen können, ohne Auftragswerte und Margen zu sehen.
- Fehlt eine Berechtigung, blendet die Oberfläche das Element aus; ausgegraute
  Schaltflächen gibt es nicht.
- Die Prüfung erfolgt ausschließlich serverseitig. Das Frontend blendet nur
  zusätzlich aus.
