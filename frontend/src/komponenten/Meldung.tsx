/**
 * Meldung mit nächstem Schritt (PLAN §14).
 *
 * Die Fehlerantworten des Backends haben die Form `{code, meldung, naechster_schritt}`. Diese
 * Komponente zeigt beides: was passiert ist **und** was der Nutzer nun tun kann. Eine Meldung
 * ohne nächsten Schritt lässt jemanden vor dem Bildschirm sitzen, der nicht weiterkommt.
 */

import type { ReactNode } from 'react'

type Props = {
  art?: 'fehler' | 'hinweis'
  text: ReactNode
  naechsterSchritt?: ReactNode
}

export function Meldung({ art = 'hinweis', text, naechsterSchritt }: Props) {
  return (
    <div className={`meldung meldung--${art}`} role={art === 'fehler' ? 'alert' : 'status'}>
      <div className="meldung__text">{text}</div>
      {naechsterSchritt ? <div className="meldung__schritt">{naechsterSchritt}</div> : null}
    </div>
  )
}
