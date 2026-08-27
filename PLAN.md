# PLAN.md – ip³ Leitstand (Repo: ip3-leitstand)

Projekt- und Finanz-Cockpit der ip³ Energietechnik GmbH.
Dieses Dokument ist die verbindliche Bauvorlage. Claude Code arbeitet die Phasen der Reihe nach ab, jede Phase endet lauffähig. Aus diesem Plan zu Beginn eine kompakte CLAUDE.md erzeugen (Arbeitsregeln, Stack, Verweis auf PLAN.md), damit nicht der gesamte Plan in jedem Kontext hängt.

---

## 1. Ziel und Kontext

ip³ Energietechnik GmbH (Theisseil) plant, baut und installiert PV-Anlagen und Batteriespeicher. Bisher laufen Auftragsliste, Umsatzplanung, Abschlagsverfolgung und Nachkalkulation verteilt über zwei Excel-Dateien, einen Rechnungs-PDF-Ordner und Kopfwissen. Das Tool ersetzt das durch eine zentrale Anwendung mit eigener Datenhaltung.

Kernfunktionen im Endausbau:

1. Projektverwaltung mit Zahlungsplan je Projekt (Abschläge, Schlussrechnung)
2. Umsatz-Ist und Umsatz-Forecast je Monat, offener Auftragsbestand
3. Fakturierung: Auftragsbestätigungen, Abschlags-, Schluss- und Servicerechnungen im ip³-Corporate-Design, inkl. E-Rechnung (ZUGFeRD) und GoBD-konformer Festschreibung
4. Nachkalkulation je Projekt: Soll aus Kalkulationsblatt gegen Ist aus DATEV-Kostenträgern, bewerteter Stückliste und TimeTac-Stunden
5. Firmen-Cockpit: Monatsübersicht Deckungsbeitrag gegen Fixkosten, Break-even, Reichweite des Auftragsbestands, optional Liquiditätssicht über OPOS
6. Anlagenregister mit Serviceaufträgen, Fristen- und Gewährleistungswächter

Nutzer: Sven Wilhelm (GF), Michael Bäumler (GF), eine Buchhaltungskraft, dazu lesender Zugriff fürs Team. Zugriff per Browser im Firmennetz, die App läuft auf einem Rechner/NAS im Büro.

---

## 2. Fixierte Architekturentscheidungen

| Thema | Entscheidung |
|---|---|
| Sprache/Runtime | Backend Python ≥ 3.11; Frontend Node LTS (nur als Build-Werkzeug) |
| Frontend | React mit Vite und TypeScript, etablierte Komponentenbibliothek (z. B. shadcn/ui oder Mantine, Entscheidung Claude Code) mit ip³-Theme, TanStack Query für Datenzugriff, TanStack Table für Tabellen; UI-Sprache Deutsch |
| Backend | FastAPI (REST, OpenAPI-Spezifikation), Pydantic-Schemas; der TypeScript-API-Client wird aus der OpenAPI-Spezifikation generiert, damit Frontend und Backend nicht auseinanderlaufen |
| Datenbank | SQLite im WAL-Modus mit `busy_timeout` und kurzen Schreibtransaktionen, **lokal auf dem Host-Rechner, niemals in einem Sync-Ordner** (OneDrive-Sync + SQLite = Korruptionsrisiko); mehrere tausend Kunden und Projekte sind für SQLite unkritisch |
| Datenzugriff | SQLAlchemy als Abstraktionsschicht, damit ein späterer Wechsel auf PostgreSQL ohne Umbau der Fachlogik möglich bleibt; alle Tabellen mit `created_at`, `updated_at`, `created_by`; Indizes auf allen Fremdschlüsseln sowie `projekt_nr`, `kunden_nr` und Monatsspalten; Listenansichten paginiert |
| Analyse | pandas; DuckDB nur falls für Auswertungen sinnvoll, keine Pflicht |
| Excel-I/O | openpyxl |
| PDF-Erzeugung | WeasyPrint (HTML/CSS-Vorlagen, CD-Schriften einbettbar) |
| E-Rechnung | Factur-X/ZUGFeRD 2.x, Profil EN 16931; Bibliothekskandidaten `drafthorse` oder `factur-x`, beim Bau aktuelle Eignung prüfen |
| Fuzzy-Matching | rapidfuzz (Migration, AR-Altbestand) |
| HTTP | requests (TimeTac-API) |
| Jobs | nächtlicher Job (APScheduler im Backend-Prozess oder OS-Taskplaner): Backup, TimeTac-Sync, Ordner-Scans, Fristenprüfung |
| Auth | Login mit Server-Sessions (httpOnly-Cookie, SameSite=Lax, bcrypt-Hashes in DB), CSRF-Schutz für alle schreibenden Requests, Sperre mit Wartezeit nach wiederholten Fehlversuchen (Versuche im audit_log); jede API-Route prüft Berechtigungen serverseitig (Abschnitt 4), das Frontend blendet nur zusätzlich aus; kein SSO in V1 |
| Backup | nächtlich `VACUUM INTO` in den OneDrive-Backup-Ordner, 30 Generationen vorhalten; Rechnungs-PDFs/XMLs liegen ohnehin im Sync |
| Konfiguration | `config.toml` + `.env` (Pfade, API-Zugänge, Stundensätze, Firmenstammdaten); keine Pfade im Code |
| Betrieb | ein Host im Büro: FastAPI über Uvicorn (ein Prozess) als Dienst mit Autostart (Windows-Dienst bzw. systemd), davor Caddy als Reverse Proxy mit TLS (interne CA/selbstsigniert, sonst gehen Session-Cookies im Klartext durchs LAN), das gebaute Frontend wird als statische Dateien ausgeliefert, eine Portfreigabe im LAN; zweite Instanz als Testumgebung mit Backup-Kopie der DB, Updates laufen erst dort |
| Logging/Status | strukturierte Logs mit Rotation in `logs/`; Backup-, Import- und Sync-Läufe schreiben Erfolg/Fehler in die DB, die Startseite zeigt einen Systemstatus-Block (letztes Backup, letzter DATEV-Import, letzter TimeTac-Sync, jeweils mit Alter); stille Job-Ausfälle darf es nicht geben |
| Zeit | Zeitstempel in UTC gespeichert, Anzeige und Monatszuordnung in Europe/Berlin |

