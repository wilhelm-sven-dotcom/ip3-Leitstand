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

Anmeldung mit persönlicher Kennung und Passwort; Passwörter werden nur als bcrypt-Hash gespeichert.
Sitzungen laufen serverseitig und werden über ein `httpOnly`-Cookie geführt. Berechtigungen sind
Schlüssel nach dem Muster `ressource.aktion` und werden ausschließlich serverseitig geprüft. Nach
mehreren Fehlanmeldungen wird die Kennung zeitweise gesperrt. Nutzer werden nie gelöscht, nur
deaktiviert, damit die Nachvollziehbarkeit der Protokolleinträge erhalten bleibt.

## 5. Belegfluss und Unveränderbarkeit

_wird in Phase 3 gefüllt (Fakturierung)._ Vorgesehen: Entwurf beliebig änderbar, danach
Festschreibung mit Vergabe der Rechnungsnummer, Zeitstempel und SHA-256-Hash über die Belegdaten;
ab diesem Zeitpunkt ist der Beleg unveränderbar – technisch durch Datenbank-Trigger abgesichert.
Korrekturen erfolgen ausschließlich über Stornobeleg oder Gutschrift mit Verweis auf den
Ursprungsbeleg und Neuausstellung. Rechnungsnummern sind je Nummernkreis lückenlos und fortlaufend.

## 6. Protokollierung

Jede schreibende Aktion wird im Änderungsprotokoll (`audit_log`) mit Zeitpunkt (UTC), Nutzer,
Aktion, betroffenem Datensatz sowie Alt- und Neuwerten festgehalten. Passwörter, Hashes und
Sitzungsschlüssel werden dabei nicht protokolliert. Das Protokoll wird von der Anwendung nur
geschrieben, nie geändert oder gelöscht.

## 7. Datensicherung und Wiederherstellung

Nächtlich erstellt die Anwendung eine in sich geschlossene Kopie der Datenbank im
OneDrive-Backup-Ordner und hält 30 Generationen vor. Erfolg und Fehler jedes Laufs stehen in der
Datenbank und auf der Startseite („Datenstand"), damit ein ausgefallener Lauf auffällt. Der
Wiederherstellungsweg ist im RUNBOOK Schritt für Schritt beschrieben und wird mindestens einmal
je Phase geprobt; das Ergebnis der Probe wird hier mit Datum vermerkt.

| Datum | Art | Ergebnis | Durchgeführt von |
|---|---|---|---|
| _wird bei der ersten Probe gefüllt_ | | | |

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
