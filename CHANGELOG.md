# Änderungsverlauf

Format: neueste Phase oben. Jede Phase endet lauffähig mit grüner Testsuite (PLAN §7).

## 0.3.0 – Phase 2: Umsatz und Forecast

Aus 280 Zahlungsplanpositionen wird eine Aussage: was ist abgerechnet, was steht noch aus, was ist
vom Auftragsbestand offen. Menüpunkt **Umsatz & Forecast**, sichtbar mit `umsatz.lesen`.

### Auswertung

* **Jahresverlauf** mit zwölf Monaten – auch den leeren – als Ist und Plan. Ist heißt: berechnet
  oder im Altbestand als gestellt gekennzeichnet (PLAN §6.7 trennt das von *bezahlt*).
* **Unterminierte Positionen** stehen in keiner Monatssäule und trotzdem sichtbar: eigene Kachel,
  eigene Zeile neben der Legende. Im Bestand sind das 689.698,50 €, darunter 12.342,06 €, die
  bereits gestellt sind – Umsatz ohne Monat.
* **Auftragsbestand** = Auftragswert plus beauftragte Nachträge minus dem, was schon abgerechnet
  ist, je laufendem Projekt und in Summe (Entscheidung Svens). Überdeckungen werden nicht auf
  null geklammert, sondern als „prüfen" ausgewiesen: dort stimmt der Auftragswert nicht.
* **Filter** für Jahr, Status, Projektleiter und Gewerk, wie in der Projektliste. Die Werte sind
  serverseitig als `Literal` deklariert – ein Tippfehler ergibt eine Meldung und nicht eine
  stillschweigend leere Auswertung, die wie „kein Umsatz" aussieht.
* Ein Jahr ohne Daten liefert zwölf leere Monate mit Status 200. Eine leere Auswertung ist eine
  Auskunft, keine Störung.

### Was die Seite ausdrücklich sagt

* **Der Ist ist unvollständig.** Die Auftragsliste führte nur die offenen Positionen; vor der
  Einführung bezahlte Rechnungen aus 2026 fehlen deshalb. Der Hinweis kommt vom Server und
  verschwindet von selbst, sobald keine Altpositionen mehr im Ist stecken – ab Phase 3.
* **Kachel und Diagramm sind nicht dieselbe Zahl.** Der Auftragsbestand rechnet über
  Auftragswerte, der Forecast über Zahlungsplanpositionen; die Differenz steht als eigene Zeile
  darunter.

### Korrektur an der Migration

19 der 87 laufenden Projekte hatten keinen Auftragswert, 9 davon mit 1.798.837,71 € offenen
Positionen – 38 % des Bestands wären unsichtbar geblieben. Für die Zeilen ohne Rechnungsart, die
PLAN §9 „Projektsummen" nennt, steht der Wert in der Quelle; die Migration übernimmt ihn jetzt
mit Vermerk in der Herkunft. Trägt eine Zeile der Gruppe eine Rechnungsart, bleibt das Feld leer:
eine Schlussrechnung ist der Rest eines größeren Auftrags, ihr Betrag wäre als Auftragswert eine
Falschangabe. Im Abnahmelauf betrifft das 7 Projekte mit 1.767.000,00 €; ohne Wert bleiben
`Breite Wiesen FF / Inbetriebnahme Schlussrechnung` und `Forster ENMAG Weiden - Schlussrechnung`.

### Bemerkenswerte Funde beim Bau

* **Die Monatssummen kamen versechsfacht heraus** (18 Mio. € statt 3 Mio. €) – dieselbe Ursache
  wie in der Filterleiste der Projektliste: `select(spalten).select_from(basis.subquery())`
  bezieht die Spalten auf die Tabelle statt auf die Unterabfrage und erzeugt ein Kreuzprodukt,
  ohne dass etwas fehlschlägt. Gefunden haben es die von Hand gerechneten Testdaten; die
  Abfragehilfe trägt den Grund jetzt als Kommentar.
* **Die Jahresauswahl war eine Sackgasse.** Sie führte nur Jahre aus den Daten – im Bestand nur
  2026. Wer im Dezember auf das nächste Jahr schauen will, wäre nicht hingekommen.

### Abnahme (PLAN §7 Phase 2: „Monatssummen entsprechen einer manuellen Stichprobe")

