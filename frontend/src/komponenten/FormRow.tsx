/**
 * Formularzeile: Beschriftung über dem Feld, Hinweis oder Fehler darunter
 * (design/Komponenten.dc.html).
 *
 * Die Fehlermeldung steht am Feld, nicht als Sammelmeldung am Formularkopf: wer fünf Felder
 * ausgefüllt hat, soll sehen, welches gemeint ist. Zahlenfelder tragen Space Grotesk und
 * stehen rechtsbündig – so lassen sich Beträge übereinander vergleichen.
 */

import { useId } from 'react'
import type { InputHTMLAttributes, ReactNode } from 'react'

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> & {
  label: string
  /** Erläuterung unter dem Feld, solange kein Fehler vorliegt. */
  hinweis?: ReactNode
  /** Fehlertext. Ist er gesetzt, wird das Feld rot umrandet und der Hinweis ersetzt. */
  fehler?: ReactNode
  /** Zahlenfeld: Space Grotesk, Tabellenziffern, rechtsbündig. */
  zahl?: boolean
  breit?: boolean
}

export function FormRow({ label, hinweis, fehler, zahl = false, breit = false, ...rest }: Props) {
  const id = useId()
  const beschreibungId = `${id}-beschreibung`

  const feldklassen = ['formularzeile__feld']
  if (zahl) feldklassen.push('formularzeile__feld--zahl')
  if (fehler) feldklassen.push('formularzeile__feld--fehler')

  return (
    <div className={`formularzeile${breit ? ' formularzeile--breit' : ''}`}>
      <label className="formularzeile__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={feldklassen.join(' ')}
        aria-invalid={fehler ? true : undefined}
        aria-describedby={fehler || hinweis ? beschreibungId : undefined}
        {...rest}
      />
      {fehler ? (
        <span id={beschreibungId} className="formularzeile__fehler" role="alert">
          {fehler}
        </span>
      ) : hinweis ? (
        <span id={beschreibungId} className="formularzeile__hinweis">
          {hinweis}
        </span>
      ) : null}
    </div>
  )
}