Datenflüsse: Die App **schreibt** nur in die eigene DB und in den Rechnungs-Ausgabeordner. Alle externen Quellen (DATEV-CSVs, Kalkulationsblätter, AR-Altbestand, TimeTac) werden **nur gelesen**.

### Verzeichnisse (Pfade in config.toml, Beispielstruktur)

```
D:\ip3-leitstand\             App + SQLite-DB (lokal, kein Sync)
OneDrive\...\01_Rechnungen\   Ausgangsrechnungen: Altbestand (nur lesen) + neue PDFs/XMLs (App schreibt), zugleich DATEV-Upload-Quelle
OneDrive\...\02_DATEV\        Kanzlei-Exporte: kostentraeger_JJJJ-MM.csv, susa_JJJJ-MM.csv, opos_JJJJ-MM-TT.csv
OneDrive\...\03_Kalkulation\  Kalkulationsblätter je Projekt (Excel), Dateiname beginnt mit Projektnummer
OneDrive\...\04_Backup\       DB-Backups
assets/cd/                    Corporate-Design-Assets (Logos, Zeichen 3, Fonts), von Sven aus der CD-Ablage einkopiert
```

---

## 3. Schlüssel und Nummernkreise

- **Projektnummer**: rein numerisch, max. 8 Stellen, DATEV-KOST-tauglich. Schema `JJNNN` (Jahr zweistellig + laufende Nummer), z. B. `26014`. Bestandsprojekte erhalten bei der Migration Nummern nach Auftragsjahr. Die Projektnummer ist der durchgängige Schlüssel: DB, DATEV-Kostenträger (KOST2), TimeTac-Projekt, Kalkulationsblatt-Dateiname, Rechnungsreferenz.
- **Serviceaufträge**: eigener Kreis `9JJNN` (führende 9), damit im KOST-Feld unterscheidbar.
- **Rechnungsnummern**: je Kreis lückenlos und fortlaufend, Schema `RE-JJJJ-NNNN` (Projekte) und `SR-JJJJ-NNNN` (Service). Mehrere Kreise sind zulässig, solange jede Nummer einmalig ist. Vergabe erst bei Festschreibung, nicht im Entwurf, damit keine Lücken durch verworfene Entwürfe entstehen.
- **AB-Nummern**: `AB-JJJJ-NNNN`.
- Tabelle `nummernkreise(kreis, jahr, letzter_wert)` mit Vergabe in einer Transaktion.

---

## 4. Berechtigungen (RBAC von Anfang an)

Kein festes Rollen-Enum. Das Rechtemodell ist ab Phase 0 ein RBAC-Schema (Tabellen siehe Datenmodell): Nutzer haben Rollen, Rollen bündeln Berechtigungen. Berechtigungen sind Schlüssel nach dem Muster `ressource.aktion`, z. B. `projekte.lesen`, `projekte.schreiben`, `rechnungen.erstellen`, `rechnungen.festschreiben`, `nachkalkulation.lesen`, `cockpit.lesen`, `importe.ausfuehren`, `stammdaten.schreiben`, `admin.nutzer`. Wo sinnvoll tragen Berechtigungen einen Sichtbarkeits-Scope `alle` oder `eigene` (ein Projektleiter sieht dann nur seine Projekte). Finanzsichtbarkeit (Nachkalkulation, Cockpit, AB-Werte) ist bewusst von der Projektsicht getrennt, damit später Mitarbeiter Projektdaten pflegen können, ohne Margen zu sehen.

V1 seedet drei Rollen und kommt ohne Rollenpflege-UI aus (die kommt später, das Modell steht bereits):

| Seed-Rolle | Rechte |
|---|---|
| admin (Sven, Michael) | alle Berechtigungen inkl. Konfiguration, Fixkosten, Nutzerverwaltung, Stornofreigabe |
| buchhaltung | Kunden/Projekte/Zahlungsplan pflegen, Fakturierung inkl. Festschreibung, Importe ausführen |
| team | lesen mit Scope `alle`, jedoch ohne `nachkalkulation.lesen` und `cockpit.lesen` |

Jede schreibende Aktion landet im `audit_log`. Jede Seite und jede Aktion prüft gegen Berechtigungen, nie gegen Rollennamen.

---

## 5. Datenmodell (SQLite)

Feldnamen deutsch, snake_case. **Alle Geldbeträge als Integer in Cent** (nie Gleitkomma), Umrechnung nur in der Anzeige. Kein Löschen von Belegen und von Stammdaten mit Bezügen, nur Statuswechsel (`inaktiv`, `storniert`); Nutzer werden nie gelöscht, nur deaktiviert (audit_log-Referenzen). Bearbeitungsmasken arbeiten mit Optimistic Locking über `updated_at`: Speichern mit veraltetem Stand ergibt eine Konfliktmeldung statt eines stillen Überschreibens.

