# Umsetzung des Designsystems

Dieser Ordner ist die **Vorlage** aus Claude Design und wird nicht in die Anwendung importiert.
Die Mockups (`*.dc.html`) sind mit Inline-Styles gebaut und brauchen `support.js` nur für die
Browservorschau. Umgesetzt wird sie in `frontend/` – dort liegt der Code, hier bleibt die Referenz.

Mockups zum Ansehen einfach im Browser öffnen.

## Was wohin wandert

| Vorlage | Ziel in der Anwendung |
|---|---|
| `ip3-tokens.css` | `frontend/src/styles/tokens.css` – Werte unverändert, nur Kommentare ergänzt |
| `Komponenten.dc.html` | `frontend/src/komponenten/*` – eine Komponente je Rezept |
| `Login.dc.html` | `frontend/src/seiten/Anmelden.tsx` |
| `Start.dc.html` | `frontend/src/seiten/Start.tsx` und `AppShell` |
| `Projektliste`, `Projektdetail`, `Festschreiben`, `Firmen-Cockpit` | Phasen 1 bis 5 |
| `brand/` | Assets kommen aus `assets/cd/` (vollständiger Bestand inklusive Schriften) |
| `support.js` | wird nicht übernommen und nie importiert |

## Bewusste Abweichungen

1. **Schriften selbst ausliefern.** Die Mockups laden Libre Franklin und Space Grotesk über Google
   Fonts. Die Anwendung läuft im Firmennetz ohne verlässlichen Internetzugang und soll keine
   externen Abrufe auslösen: Einbindung per `@font-face` aus `assets/cd/fonts/`. Libre Franklin
   liegt in 400, 600, 700 und 800 vor – für das im Designsystem genannte Gewicht 500 wird 600
   gesetzt, damit der Browser nichts synthetisiert.
