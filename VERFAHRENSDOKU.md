# Verfahrensdokumentation ip³ Leitstand

Grundgerüst nach den Grundsätzen zur ordnungsmäßigen Führung und Aufbewahrung von Büchern,
Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff (GoBD).

> **Status: Entwurf, Phase 0.** Die Abschnitte werden mit den Phasen gefüllt, in denen die
> beschriebenen Funktionen entstehen. Die Abstimmung mit dem Steuerberater steht aus
> (PLAN §13.4) – ohne diese Abstimmung ist das Dokument nicht abgeschlossen.

## 1. Unternehmen und Zweck des Verfahrens

ip³ Energietechnik GmbH, Theisseil. Planung, Bau und Installation von Photovoltaikanlagen und
Batteriespeichern. Der ip³ Leitstand führt Projekte, Zahlungspläne und Ausgangsrechnungen, erstellt
Auftragsbestätigungen und Rechnungen und wertet Kosten je Projekt aus. Die Finanzbuchhaltung selbst
findet weiterhin bei der Steuerberatungskanzlei statt; der Leitstand ist vorgelagertes System für
Ausgangsrechnungen und Steuerungsrechnung.

## 2. Beteiligte und Verantwortlichkeiten

| Rolle | Person | Verantwortung |
|---|---|---|
| Verfahrensverantwortung | Sven Wilhelm (Geschäftsführung) | Konfiguration, Nutzerverwaltung, Freigabe von Stornos, Prüfung der Datensicherung |
| Fachliche Nutzung | Buchhaltungskraft | Erstellung und Festschreibung von Belegen, Importe |
| Technischer Betrieb | Sven Wilhelm | Host, Dienste, Updates über die Testinstanz, Restore |

## 3. Systemüberblick

Ein Rechner im Büro betreibt Anwendung und Datenbank (SQLite, lokal). Der Zugriff erfolgt im
Firmennetz über den Browser, verschlüsselt über einen vorgeschalteten Reverse Proxy. Erzeugte
Rechnungen liegen als PDF und, bei inländischen Geschäftskunden, als PDF/A-3 mit eingebettetem
XML im OneDrive-Ordner `01_Rechnungen`, der zugleich Quelle für den Upload zur Kanzlei ist.
Technische Einzelheiten: PLAN §2, Betriebsabläufe: RUNBOOK.

## 4. Zugriffsschutz

Anmeldung mit persönlicher Kennung (E-Mail-Adresse) und Passwort. Passwörter werden nur als
bcrypt-Hash gespeichert, Sitzungsschlüssel nur als SHA-256-Hash – eine Sicherungskopie der
Datenbank enthält damit keine verwendbaren Zugangsdaten.

Sitzungen laufen serverseitig und werden über ein `httpOnly`-Cookie mit `SameSite=Lax` geführt.
Sie enden nach zwölf Stunden, mit „Angemeldet bleiben" nach 30 Tagen, zusätzlich nach acht
Stunden ohne Aktivität. Alle schreibenden Anfragen tragen ein sitzungsgebundenes Token
(CSRF-Schutz); zusätzlich wird die Herkunft der Anfrage geprüft.

Berechtigungen sind Schlüssel nach dem Muster `ressource.aktion` und werden ausschließlich
serverseitig geprüft; die Oberfläche blendet zusätzlich aus. Ein automatischer Test verlangt für
jede schreibende Schnittstelle eine solche Prüfung. Die Zuordnung von Rollen zu Berechtigungen
steht in `docs/BERECHTIGUNGEN.md` und wird aus dem Programmcode erzeugt.

Nach fünf Fehlanmeldungen wird die Kennung 15 Minuten gesperrt; während der Sperre wird auch ein
richtiges Passwort abgelehnt. Zusätzlich wird die Absenderadresse gedrosselt. Alle Fehlversuche
stehen im Änderungsprotokoll.

Nutzer werden nie gelöscht, nur deaktiviert. Ein deaktivierter Nutzer verliert seine Sitzung
sofort, und die Verweise im Änderungsprotokoll bleiben auflösbar.