```
firmen           id, kuerzel ('ip3' als Standard, später z. B. 'mt2s'), firmierung, anschrift, ust_id, st_nr,
                 hrb, bank JSON, aktiv BOOL
kunden           id, kunden_nr UNIQUE (fortlaufend ab 10001, Kreis in nummernkreise), name, zusatz,
                 strasse, plz, ort, ust_id, typ ('b2b'|'b2c'), zahlungsziel_tage NULL (sonst config-Default),
                 email, telefon, status ('aktiv'|'inaktiv'), bemerkung
ansprechpartner  id, kunde_id, name, funktion, telefon, email, bemerkung
projekte         id, projekt_nr UNIQUE, firma_id, typ ('projekt'|'service'), kunde_id, standort,
                 pv_kwp, wr_typ, speicher_kwh, ladestation, auftrag_vom, ab_wert_netto,
                 pl_user_id NULL (FK users, Basis für Scope 'eigene'), pl_name (Text aus Migration),
                 vertriebsweg, ust_kz ('19'|'0'|'13b'|'gemischt'), status
                 ('angebot'|'beauftragt'|'in_bau'|'abgeschlossen'|'storniert'),
                 anlage_id NULL, quelle_migration, bemerkung
zahlungsplan     id, projekt_id, pos_nr, bezeichnung, gewerk ('pv'|'speicher'|'ls'|'service'|'nachtrag'),
                 art ('abschlag'|'schluss'|'einmal'), betrag_netto, plan_monat 'JJJJ-MM',
                 trigger_status NULL, rechnung_id NULL
nachtraege       id, projekt_id, bezeichnung, betrag_netto, status ('angeboten'|'beauftragt'|'berechnet'), datum
meilensteine     id, projekt_id, typ ('uebergabetermin'|'freigabe_planung'|'plan_erstellt'|'anmeldung_nb'|
                 'mastr'|'lieferung'|'montage'|'fertigmeldung'|'zaehler'|'abnahme'|'inbetriebnahme'),
                 geplant_kw NULL, erledigt_am NULL, bemerkung
                 (trägt Termine und Status der Teamliste; liefert die Trigger für Abschlagsvorschläge,
                 Fristen und die Anlagenregister-Automatik)
rechnungen       id, rechnung_nr NULL (bis Festschreibung, UNIQUE je firma_id), firma_id,
                 art ('ab'|'abschlag'|'schluss'|'service'|'gutschrift'|'storno'),
                 projekt_id, kunde_snapshot JSON, datum, leistungszeitraum, faellig_am (aus Kunden-Zahlungsziel),
                 netto, ust, brutto, status ('entwurf'|'festgeschrieben'|'storniert'),
                 storno_ref NULL, pdf_pfad, xml_pfad NULL, hash NULL, festgeschrieben_am, erstellt_von
rechnungspos     id, rechnung_id, pos, bezeichnung, menge, einheit, ep_netto, ust_satz,
                 zahlungsplan_id NULL (Verknüpfung Abschlag)
soll_kalkulation projekt_id PK, material_soll, dl_soll, stunden_soll, marge_soll, quelle_datei, eingelesen_am
stueckliste      id, projekt_id, artikel_nr, bezeichnung, menge_soll, menge_ist NULL,
                 ek_preis, quelle ('projektbestellt'|'lager'), gewerk, bewertet_betrag NULL
ist_kosten       id, projekt_id, quelle ('datev'|'stueckliste'|'timetac'), monat 'JJJJ-MM',
                 betrag, referenz, importlauf_id
stunden          id, projekt_id, monat, mitarbeiter, stunden, satz, quelle 'timetac', importlauf_id
anlagen          id, projekt_id_ursprung, kunde_id, standort, pv_kwp, speicher_kwh,
                 inbetriebnahme, abnahme_datum, gewaehrleistung_ende, wartungsvertrag BOOL, mastr_nr, bemerkung
fristen          id, bezug ('projekt'|'anlage'), bezug_id, typ ('mastr'|'fertigmeldung'|'reservierung'|
                 'gewaehrleistung'|'sonstig'), bezeichnung, faellig_am, vorlauf_tage, erledigt_am NULL
dokumente        id, projekt_id, typ ('ab'|'abnahme'|'anlagendoku'|'konformitaet'|'messkonzept'|'sonstig'),
                 pfad, vorhanden BOOL, geprueft_am
fixkosten_plan   id, monat 'JJJJ-MM', block, betrag, bemerkung
datev_salden     id, monat, konto, bezeichnung, saldo, block NULL, importlauf_id
konten_mapping   id, konto_von, konto_bis, block ('personal'|'raum'|'fahrzeuge'|'versicherung'|
                 'werbung'|'zins'|'sonstiges'|'neutral')
opos             id, rechnung_nr, kunde, betrag, faellig_am, offen_betrag, stand_datum, importlauf_id
importlaeufe     id, quelle, datei, zeitraum, gestartet, ergebnis JSON
users            id, name, pw_hash, aktiv BOOL
rollen           id, name, beschreibung
berechtigungen   id, schluessel ('ressource.aktion'), scope ('alle'|'eigene') NULL
rollen_berechtigungen  rolle_id, berechtigung_id
user_rollen      user_id, rolle_id
audit_log        id, ts, user, aktion, tabelle, datensatz_id, alt JSON, neu JSON
nummernkreise    firma_id, kreis, jahr, letzter_wert
```

