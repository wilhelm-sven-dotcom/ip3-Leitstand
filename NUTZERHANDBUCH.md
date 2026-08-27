# Nutzerhandbuch ip³ Leitstand

Kurzanleitung je Rolle. Wird mit jeder Phase erweitert. Stand: Phase 1.

Vorhanden sind Anmeldung, Startseite mit Datenstand, Passwortwechsel, die Übernahme der
Bestandsdaten und die Masken für Kunden, Projekte, Termine und Zahlungsplan. Fakturierung,
Umsatzübersicht und Nachkalkulation folgen mit den Phasen 2 bis 6.

## Anmelden

1. Die Adresse des Leitstands im Browser öffnen (steht im Runbook, Abschnitt 1). Am besten als
   Lesezeichen ablegen.
2. E-Mail-Adresse und Passwort eingeben.
3. Beim ersten Anmelden verlangt der Leitstand ein neues Passwort. Das ist Absicht: das
   bisherige wurde am Rechner vergeben und ist nur für diese erste Anmeldung gedacht.

**„Angemeldet bleiben"** hält die Anmeldung 30 Tage statt 12 Stunden. Nur an Rechnern
verwenden, zu denen niemand sonst Zugang hat.

**Nach mehreren Fehlversuchen** ist die Kennung 15 Minuten gesperrt. Die Sperre läuft von
selbst ab – ein Neustart des Browsers hilft nicht und ist auch nicht nötig. In dieser Zeit
wird auch das richtige Passwort abgelehnt.

**Passwort vergessen:** an Sven Wilhelm oder Michael Bäumler wenden. Dort lässt es sich am
Host zurücksetzen; ein Versand per E-Mail gibt es im Leitstand nicht.

## Passwort ändern

Ein gutes Passwort ist ein Satz aus mehreren Wörtern – leichter zu merken und sicherer als ein
kurzes mit Sonderzeichen. Mindestens zwölf Zeichen.

Nach dem Wechsel werden alle **anderen** Anmeldungen beendet: wer das alte Passwort kannte,
kommt über eine offene Sitzung nicht weiter. Die eigene Sitzung bleibt bestehen.

## Startseite

Die Startseite ist der Arbeitsvorrat: was heute zu tun ist. Die Kennzahlen und
Rechnungsvorschläge kommen mit den Phasen 2 und 3; bis dahin führen die Menüpunkte Projekte und
Stammdaten zu den Daten.

Unten steht der **Datenstand**: wann die nächtliche Sicherung zuletzt lief und welche
Datenquellen noch nicht eingerichtet sind. Ein roter Punkt bedeutet, dass ein Hintergrundlauf
nicht funktioniert hat. Dann bitte Sven Bescheid geben – der Leitstand arbeitet weiter, aber
die Sicherung ist dann nicht auf dem aktuellen Stand.

## Projekte

**Menü → Projekte.** Die Liste zeigt alle Projekte, die neuesten zuerst, und blättert in Schritten
von 25. Über der Tabelle stehen die Filter: Jahr, Status, Projektleiter und Gewerk. Das Suchfeld
sucht in Projektnummer, Kunde, Ort und Bezeichnung – **Umlaute spielen keine Rolle**, „poellath"
findet Pöllath und „vohenstrauss" Vohenstrauß.

Die Kopfzeile zählt mit: „100 Projekte im Jahr 2026 · Auftragsvolumen 4,9 Mio. €". Die Zahlen
beziehen sich immer auf die eingestellten Filter.

Ein Klick auf eine Zeile öffnet das Projekt. Dort gibt es vier Reiter:

* **Übersicht** – Anlagendaten und die Termine. Bei den übernommenen Projekten steht unter
  „Herkunft", aus welcher Zeile welcher Datei sie stammen.
* **Zahlungsplan & Rechnungen** – die geplanten Abschläge und die Schlussrechnung.
* **Nachkalkulation** und **Dokumente & Fristen** kommen mit den Phasen 4 und 6. Die Reiter sind
  sichtbar, damit erkennbar bleibt, was noch fehlt.

### Termine

Im Reiter Übersicht, Abschnitt **Termine**. Je Schritt drei Zustände:

| Zustand | Bedeutung |
|---|---|
| keine Angabe | Über den Schritt ist nichts bekannt. So kommen die übernommenen Projekte aus der Teamliste, wo eine leere Zelle keine Aussage ist. |
| offen | Der Schritt ist ausdrücklich noch nicht erledigt. |
| erledigt | Mit Datum, wo eines bekannt ist. Die Teamliste kreuzte nur an, ohne Datum – dort bleibt das Feld leer, weil ein erfundenes Datum eine Falschangabe wäre. |

Ein eingetragenes Datum setzt den Schritt automatisch auf „erledigt". Gespeichert wird der ganze
Abschnitt mit **einem** Klick auf „Termine speichern"; im Änderungsprotokoll steht dann ein
Eintrag für den Vorgang und nicht zehn.

### Zahlungsplan

