/**
 * Monatsbalken (design/Komponenten.dc.html).
 *
 * Ist gefüllt in ip³ Blau, Plan als Kontur. Damit ist ohne Legende erkennbar, was schon
 * gestellt ist und was noch aussteht – die Frage, um die es im Forecast geht.
 *
 * Keine Achsen, keine Gitterlinien: die Zahlen stehen in der Sprechblase, und die Kacheln
 * darüber tragen die Summen. Ein Diagramm auf einer Startseite soll den Verlauf zeigen, nicht
 * das Ablesen einzelner Werte ersetzen.
 */

export type Monatswert = {
  /** Monat als `'JJJJ-MM'`. */
  monat: string
  /** Fertig formatierte Beschriftung, z. B. „Aug". */
  beschriftung: string
  /** Wert in Cent. Ohne `planBetrag` ist das der ganze Balken. */
  betrag: number
  /**
   * Plananteil in Cent, als Kontur **über** dem Ist gezeichnet.
   *
   * Ein Monat kann beides tragen: im Bestand ist der Mai 2026 zu 289.398,34 € gestellt und hat
   * daneben offene Positionen. Zwei Balken nebeneinander wären 24 Säulen für zwölf Monate;
   * gestapelt bleibt die Bildsprache aus `design/Komponenten.dc.html` – Ist gefüllt, Plan Kontur –
   * und die Gesamthöhe zeigt, was der Monat insgesamt bringt.
   */
  planBetrag?: number
  /** Plan (Kontur) statt Ist (gefüllt) – für Monate, die nur Plan sind. */
  plan?: boolean
  /** Laufender Monat – wird in der Beschriftung hervorgehoben. */
  aktuell?: boolean
  /** Text der Sprechblase, z. B. „August · 612 T€". */
  titel?: string
}

type Props = {
  werte: Monatswert[]
  hoehe?: number
}

export function MonthBars({ werte, hoehe = 80 }: Props) {
  if (werte.length === 0) return null

  const gesamt = (wert: Monatswert) => Math.abs(wert.betrag) + Math.abs(wert.planBetrag ?? 0)
  const groesster = Math.max(...werte.map(gesamt), 1)
  const anteil = (betrag: number) => (Math.abs(betrag) / groesster) * hoehe

  return (
    <div>
      <div className="monatsbalken" style={{ height: hoehe }}>
        {werte.map((wert) =>
          wert.planBetrag === undefined ? (
            <div
              key={wert.monat}
              className={`monatsbalken__balken monatsbalken__balken--${wert.plan ? 'plan' : 'ist'}`}
              style={{ height: Math.max(2, anteil(wert.betrag)) }}
              title={wert.titel ?? `${wert.beschriftung}`}
            />
          ) : (
            // Gestapelt: Plan als Kontur oben, Ist gefüllt unten. Leere Anteile bekommen keine
            // Mindesthöhe – ein 2-px-Strich für 0,00 € wäre eine Behauptung.
            <div
              key={wert.monat}
              className="monatsbalken__saeule"
              title={wert.titel ?? `${wert.beschriftung}`}
            >
              {wert.planBetrag ? (
                <div
                  className="monatsbalken__balken monatsbalken__balken--plan"
                  style={{ height: Math.max(2, anteil(wert.planBetrag)) }}
                />
              ) : null}
              {wert.betrag ? (
                <div
                  className="monatsbalken__balken monatsbalken__balken--ist"
                  style={{ height: Math.max(2, anteil(wert.betrag)) }}
                />
              ) : null}
            </div>
          ),
        )}
      </div>
      <div className="monatsbalken__beschriftung">
        {werte.map((wert) => (
          <span key={wert.monat} className={wert.aktuell ? 'aktuell' : undefined}>
            {wert.beschriftung}
          </span>
        ))}
      </div>
    </div>
  )
}