DB-Trigger: UPDATE/DELETE auf `rechnungen` und `rechnungspos` mit `status='festgeschrieben'` blockieren (Ausnahme: Statuswechsel auf `storniert` mit gesetztem `storno_ref`). Zahlungsplanpositionen mit gesetzter `rechnung_id` sind gesperrt, Änderung nur über Storno des Belegs. UNIQUE-Constraints mindestens: `zahlungsplan(projekt_id, pos_nr)`, `rechnungen(firma_id, rechnung_nr)`, `meilensteine(projekt_id, typ)`.

---

## 6. Geschäftsregeln (kritisch, in Tests absichern)

1. **Schlussrechnung nach § 14 Abs. 5 UStG**: In der Schlussrechnung werden alle festgeschriebenen Abschlagsrechnungen des Projekts einzeln aufgeführt und mit Netto und darauf entfallender USt je Steuersatz abgesetzt, ausgewiesen wird der Restbetrag. Fehlende Absetzung führt zu unrichtigem Steuerausweis (§ 14c UStG), deshalb darf eine Schlussrechnung technisch nicht ohne Absetzungsblock erzeugbar sein.
2. **Steuerlogik**: Steuersatz je Rechnungsposition. Projekte tragen ein Kennzeichen `ust_kz`: 0 % nach § 12 Abs. 3 UStG für begünstigte Anlagen (Lieferung/Installation auf Wohngebäuden), 19 % Standard Gewerbe, `13b` für Bauleistungen mit Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG: kein USt-Ausweis, Pflichthinweis „Steuerschuldnerschaft des Leistungsempfängers" auf dem Beleg, nur wählbar bei hinterlegter USt-ID des Kunden), `gemischt` erzwingt Angabe je Position. Kein stiller Default bei `gemischt`.
3. **E-Rechnung**: Ab dem 1.1.2027 besteht für ip³ (Vorjahresumsatz 2026 über 800.000 €) die Pflicht, für inländische B2B-Umsätze E-Rechnungen auszustellen. Das Tool erzeugt daher ab sofort für Kunden mit `typ='b2b'` ZUGFeRD/Factur-X (PDF/A-3 mit eingebettetem XML, EN 16931), für `b2c` und Kleinbetragsrechnungen unter 250 € normales PDF. XML im Test gegen einen EN-16931-Validator prüfen.
4. **GoBD**: Rechnungsnummern lückenlos je Kreis; Festschreibung setzt Nummer, Zeitstempel und SHA-256-Hash über die Belegdaten; danach unveränderbar; Korrektur nur per Stornobeleg (Negativbeträge, eigener Beleg, Verweis `storno_ref`) plus Neuausstellung. Eine Verfahrensdokumentation als `VERFAHRENSDOKU.md` mitführen (Grundgerüst generieren, Abstimmung mit dem Steuerberater ist Aufgabe von Sven).
5. **Keine Doppelbelastung in der Nachkalkulation**: Materialkosten kommen entweder über DATEV-Kostenträger (projektbestellt) oder über die bewertete Stückliste (Lagerentnahme), nie beides. Steuerung über `stueckliste.quelle`: nur Positionen `lager` werden mit EK bewertet, Positionen `projektbestellt` erwartet das System im DATEV-Import. Plausibilitätsprüfung: Meldung, wenn ein Projekt DATEV-Materialkosten hat, aber alle Stücklistenpositionen auf `lager` stehen (oder umgekehrt).
6. **Eigenleistung**: Auf Projektebene zählen TimeTac-Stunden mal Verrechnungssatz (kalkulatorisch) ins Projekt-Ist. Auf Firmenebene (Cockpit) zählen die echten Personalkosten aus der SuSa im Fixkostenblock; die kalkulatorische Eigenleistung wird dort neutralisiert, sonst zählt Personal doppelt.
7. **Gestellt ist nicht bezahlt**: Umsatz-Ist im Forecast = festgeschriebene Rechnungen je Monat. Zahlungsstatus kommt ausschließlich aus dem OPOS-Import und wird getrennt ausgewiesen (offen/bezahlt/überfällig).
8. **Abschlagsvorschläge**: Ist bei einer Zahlungsplanposition `trigger_status` gesetzt (z. B. `lieferung`, `dachmontage`, `abnahme`) und erreicht das Projekt diesen Status, erscheint die Position als Rechnungsvorschlag auf der Startseite. Nur Vorschlag, nie Automatikversand.
9. **Anlagenregister-Automatik**: Wechselt ein Projekt auf `abgeschlossen`, wird (falls noch nicht vorhanden) ein Anlagen-Datensatz angelegt und die Gewährleistungsfrist gesetzt: Abnahmedatum plus 4 Jahre (VOB) bzw. 5 Jahre (BGB), Vertragsart wird beim Abschluss abgefragt, Erinnerung 3 Monate vor Ablauf.
10. **Zahlenformate**: durchgängig deutsch: 1.250,00 €, 5.695 kWp, 45,6 MW. Einheiten mit geschütztem Leerzeichen.
11. **Geldrechnung**: Beträge in Cent, kaufmännische Rundung; USt wird je Steuersatz auf die Nettosumme des Belegs berechnet und gerundet, nicht je Position aufsummiert (sonst Rundungsdifferenzen zwischen Positionssumme und Belegsumme).
12. **Zahlungsplan-Deckung**: Die Summe der Zahlungsplanpositionen wird laufend gegen AB-Wert plus beauftragte Nachträge geprüft; Abweichung ergibt eine sichtbare Warnung am Projekt, keine harte Sperre.
13. **Zahlungsabgleich mit Toleranz**: „bezahlt" gilt bei Restbetrag null oder innerhalb einer konfigurierbaren Skonto-Toleranz (Default 3 %); Differenzen innerhalb der Toleranz erscheinen als „bezahlt mit Abzug" statt dauerhaft als überfällig.
14. **Gutschriften**: Teilkorrekturen laufen als Belegart `gutschrift` mit Negativbeträgen im selben Nummernkreis und mit denselben Festschreibungsregeln; der Vollstorno bleibt `storno`.

