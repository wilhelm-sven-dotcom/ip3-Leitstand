# Offene Punkte

Zwei Arten von Einträgen: **Rückfragen** brauchen eine Entscheidung von Sven; bis dahin gilt der
genannte Zwischenstand, damit die Entwicklung nicht stehenbleibt. **Zulieferungen** sind Dateien
oder Zugänge, ohne die eine spätere Phase nicht gebaut werden kann.

Erledigt seit PLAN §13: die Corporate-Design-Assets liegen in `assets/cd/` (§13.7) und das
Designsystem aus Claude Design in `design/` (§13.9).

## Rückfragen aus Phase 0 (Zwischenstand ist umgesetzt, Änderung jederzeit möglich)

| # | Frage | Zwischenstand | Wo geändert |
|---|---|---|---|
| 1 | Darf die Rolle `team` Auftragswerte und Zahlungsplanbeträge sehen? PLAN §4 trennt Finanzsichtbarkeit bewusst ab, die Rollentabelle liest sich offener. | Nein. Eigener Berechtigungsschlüssel `projekte.werte_lesen`, den `team` nicht hat: die Projektliste zeigt Kunde, Leistung, Termine und Status, aber keine Beträge. | Seed in `backend/app/werkzeuge/seed.py` |
| 2 | Soll `buchhaltung` Nachkalkulation und Firmen-Cockpit sehen? | Nein, exakt nach PLAN §4: Stammdaten, Zahlungsplan, Fakturierung, Importe. | dito |
| 3 | Sitzungsdauer | 12 Stunden; mit „Angemeldet bleiben" 30 Tage; Abmeldung nach 8 Stunden ohne Aktivität. | `config.toml`, Abschnitt `[sitzung]` |
| 4 | Sperre nach Fehlanmeldungen | 5 Fehlversuche je Kennung, dann 15 Minuten Wartezeit; zusätzlich Drosselung je Absender-IP. | `config.toml`, Abschnitt `[anmeldung]` |
| 5 | Anmeldekennung | E-Mail-Adresse (`vorname@ip3-energie.de`), wie im Design vorgesehen. | Nutzerverwaltung |
| 6 | Passwort zurücksetzen, solange es keine Nutzerverwaltungs-Oberfläche gibt | Über die Kommandozeile auf dem Host: `ip3-leitstand passwort-setzen`. Kein Mailversand in V1. | RUNBOOK, Abschnitt Störungen |
| 7 | Gewährleistungsfrist: VOB (4 Jahre) oder BGB (5 Jahre) als Standard je Auftragsart (PLAN §13.8) | Wird beim Projektabschluss abgefragt, kein stiller Standard. Relevant erst in Phase 6. | – |

## Zulieferungen, ohne die spätere Phasen nicht starten können

| Phase | Was fehlt | Wofür |
|---|---|---|
| 0/1 | Firmenstammdaten für den Rechnungskopf: USt-IdNr., Steuernummer, HRB, Geschäftsführer, Bankverbindung; Verrechnungssätze je Stunde; OneDrive-Pfade; Host-Rechner und Dienstkonto | `config.toml`. Solange die Pfade fehlen, zeigt der Systemstatus einen Konfigurationshinweis. |
| 1 | Die zwei Bestandsdateien `Offene_Auftra_ge_2025.xlsx` und `Teambesprechung_NEU.xlsx` | Migration der 530 Projekte und ~290 Zahlungsplanpositionen (PLAN §9) |
| 1 | Nach der Migration: Projektleiter-Namen den Nutzerkonten zuordnen (`pl_user_id`) | Sichtbarkeits-Scope `eigene` |
| 1/2 | Bedeutung des `erledigt`-Kreuzes in der Altliste: gestellt oder bezahlt? (PLAN §13.2) | Umsatz-Ist gegen Zahlungsstatus. Zwischenstand: als „Rechnung gestellt" importiert. |
| 3 | Beispiel-Kalkulationsblatt und eine Beispiel-Ausgangsrechnung (PLAN §13.1) | Layoutreferenz der Rechnungsvorlage, Parser für den Rechnungs-Altbestand |
| 3 | Zahlungsziel-Standard und Skonto-Toleranz festlegen (PLAN §13.10) | Fälligkeit und Zahlungsabgleich; Vorbelegung: 14 Tage, 3 % |
| 3 | Auf dem Windows-Host GTK/Pango-Bibliotheken für WeasyPrint bereitstellen | PDF-Erzeugung. Früh beschaffen, sonst blockiert es Phase 3. |
| 4 | TimeTac: API-Freischaltung und Zugangsdaten (PLAN §13.3) | Stunden-Synchronisation; Ersatzweg ist der CSV-Berichtsexport |
| 4/5 | Steuerberater-Abstimmung: KOST2 je Projektnummer, drei monatliche Exporte (Kostenträger, SuSa, OPOS), Review der Verfahrensdokumentation (PLAN §13.4) | Ist-Kosten, Firmen-Cockpit, GoBD |
| 5 | Erstbefüllung des Konten-Mappings mit Buchhaltung und Steuerberater (PLAN §13.5) | Fixkostenblöcke im Cockpit |
| – | Das Werkzeug als Verarbeitungstätigkeit ins Verzeichnis nach Art. 30 DSGVO aufnehmen (PLAN §13.11) | Datenschutz. Zweck der TimeTac-Stunden ist Kostenrechnung, keine Leistungskontrolle. |
