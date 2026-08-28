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

## Entschieden für Phase 2 (27.08.2026)

| # | Frage | Entscheidung |
|---|---|---|
| 12 | Der Umsatz-Ist besteht in Phase 2 nur aus den 150 gestellten Altpositionen (862.152,24 €). Die Auftragsliste führte aber nur die **offenen** Positionen – vor der Einführung bezahlte Rechnungen aus 2026 fehlen darin und damit im Ist. | **Ist zeigen und die Lücke benennen.** Über dem Diagramm steht ein Hinweis, der vom Server kommt und verschwindet, sobald keine Altpositionen mehr im Ist stecken. Vollständig wird der Ist mit Phase 3 (eigene Belege) und dem DATEV-Abgleich in Phase 4. |
| 13 | „Offener Auftragsbestand" (PLAN §7 Phase 2) – Summe der offenen Zahlungsplanpositionen oder Auftragswert minus Gestelltes? | **Auftragswert plus beauftragte Nachträge minus dem, was schon abgerechnet ist**, je laufendem Projekt (`beauftragt`, `in_bau`). Die Differenz zur Summe der offenen Positionen steht als eigene Zeile darunter – bei den Altprojekten führte die Auftragsliste nur die offenen Abschläge. |
| 14 | Abschlagsvorschläge (PLAN §6.8) schon in Phase 2? | **Erst mit Phase 3.** Ein Vorschlag, aus dem sich keine Rechnung erzeugen lässt, ist eine Liste ohne Knopf. |

**Was mit Entscheidung 13 aufgefallen ist:** 19 der 87 laufenden Projekte hatten keinen
Auftragswert, 9 davon mit 1.798.837,71 € offenen Positionen. Für die Zeilen ohne Rechnungsart, die
PLAN §9 „Projektsummen" nennt, steht der Wert in der Quelle – die Migration übernimmt ihn jetzt
(7 Projekte, 1.767.000,00 €). Ohne Wert bleiben `Breite Wiesen FF / Inbetriebnahme
Schlussrechnung` (25.000,00 €) und `Forster ENMAG Weiden - Schlussrechnung - PV` (6.837,71 €):
eine Schlussrechnung ist der Rest eines größeren Auftrags, ihr Betrag wäre als Auftragswert eine
Falschangabe. **Diese beiden und die 10 Teamlisten-Projekte mit unlesbarem Auftragswert stehen auf
der Umsatzseite unter der Bestandstabelle und sind nachzutragen.**

## Entschieden für Phase 3 (27.08.2026)

| # | Frage | Entscheidung |
|---|---|---|
| 15 | Rechnungsnummernkreis: die Word-Vorlage nutzt `PV-ET 25-1713`, PLAN §3 legt `RE-JJJJ-NNNN` fest. | **Neuer Kreis `RE-JJJJ-NNNN`**, dazu `SR-JJJJ-NNNN` für Service und `AB-JJJJ-NNNN` für Auftragsbestätigungen, je Jahr bei 1 beginnend. Der Word-Kreis endet mit der letzten von Hand geschriebenen Rechnung. Der Wechsel steht mit Datum und Grund in `VERFAHRENSDOKU.md` §9 – ein Kreiswechsel ist zulässig, ein unerklärter nicht. |
| 16 | § 14 Abs. 5 UStG verlangt, dass eine Schlussrechnung **alle** vorher gestellten Abschläge einzeln absetzt. Zu den 150 Altpositionen kennt der Leitstand nur das Netto – keine Rechnungsnummer, kein Datum, keinen Steuersatz. | **Schlussrechnung für diese Projekte gesperrt.** Der Leitstand nennt den Grund und die betroffenen Positionen. Im Bestand sind das **28 der 87 laufenden Projekte**; sie werden ein letztes Mal wie bisher abgerechnet. **Abschlagsrechnungen bleiben dort möglich** – ein Abschlag braucht keinen Absetzungsblock. |
| 17 | Rechnungslayout: neu im ip³-CD oder die Word-Vorlage nachbauen? | **Neu im ip³-CD** (PLAN §11). Anschreiben, Zahlungsbedingung, Grußformel und Fußzeile sind wörtlich aus der Word-Vorlage übernommen und stehen als Textbausteine in `config.toml` unter `[fakturierung.texte]` – ohne Codeänderung anpassbar. |