---

## 7. Phasenplan

Jede Phase endet mit lauffähiger App, pytest-Suite grün, kurzer Statusnotiz in `CHANGELOG.md`. Buchführungsrelevante Unklarheiten (Steuer, Nummern, Festschreibung) werden nachgefragt, nicht angenommen.

### Phase 0 – Fundament
Monorepo mit `backend/` (FastAPI, SQLAlchemy, Migrationen z. B. über Alembic) und `frontend/` (React, Vite, TypeScript), config.toml/.env (`.env` nie ins Repo, `.env.example` daneben), DB-Schema, RBAC-Grundmodell mit den drei Seed-Rollen, Login mit Server-Sessions hinter Caddy/TLS, OpenAPI-Client-Generierung als Build-Schritt, Umsetzung des Designsystems aus dem Claude-Design-Ergebnis (Ablage `design/`: Design-Tokens als CSS-Variablen, Basiskomponenten, Statusbadges), Startseite mit Systemstatus-Block, nächtlicher Backup-Job, audit_log, Auslieferung des gebauten Frontends über das Backend, Seed-Skript mit Demodaten für Entwicklung und Schulung, `RUNBOOK.md` (Start/Stopp, Update über die Testinstanz, Restore Schritt für Schritt).
Akzeptanz: App startet im ip³-Design als ein Dienst hinter TLS, Login und serverseitige Berechtigungsprüfung funktionieren, ein Backup wurde nach RUNBOOK testweise zurückgespielt.

### Phase 1 – Migration und Stammdaten
Importer für die zwei Bestandsdateien (Struktur siehe Abschnitt 9) mit Vorschau- und Zuordnungsmaske (Fuzzy-Match Teamliste ↔ Auftragsliste, Rest manuell zuordnen oder als eigenes Projekt anlegen). Projektnummernvergabe nach Auftragsjahr, Termin- und Statusspalten wandern nach `meilensteine`. CRUD-Masken für Kunden, Ansprechpartner, Projekte, Meilensteine, Zahlungsplan, Nachträge, jeweils mit Konfliktprüfung beim Speichern (Optimistic Locking).
Akzeptanz: 530 Projekte und ca. 290 Zahlungsplanpositionen in der DB; Kontrollsummen (Summe AB-Werte, Summe Zahlungsplan je Monat) stimmen mit den Quelldateien überein und sind im Importprotokoll dokumentiert.

### Phase 2 – Umsatz und Forecast
Dashboard: Umsatz je Monat als Ist (festgeschriebene bzw. migriert-gestellte Positionen) und Plan (offene Zahlungsplanpositionen nach `plan_monat`), Jahresverlauf, offener Auftragsbestand gesamt und je Projekt, Filter nach Jahr/PL/Gewerk. Positionen ohne Planmonat erscheinen als „unterminiert" mit Summenausweis.
Akzeptanz: Monatssummen entsprechen einer manuellen Stichprobe aus der Altliste.

### Phase 3 – Fakturierung
Kundenstamm, AB-Erzeugung aus Projekt + Zahlungsplan, Abschlagsrechnung aus Zahlungsplanposition, Schlussrechnung mit automatischem Absetzungsblock, Servicerechnung mit freien Positionen, Storno. Entwurf → Vorschau (PDF) → Festschreibung (Nummer, Hash, Sperre) → Ablage PDF+XML in `01_Rechnungen` (Namensschema `RE-JJJJ-NNNN_<projekt_nr>_<kunde>.pdf`). Vorlagen in HTML/CSS im ip³-CD (Abschnitt 11). ZUGFeRD für B2B.
Akzeptanz-Testfälle: Schlussrechnung mit 3 Abschlägen und gemischten Steuersätzen rechnet korrekt; 0-%-Fall; Storno erzeugt Gegenbeleg und gibt die Zahlungsplanposition wieder frei; festgeschriebener Beleg unveränderbar; Nummernvergabe lückenlos unter Parallelzugriff; XML validiert.

### Phase 4 – Ist-Kosten und Nachkalkulation
DATEV-Kostenträger-Import (CSV, Spalten-Mapping konfigurierbar, idempotent je Monat), TimeTac-Sync (Abschnitt 8), Kalkulationsblatt-Einleser (EXPORT-Tab), Maske „Mengen-Ist bestätigen" je Projekt bei Abschluss, Bewertung der Lagerpositionen. Nachkalkulations-Ansicht je Projekt: AB-Wert + berechnete Nachträge | Soll (Kalkulation) | Ist (DATEV + Stückliste + Stunden) | Marge € und %, Ampel gegen `marge_soll`.
Akzeptanz: Testprojekt mit allen drei Ist-Quellen rechnet nachvollziehbar, Doppelbelastungssperre greift.

