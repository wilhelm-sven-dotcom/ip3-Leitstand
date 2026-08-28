# Beispieldateien zum Ausprobieren

Diese vier Dateien sind **erfunden**. Sie enthalten keine echten Geschäftsvorfälle und keine
echten Mitarbeiterzeiten. Sie sind auf die Demodaten abgestimmt
(`uv run ip3-leitstand seed --demodaten`), damit die Nachkalkulation beim ersten Anschauen
Zahlen zeigt statt leerer Tabellen.

**Nicht in eine Produktivdatenbank einlesen.** Die Beträge landen sonst als Ist-Kosten an den
Projekten 26001 und 26002.

| Datei | Gehört in den Ordner | Was sie enthält |
|---|---|---|
| `26001_Beispiel_Kalkulation.xlsx` | `pfade.kalkulation` (`03_Kalkulation`) | Sollwerte für Projekt 26001: Material 232.000,00 €, Dienstleistung 38.000,00 €, 620 Stunden, Soll-Marge 18 %, 7 Stücklistenpositionen (gemischt `lager` und `projektbestellt`) |
| `26002_Beispiel_Kalkulation.xlsx` | `pfade.kalkulation` (`03_Kalkulation`) | Sollwerte für Projekt 26002: 158.000,00 € / 24.000,00 € / 380 Stunden / 18 %, 4 Positionen |
| `kostentraeger_2026-07.csv` | `pfade.datev` (`02_DATEV`) | 13 Buchungszeilen im DATEV-Standardformat (Windows-1252, Semikolon) |
| `timetac_2026-07.csv` | frei wählbar, Pfad wird dem Befehl mitgegeben | 10 Zeiterfassungszeilen für die Rückfallebene `ip3-leitstand timetac-csv` – im Regelbetrieb kommen die Stunden über die Schnittstelle |

## Absichtliche Stolpersteine

Die Dateien sind so gebaut, dass die Prüfungen des Leitstands sichtbar greifen. Wenn im
Importprotokoll Befunde stehen, ist das **das erwartete Ergebnis**, kein Fehler:

**`kostentraeger_2026-07.csv`** – drei der 13 Zeilen werden bewusst nicht übernommen:

- Konto `8400` (Erlöse) liegt außerhalb der Kostenkonten. Eine Kostenträgerauswertung führt
  meist auch Erlöse; würde der Leitstand sie als Kosten übernehmen, drehte sich die Marge ins
  Gegenteil.
- Die Hallenmiete hat **kein KOST2** und ist damit Gemeinkosten, kein Projekt.
- KOST2 `29999` gehört zu keinem Projekt in der Datenbank.

Eine Zeile ist eine Lieferantengutschrift (Soll/Haben-Kennzeichen `H`); sie **mindert** die
Kosten, statt sie zu erhöhen.

**`timetac_2026-07.csv`** – zwei Stolpersteine:

- „Interne Besprechung" lässt sich keinem Projekt zuordnen und erscheint als Befund.
- „Neu, Kollege" steht in keiner Satzgruppe unter `[stundensaetze]`, rechnet deshalb mit dem
  Standardsatz und erscheint als Pflegehinweis.
- Die Dauern stehen gemischt als `08:00` und `10,00` – beide Schreibweisen kommen in echten
  Exporten vor und werden unterschiedlich gelesen (8 Stunden bzw. 10 Stunden).

## So sieht man das Ergebnis

1. Die beiden Excel-Dateien in den Ordner aus `pfade.kalkulation` kopieren, die
   `kostentraeger_2026-07.csv` in den Ordner aus `pfade.datev`.
2. Im Leitstand unter **Importe & Daten** die Vorschau je Quelle aufrufen und übernehmen.
3. Die Stunden kommen im Regelbetrieb über die Schnittstelle. Solange die Zugangsdaten fehlen,
   tut es die Beispieldatei:

   ```bash
   cd backend
   uv run ip3-leitstand timetac-csv ../vorlagen/beispiele/timetac_2026-07.csv
   ```

4. Bei Projekt 26001 unter **Nachkalkulation** stehen dann Erlös, Soll, Ist je Quelle und die
   Marge gegen die Soll-Marge. Die Lagerentnahme kommt dazu, sobald unter **Mengen-Ist
   bestätigen** gezählt wurde – bis dahin sagt ein Hinweis, dass sie fehlt.
