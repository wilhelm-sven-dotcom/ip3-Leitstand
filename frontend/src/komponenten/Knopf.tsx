/**
 * Schaltfläche in drei Ausführungen (design/Komponenten.dc.html).
 *
 * ``festschreiben`` ist Akzent-Rot und bleibt der Festschreibung vorbehalten – dem einzigen
 * unwiderruflichen Vorgang im Leitstand. Würde die Farbe auch für „Speichern" verwendet,
 * verliert sie ihre Bedeutung.
 */

import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react'

type Art = 'primaer' | 'sekundaer' | 'festschreiben'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  art?: Art
  klein?: boolean
  children: ReactNode
  /** Für den Dialog, der den Fokus beim Öffnen setzt. React 19 reicht ref als Prop durch. */
  ref?: Ref<HTMLButtonElement>
}

export function Knopf({ art = 'primaer', klein = false, children, ...rest }: Props) {
  const klassen = ['knopf', `knopf--${art}`]
  if (klein) klassen.push('knopf--klein')
  return (
    <button type="button" className={klassen.join(' ')} {...rest}>
      {children}
    </button>
  )
}