### Phase 5 – Firmen-Cockpit
SuSa-Import + Konten-Mapping-Pflege, Fixkosten-Planwerte für Zukunftsmonate, Monatsansicht: Umsatz (Ist+Plan) → Deckungsbeitrag (zunächst kalkulierte Marge, ab verfügbarer Nachkalkulation Ist-Marge) → Fixkostenblock → Über-/Unterdeckung je Monat und kumuliert. Kennzahlen: Break-even-Monatsumsatz bei Durchschnittsmarge, Reichweite des offenen Auftragsbestands in Monaten Fixkostendeckung. Umschaltbare Liquiditätssicht über OPOS. Klarer Hinweis im UI: Steuerungssicht, keine handelsrechtliche BWA.

### Phase 6 – Service, Anlagen, Fristen
Anlagenregister-Automatik, Serviceaufträge (typ='service', Bezug Anlage oder freier Kunde, Positionen manuell oder aus Artikelstamm-CSV), Nachträge in den Zahlungsplan, Fristenwächter (MaStR-Registrierung nach Inbetriebnahme, Fertigmeldungen, Netzanschluss-Reservierungen mit Ablaufdatum, Gewährleistung) mit Startseiten-Widget und optionalem täglichen E-Mail-Digest. Servicehistorie je Anlage. Liste „Anlagen ohne Wartungsvertrag".

### Phase 7 – Ausbau (nach Freigabe durch Sven)
Pipeline-Einbindung aus dem Excel-Angebots-Tool (gewichtete Angebotssumme im Forecast), Kapazitätsplanung je KW (Soll-Stunden aus Kalkulation gegen verfügbare TimeTac-Stunden), Doku-Vollständigkeits-Scan der Projektordner mit Schlussrechnungs-Sperrhinweis, Vergütungs-Controlling für eigene Bestandsanlagen (erwartete Gutschrift gegen Zahlungseingang).

---

## 8. Integrationen

### TimeTac
REST-API v3 unter `api.timetac.com`, OAuth2 (Client Credentials); die API muss von TimeTac für das Firmenkonto freigeschaltet werden (Zugangsdaten besorgt Sven). Nightly-Sync: Projekte/Tasks und Zeitbuchungen des laufenden und Vormonats lesen, Zuordnung über die Projektnummer im TimeTac-Projektnamen bzw. -nummernfeld, Schreiben in `stunden` (idempotent je Monat). Verrechnungssätze aus config. Endpunkt- und Felddetails beim Bau gegen docs.timetac.com verifizieren. Fallback, falls API-Freischaltung sich verzögert: CSV-Import aus dem TimeTac-Berichtsexport mit gleichem Zielschema.

### DATEV (dateibasiert, keine Direktschnittstelle in V1)
Drei Kanzlei-Exporte landen monatlich in `02_DATEV`:
1. Kostenträgerauswertung mit Einzelbuchungen → `ist_kosten` (quelle='datev'), Schlüssel = KOST2 = Projektnummer
2. Summen- und Saldenliste → `datev_salden`, Blockzuordnung über `konten_mapping`
3. OPOS Debitoren → `opos`

Spaltenbezeichnungen variieren je Kanzlei-Export, deshalb Mapping in config, Import mit Vorschau, jeder Lauf ersetzt den Zeitraum statt anzuhängen (`importlaeufe`). Unbekannte Konten ohne Mapping erscheinen als Pflegehinweis.

### Kalkulationsblatt (EXPORT-Tab, Vorlage gibt das Tool vor)
Jedes Kalkulationsblatt erhält ein Blatt `EXPORT` mit benannten Zellen:
`exp_projekt_nr`, `exp_material_soll`, `exp_dl_soll`, `exp_stunden_soll`, `exp_marge_soll`
sowie einer Positionstabelle ab `exp_positionen_start`:
`artikel_nr | bezeichnung | menge | ep_ek | quelle (projektbestellt|lager) | gewerk (pv|speicher|ls)`.
Claude Code erzeugt die Vorlagendatei; Sven passt sein bestehendes Kalkulationsblatt einmalig daran an (Beispieldatei folgt, bis dahin gegen die eigene Vorlage entwickeln). Der nightly Job scannt `03_Kalkulation`, Dateiname beginnt mit Projektnummer.

### AR-Altbestand
Einmaliger Scan von `01_Rechnungen` für Rechnungen vor Tool-Einführung: Zuordnung über Projektnummer/Kundenname im Dateinamen bzw. PDF-Text (Fuzzy + manuelle Bestätigungsmaske), Ergebnis als migrierte `rechnungen` mit Status `festgeschrieben` und Kennzeichen `quelle_migration`. Danach ist der Ordner nur noch Ablageziel neuer Belege.

---

## 9. Migration der Bestandsdaten

