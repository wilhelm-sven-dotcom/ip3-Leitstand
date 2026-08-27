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
  /** Wert in Cent. */
  betrag: number
  /** Plan (Kontur) statt Ist (gefüllt). */
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

  const groesster = Math.max(...werte.map((w) => Math.abs(w.betrag)), 1)

  return (
    <div>
      <div className="monatsbalken" style={{ height: hoehe }}>
        {werte.map((wert) => (
          <div
            key={wert.monat}
            className={`monatsbalken__balken monatsbalken__balken--${wert.plan ? 'plan' : 'ist'}`}
            style={{ height: Math.max(2, (Math.abs(wert.betrag) / groesster) * hoehe) }}
            title={wert.titel ?? `${wert.beschriftung}`}
          />
        ))}
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
