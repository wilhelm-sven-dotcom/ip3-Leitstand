/**
 * Anmeldeseite (design/Login.dc.html).
 *
 * Navy-Fläche, das Zeichen 3 groß und leise dahinter, Akzent-Rot ausschließlich für den
 * Anmeldeknopf. Die Wortmarke wird als Grafikdatei gesetzt, nie mit einer Systemschrift
 * nachgebaut (PLAN §11).
 *
 * „Passwort vergessen?" löst keinen Mailversand aus – den gibt es in V1 nicht (PLAN §12) –
 * sondern zeigt, an wen man sich wendet.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import wortmarkeWeiss from '@cd/logos/ip3-energietechnik-weiss.svg'
import zeichen from '@cd/zeichen/zeichen-3-kontur-akzent.png'
import { useSitzung } from '@/sitzung/SitzungKontext'
import type { ApiFehler } from '@/api/client'
import './anmelden.css'

export function Anmelden() {
  const { anmelden } = useSitzung()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [passwort, setPasswort] = useState('')
  const [angemeldetBleiben, setAngemeldetBleiben] = useState(false)
  const [fehler, setFehler] = useState<ApiFehler | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [hinweisSichtbar, setHinweisSichtbar] = useState(false)

  async function absenden(ereignis: React.FormEvent) {
    ereignis.preventDefault()
    setFehler(null)
    setLaeuft(true)
    const ergebnis = await anmelden(email, passwort, angemeldetBleiben)
    setLaeuft(false)
    if (ergebnis.ok) {
      navigate('/', { replace: true })
    } else {
      setFehler(ergebnis.fehler)
      setPasswort('')
    }
  }

  return (
    <div className="anmelden">
      <img className="anmelden__zeichen" src={zeichen} alt="" />

      <div className="anmelden__spalte">
        <img className="anmelden__marke" src={wortmarkeWeiss} alt="ip³ Energietechnik GmbH" />

        <h1 className="anmelden__titel">
          Anmelden<span className="anmelden__punkt">.</span>
        </h1>
        <p className="anmelden__unterzeile">Internes Projekt- und Finanz-Cockpit</p>

        <form className="anmelden__formular" onSubmit={absenden} noValidate>
          <label className="anmelden__feld">
            <span className="anmelden__label">E-Mail</span>
            <input
              type="email"
              name="email"
              autoComplete="username"
              placeholder="vorname@ip3-energie.de"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </label>

          <label className="anmelden__feld">
            <span className="anmelden__label">Passwort</span>
            <input
              type="password"
              name="passwort"
              autoComplete="current-password"
              placeholder="••••••••••"
              value={passwort}
              onChange={(e) => setPasswort(e.target.value)}
              required
            />
          </label>

          <label className="anmelden__haken">
            <input
              type="checkbox"
              checked={angemeldetBleiben}
              onChange={(e) => setAngemeldetBleiben(e.target.checked)}
            />
            Angemeldet bleiben
          </label>

          {fehler ? (
            <div className="anmelden__fehler" role="alert">
              <strong>{fehler.meldung}</strong>
              <span>{fehler.naechster_schritt}</span>
            </div>
          ) : null}

          <button type="submit" className="anmelden__knopf" disabled={laeuft}>
            {laeuft ? 'Anmelden …' : 'Anmelden'}
          </button>

          <button
            type="button"
            className="anmelden__vergessen"
            onClick={() => setHinweisSichtbar((sichtbar) => !sichtbar)}
          >
            Passwort vergessen?
          </button>
          {hinweisSichtbar ? (
            <p className="anmelden__hinweis">
              Wenden Sie sich an Sven Wilhelm oder Michael Bäumler – dort lässt sich Ihr
              Passwort zurücksetzen. Einen Versand per E-Mail gibt es im Leitstand nicht.
            </p>
          ) : null}
        </form>
      </div>

      <footer className="anmelden__fuss">
        <span>
          ip³ Energietechnik GmbH · Theisseil · info@ip3-energie.de · www.ip3-energie.de
        </span>
        <span>Nur für interne Nutzung</span>
      </footer>
    </div>
  )
}