**Korrektur zu einer früheren Rückfrage:** die Steuernummer war als Pflichtangabe geführt. § 14
Abs. 4 Nr. 2 UStG verlangt die Steuernummer **oder** die USt-IdNr.; die Vorlage führt
`DE346672260`, das genügt. Beides zu fordern hätte die Fakturierung ohne Rechtsgrund blockiert.
Die Steuernummer bleibt wünschenswert, ist aber keine Voraussetzung.

## Entschieden für Phase 4 (28.08.2026)

| # | Frage | Entscheidung |
|---|---|---|
| 18 | Wie ist die Marge zu rechnen – auf den Erlös oder als Aufschlag auf die Kosten? Der Wert muss zu dem passen, was das Kalkulationsblatt als `exp_marge_soll` ausgibt. | **Marge auf den Erlös.** `Marge € = Erlös − Ist`, `Marge % = Marge € / Erlös`. 18 % heißt: von 100.000 € Auftrag bleiben 18.000 € übrig. Gespeichert wird in Promille, damit der Vergleich mit `marge_soll` ohne Gleitkomma auskommt. |
| 19 | Wo steht die Nachkalkulation? PLAN §7 nennt nur die Ansicht je Projekt. | **Beides:** Reiter im Projektdetail **und** Übersichtsliste `/nachkalkulation` über alle Projekte, sortiert nach der schwächsten Marge. Dort fällt ein kippendes Projekt auf, ohne dass man jedes einzeln öffnet. |
| 20 | Wie kommt eine TimeTac-Stunde zu ihrem Verrechnungssatz? | **Zuordnung je Mitarbeiter.** In `config.toml` steht je Name eine Satzgruppe (`[stundensaetze.mitarbeiter]`), die Gruppen tragen den Satz (`[stundensaetze.saetze]`). Ein Name ohne Zuordnung rechnet mit dem Standardsatz und erscheint als Pflegehinweis im Importprotokoll – die Stunde wegzulassen wäre schlimmer, dann fehlte sie im Ist und die Marge sähe besser aus. |
| 21 | Ampelschwellen gegen die Sollmarge | **„Im Soll" ab der Sollmarge, „knapp" bis 5 Prozentpunkte darunter, sonst „unter Soll".** Ohne Sollmarge keine Ampel. Die Schwelle steht in `config.toml` unter `[nachkalkulation] ampel_gelb_promille` – sie ist eine Einschätzung, keine Rechengröße. *(technisch entschieden)* |
| 22 | Farbe der Ampel | **Kein Ampelgrün.** Das Corporate Design verbietet Grün ausdrücklich (PLAN §11). „Im Soll" trägt ip³ Blau, „knapp" Akzent-Rot als Kontur, „unter Soll" Akzent-Rot gefüllt, ohne Sollmarge grau. *(technisch entschieden)* |
| 23 | TimeTac-Anmeldung: welcher OAuth2-Weg? | **Client Credentials.** Sven hat eine Client-ID (`CLIENT__API_USER_…`) und ein Secret, kein Dienstkonto mit Passwort. Die Zugangsdaten kommen ausschließlich aus der `.env` auf dem Host, nie aus der `config.toml` und nie ins Repository. |
| 24 | Die Entwicklungsumgebung erreicht `api.timetac.com` nicht (Netzwerkrichtlinie, 403). | **Gegen aufgezeichnete Antworten bauen, auf dem Host prüfen.** Basis-URL, Abfrageparameter und Feldnamen sind konfigurierbar; die Testsuite läuft ohne Netz. `ip3-leitstand timetac-test` macht den ersten echten Lauf nachvollziehbar, ohne etwas zu schreiben. |
| 25 | Bleibt der CSV-Weg, nachdem die API da ist? | **Ja, als Rückfallebene** (PLAN §8). Er kostet über den DATEV-CSV-Leser hinaus wenig, trägt bei einem Ausfall der Schnittstelle und lädt alte Monate nach, die die API nicht mehr hergibt. |

## Was der Phase-4-Abnahmelauf zutage brachte

**Zwei Fehler im eigenen Code, behoben:**