## 5. Belegfluss und Unveränderbarkeit

Die Belegverarbeitung ist seit Phase 3 (Version 0.4.0) in Betrieb. Die **technische Absicherung
der Unveränderbarkeit steht seit Phase 0**, damit sie nicht nachträglich aufgesetzt werden musste:

Datenbank-Trigger verhindern jede Änderung und jedes Löschen an einem Beleg mit dem Status
`festgeschrieben` – auch durch ein Importskript oder einen direkten Zugriff mit einem
Datenbankwerkzeug, nicht nur durch die Anwendung. Erlaubt ist ausschließlich der Statuswechsel
auf `storniert` mit Verweis auf den Stornobeleg; ein weiterer Trigger stellt sicher, dass dabei
Nummer, Beträge, Datum, Hash und Kundenstand unverändert bleiben. Ebenso gesperrt sind
Rechnungspositionen festgeschriebener Belege und Zahlungsplanpositionen, die einem Beleg
zugeordnet sind.

**Ablauf einer Rechnung.** Der Entwurf ist beliebig änderbar und trägt **keine** Nummer. Die
Festschreibung ist ein einziger, unumkehrbarer Vorgang und läuft in dieser Reihenfolge:

1. Prüfung der Pflichtangaben nach § 14 UStG (Firmenstammdaten, Anschrift des Empfängers,
   Leistungszeitraum, mindestens eine Position, Steuersatz passend zum Kennzeichen). Fehlt etwas,
   wird der Beleg abgewiesen und **alles** Fehlende genannt – nach der Festschreibung wäre jede
   Nachbesserung ein Stornobeleg.
2. Vergabe der Rechnungsnummer aus dem Nummernkreis des Belegjahres.
3. Berechnung der Summen und der Umsatzsteuer je Steuersatz auf die Nettosumme des Belegs.
4. Erzeugung von PDF und – bei Geschäftskunden – des EN-16931-XML im Arbeitsspeicher.
5. Ein einziger Schreibvorgang mit Nummer, Summen, Steueraufteilung, Kundenstand, Ablagepfaden,
   SHA-256-Hash über die Belegdaten und Zeitstempel; damit wechselt der Status auf
   `festgeschrieben`, und der Trigger sperrt jede weitere Änderung.
6. Ablage von PDF und XML im Rechnungsordner, nach dem Commit.

Scheitert Schritt 4, rollt die Nummer mit zurück – es entsteht keine Lücke. Scheitert Schritt 6,
ist der Beleg gültig und die Ablage fehlt; sie lässt sich nachholen, weil der Hash die Belegdaten
abdeckt und nicht die Bytes der PDF-Datei. Dasselbe Dokument entsteht aus denselben Daten erneut.

**Der Kundenstand wird als Kopie mitgeschrieben** (`kunde_snapshot`). Eine spätere Adressänderung
beim Kunden verändert einen ausgestellten Beleg nicht; § 14 UStG verlangt die Angaben zum
Ausstellungszeitpunkt.

**Der Absetzungsblock der Schlussrechnung** (§ 14 Abs. 5 UStG) wird beim Erzeugen des Belegs
gespeichert, nicht beim Anzeigen abgeleitet: ein später entstehender Abschlag darf eine
festgeschriebene Schlussrechnung nicht rückwirkend verändern. Er ist Teil des Belegs und
denselben Sperren unterworfen.

Korrekturen erfolgen ausschließlich über Stornobeleg oder Gutschrift mit Verweis auf den
Ursprungsbeleg und Neuausstellung. Der Storno ist ein eigener Beleg mit eigener Nummer und
Negativbeträgen; das Original behält Nummer und Beträge und wechselt auf `storniert`.

Rechnungsnummern sind je Nummernkreis lückenlos und fortlaufend. Die Vergabe läuft in derselben
Transaktion wie die Festschreibung des Belegs – eine vorab geholte und dann nicht verwendete
Nummer wäre eine Lücke. Ein automatischer Test lässt zehn gleichzeitige Vorgänge Nummern ziehen
und prüft, dass keine doppelt und keine übersprungen wird.

