/**
 * Leerzustand (design/Komponenten.dc.html).
 *
 * Ein leerer Bereich sagt nicht „keine Daten", sondern was als Nächstes zu tun ist. Begleitet
 * vom Zeichen 3 mit höchstens 0,12 Deckkraft – und nur hier sowie auf der Anmeldeseite, nie
 * auf gefüllten Datenseiten (PLAN §11).
 */

import type { ReactNode } from 'react'
import zeichen from '@cd/zeichen/zeichen-3-kontur-rot.png'

type Props = {
  titel: string
  /** Der nächste Schritt, in einem Satz. */
  text?: ReactNode
  /** Höchstens eine Aktion. */
  aktion?: ReactNode
  /** Zeichen 3 ausblenden – für kleine Bereiche, in denen es nicht atmen kann. */
  ohneZeichen?: boolean
}

export function EmptyState({ titel, text, aktion, ohneZeichen = false }: Props) {
  return (
    <div className="leerzustand">
      {ohneZeichen ? null : <img className="leerzustand__zeichen" src={zeichen} alt="" />}
      <div className="leerzustand__titel">{titel}</div>
      {text ? <div className="leerzustand__text">{text}</div> : null}
      {aktion ? <div className="leerzustand__aktion">{aktion}</div> : null}
    </div>
  )
}