| Was | Warum es zählt |
|---|---|
| Eine zweite Mengenbestätigung in einem anderen Monat hätte die Lagerentnahme **addiert** statt ersetzt. | Die Lagerbewertung ist der aktuelle Wertansatz, keine Reihe je Bestätigung. Eine verdoppelte Zahl sieht in der Nachkalkulation aus wie ein teures Projekt, nicht wie ein Fehler. Jetzt gibt es genau eine Zeile je Projekt. |
| Der Hinweis „Mengen-Ist offen" versprach eine Bewertung mit der kalkulierten Menge – tatsächlich stand dort 0 €. | Der Hinweis sagt jetzt, was wirklich gilt: solange nichts bestätigt ist, fehlt die Lagerentnahme im Ist und die Marge sieht besser aus, als sie ist. |

**Für Sven, vor dem ersten echten Monatslauf:**

| Was | Warum |
|---|---|
| **Verrechnungssätze bestätigen** (65/75/78/85 € je Stunde) und die Mitarbeiter den Gruppen zuordnen | Es sind Platzhalter. Ohne sie ist die Eigenleistung – und damit die Marge – nur so gut wie die Vorbelegung (PLAN §13.6). |
| **Kontenbereiche mit der Buchhaltung abstimmen** (vorbelegt SKR03-Aufwand 3000–4999) | Was außerhalb liegt, bleibt draußen. Stimmt der Bereich nicht, fehlen Kosten im Ist oder es rutscht ein Erlös hinein (PLAN §13.4, §13.5). |
| **KOST2 = Projektnummer** mit der Kanzlei vereinbaren | Ohne sie lässt sich keine Buchung einem Projekt zuordnen; sie erscheinen dann sämtlich als Befund. |
| **Projektnummer in den TimeTac-Projektnamen** aufnehmen | Sonst versucht der Leitstand einen Abgleich über Kundenname und Standort und nimmt nur einen eindeutigen Treffer – der Rest bleibt liegen, statt auf ein fremdes Projekt gebucht zu werden. |
| **Erster echter TimeTac-Lauf** mit `ip3-leitstand timetac-test` auf dem Windows-Host | Endpunkte und Feldnamen sind nach der v3-Dokumentation vorbelegt, aber nicht am lebenden Objekt bestätigt (Entscheidung 24). |

**Beim Aufsetzen der Probeinstallation aufgefallen (28.08.2026), noch offen:**

| Was | Warum es zählt |
|---|---|
| `IP3_SITZUNG_SCHLUESSEL` wird in der Umgebung `produktion` beim Start **verlangt**, aber von keiner Zeile Code gelesen. Die Sitzungskennungen sind Zufallswerte in der Datenbank und werden nicht signiert. | Der Wert schadet nicht und ist vorgemerkt, falls die Sitzungen später signiert werden. Die Beschreibung in `.env.example` war aber falsch – sie behauptete, ein Verlust melde alle Nutzer ab. Der Text ist korrigiert; zu entscheiden bleibt, ob die harte Startsperre bestehen bleibt oder erst wieder eingeführt wird, wenn der Schlüssel wirklich etwas tut. |
| Die TimeTac-Rückfallebene war gebaut und getestet, aber von außen nicht erreichbar – nur aus Python. | Behoben mit `ip3-leitstand timetac-csv`. Eine Rückfallebene, die im Störfall erst programmiert werden muss, ist keine. |
| Der Riegel gegen Datenbanken in Sync-Ordnern kannte `icloud`, aber nicht die macOS-Schreibweise `~/Library/Mobile Documents/com~apple~CloudDocs`. | Auf einem Mac mit synchronisiertem Dokumentenordner zeigt `~/Documents` genau dorthin – der übliche Ablageort wäre also durchgerutscht und die Datenbank irgendwann beschädigt worden. Beide Namen sind ergänzt; weil der Pfad vor der Prüfung aufgelöst wird, greift der Riegel auch über die Verknüpfung. |

## Was der Phase-3-Abnahmelauf zutage brachte – vor der ersten Rechnung zu erledigen