## 6. Protokollierung

Jede schreibende Aktion wird im Änderungsprotokoll (`audit_log`) mit Zeitpunkt (UTC), Nutzer,
Aktion, betroffenem Datensatz sowie Alt- und Neuwerten festgehalten. Ein Filter entfernt vor dem
Schreiben alle Felder, deren Bezeichnung auf ein Geheimnis hindeutet (Passwort, Hash, Token) –
auch in verschachtelten Strukturen. Das ist keine Vorsichtsmaßnahme am Rand: die Datenbank samt
Protokoll liegt nach jeder Nacht als Sicherungskopie im OneDrive-Ordner.

Der Protokolleintrag entsteht in derselben Transaktion wie die Änderung. Scheitert die Änderung,
verschwindet auch der Eintrag – ein Protokoll über einen Vorgang, der nie stattgefunden hat,
wäre schlimmer als kein Eintrag.

Die Anwendung schreibt das Protokoll ausschließlich; es gibt keinen Programmpfad, der einen
Eintrag ändert oder löscht. Ein automatischer Test prüft das.

Zusätzlich hält die Anwendung jeden Lauf eines Hintergrundjobs (`job_laeufe`) mit Beginn, Ende,
Ergebnis und Meldung fest. Die Startseite zeigt daraus den Datenstand, damit ein ausgefallener
nächtlicher Lauf auffällt.

## 6a. Externe Datenquellen (ab Phase 4)

Der Leitstand liest fünf externe Quellen. **Er schreibt in keine von ihnen zurück** – weder in
die DATEV-Exporte, noch in TimeTac, noch in die Kalkulationsblätter. Sie bleiben in der Hand
ihrer jeweiligen Herkunft; der Leitstand nimmt Kopien ihrer Werte in die eigene Datenbank auf.

| Quelle | Herkunft | Was übernommen wird |
|---|---|---|
| Kostenträgerauswertung | Steuerkanzlei, monatlich in `02_DATEV` | Einzelbuchungen mit KOST2 = Projektnummer, verdichtet auf Projekt, Monat und Konto |
| TimeTac | REST-Schnittstelle v3 bzw. Berichtsexport | Arbeitsstunden je Projekt, Monat und Mitarbeiter |
| Kalkulationsblatt | Projektleitung, in `03_Kalkulation` | Sollwerte und Stückliste je Projekt |
| Summen- und Saldenliste | Steuerkanzlei, monatlich in `02_DATEV` | Saldo je Sachkonto und Monat, einem Kostenblock zugeordnet |
| Offene Posten Debitoren | Steuerkanzlei, monatlich in `02_DATEV` | Restbetrag je Rechnungsnummer zu einem Stichtag |

**Jeder Lauf ist protokolliert.** Neben dem Joblauf (`job_laeufe`) entsteht je Import ein
Eintrag in `importlaeufe` mit Quelle, Datei, Zeitraum, Kontrollsummen, Einzelbuchungen und allen
Werten, die sich nicht deuten ließen. Damit ist jede Zahl im Ist bis in die Quelldatei
zurückverfolgbar.

**Jeder Lauf ersetzt seinen Zeitraum, statt anzuhängen.** Wird ein Monat nachgeliefert oder
korrigiert, wird er einfach erneut eingelesen; das Löschen des alten Standes und das Einfügen des
neuen stehen in derselben Transaktion. Ein abgebrochener Lauf lässt den vorigen Stand stehen.
Eine Eindeutigkeitsbedingung auf `ist_kosten` fängt den Fall ab, dass ein künftiger Importweg das
Löschen vergisst – doppelte Beträge fielen in einer Auswertung sonst nicht auf.

