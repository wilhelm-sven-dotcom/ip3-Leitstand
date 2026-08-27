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

Die Belegverarbeitung entsteht in Phase 3. Die **technische Absicherung der Unveränderbarkeit
steht seit Phase 0**, damit sie nicht nachträglich aufgesetzt werden muss:

Datenbank-Trigger verhindern jede Änderung und jedes Löschen an einem Beleg mit dem Status
`festgeschrieben` – auch durch ein Importskript oder einen direkten Zugriff mit einem
Datenbankwerkzeug, nicht nur durch die Anwendung. Erlaubt ist ausschließlich der Statuswechsel
auf `storniert` mit Verweis auf den Stornobeleg; ein weiterer Trigger stellt sicher, dass dabei
Nummer, Beträge, Datum, Hash und Kundenstand unverändert bleiben. Ebenso gesperrt sind
Rechnungspositionen festgeschriebener Belege und Zahlungsplanpositionen, die einem Beleg
zugeordnet sind.

Vorgesehener Ablauf ab Phase 3: Entwurf beliebig änderbar, danach Festschreibung mit Vergabe der
Rechnungsnummer, Zeitstempel und SHA-256-Hash über die Belegdaten. Korrekturen erfolgen
ausschließlich über Stornobeleg oder Gutschrift mit Verweis auf den Ursprungsbeleg und
Neuausstellung.

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
| _wird ab Phase 3 gefüllt_ | | | |