| Was | Zahlen aus dem Abnahmelauf | Warum es zählt |
|---|---|---|
| **Anschriften der Bestandskunden fehlen** | von 484 Kunden hat **keiner** Straße und PLZ, 454 haben einen Ort | § 14 UStG verlangt die vollständige Anschrift des Empfängers. Der Leitstand weist einen Beleg ohne sie ab – mit einer Meldung, die sagt, was fehlt. Die Teamliste führte keine Anschriften; sie sind in der Kundenmaske nachzutragen, mindestens für die Kunden, die als Nächstes eine Rechnung bekommen. |
| **Alle Kunden stehen auf „Privatkunde"** | 484 von 484 | Die Quelldateien sagen nichts über Privat oder Gewerbe, die Migration setzt deshalb `b2c`. Davon hängt ab, ob eine E-Rechnung entsteht: ab dem 1.1.2027 ist sie für inländische B2B-Umsätze Pflicht (PLAN §6.3). Umstellbar in der Kundenmaske. |
| **Zahlungsziel und Skonto-Toleranz** | Vorbelegung 14 Tage, 3 % | Die Fälligkeit steht auf jedem Beleg. Wenn 14 Tage nicht stimmen, jetzt ändern – bei festgeschriebenen Belegen ist es zu spät. Abweichende Ziele lassen sich je Kunde hinterlegen. |
| **12 laufende Projekte ohne Auftragswert** | davon 10 aus der Teamliste (unlesbare Zelle), 2 aus der Auftragsliste (bewusst leer) | Ohne Auftragswert lässt sich keine Schlussrechnung vorbelegen; sie ist dann von Hand zu füllen. Die Liste steht auf der Umsatzseite unter der Bestandstabelle. |

## Befunde in den Quelldateien, die Sven kennen sollte

Beide Dateien rechnen an ihren Kopfzeilen falsch. Der Importer rechnet die Kontrollsummen selbst
über die Datenzeilen nach und protokolliert die Abweichung samt Grund – eine falsche Summe kann
er nicht treffen.

| Datei | Zelle | Fehler | Auswirkung |
|---|---|---|---|
| Teambesprechung_NEU | `I7` | `SUMME(I24:I527)` statt über alle Datenzeilen | Der ausgewiesene Auftragsbestand von 16.560.441,44 € übergeht **29 Projekte mit 1.525.463,42 €** (16 Zeilen oben, 13 unten). Tatsächlich 18.085.904,86 €. |
| Teambesprechung_NEU | `C6` | derselbe Bereichsfehler | PV-Leistung 14.088,40 kWp ausgewiesen, tatsächlich 15.423,20 kWp. |
| Offene_Auftraege_2025 | `Z5` | `SUMME(Z8:AC3243)` summiert ein Rechteck über die Augustspalte | Die Juli-Summe zählt den August mit: 360.813,53 € statt 226.302,01 €. |

Dazu ein Befund aus den Datenzeilen selbst:

**Mehrere Positionen eines Projekts tragen denselben Namen.** Bei `HPZ, Irchenrieth` heißen vier
Zeilen der Auftragsliste (272–275) alle „1. Abschlag PV", mit 115.285,27 €, 134.499,48 €,
115.285,27 € und 19.214,21 € in September bis November. Gemeint sind offensichtlich der erste bis
vierte Abschlag. Der Import übernimmt den Text unverändert – eine erfundene Nummerierung wäre
eine Behauptung über die Quelle – und **listet jeden solchen Fall im Importprotokoll**. Ab Phase 3
steht dieser Text auf der Rechnung; er ist im Zahlungsplan des Projekts nachzuziehen.

## Zuordnungen des Abnahmelaufs (27.08.2026) – zur Prüfung durch Sven

Der Abnahmelauf hat alle 24 offenen Zuordnungen in der Maske entschieden. **Bei 15 Kunden stimmt
die Summe der Auftragszeilen auf den Euro mit dem AB-Wert genau eines Projekts der Teamliste
überein** – das war das Entscheidungskriterium, nicht die Namensähnlichkeit. Die übrigen 9 Kunden
haben in der Teamliste kein Gegenstück und haben ein eigenes Projekt bekommen.

Beim echten Lauf entscheidet Sven neu; diese Liste ist als Vorschlag gedacht.

