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

14. **Für „Umsatz & Forecast" gibt es kein Mockup.** Die Seite entsteht im Duktus von
    Projektliste (Filterleiste, Datentabelle) und Firmen-Cockpit (Kachelreihe, Monatsbalken).
    Neu ist eine **gestapelte** Variante der Monatsbalken: Ist gefüllt, Plan als Kontur darüber,
    Gesamthöhe Ist plus Plan. Das Designsystem kennt „Ist gefüllt, Plan Kontur" für Monate, die
    entweder das eine oder das andere sind; in den echten Daten trägt ein Monat beides (Februar
    2026: 8.840,00 € Ist und 7.557,88 € Plan). Zwei Balken nebeneinander wären 24 Säulen für
    zwölf Monate – gestapelt bleibt die Bildsprache erhalten und der Monat lesbar.
15. **Was nicht im Diagramm steht, steht daneben.** Positionen ohne Planmonat gehören in keine
    Monatssäule. Sie stehen deshalb in einer eigenen Kachel und noch einmal in Akzent-Rot neben
    der Legende („Nicht im Verlauf: 689.698,50 € ohne Planmonat"). Eine Fußnote unter dem
    Diagramm hätte dieselbe Information und würde nicht gelesen.

16. **Für die Belegliste und das Belegdetail gibt es kein Mockup**, nur für den
    Festschreiben-Dialog (`Festschreiben.dc.html`). Die Liste folgt der Projektliste
    (Filterleiste über der Datentabelle, Zahlen rechtsbündig, Zeile öffnet das Detail), das
    Detail dem Projektdetail (Kopfdaten als Beschreibungsliste, Abschnitte mit blauer
    Zwischenüberschrift). **Netto und Zahlbetrag stehen nebeneinander**, weil das bei einer
    Schlussrechnung zwei verschiedene Zahlen sind – die Gesamtleistung und der Restbetrag nach
    Absetzung der Abschläge. Nur eine davon zu zeigen wäre je Belegart die falsche.

17. **Der Summenblock steht rechts, wie auf dem Beleg.** Auf dem Bildschirm wäre eine Kachel
    naheliegender; die Anordnung des Papiers macht den Vergleich mit der Vorschau daneben aber
    unmittelbar. Die Endsumme trägt eine Linie darüber und Space Grotesk in Dialoggröße.

18. **Das Rechnungs-PDF trägt kein Zeichen 3.** Die Corporate-Design-Regel schließt das
    Wasserzeichen auf zahlen- und tabellenlastigen Flächen aus, und eine Rechnung ist genau das.
    Die Marke trägt der Briefkopf mit der Wortmarke und der 2-pt-Linie in ip³ Blau.

19. **Der Prozentsatz bekommt ein geschütztes Leerzeichen** (`19 %`), wie jede andere Einheit
    (PLAN §6.10). Das vorhandene `prozent()` aus dem Formatmodul zeigt immer eine
    Nachkommastelle („19,0 %"); auf einer Rechnung steht `19 %`. Deshalb ein eigenes `satzText`
    für Steuersätze – dieselbe NBSP-Konstante, andere Nachkommaregel.

20. **Die Menge einer Position wird formatiert, nicht durchgereicht.** Die Schnittstelle liefert
    sie als Dezimaltext mit drei Nachkommastellen (`"1.000"`), und auf deutsch gelesen ist das
    eintausend. Im Rundgang stand so bei einer Menge von 1 die Zahl 1.000 in der Tabelle;
    `mengeText` schneidet die Nullen ab und setzt das Dezimalkomma.

## Prüfliste vor dem Abschluss einer Frontend-Änderung

- Farben ausschließlich über die Token-Variablen, kein Grün, keine Verläufe.
- Alle Zahlen in Space Grotesk mit `font-variant-numeric: tabular-nums`.
- Deutsche Formate: `1.250,00 €`, `5.695 kWp`, `TT.MM.JJJJ`; geschütztes Leerzeichen vor der Einheit.
- Negative Werte in Akzent-Rot, nie mit Klammern oder Minuszeichen allein.
- Fehlende Berechtigung blendet Elemente aus, graut sie nicht aus.
- Übergänge 150–200 ms und nur als Reaktion auf eine Nutzeraktion.
- Zeichen 3 nur auf Anmeldeseite und in Leerzuständen (Deckkraft ≤ 0,12), nie auf Datenseiten.
