# ip³-Cockpit — Design-Übergabe an Claude Code

Designsystem und Screen-Mockups für **ip3-cockpit** (internes Projekt- und Finanz-Cockpit der ip³ Energietechnik GmbH). Diesen Ordner als `design/` ins Repo legen; Umsetzung als React-Web-App (Vite, TypeScript) in Phase 0.

## Inhalt

| Datei | Zweck |
|---|---|
| `ip3-tokens.css` | Design-Tokens als CSS-Variablen (Farben, Typo-Skala, Abstände, Radien, Schatten, Bewegung) — 1:1 übernehmen |
| `Komponenten.dc.html` | Komponentenrezepte: Seitentitel, Statusbadge-Set (8), Schaltflächen, KPI-Kachel, Datentabelle, Aktionskarte, Monatsbalken, Formularzeile, Leerzustand, Bestätigungsdialog |
| `Start.dc.html` | Startseite = Arbeitsvorrat: Kennzahlenzeile, „Heute wichtig"-Aktionskarten (je genau eine Aktion), Monats-Miniatur |
| `Projektliste.dc.html` | Liste mit Filtern (Jahr, Status, PL, Gewerk), Suche, Pagination |
| `Projektdetail.dc.html` | Tab „Zahlungsplan & Rechnungen", Belegliste, Seitenpanel für Belegdetails (Zeile klicken, Esc schließt) |
| `Festschreiben.dc.html` | Bestätigungsdialog mit vollständiger Zusammenfassung; Checkbox schaltet den roten Button frei |
| `Firmen-Cockpit.dc.html` | Monatsansicht: Umsatz → Deckungsbeitrag → Fixkosten → Überdeckung, Break-even, Reichweite Auftragsbestand |
| `Login.dc.html` | Navy-Fläche, Zeichen 3 groß und leise, Akzent-Rot nur als CTA |
| `brand/` | Logos (SVG), Zeichen-3-Konturen (PNG, freigestellt) — Dateien einbetten, nie nachbauen |
| `support.js` | Nur Laufzeit für die HTML-Vorschau der Mockups, nicht übernehmen |

Mockups im Browser öffnen (Doppelklick genügt). Alle Beispieldaten sind fiktiv.

## Schriften

Libre Franklin (UI, Headlines 700/800 mit letter-spacing −0.02em) und Space Grotesk (ALLE Zahlen, `font-variant-numeric: tabular-nums`). Als TTF von fonts.google.com ins Repo legen und per `@font-face` einbinden; Fallback Arial. Die Mockups laden sie über Google Fonts.

## Komponentenschnitt (React)

`AppShell` (Sidebar 224 px + Topbar 56 px + Content max 1280 px) · `PageTitle` (Endpunkt in `--akzent-rot`) · `StatusBadge` (genau 8 Varianten: Entwurf, Geplant, Gestellt, Festgeschrieben, Bezahlt, Überfällig, Frist bald fällig, Storniert) · `KpiTile` · `DataTable` (Kopf ip³ Blau, sticky, Zebra `#F5F6F9`, Zahlen rechts, Einheit im Kopf) · `ActionCard` · `MonthBars` (Ist gefüllt, Plan Kontur `#8D8AB8`) · `FormRow` · `ConfirmDialog` · `DetailPanel` (420 px, Fokus-Trap) · `EmptyState` (Zeichen 3, Opacity ≤ 0,12).

## Interaktion

- Übergänge 150–200 ms `cubic-bezier(.2,0,0,1)`, nur als Reaktion auf Nutzeraktionen; keine Dauer-Animationen.
- Tastatur: `Strg K` Suche · `Esc` schließt Panel/Dialog · `Enter` bestätigt Festschreiben NICHT ohne Checkbox.
- Berechtigungen: Elemente ausblenden, nie ausgrauen.
- Formate: `Intl.NumberFormat('de-DE')`, Datum TT.MM.JJJJ, geschütztes Leerzeichen vor kWp/kWh/€, negative Werte in `--akzent-rot`.

## Do / Don't

**Do:** jede Farbe aus den Tokens · Hierarchie über Größe/Gewicht · Leerzustände erklären den nächsten Schritt · UI-Texte deutsch, kurz, bodenständig.
**Don't:** kein Grün (auch nicht „bezahlt") · keine Verläufe, Illustrationen, Emojis, Ausrufezeichen · Zeichen 3 nie auf Datenseiten · keine Schatten außer Dialog/Panel · kein Denglisch.

## Akzeptanz

Ohne Einweisung findbar: offenen Abschlag stellen (Start → Karte → Festschreiben), Projekt suchen (Strg K), Monatsstand lesen (Firmen-Cockpit). Jede Seite wirkt ruhig, obwohl sie Zahlen trägt.
