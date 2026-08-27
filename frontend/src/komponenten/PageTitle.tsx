/**
 * Seitentitel mit dem roten Endpunkt (PLAN §11).
 *
 * Der Punkt in Akzent-Rot ist die wiederkehrende Geste der Marke – dieselbe wie der
 * Sonnenpunkt im Zeichen 3. Er wird deshalb hier gesetzt und nicht in den Titeltext
 * geschrieben, damit er überall gleich aussieht und nie fehlt.
 */

import type { ReactNode } from 'react'

type Props = {
  children: ReactNode
  /** Zeile unter dem Titel: Anzahl, Summe, Zeitraum. */
  meta?: ReactNode
  /** Aktionen rechts neben dem Titel. */
  aktionen?: ReactNode
}

export function PageTitle({ children, meta, aktionen }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 'var(--abstand-4)',
        flexWrap: 'wrap',
      }}
    >
      <div>
        <h1 className="seitentitel">
          {children}
          <span className="seitentitel__punkt">.</span>
        </h1>
        {meta ? <div className="seitentitel__meta">{meta}</div> : null}
      </div>
      {aktionen ? (
        <div style={{ display: 'flex', gap: 'var(--abstand-3)', flexShrink: 0 }}>{aktionen}</div>
      ) : null}
    </div>
  )
}