**Der Zahlungsstatus wird nicht abgeleitet, sondern gelesen.** Ob eine Ausgangsrechnung bezahlt
ist, sagt ausschließlich der OPOS-Import (PLAN §6.7). Der Leitstand hat keinen Zugriff auf
Kontoauszüge und stellt keine Vermutungen an: eine Rechnung, die jünger ist als der jüngste
OPOS-Stichtag, trägt den Status „ohne Stand" und nicht „bezahlt". Ein Restbetrag innerhalb der
konfigurierten Skonto-Toleranz gilt als „bezahlt mit Abzug" (PLAN §6.13); die Toleranz steht in
der `config.toml` und ist damit nachvollziehbar dokumentiert.

**Das Firmen-Cockpit ist eine Steuerungssicht, keine handelsrechtliche Auswertung.** Es
vermischt bewusst Buchhaltungswerte (Summen- und Saldenliste), Auftragswerte, kalkulatorische
Verrechnungssätze und Planzahlen. Es ersetzt keine BWA und wird nicht als solche verwendet; der
Hinweis steht auf der Ansicht selbst und wird von der Schnittstelle mitgeliefert. Die
kalkulatorische Eigenleistung aus TimeTac wird auf Firmenebene neutralisiert, damit die echten
Personalkosten aus der Buchhaltung nicht doppelt zählen (PLAN §6.6).

**Zugangsdaten** zu TimeTac liegen ausschließlich in der Umgebung des Dienstkontos auf dem Host
(`.env`), nie in der Konfigurationsdatei und nie im Quelltext. Zugangstoken werden im Speicher
gehalten und erscheinen weder im Protokoll noch im Änderungsprotokoll.

**Zweckbindung der Arbeitsstunden:** Die aus TimeTac übernommenen Stunden dienen ausschließlich
der Kostenrechnung je Projekt, nicht der Leistungskontrolle einzelner Beschäftigter. Sie werden
je Projekt und Monat verdichtet ausgewertet; die Mitarbeiterangabe bleibt nur zur Zuordnung des
Verrechnungssatzes erhalten.

## 7. Datensicherung und Wiederherstellung

