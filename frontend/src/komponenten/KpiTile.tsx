/**
 * Kennzahlenkachel (design/Komponenten.dc.html).
 *
 * Der Wert steht in Space Grotesk mit Tabellenziffern, damit mehrere Kacheln nebeneinander
 * bündig wirken. Negative Werte in Akzent-Rot – kein Grün für positive, die stehen im
 * normalen Textton (PLAN §11).
 */

import type { ReactNode } from 'react'

type Props = {
  label: string
  /** Fertig formatierter Wert, z. B. aus `euro()` oder `leistung()`. */
  wert: ReactNode
  /** Zusatzzeile unter dem Wert: Vergleich, Erläuterung, Zeitraum. */
  zusatz?: ReactNode
  /** Bewertung des Zusatzes: Blau für gut, Akzent-Rot für schlecht, sonst grau. */
  zusatzArt?: 'positiv' | 'negativ' | 'neutral'
  /** Wert in Akzent-Rot darstellen – für Unterdeckung und Überfälligkeit. */
  negativ?: boolean
}

export function KpiTile({ label, wert, zusatz, zusatzArt = 'neutral', negativ = false }: Props) {
  return (
    <div className="kpi">
      <div className="kpi__label">{label}</div>
      <div className={`kpi__wert${negativ ? ' kpi__wert--negativ' : ''}`}>{wert}</div>
      {zusatz ? (
        <div
          className={
            zusatzArt === 'neutral' ? 'kpi__zusatz' : `kpi__zusatz kpi__zusatz--${zusatzArt}`
          }
        >
          {zusatz}
        </div>
      ) : null}
    </div>
  )
}
