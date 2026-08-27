# Nutzerhandbuch ip³ Leitstand

Kurzanleitung je Rolle. Wird mit jeder Phase erweitert. Stand: Phase 0.

In Phase 0 gibt es Anmeldung, Startseite mit Datenstand und den Passwortwechsel. Projekte,
Fakturierung und Auswertungen folgen mit den Phasen 1 bis 6.

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

Die Startseite ist der Arbeitsvorrat: was heute zu tun ist. In Phase 0 ist er noch leer, weil
die Projektdaten erst übernommen werden.

Unten steht der **Datenstand**: wann die nächtliche Sicherung zuletzt lief und welche
Datenquellen noch nicht eingerichtet sind. Ein roter Punkt bedeutet, dass ein Hintergrundlauf
nicht funktioniert hat. Dann bitte Sven Bescheid geben – der Leitstand arbeitet weiter, aber
die Sicherung ist dann nicht auf dem aktuellen Stand.

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