| Kunde der Auftragsliste | Entscheidung | Grund |
|---|---|---|
| Nachtmann, Weiden (550.000 €) | eigenes Projekt | kein Gegenstück; der frühere Fuzzy-Treffer „Hubmann, Weiden" wäre falsch gewesen |
| J.K. Landgraf, Weiden (450.000 €) | eigenes Projekt | kein Gegenstück |
| Volksfestplatz Weiden 1 und 2 (je 218.000 €) | je eigenes Projekt | kein Gegenstück |
| Speicherprojekt Hausner, Püllersreuth (160.000 €) | eigenes Projekt | kein Gegenstück (PLAN §9 nennt den Fall) |
| Edeka, Heimhausen (91.000 €) | eigenes Projekt | kein Gegenstück |
| Ärztehaus Weiden (80.000 €) | eigenes Projekt | kein Gegenstück |
| Breite Wiesen FF / Inbetriebnahme (25.000 €) | eigenes Projekt | kein Gegenstück |
| Forster ENMAG Weiden (6.837,71 €) | eigenes Projekt | zwei Forster-Projekte, beide anderer Ort, kein passender Wert – hier ist eine Rückfrage sinnvoller als eine Zuordnung |
| Pöllath, Weiden 210,67 kWp | Pöllath, **Erbendorf** (210,7 kWp) | Summe 179.000,00 € = AB-Wert; die Leistung im Kundentext ist der Unterscheider, der Ort in der Auftragsliste ist ungenau |
| Pöllath, Weiden 29,58 kWp | Pöllath, Weiden (29,6 kWp) | Summe 33.000,00 € = AB-Wert |
| HL-Immobilien Bürgerbräu, Weiden | HL-Immobilien, Weiden (Bürgerbräu) | Summe 162.966,01 € = AB-Wert |
| Wolfrath Alex und Jenny, Vohenstrauß | Wolfrath, Vohenstrauß | Summe 21.593,94 € = AB-Wert |
| Graser, Pressath Bahnhofstraße 7 | Graser, Pressath, Bahnhofstraße | Summe 20.278,22 € ≈ AB-Wert 20.278,00 € |
| Lautenbacher, Neusorg | Lautenbacher, Neusorg (14,6 kWp, 2026) | PV + Speicher = 18.500,00 € = AB-Wert; es gibt drei Projekte dieses Kunden |
| Hausner Peter, Windischeschenbach | Hausner Peter, … – Speicher privat | Summe 13.600,00 € = AB-Wert |
| Ertl, Vohenstrauß | Ertl, Vohenstrauß (25.06.2026) | Summe 10.406,94 € ≈ AB-Wert 10.406,00 €; drei Projekte dieses Kunden |
| Heider, Altenstadt | Heider, Altenstadt (04.05.2026) | Summe 4.990,36 € = AB-Wert |
| Haas, Waldershof - Speicher | Haas, … – Batteriespeicher + Wechselrichter | Summe 3.500,00 € = AB-Wert |
| Hößl, Grafenwöhr | Hößl, Grafenwöhr (24,6 kWp) | PV + Speicher = 30.291,98 € ≈ AB-Wert 30.291,00 €; die Wallbox kommt oben drauf |
| Dippl, Grafenwöhr | Dippl, Grafenwöhr (14,1 kWp) | PV + Speicher = 21.835,73 € ≈ AB-Wert 21.835,00 € |
| TSV Waldershof | TSV Waldershof e.V. (29,6 kWp) | Summe 29.064,65 € ≈ AB-Wert 29.064,00 € – **nicht** das Grünstromspeicher-Projekt (186.632 €) |
| Schuller, Theisseil - Wallbox | Schuller, Theisseil | die Wallboxrechnung gehört zu diesem Auftrag |
| Netto, Marktleugast | Netto-Markt, Marktleugast (99,2 kWp) | **hier ist eine Entscheidung nötig:** die 8 Zeilen dieses Kunden gehören zu **zwei** Projekten – PV 60.765,81 € und Speicher 133.662,50 €, beide als eigenes Projekt in der Teamliste. Die Auftragsliste unterscheidet sie im Kundentext nicht, deshalb landen alle 8 am PV-Projekt und dort steht eine Überdeckung von 133.663,31 €. |

**Was daraus folgt:** die Auftragsliste trennt PV und Speicher nur in der Rechnungsart, nicht im
Kunden. Wo ein Kunde für PV und Speicher zwei Projekte hat, landen beide Zahlungspläne am
zugeordneten Projekt. Für Umsatz und Forecast je Monat ändert das nichts, für den Umsatz je
Projekt schon. Die betroffenen Fälle stehen nach dem Lauf unter „Projekte mit unvollständigem
Zahlungsplan" und lassen sich in der Zahlungsplanmaske umhängen.

## Zulieferungen, ohne die spätere Phasen nicht starten können