### Datei 1: `Offene_Auftra_ge_2025.xlsx`, Blatt `Et-Einnahmen` (ca. 291 Zeilen)
- Datenzeilen ab Zeile 8. Spalte A: Freitext `Kunde, Ort - Rechnungsart` (Rechnungsarten: `1./2./3. Abschlag PV|Speicher`, `Schlussrechnung PV|Speicher`, `Rechnung 100 %`, Wallbox u. ä.). Zeilen ohne Rechnungsart-Suffix sind Projektsummen ohne Zahlungsplan (z. B. `Speicherprojekt Hausner, Püllersreuth` 160.000) → als eine offene Zahlungsplanposition anlegen.
- Spalte B: Nettobetrag. Spalte D: `x` = erledigt (Import als „Rechnung gestellt" behandeln, Kennzeichen `quelle_migration`; endgültige Bedeutung klärt Sven, siehe offene Punkte).
- Monatslogik: je Monat Januar bis November ein Spaltenpaar aus Marker-Spalte (`x`) und Formelspalte `=IF(<Marker>="x";$B<zeile>;"")`; Marker-Spalten sind G, J, M, P, S, V, Y, AB, AE, AH, AJ. Der Marker-Monat wird `plan_monat` (Jahr 2026 bzw. aus Kontext).

### Datei 2: `Teambesprechung_NEU.xlsx`, Blatt `Übersicht Projekte` (530 Projektzeilen)
- Kopfzeile in Zeile 5, Daten ab Zeile 8, Projektzeilen erkennbar an gefülltem Kunden (Spalte B).
- Spalten: B Kunde | C PV-Leistung | D WR | E Speicher kWh | F Storage | G Ladestation | H Auftrag vom | I AB-Wert € | J–P Nachkalkulations-Block (Status, Bemerkung, Netto-Ausgaben, NK €, GWL, Vertrieb, Gewinn %) | R Projektleiter | T–AA Vorplanungsphasen in KW | AC–AK Montage-/Liefertermine in KW | AM–AT Statusblock (Übergabetermin, Freigabe Planung, Schalt-/Lageplan, Anmeldung Netzbetreiber, MaStR, Fertigmeldung, Zähler, Abnahme) | AV–BC Abschlagskreuze PV 1–4 und SP 1–4 (`x`/`-`/leer) | BD Ladestation | BE Rechnung an ET | BF Provision | BG Bemerkung.
- Kunde+Ort per rapidfuzz gegen die Präfixe aus Datei 1 matchen; Trefferquote wird nicht 100 % sein, deshalb Zuordnungsmaske mit Bestätigung. Nachkalkulations-Altwerte (ca. 26 gefüllte Zeilen) als Notiz übernehmen, nicht als Ist-Kosten.
- Termin- und Statusspalten (T–AA, AC–AK, AM–AT) werden zu `meilensteine`-Einträgen; Projektleiter-Namen landen in `pl_name`, die Verknüpfung `pl_user_id` wird nach der Migration manuell gesetzt.
- Statusableitung fürs Projektfeld `status`: Abnahme gesetzt → `abgeschlossen`, sonst `in_bau` bzw. `beauftragt`.

Beide Quelldateien werden nach erfolgreicher Migration schreibgeschützt (Stichtag), das Tool ist ab dann führend.

---

## 10. Fakturierung im Detail

- **Belegarten**: AB (keine Rechnung, kein Nummernkreis-Zwang zur Lückenlosigkeit, aber fortlaufend), Abschlagsrechnung (aus Zahlungsplanposition), Schlussrechnung (Projekt), Servicerechnung, Gutschrift, Storno.
- **Pflichtangaben § 14 UStG** vollständig aus Firmenstammdaten (config: Firmierung, Anschrift, USt-ID/St-Nr., HRB, Geschäftsführer, Bankverbindung) und Kundenstamm; Leistungszeitraum Pflichtfeld.
- **Fälligkeit**: `faellig_am` aus dem Zahlungsziel des Kunden bzw. config-Default (14 Tage); Überfälligkeit berechnet sich daraus, der OPOS-Import liefert zusätzlich die tatsächlichen Zahlungen.
- **Workflow**: Entwurf beliebig änderbar → PDF-Vorschau → Festschreibung (vergibt Nummer, erzeugt PDF und ggf. XML, Hash, Ablage, Sperre). Versand macht der Mensch per E-Mail, kein Mailversand aus dem Tool in V1.
- **Schlussrechnung**: zieht automatisch alle festgeschriebenen Abschläge des Projekts (je Gewerk filterbar, Standard: alle), Absetzungsblock siehe Geschäftsregel 1, Restbetrag ausgewiesen.
- **AB-Einlesen Bestand**: PDF-Upload je Projekt als Dokument; optional KI-Extraktion der Positionen mit Prüfmaske (nice-to-have, Phase 7).

---

## 11. Corporate Design (verbindlich für alle erzeugten Dokumente)

Assets liegen in `assets/cd/` (Sven kopiert sie aus der CD-Ablage ein; Dateinamen per `ls` prüfen, nie raten). Kurzfassung der Vorgaben:

- **Farben**: ip³ Blau `#2F2482` (Überschriften, Strukturflächen, Tabellenkopf), Navy `#0C1A3D`, ip³ Rot `#8D0C07` (nur Logo/Zeichen), Akzent-Rot `#C83C30` (sparsam, einziger Akzent). Text `#1A1A1A`, Sekundär `#666666`, Linien `#E0E0E0`, Infoflächen `#F5F6F9`. Keine weiteren Farben, keine Verläufe, kein Ampelgrün (positiv = Blau, negativ = Akzent-Rot, auch in Diagrammen: Serienfolge `#2F2482`, `#C83C30`, `#0C1A3D`, `#8D8AB8`, `#E8A49C`).
- **Schriften**: Libre Franklin (Fließtext Regular, Headlines Bold/ExtraBold), Space Grotesk Medium/Bold für Zahlen und Kennwerte mit Tabellenziffern. TTFs aus `assets/cd/fonts/` per `@font-face` in WeasyPrint einbetten. Fallback Archivo, Arial. Nie Calibri oder Serifen.
- **Geschäftsdokumente (Rechnung, AB)**: weißer Grund, Wortmarke `ip3-energietechnik-farbig` oben links 55 mm breit, darunter 2-pt-Linie in ip³ Blau. Überschriften in ip³ Blau. Fußzeile 8 pt in `#666666`: links `ip³ Energietechnik GmbH · Theisseil · info@ip3-energie.de · www.ip3-energie.de` plus Pflichtangaben (HRB, GF, Bank), rechts Seitenzahl. Tabellen: Kopfzeile ip³ Blau mit weißer Schrift, Zebrastreifen `#F5F6F9`, Zahlen rechtsbündig, Einheit in die Spaltenüberschrift. **Kein Wasserzeichen auf Rechnungen** (zahlenlastige Seiten bleiben frei).
- **Schreibweise**: ip³ mit hochgestellter 3 im Text, `ip3` nur in Dateinamen; als Absender immer die Logodatei, nie nachgebaut. Zahlen deutsch formatiert.
- **App-UI**: verbindlich nach dem mit Claude Design erarbeiteten Designsystem (Ablage im Repo unter `design/`, Auftrag siehe DESIGN-PROMPT.md); App-Icon `ip3-app-icon-blau.svg`. Kein ENMAG-Co-Branding im Tool. Liegt das Design-Ergebnis noch nicht vor, gilt dieser Abschnitt als Interimsvorgabe.

---

## 12. Nichtziele (V1)

Kein ERP, keine Lagerbuchhaltung, keine handelsrechtliche BWA (Abgrenzungen, AfA, teilfertige Arbeiten bleiben beim Steuerberater), keine DATEVconnect-Direktanbindung, kein automatischer Mahn- oder Mailversand, keine Mobile-App (Browser reicht). Kein volles Mehrmandanten-UI in V1, aber die Firmen-Dimension (`firmen`, `firma_id` auf Projekten und Rechnungen, Nummernkreise je Firma) steckt von Anfang an im Schema, Standard ip³, damit später z. B. MT2S ohne Umbau fakturieren kann.

---

## 13. Offene Punkte, Input von Sven

1. Beispiel-Kalkulationsblatt (für EXPORT-Tab-Anpassung) und eine Beispiel-Ausgangsrechnung (Layoutreferenz + Parser Altbestand)
2. Bedeutung des `erledigt`-Kreuzes in der Altliste: gestellt oder bezahlt
3. TimeTac: API-Freischaltung und Client-Zugangsdaten beantragen
4. Steuerberater-Abstimmung: KOST2 je Projektnummer, drei monatliche CSV-Exporte (Kostenträger, SuSa, OPOS), Verfahrensdoku-Review
5. Erstbefüllung Konten-Mapping (mit Buchhaltung/Steuerberater)
6. Firmenstammdaten für den Rechnungskopf (USt-ID, St-Nr., HRB, Bank), Verrechnungssätze je Stunde, OneDrive-Pfade, Host-Rechner
7. CD-Assets nach `assets/cd/` kopieren
8. Entscheidung Gewährleistungsdefault (VOB 4 Jahre oder BGB 5 Jahre) je Auftragsart
9. Claude-Design-Ergebnis (Designsystem, CSS-Variablen, Screen-Mockups) nach `design/` ins Repo legen
10. Nach der Migration: Projektleiter-Namen den Nutzerkonten zuordnen (`pl_user_id`); Zahlungsziel-Default und Skonto-Toleranz in der config festlegen
11. Datenschutz: das Tool als Verarbeitungstätigkeit ins Verzeichnis nach Art. 30 DSGVO aufnehmen (Kunden- und Beschäftigtendaten); Zweck der TimeTac-Stunden im Tool ist Kostenrechnung, keine Leistungskontrolle, intern so kommunizieren

---

## 14. Arbeitsweise für Claude Code

- Phase für Phase, keine Phase überspringen; nach jeder Phase lauffähiger Stand, pytest grün, kurzer Eintrag in `CHANGELOG.md`.
- Tests mindestens für: Steuer- und Absetzungslogik, Nummernvergabe unter Parallelzugriff, Festschreibungs-/Stornosperren, Doppelbelastungssperre, alle Datei-Parser (mit Fixture-Dateien), Migrationskontrollsummen; API-Endpunkte mit pytest gegen eine Testdatenbank, für die Kern-Workflows (Abschlag stellen, festschreiben) ein schlanker End-to-End-Test (z. B. Playwright).
- Berechtigungen ausschließlich serverseitig durchsetzen; das Frontend blendet nur aus und ist nie die einzige Sperre.
- Frontend-Abhängigkeiten konservativ wählen, Versionen über Lockfile pinnen, Updates gesammelt statt laufend.
- Bei buchführungs- oder steuerrelevanten Unklarheiten nachfragen statt annehmen; bei rein technischen Detailfragen entscheiden und die Annahme im Code kommentieren.
- Keine zusätzlichen Frameworks ohne Not, keine Cloud-Dienste, alle Daten bleiben lokal bzw. im Firmen-OneDrive.
- UI-Texte, Kommentare für Fachlogik und Commit-Messages auf Deutsch.
- `RUNBOOK.md` und ein kurzes `NUTZERHANDBUCH.md` je Rolle werden mit jeder Phase aktuell gehalten.
- Eine Funktion gilt erst als fertig, wenn ihre Fehlerpfade (fehlerhafte Importdatei, TimeTac nicht erreichbar, Speicherkonflikt, fehlende Berechtigung) eine verständliche deutsche Meldung mit nächstem Schritt erzeugen statt eines Stacktrace.
