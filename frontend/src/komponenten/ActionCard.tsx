/**
 * Aktionskarte für den Arbeitsvorrat der Startseite (design/Start.dc.html).
 *
 * **Genau eine Aktion je Karte.** Wer vor einer Karte mit drei Möglichkeiten steht,
 * entscheidet nicht, sondern liest weiter. Die Karte sagt: das ist zu tun, und das ist der
 * Knopf dafür.
 */

import type { ReactNode } from 'react'

type Props = {
  /** Kategorie in Versalien: „Rechnungsvorschlag", „Überfällig", „Frist bald fällig". */
  kicker: string
  /** Kicker in Akzent-Rot – für Überfälligkeiten und Fristen. */
  warnung?: boolean
  titel: ReactNode
  meta?: ReactNode
  /** Fertig formatierter Betrag. */
  betrag?: ReactNode
  betragNegativ?: boolean
  /** Die eine Aktion. */
  aktion?: ReactNode
}

export function ActionCard({
  kicker,
  warnung = false,
  titel,
  meta,
  betrag,
  betragNegativ = false,
  aktion,
}: Props) {
  return (
    <div className="aktionskarte">
      <div>
        <div className={`aktionskarte__kicker${warnung ? ' aktionskarte__kicker--warnung' : ''}`}>
          {kicker}
        </div>
        <div className="aktionskarte__titel">{titel}</div>
        {meta ? <div className="aktionskarte__meta">{meta}</div> : null}
      </div>
      {betrag ? (
        <div
          className={`aktionskarte__betrag${betragNegativ ? ' aktionskarte__betrag--negativ' : ''}`}
        >
          {betrag}
        </div>
      ) : (
        <div />
      )}
      <div>{aktion}</div>
    </div>
  )
}
