# Offene Punkte

Zwei Arten von Einträgen: **Rückfragen** brauchen eine Entscheidung von Sven; bis dahin gilt der
genannte Zwischenstand, damit die Entwicklung nicht stehenbleibt. **Zulieferungen** sind Dateien
oder Zugänge, ohne die eine spätere Phase nicht gebaut werden kann.

Erledigt seit PLAN §13: die Corporate-Design-Assets liegen in `assets/cd/` (§13.7), das
Designsystem aus Claude Design in `design/` (§13.9), die beiden Bestandsdateien und die
Rechnungsvorlage sind geliefert (§13.1, Zulieferung Phase 1). Aus der Rechnungsvorlage stammen
die Firmenstammdaten in `config.example.toml`; sie enthielt zwei Briefköpfe – der zweite
(Ringstraße 15, Weiden, HRB 3547, USt-IdNr. DE267260868) ist laut Sven eine Altfassung und wird
nicht übernommen.

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

## Entschieden für Phase 1 (27.08.2026)

| # | Frage | Entscheidung |
|---|---|---|
| 8 | Planjahr der Monatsspalten der Auftragsliste. Die Datei heißt „2025", wurde aber am 26.08.2026 gespeichert und gedruckt; die Monatsköpfe tragen kein Jahr. | **2026.** `plan_monat` wird `2026-01` bis `2026-11`. Dafür sprachen die Daten: nur 150 der 280 Zeilen sind als erledigt markiert, und die drei größten Positionen (Nachtmann 550.000 €, Landgraf 450.000 €, Edeka 91.000 €) liegen im November. |
| 9 | Bedeutung des `erledigt`-Kreuzes (PLAN §13.2), 150 Zeilen mit 862.152,24 € | **„Rechnung gestellt".** Wird als berechnet importiert, der Zahlungsstatus bleibt offen bis zum OPOS-Import in Phase 5. Damit ist §13.2 geschlossen. |
| 10 | Firmen im Rechnungskopf | **Nur ip³ Energietechnik GmbH, Theisseil.** Eine zweite Gesellschaft kann die Tabelle `firmen` später ohne Schemaänderung aufnehmen. |
| 11 | Lücke zwischen AB-Wert und Summe des Zahlungsplans bei Altprojekten (die Auftragsliste führt nur die offenen Positionen; Beispiel KMV Medi Center: 5.303,95 € Plan gegen 154.070,64 € AB-Wert) | **Lücke ausweisen, nicht füllen.** Importiert wird nur, was in der Datei steht; das Importprotokoll listet die Differenz je Projekt. Keine Sammelposition, die es als Rechnung nie gab, und kein Umsatz ohne Belegbezug. |

## Befunde in den Quelldateien, die Sven kennen sollte

Beide Dateien rechnen an ihren Kopfzeilen falsch. Der Importer rechnet die Kontrollsummen selbst
über die Datenzeilen nach und protokolliert die Abweichung samt Grund – eine falsche Summe kann
er nicht treffen.

| Datei | Zelle | Fehler | Auswirkung |
|---|---|---|---|
| Teambesprechung_NEU | `I7` | `SUMME(I24:I527)` statt über alle Datenzeilen | Der ausgewiesene Auftragsbestand von 16.560.441,44 € übergeht **29 Projekte mit 1.525.463,42 €** (16 Zeilen oben, 13 unten). Tatsächlich 18.085.904,86 €. |
| Teambesprechung_NEU | `C6` | derselbe Bereichsfehler | PV-Leistung 14.088,40 kWp ausgewiesen, tatsächlich 15.423,20 kWp. |
| Offene_Auftraege_2025 | `Z5` | `SUMME(Z8:AC3243)` summiert ein Rechteck über die Augustspalte | Die Juli-Summe zählt den August mit: 360.813,53 € statt 226.302,01 €. |

## Zulieferungen, ohne die spätere Phasen nicht starten können

| Phase | Was fehlt | Wofür |
|---|---|---|
| 0/1 | Firmenstammdaten für den Rechnungskopf: USt-IdNr., Steuernummer, HRB, Geschäftsführer, Bankverbindung; Verrechnungssätze je Stunde; OneDrive-Pfade; Host-Rechner und Dienstkonto | `config.toml`. Solange die Pfade fehlen, zeigt der Systemstatus einen Konfigurationshinweis. |
| 0/1 | **Steuernummer** der ip³ Energietechnik GmbH. Die Rechnungsvorlage nennt nur die USt-IdNr. | `config.toml`, Pflichtangabe nach § 14 UStG. Der Systemstatus zeigt sie bis dahin als fehlend. |
| 1 | Nach der Migration: Projektleiter-Namen den Nutzerkonten zuordnen (`pl_user_id`) | Sichtbarkeits-Scope `eigene` |
| 3 | Beispiel-Kalkulationsblatt (PLAN §13.1). Die Rechnungsvorlage liegt vor. | Einleser für das Kalkulationsblatt in Phase 4 |
| 3 | **Rechnungsnummernkreis:** die Vorlage nutzt `PV-ET 25-1713`, PLAN §3 legt `RE-JJJJ-NNNN` fest. Fortführen oder umstellen? | GoBD-relevant, weil die Nummernfolge lückenlos bleiben muss. Vor Phase 3 zu entscheiden, sonst wäre eine Umnummerierung nötig. |
| 3 | Zahlungsziel-Standard und Skonto-Toleranz festlegen (PLAN §13.10) | Fälligkeit und Zahlungsabgleich; Vorbelegung: 14 Tage, 3 % |
| 3 | Auf dem Windows-Host GTK/Pango-Bibliotheken für WeasyPrint bereitstellen | PDF-Erzeugung. Früh beschaffen, sonst blockiert es Phase 3. |
| 4 | TimeTac: API-Freischaltung und Zugangsdaten (PLAN §13.3) | Stunden-Synchronisation; Ersatzweg ist der CSV-Berichtsexport |
| 4/5 | Steuerberater-Abstimmung: KOST2 je Projektnummer, drei monatliche Exporte (Kostenträger, SuSa, OPOS), Review der Verfahrensdokumentation (PLAN §13.4) | Ist-Kosten, Firmen-Cockpit, GoBD |
| 5 | Erstbefüllung des Konten-Mappings mit Buchhaltung und Steuerberater (PLAN §13.5) | Fixkostenblöcke im Cockpit |
| – | Das Werkzeug als Verarbeitungstätigkeit ins Verzeichnis nach Art. 30 DSGVO aufnehmen (PLAN §13.11) | Datenschutz. Zweck der TimeTac-Stunden ist Kostenrechnung, keine Leistungskontrolle. |