Die Monatssummen wurden **unabhängig** aus `Offene_Auftraege_2025.xlsx` nachgerechnet – die
Markerspalten direkt gelesen, nicht über den Importer. Sie stimmen Monat für Monat, Ist und Plan
getrennt: 280 Zeilen, 150 gestellt, 3.826.937,38 € netto; Ist 862.152,24 €, Plan 2.964.785,14 €;
Juli 226.302,01 € (die Datei selbst weist an ihrer Kopfzeile falsch 360.813,53 € aus), November
1.261.894,53 €, ohne Monat 689.698,50 €. Auftragsbestand 4.661.559,76 €.

Tests: 684 im Backend, 105 im Frontend.

## 0.2.0 – Phase 1: Bestandsdaten und Stammdatenmasken

Der Leitstand kennt jetzt den Bestand: 484 Kunden, 539 Projekte, 5.848 Termine und 280
Zahlungsplanpositionen aus den beiden bisher geführten Excel-Dateien, mit Kontrollsummen, die zu
den Quelldateien passen. Dazu die Masken, um das alles zu pflegen. Ab hier ist der Leitstand die
führende Aufzeichnung; die Excel-Dateien werden schreibgeschützt (VERFAHRENSDOKU §9).

### Übernahme der Bestandsdaten (PLAN §9)