Aus jeder Position entsteht ab Phase 3 eine Rechnung. Die Summenzeile vergleicht laufend mit dem
Auftragswert plus den **beauftragten** Nachträgen. Passt es nicht zusammen, steht dort ein
Hinweis – kein Fehler: bei den übernommenen Altprojekten führt die Auftragsliste nur die offenen
Positionen, der in früheren Jahren berechnete Teil fehlt.

Ein **Schloss** an einer Position heißt: nicht änderbar. Zwei Gründe, zwei Wege:

* **„Gestellt" aus dem Altbestand.** Die Rechnung wurde vor der Einführung des Leitstands
  gestellt; es gibt keinen Beleg, den man stornieren könnte. Der Betrag zählt zum Umsatz eines
  vergangenen Monats. Wer korrigieren muss, nimmt zuerst das Kennzeichen „gestellt" zurück –
  ein eigener Knopf mit Rückfrage. Beides steht im Änderungsprotokoll.
* **Berechnet.** Zu der Position gehört ein festgeschriebener Beleg. Änderungen laufen über den
  Storno (ab Phase 3).

**Nachträge** stehen darunter. Erst ab dem Status „beauftragt" zählen sie zum Soll des
Zahlungsplans – ein Angebot ist kein Auftrag. Eine entfallene Leistung wird als negativer Betrag
erfasst.

### Projektleiter zuordnen

**Projekte → Projektleiter zuordnen** (nur mit Schreibrecht). Die Teamliste führt Vornamen, der
Leitstand braucht Konten. Hier wird je Name ein Konto gewählt; die Zuordnung wirkt auf alle
Projekte dieses Namens. Der Name bleibt stehen – er ist der Nachweis, woher die Angabe kommt.

## Stammdaten

**Menü → Stammdaten.** Kunden mit Ansprechpartnern. Gesucht wird wie in der Projektliste, Umlaute
egal. Kunden werden **nicht gelöscht**, sondern auf „inaktiv" gesetzt: an ihnen hängen Projekte
und später Rechnungen. Ansprechpartner dürfen entfernt werden.

Die Kundennummer vergibt der Leitstand fortlaufend ab 10001.

## Bestandsdaten übernehmen

**Menü → Importe & Daten.** Einmaliger Vorgang, in der Regel von der Geschäftsführung. Der Ablauf
steht im [RUNBOOK](RUNBOOK.md), Abschnitt 9. Kurz: Kontrollsummen lesen, offene Zuordnungen
entscheiden, übernehmen. Danach ist der Leitstand führend und die Excel-Dateien werden
schreibgeschützt.

## Abmelden

Über „Abmelden" unten links in der Seitenleiste. An gemeinsam genutzten Rechnern immer
abmelden, nicht nur das Fenster schließen.

## Rollen

| Rolle | Wer | Was sie darf |
|---|---|---|
| admin | Sven Wilhelm, Michael Bäumler | alles: Konfiguration, Fixkosten, Nutzerverwaltung, Stornofreigabe, Hintergrundläufe |
| buchhaltung | Buchhaltungskraft | Kunden, Projekte und Zahlungsplan pflegen, Rechnungen erstellen und festschreiben, Importe ausführen |
| team | übrige Mitarbeiter | lesender Zugriff auf Projekte, Termine und Anlagen – ohne Beträge, ohne Nachkalkulation, ohne Firmen-Cockpit |

Was eine Rolle nicht darf, ist gar nicht sichtbar: der Menüpunkt fehlt, die Schaltfläche
erscheint nicht. Ausgegraute Elemente gibt es nicht. Wer etwas braucht, das er nicht sieht,
wendet sich an die Geschäftsführung.

Der Berechtigungskatalog steht in [docs/BERECHTIGUNGEN.md](docs/BERECHTIGUNGEN.md).

**Für die Geschäftsführung:** Konten werden bis auf Weiteres am Host über die Kommandozeile
angelegt und gesperrt – eine Nutzerverwaltung in der Oberfläche kommt später. Die Befehle
stehen im [RUNBOOK](RUNBOOK.md), Abschnitte 2 und 8. Ein ausgeschiedener Mitarbeiter wird
deaktiviert, nicht gelöscht: seine Einträge im Änderungsprotokoll müssen zuordenbar bleiben.

## Wenn etwas nicht funktioniert

Der Leitstand sagt bei jedem Fehler, was passiert ist und was zu tun ist. Bei einem
unerwarteten Fehler nennt er eine **Vorgangsnummer** – diese Nummer bitte weitergeben, damit
sich der Eintrag im Protokoll finden lässt.

Zwei Meldungen, die keine Störung sind:

* **„Der Datensatz wurde zwischenzeitlich von jemand anderem geändert."** Zwei Personen haben
  denselben Datensatz bearbeitet. Der Leitstand verwirft die eigene Eingabe lieber, als die
  Änderung des anderen stillschweigend zu überschreiben. Seite neu laden und erneut eingeben.
* **„Der Beleg ist festgeschrieben und kann nicht mehr geändert werden."** Ab Phase 3: so
  verlangen es die GoBD. Korrekturen laufen über einen Storno oder eine Gutschrift.
* **„Diese Position ist im Altbestand als gestellt gekennzeichnet."** Siehe Zahlungsplan oben:
  zuerst das Kennzeichen zurücknehmen, dann ist die Position frei.