2. **Datenstand-Leiste auf der Startseite.** Die Mockups zeigen keinen Systemstatus, PLAN §2 und §7
   verlangen ihn („stille Job-Ausfälle darf es nicht geben"). Umsetzung als ruhige Leiste unter dem
   Inhalt: letztes Backup, letzter DATEV-Import, letzter TimeTac-Sync mit Alter. Kein Rot, solange
   alles in Ordnung ist.
3. **Startseite in Phase 0.** Kennzahlenzeile und Aktionskarten des Mockups brauchen Projekt- und
   Rechnungsdaten aus den Phasen 1 bis 3. Bis dahin zeigt die Startseite Begrüßung, Leerzustände
   mit dem nächsten Schritt und die Datenstand-Leiste. Die Komponenten selbst
   (`KpiTile`, `ActionCard`) entstehen trotzdem schon nach Vorlage und sind unter
   `/entwurf/komponenten` zu sehen (nur im Entwicklungsmodus).
4. **„Passwort vergessen?"** führt nicht zu einem Mailversand (in V1 nicht vorgesehen), sondern
   zeigt den Hinweis, sich an die Geschäftsführung zu wenden.
5. **Anmeldung per E-Mail-Adresse**, wie im Login-Mockup vorgesehen. Das Datenmodell in PLAN §5
   nennt nur `name`; die Tabelle `users` hat daher zusätzlich `email`.
6. **Menüpunkt „Stammdaten".** Das Menü der Mockups hat keinen Punkt für Kunden, PLAN §7
   verlangt für Phase 1 aber eine Maske für Kunden und Ansprechpartner. Der Punkt steht unter
   „Projekte" und ist mit `kunden.lesen` sichtbar – die Rolle `team` sieht die Liste also, das
   Formular bleibt dort aber gesperrt. Ohne eigenen Punkt wäre ein Kunde ohne Projekt gar nicht
   erreichbar.
7. **Zuordnungsmaske der Bestandsübernahme** unter „Importe & Daten". In den Mockups nicht
   vorgesehen, von PLAN §7 und §9 ausdrücklich verlangt. Umgesetzt im Duktus der Projektliste:
   Kennzahlenreihe, Tabelle, Fußzeile mit dem Fortschritt.

8. **Zweiter Badge-Satz für den Projektstatus.** `design/README.md` legt genau acht
   Statusbadges fest – die beschreiben **Belege** (Entwurf, Gestellt, Bezahlt …). Die
   Projektliste zeichnet daneben einen Projektlebenslauf (Angebot, Beauftragt, In Bau,
   Abgeschlossen, Storniert) mit eigenen Farben. Umgesetzt als eigene Komponente
   `ProjektStatusBadge` mit denselben Maßen und derselben Formsprache; der Achter-Satz bleibt
   unangetastet. „Gestellt" an einem Projekt wäre eine Aussage über eine Rechnung, die es nicht
   gibt.
9. **Zeitleiste der Meilensteine als Tabelle in drei Gruppen.** Die Mockups zeigen den Reiter
   „Übersicht" nicht. Die 19 Meilensteintypen folgen der Teamliste (PLAN §9) und sind nach
   Projektablauf, Liefer- und Montageterminen und zusammenfassenden Schritten gruppiert. Je
   Schritt drei Zustände (keine Angabe, offen, erledigt) – so, wie es Migration 0003 vorsieht.
   Erledigte Schritte stehen in ip³ Blau, nicht in Grün.
10. **Reiter für spätere Phasen bleiben sichtbar**, als `<button disabled>` mit dem Hinweis
    „ab Phase 4" bzw. „ab Phase 6" – wie die Menüpunkte in der Seitenleiste. Wer nur einen
    Reiter sieht, hält den Rest für verloren.
11. **Übergreifende Suche in der Kopfzeile (Strg K) kommt später.** Projektliste und Kundenliste
    haben je eine eigene Suche mit serverseitigem Blättern. Eine zweite, die überall gleichzeitig
    sucht, ist erst sinnvoll, wenn es mehr zu finden gibt als Projekte und Kunden – vorgesehen ab
    Phase 3 (Belege). Das Feld steht als Platzhalter mit Hinweis in der Kopfzeile.
12. **Neues Projekt als eigene Seite**, nicht im Seitenpanel: es sind mehr Felder als in einer
    Liste Platz haben, und der Kunde wird über ein Suchfeld gewählt (475 Kunden in einem
    Auswahlfeld sind unbenutzbar). Bearbeitet wird dagegen im Panel, wie bei den Kunden.

13. **Gesperrte Zahlungsplanpositionen sind von Anfang an als gesperrt gezeichnet.** Die
    Schnittstelle liefert je Position einen `sperrgrund`; steht dort etwas, trägt die Zeile ein
    Schloss und das Seitenpanel zeigt den Grund samt Ausweg statt eines Formulars. Niemand soll
    erst beim Speichern erfahren, dass er etwas nicht ändern darf (CLAUDE.md Regel 8). Die
    Rücknahme des Kennzeichens „gestellt" ist ein eigener Knopf mit Rückfrage – kein
    Nebeneffekt des Speicherns.

## Prüfliste vor dem Abschluss einer Frontend-Änderung

- Farben ausschließlich über die Token-Variablen, kein Grün, keine Verläufe.
- Alle Zahlen in Space Grotesk mit `font-variant-numeric: tabular-nums`.
- Deutsche Formate: `1.250,00 €`, `5.695 kWp`, `TT.MM.JJJJ`; geschütztes Leerzeichen vor der Einheit.
- Negative Werte in Akzent-Rot, nie mit Klammern oder Minuszeichen allein.
- Fehlende Berechtigung blendet Elemente aus, graut sie nicht aus.
- Übergänge 150–200 ms und nur als Reaktion auf eine Nutzeraktion.
- Zeichen 3 nur auf Anmeldeseite und in Leerzuständen (Deckkraft ≤ 0,12), nie auf Datenseiten.