| Phase | Was fehlt | Wofür |
|---|---|---|
| 0/1 | Firmenstammdaten für den Rechnungskopf: USt-IdNr., Steuernummer, HRB, Geschäftsführer, Bankverbindung; Verrechnungssätze je Stunde; OneDrive-Pfade; Host-Rechner und Dienstkonto | `config.toml`. Solange die Pfade fehlen, zeigt der Systemstatus einen Konfigurationshinweis. |
| – | **Steuernummer** der ip³ Energietechnik GmbH – wünschenswert, nicht erforderlich: § 14 Abs. 4 Nr. 2 UStG verlangt Steuernummer **oder** USt-IdNr., und letztere liegt vor. | `config.toml`. Der Systemstatus meldet nur noch, wenn **beide** fehlen. |
| 1 | Nach der Migration: Projektleiter-Namen den Nutzerkonten zuordnen (`pl_user_id`) | Sichtbarkeits-Scope `eigene` |
| ~~4~~ | ~~Beispiel-Kalkulationsblatt (PLAN §13.1)~~ – **erledigt auf anderem Weg:** der Leitstand gibt die Vorlage vor (`vorlagen/Kalkulationsblatt-Vorlage.xlsx`, PLAN §8). Sven passt sein Blatt einmalig daran an. | – |
| **jetzt** | Zahlungsziel-Standard und Skonto-Toleranz bestätigen (PLAN §13.10) | Die Fälligkeit steht auf jedem festgeschriebenen Beleg; Vorbelegung 14 Tage und 3 %. Bei festgeschriebenen Belegen ist eine Änderung nicht mehr rückwirkend. |
| **jetzt** | Auf dem Windows-Host GTK/Pango-Bibliotheken für WeasyPrint bereitstellen und den Ordner `01_Rechnungen` einrichten | Ohne GTK/Pango entsteht kein PDF; ohne Ordner wird der Beleg festgeschrieben, aber nicht abgelegt (nachholbar). In der Entwicklungsumgebung liegen die Bibliotheken vor. |
| ~~4~~ | ~~TimeTac: API-Freischaltung~~ – **erledigt**, Client-ID und Secret liegen vor (28.08.2026). | – |
| **jetzt** | TimeTac-Zugangsdaten in die `.env` auf dem Host eintragen und `ip3-leitstand timetac-test` ausführen | Der erste echte Lauf ist noch nicht gefahren: die Entwicklungsumgebung erreicht `api.timetac.com` nicht. Endpunkte und Feldnamen sind nach der v3-Dokumentation vorbelegt und in `config.toml` nachziehbar. |
| **jetzt** | Verrechnungssätze bestätigen und die Mitarbeiter den Satzgruppen zuordnen (PLAN §13.6) | `[stundensaetze]`. Die vier Sätze sind Platzhalter; ohne sie ist die Eigenleistung und damit die Marge nur so gut wie die Vorbelegung. |
| **jetzt** | Kontenbereiche des Kostenträgerexports mit der Buchhaltung abstimmen | `[datev.kostentraeger] kostenkonten`, vorbelegt mit dem SKR03-Aufwandsbereich. Was außerhalb liegt, bleibt draußen – stimmt der Bereich nicht, fehlen Kosten im Ist. |
| **jetzt** | Steuerberater-Abstimmung: **KOST2 = Projektnummer**, der monatliche Kostenträgerexport nach `02_DATEV` und **welcher Kontenrahmen geführt wird** (PLAN §13.4). Zum Weiterleiten: `docs/KANZLEI-ANFORDERUNG.md`. | Ohne KOST2 lässt sich keine Buchung einem Projekt zuordnen. Beim Kontenrahmen liegt die Falle: bei SKR04 sind die 4000er **Erlöse**, bei SKR03 Betriebsausgaben – ein falscher Bereich bucht Umsatz als Kosten. |
| 5 | SuSa und OPOS als monatliche Exporte, Review der Verfahrensdokumentation (PLAN §13.4) | Firmen-Cockpit, Zahlungsstatus, GoBD |
| 5 | Erstbefüllung des Konten-Mappings mit Buchhaltung und Steuerberater (PLAN §13.5) | Fixkostenblöcke im Cockpit |
| – | Das Werkzeug als Verarbeitungstätigkeit ins Verzeichnis nach Art. 30 DSGVO aufnehmen (PLAN §13.11) | Datenschutz. Zweck der TimeTac-Stunden ist Kostenrechnung, keine Leistungskontrolle. |