* Leser für beide Dateien, gebaut an den echten Eigenheiten: Rechnungsarten in 21 Schreibweisen,
  Beträge mit zwei Trennzeichen, Excel-Seriennummern neben Tippfehlern im Datum,
  Speicherangaben als Produkttext („2x BYD HVM 22.1"), Termin- und Statusspalten mit `x`, `-`,
  `o`, Kalenderwochen und Klartext. Jede Zelle, die nicht sicher lesbar war, steht als Befund
  im Importprotokoll – nichts verschwindet still.
* **Zuordnung Auftragsliste ↔ Teamliste** mit getrennter Bewertung von Name und Ort. Die
  strengere Regel verhinderte eine belegte Fehlzuordnung: 550.000 € wären von „Nachtmann,
  Weiden" auf „Hubmann, Weiden" gelaufen.
* Zuordnungsmaske für den Rest: 24 Kunden mit 2,5 Mio. €, nach Betrag sortiert, mit Kandidaten
  samt Leistung, Datum und Wert zur Unterscheidung. Je Kunde: Vorschlag bestätigen, anderes
  Projekt suchen oder eigenes Projekt anlegen. Die Übernahme ist erst freigeschaltet, wenn
  keine Entscheidung mehr offen ist.
* Ein Lauf, eine Transaktion, kein zweites Mal. Bricht er ab, ist die Datenbank unverändert –
  in der Abnahme geprüft, nachdem ein echter Fehler ihn hat abbrechen lassen (siehe unten).
* **Lücken werden ausgewiesen, nicht gefüllt** (Entscheidung Svens): bei 9 Projekten passt der
  Zahlungsplan nicht zum Auftragswert, weil die Auftragsliste nur die offenen Positionen führt.
  Eine erfundene Sammelposition wäre Umsatz ohne Belegbezug.

### Masken

* **Kunden und Ansprechpartner** mit Suche über Name, Ort und Nummer – umlautunabhängig,
  „poellath" findet Pöllath. Kunden werden nicht gelöscht, sondern inaktiv.
* **Projektliste** nach `design/Projektliste.dc.html`: Filter für Jahr, Status, Projektleiter
  und Gewerk, serverseitiges Blättern über 539 Projekte, Auftragsvolumen der Auswahl in der
  Kopfzeile.
* **Projektdetail** mit Reitern, Anlagendaten und der Zeitleiste der Termine (19 Schritte in
  drei Gruppen, je drei Zustände). Reiter für Phase 4 und 6 sind sichtbar und gesperrt.
* **Zahlungsplan und Nachträge** mit Deckungsprüfung gegen Auftragswert plus beauftragte
  Nachträge (PLAN §6.12) und zwei Sperren, die von Anfang an als Sperre gezeichnet sind.
* **Projektleiter-Zuordnung**: elf Namen der Teamliste auf Nutzerkonten, wirksam für alle
  Projekte eines Namens. Ohne sie greift der Sichtbarkeits-Scope `eigene` nicht.

### Buchführungsrelevante Absicherung

* Migration `0005`: Trigger, die migriert-gestellte Zahlungsplanpositionen unveränderbar und
  unlöschbar machen. Erlaubt bleiben genau zwei Wege, beide ohne Änderung der Beträge: das
  Kennzeichen zurücknehmen oder die Position ab Phase 3 mit einem Beleg verknüpfen. Per SQL an
  der Anwendung vorbei geprüft.
* Finanzsichtbarkeit: ohne `projekte.werte_lesen` fehlen Auftragswert, Zahlungsplan und Summen
  in der **Antwort**, nicht nur in der Anzeige. Wer sie nicht lesen darf, darf sie auch nicht
  setzen.

### Bemerkenswerte Funde beim Bau

Sechs Fehler, drei davon in Code, der schon stand:

* **Die Abnahme brach die Übernahme ab.** Zwei Kundentexte der Auftragsliste können auf dasselbe
  Projekt zeigen – „Schuller, Theisseil" und „Schuller, Theisseil - Wallbox" sind derselbe
  Auftrag. Jede Zuordnung zählte ihre Positionsnummern wieder bei 1, die zweite verletzte
  `UNIQUE(projekt_id, pos_nr)`, und der Lauf scheiterte, nachdem 24 Entscheidungen getroffen
  waren. Die Transaktion hat dabei gehalten: die Datenbank stand unverändert da, das
  Importprotokoll war leer.
* **`Decimal` passt nicht in eine JSON-Spalte.** Ein Projekt mit Leistungsangabe zu speichern
  ergab einen Serverfehler mit Stacktrace, weil das Änderungsprotokoll `pv_kwp` nicht
  serialisieren konnte – genau das, was CLAUDE.md Regel 8 verbietet.
* **`Decimal("514.08") == 514.08` ist in Python `False`.** Jede Speicherung ohne echte Änderung
  hätte „514.08 → 514.08" protokolliert und die wirklichen Änderungen darin untergehen lassen.
* **Die Filterleiste umging die Sichtbarkeitsgrenze.** Jahre und Projektleiternamen entstanden
  über ein Kreuzprodukt; die Auswahlliste hätte Angaben aus Projekten verraten, die der Nutzer
  selbst nicht öffnen darf.
* **Die Konfliktprüfung kürzte auf ganze Sekunden** (aus Phase 0). Zwei Speicherungen innerhalb
  derselben Sekunde galten als derselbe Stand – der zweite überschrieb den ersten
  stillschweigend, also genau der Fehler, den die Prüfung verhindern soll.
* **`0,145 € * 100` ergibt 14 Cent statt 15.** Die Umrechnung von Euro-Eingaben stand zweimal im
  Frontend nachgebaut; sie rechnet jetzt an einer Stelle auf ganzen Zahlen und rundet
  kaufmännisch (PLAN §6.11).

Dazu drei Befunde in den Quelldateien selbst, die Sven kennen sollte: drei falsche
Summenformeln (der ausgewiesene Auftragsbestand übergeht 29 Projekte mit 1,5 Mio. €) und vier
Zeilen bei einem Kunden, die alle „1. Abschlag PV" heißen. Einzelheiten in
`docs/OFFENE-PUNKTE.md`.

### Offen

Vor Phase 3 zu entscheiden: der Rechnungsnummernkreis (`PV-ET JJ-NNNN` fortführen oder auf
`RE-JJJJ-NNNN` umstellen) – GoBD-relevant, weil die Nummernfolge lückenlos bleiben muss. Weiter
fehlen die Steuernummer für den Rechnungskopf sowie Backup-Zielpfad, Host und Dienstkonto.

Tests: 641 im Backend, 91 im Frontend.

## 0.1.0 – Phase 0: Fundament

Erste lauffähige Fassung: der Leitstand startet als ein Dienst im ip³-Design, Anmeldung und
serverseitige Berechtigungsprüfung funktionieren, die nächtliche Sicherung läuft und ist
zurückspielbar. Projekt-, Fakturierungs- und Auswertungsfunktionen folgen mit den Phasen 1 bis 6.

### Grundlagen

* **Monorepo** mit `backend/` (FastAPI, SQLAlchemy, Alembic) und `frontend/` (React, Vite,
  TypeScript). Paketverwaltung über uv und npm, Versionen über Lockfiles gepinnt.
* **Konfiguration** aus `config.toml` und `.env`; Umgebungsvariablen überschreiben die Datei,
  sodass sich die Testinstanz allein über `IP3_APP__PORT` auf einen anderen Port legen lässt.
  Fehlerhafte Konfiguration erzeugt eine Meldung in Klartext mit nächstem Schritt.
* **Startsperre für Datenbanken in Sync-Ordnern**: liegt der Datenbankpfad in OneDrive,
  Dropbox oder auf einem Netzlaufwerk, verweigert der Leitstand den Start. SQLite wird dort
  beschädigt; ein Abbruch ist billiger als eine unbemerkt zerstörte Datenbank.
* **Datenbankzugriff** mit den PRAGMAs im Verbindungsereignis (sie gelten je Verbindung),
  WAL-Modus und `BEGIN IMMEDIATE` für Schreibvorgänge.

### Datenmodell

* Alle Tabellen aus PLAN §5 plus zwei technisch nötige: `sitzungen` für die serverseitigen
  Anmeldungen, `job_laeufe` für den Datenstand. Das Schema ist von Anfang an vollständig.
* Geldbeträge als Integer in Cent, Zeitpunkte in UTC über einen eigenen Spaltentyp, der Werte
  ohne Zeitzone abweist. Monate als `'JJJJ-MM'` mit portabler Prüfbedingung.
* Optimistic Locking über `updated_at` für alle von Menschen bearbeiteten Tabellen;
  Importtabellen bewusst ohne.
* Indizes auf allen Fremdschlüsseln sowie auf `projekt_nr`, `kunden_nr`, `rechnung_nr` und den
  Monatsspalten. Ein Test prüft das.

### Buchführungsrelevante Absicherung

* **Datenbank-Trigger** verhindern Änderung und Löschung festgeschriebener Belege, ihrer
  Positionen und berechneter Zahlungsplanpositionen – auch durch Zugriffe an der Anwendung
  vorbei. Erlaubt bleibt allein der Statuswechsel auf `storniert` mit Verweis, wobei Nummer,
  Beträge, Datum und Hash unverändert bleiben müssen.
* **Nummernvergabe** in derselben Transaktion wie der Beleg, damit keine Lücken entstehen. Ein
  Test lässt zehn Threads gleichzeitig Nummern ziehen.
* **Umsatzsteuer je Steuersatz auf die Belegsumme**, nicht je Position aufsummiert (PLAN §6.11);
  kaufmännische Rundung.

### Anmeldung und Berechtigungen

* Server-Sitzungen mit `httpOnly`-Cookie; der Sitzungsschlüssel liegt nur als Hash in der
  Datenbank – die Sicherungskopie im OneDrive enthält keine verwendbaren Zugangsdaten.
* CSRF-Schutz über ein sitzungsgebundenes Token plus Herkunftsprüfung, verankert in der
  Abhängigkeit, die den angemeldeten Nutzer ermittelt: keine Route kann die Prüfung vergessen.
* Sperre nach fünf Fehlanmeldungen für 15 Minuten, gezählt im Änderungsprotokoll; während der
  Sperre wird auch ein richtiges Passwort abgelehnt. Zusätzlich Drosselung je Absenderadresse.
* Die Anmeldung gibt nicht preis, was falsch war – unbekannte Kennung, falsches Passwort und
  deaktiviertes Konto ergeben dieselbe Antwort, auch in der Antwortzeit.
* RBAC mit den drei Rollen aus PLAN §4. Finanzsichtbarkeit ist abgetrennt: `projekte.lesen`
  zeigt Termine und Anlagendaten, `projekte.werte_lesen` erst die Beträge.
* Ein Regressionstest verlangt für jede schreibende `/api`-Route eine Berechtigungsprüfung.
* `docs/BERECHTIGUNGEN.md` wird aus dem Katalog erzeugt, nicht gepflegt.

### Betrieb

* **Nächtliche Sicherung** per `VACUUM INTO` – eine in sich geschlossene Kopie, erzeugt auch
  während gearbeitet wird. 30 Generationen, Rotation ausschließlich nach Namensmuster und ohne
  die Dateien zu öffnen (sonst holt OneDrive alte Sicherungen aus der Cloud zurück). Jede
  Sicherung wird auf Integrität geprüft.
* **Datenstand** auf der Startseite: für jeden Hintergrundlauf, wann er zuletzt erfolgreich war
  und wie alt dieser Stand ist. Läufe späterer Phasen erscheinen als „kommt später" und färben
  den Gesamtstatus nicht. Der Zeitplan läuft in Ortszeit und warnt bei mehreren
  Arbeitsprozessen.
* **Ein Prozess liefert API und Oberfläche.** Tiefe Adressen funktionieren nach einem Neuladen,
  `/api`-Pfade bleiben JSON, die `index.html` wird nie zwischengespeichert. Fehlt der Build,
  startet die Anwendung trotzdem und protokolliert einen Hinweis.
* **Kommandozeile** für alles am Host: `server`, `schema`, `seed`, `backup`, `pruefen`,
  `nutzer-anlegen`, `nutzer-deaktivieren`, `nutzer-liste`, `passwort-setzen`, `openapi`,
  `berechtigungen-doku`. Konten legt bis auf Weiteres die Kommandozeile an – ohne sie wären die
  drei Rollen aus PLAN §4 nicht vergebbar, und der Leitstand hätte genau einen Nutzer. Das fiel
  erst bei der Abnahme auf.
* **Deploy-Unterlagen**: Caddyfile mit interner Zertifizierungsstelle, systemd-Unit,
  NSSM-Anleitung für Windows samt dem Hinweis, dass ein Dienst unter `LocalSystem` das OneDrive
  des angemeldeten Nutzers nicht erreicht.

### Oberfläche

* Designsystem aus `design/` umgesetzt: Tokens unverändert übernommen, Markenschriften selbst
  ausgeliefert statt über Google Fonts, alle Komponenten nach den Rezepten.
* Anmeldeseite in Navy mit dem Zeichen 3, Startseite mit Datenstand, Passwortwechsel.
* Menüpunkte ohne Berechtigung werden ausgeblendet, nicht ausgegraut.
* Deutsche Zahlenformate mit geschütztem Leerzeichen vor der Einheit und Minuszeichen statt
  Bindestrich.
* TypeScript-Client aus der OpenAPI-Spezifikation erzeugt; ein Test hält die Spezifikation
  aktuell.
* Komponentengalerie unter `/entwurf/komponenten`, nur im Entwicklungsmodus.

### Bemerkenswerte Funde beim Bau

Vier Fehler, die ohne die zugehörigen Tests unbemerkt geblieben wären, und eine Lücke, die erst
die Abnahme zeigte:

* Alembic ruft `fileConfig()` auf, was standardmäßig **alle bestehenden Logger deaktiviert**.
  Nach einer Migration aus dem laufenden Programm protokollierte die Anwendung nichts mehr –
  ein stiller Ausfall genau der Protokollierung, die PLAN §2 verlangt.
* Der Struktur-Regressionstest für Berechtigungen fand in seiner ersten Fassung **gar keine
  Routen**: FastAPI hängt eingebundene Router nicht flach in `app.routes` ein. Der Test wäre
  wirkungslos gewesen, ohne fehlzuschlagen. Er sichert sich jetzt selbst ab.
* Die Routen lasen die globale Konfiguration statt der, mit der die Anwendung erzeugt wurde –
  eine Instanz mit abweichender Konfiguration hätte gegen falsche Werte gearbeitet.
* Die Integritätsprüfung einer Sicherung brach bei einer stark beschädigten Datei mit einer
  Ausnahme ab, statt „nicht in Ordnung" zu melden.
* Bei der Abnahme zeigte sich, dass es **keinen Weg gab, einen zweiten Nutzer anzulegen**. Der
  Seed erzeugt einen Administrator, alles Weitere sollte die Nutzerverwaltung übernehmen – die
  erst später kommt. Damit wären die drei Rollen aus PLAN §4 in Phase 0 nicht vergebbar
  gewesen. Nachgezogen als `nutzer-anlegen` und `nutzer-deaktivieren`.

### Offen

Fehlende Zulieferungen und Rückfragen stehen in `docs/OFFENE-PUNKTE.md`. Für den Betrieb
gebraucht werden zuerst: Firmenstammdaten für den Rechnungskopf, Backup-Zielpfad, Host und
Dienstkonto. Für Phase 1 die zwei Excel-Bestandsdateien.

Tests: 393 im Backend, 52 im Frontend.