Nächtlich erstellt die Anwendung eine in sich geschlossene Kopie der Datenbank im
OneDrive-Backup-Ordner und hält 30 Generationen vor. Erfolg und Fehler jedes Laufs stehen in der
Datenbank und auf der Startseite („Datenstand"), damit ein ausgefallener Lauf auffällt. Der
Wiederherstellungsweg ist im RUNBOOK Schritt für Schritt beschrieben und wird mindestens einmal
je Phase geprobt; das Ergebnis der Probe wird hier mit Datum vermerkt.

| Datum | Art | Ergebnis | Durchgeführt von |
|---|---|---|---|
| 27.08.2026 | Rückspielung nach RUNBOOK Abschnitt 7, auf einer Prüfinstanz mit Demodaten | Erfolgreich. Integritätsprüfung ohne Befund, Schemastand passend, Anmeldung mit dem Passwortstand von vor der Sicherung möglich. Ein nach der Sicherung angelegtes Konto war erwartungsgemäß nicht mehr vorhanden; die beiseitegelegte Datenbank blieb erhalten. | Phase-0-Abnahme (Entwicklung) |
| _nächste Probe nach der Installation auf dem Bürorechner_ | | | |

## 8. Aufbewahrung

Ausgangsrechnungen liegen als PDF (bei Geschäftskunden mit eingebettetem XML) im OneDrive und
unterliegen der zehnjährigen Aufbewahrungsfrist. Die Datenbank hält die zugehörigen Belegdaten
samt Hash. Eine Auslagerung oder Löschung erfolgt nicht ohne Abstimmung mit dem Steuerberater.

## 9. Änderungen am Verfahren

Änderungen an der Anwendung werden versioniert (`CHANGELOG.md`) und zuerst auf der Testinstanz
geprüft. Änderungen, die Belegerstellung, Nummernvergabe, Steuerausweis oder Festschreibung
betreffen, werden hier vermerkt.

| Datum | Version | Änderung | Auswirkung auf die Buchführung |
|---|---|---|---|
| 27.08.2026 | 0.4.0 | **Fakturierung im Leitstand** (Phase 3) und **Wechsel des Rechnungsnummernkreises**. Bis zur Einführung liefen die Rechnungen als Word-Dokumente im Kreis `PV-ET JJ-NNNN`, zuletzt `PV-ET 25-1713`. Ab dem Stichtag vergibt der Leitstand die Nummern selbst, in den neuen Kreisen `RE-JJJJ-NNNN` (Projektrechnungen), `SR-JJJJ-NNNN` (Servicerechnungen) und `AB-JJJJ-NNNN` (Auftragsbestätigungen), je Jahr bei 1 beginnend. | Der alte Kreis wird nicht fortgeschrieben und endet mit der letzten von Hand geschriebenen Rechnung; die neuen Kreise beginnen lückenlos bei 1. Beide Nummernfolgen sind in sich vollständig und voneinander unterscheidbar. Der Grund für den Wechsel ist die maschinelle Vergabe: die Zählweise des alten Kreises ist aus den Dokumenten nicht eindeutig rekonstruierbar, eine Fortschreibung hätte das Risiko einer doppelt vergebenen Nummer getragen. Die Dokumente des alten Kreises bleiben in der bisherigen Ablage aufbewahrungspflichtig. |
| 27.08.2026 | 0.4.0 | **Keine Schlussrechnung für Projekte mit Abschlägen aus dem Altbestand.** Zu den 150 Positionen, die die Auftragsliste als „gestellt" führte, sind Rechnungsnummer, Rechnungsdatum und Steuersatz im Leitstand nicht bekannt. | § 14 Abs. 5 UStG verlangt, dass eine Schlussrechnung alle vorher berechneten Abschläge einzeln mit Netto und darauf entfallender Umsatzsteuer absetzt. Da diese Angaben fehlen, wäre der Absetzungsblock unvollständig und der Steuerausweis unrichtig (§ 14c UStG). Der Leitstand verweigert die Erzeugung deshalb und nennt den Grund; die betroffenen 28 laufenden Projekte werden ein letztes Mal außerhalb abgerechnet. Abschlagsrechnungen sind dort weiter möglich, weil ein Abschlag keinen Absetzungsblock trägt. |
| 27.08.2026 | 0.2.0 | **Übernahme der Bestandsdaten** (Phase 1). Kunden, Projekte, Termine und Zahlungsplan aus den beiden bisher geführten Excel-Dateien. Stichtag der Übernahme ist der Tag des Laufs; ab dann ist der Leitstand die führende Aufzeichnung, die Excel-Dateien werden schreibgeschützt aufbewahrt. | Keine Belege betroffen: die Übernahme schreibt **keine** Rechnungen. Die 150 Positionen, die die Auftragsliste als „gestellt" führte, werden als solche gekennzeichnet, aber ohne Beleg im Leitstand – die zugehörigen Rechnungen wurden vor der Einführung außerhalb erstellt und liegen als Ausgangsrechnungen der bisherigen Ablage vor. Ihr Betrag ist im Leitstand unveränderbar (Datenbank-Trigger); eine Korrektur verlangt die ausdrückliche Rücknahme des Kennzeichens und steht im Änderungsprotokoll. |

### Stichtag und Nachvollziehbarkeit der Übernahme

Jeder übernommene Datensatz trägt in `quelle_migration` Datei und Zeile seiner Herkunft. Der Lauf
selbst steht in `importlaeufe` mit Zeitpunkt, Dateinamen, Kontrollsummen und allen Befunden – auch
denen, die auf Fehler in den Quelldateien hinweisen (drei falsche Summenformeln, siehe
`docs/OFFENE-PUNKTE.md`). Ein zweiter Lauf ist ausgeschlossen; die Prüfung sitzt in der Anwendung
und wird durch das Importprotokoll belegt.

Was **nicht** übernommen wurde, weil es in den Quelldateien nicht steht: Rechnungsnummern,
Rechnungsdaten, Zahlungseingänge. Der Umsatz-Ist vergangener Monate ergibt sich für die Zeit vor
dem Stichtag deshalb weiter aus der Buchhaltung und nicht aus dem Leitstand.
