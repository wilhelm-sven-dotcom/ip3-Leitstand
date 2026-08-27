/**
 * Zusammenfassung für Bestätigungsdialoge (design/Festschreiben.dc.html).
 *
 * Die Zahlen, die bestätigt werden: Nettobetrag, Umsatzsteuer je Satz, Bruttosumme. Die
 * Summenzeile ist abgesetzt, damit man sie nicht mit einer Position verwechselt.
 */

import type { ReactNode } from 'react'

type Zeile = {
  label: string
  /** Fertig formatierter Wert. */
  wert: ReactNode
  /** Abgesetzte Summenzeile. */
  summe?: boolean
}

type Props = {
  zeilen: Zeile[]
}

export function Zusammenfassung({ zeilen }: Props) {
  return (
    <div className="zusammenfassung">
      {zeilen.map((zeile) => (
        <div
          key={zeile.label}
          className={`zusammenfassung__zeile${zeile.summe ? ' zusammenfassung__zeile--summe' : ''}`}
        >
          <span className="zusammenfassung__label">{zeile.label}</span>
          <span className="zusammenfassung__wert">{zeile.wert}</span>
        </div>
      ))}
    </div>
  )
}
