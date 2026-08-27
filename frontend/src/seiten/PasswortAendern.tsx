/**
 * Passwort ändern.
 *
 * Zwei Wege hierher: freiwillig über das Menü, oder erzwungen, weil das Passwort über die
 * Kommandozeile vergeben wurde (`muss_passwort_wechseln`). Im zweiten Fall erklärt die Seite,
 * warum sie erscheint – sonst wirkt sie wie eine Fehlfunktion.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageTitle } from '@/komponenten/PageTitle'
import { FormRow } from '@/komponenten/FormRow'
import { Knopf } from '@/komponenten/Knopf'
import { Meldung } from '@/komponenten/Meldung'
import { api, fehlerAuslesen } from '@/api/client'
import type { ApiFehler } from '@/api/client'
import { useSitzung } from '@/sitzung/SitzungKontext'
import type { AngemeldeterNutzer } from '@/sitzung/SitzungKontext'

export function PasswortAendern() {
  const { nutzer, nutzerSetzen } = useSitzung()
  const navigate = useNavigate()

  const [altes, setAltes] = useState('')
  const [neues, setNeues] = useState('')
  const [wiederholung, setWiederholung] = useState('')
  const [fehler, setFehler] = useState<ApiFehler | null>(null)
  const [laeuft, setLaeuft] = useState(false)
  const [erledigt, setErledigt] = useState(false)

  const pflicht = nutzer?.muss_passwort_wechseln ?? false
  // Die Wiederholung prüft die Oberfläche selbst: dafür braucht es keine Anfrage.
  const wiederholungFalsch = wiederholung.length > 0 && neues !== wiederholung

  async function absenden(ereignis: React.FormEvent) {
    ereignis.preventDefault()
    if (wiederholungFalsch) return
    setFehler(null)
    setLaeuft(true)

    const { data, error } = await api.POST('/api/auth/passwort-aendern', {
      body: { altes_passwort: altes, neues_passwort: neues },
    })
    setLaeuft(false)

    if (data) {
      nutzerSetzen(data as AngemeldeterNutzer)
      setErledigt(true)
      setAltes('')
      setNeues('')
      setWiederholung('')
      if (pflicht) {
        navigate('/', { replace: true })
      }
      return
    }
    setFehler(fehlerAuslesen(error))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-5)' }}>
      <PageTitle meta={nutzer?.email}>Passwort ändern</PageTitle>

      {pflicht ? (
        <Meldung
          art="hinweis"
          text="Bevor Sie weiterarbeiten können, brauchen Sie ein eigenes Passwort."
          naechsterSchritt={
            'Das bisherige Passwort wurde am Rechner vergeben und ist deshalb nur für die ' +
            'erste Anmeldung gedacht.'
          }
        />
      ) : null}

      {erledigt && !pflicht ? (
        <Meldung
          art="hinweis"
          text="Das Passwort wurde geändert."
          naechsterSchritt="Ihre übrigen Anmeldungen an anderen Rechnern wurden beendet."
        />
      ) : null}

      {fehler ? (
        <Meldung art="fehler" text={fehler.meldung} naechsterSchritt={fehler.naechster_schritt} />
      ) : null}

      <form
        onSubmit={absenden}
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-4)' }}
      >
        <FormRow
          label="Bisheriges Passwort"
          type="password"
          autoComplete="current-password"
          value={altes}
          onChange={(e) => setAltes(e.target.value)}
          fehler={fehler?.felder?.altes_passwort}
          required
        />
        <FormRow
          label="Neues Passwort"
          type="password"
          autoComplete="new-password"
          value={neues}
          onChange={(e) => setNeues(e.target.value)}
          hinweis="Mindestens 12 Zeichen. Ein Satz aus mehreren Wörtern ist leichter zu merken und sicherer als ein kurzes Passwort mit Sonderzeichen."
          fehler={fehler?.felder?.neues_passwort ?? fehler?.felder?.passwort}
          required
        />
        <FormRow
          label="Neues Passwort wiederholen"
          type="password"
          autoComplete="new-password"
          value={wiederholung}
          onChange={(e) => setWiederholung(e.target.value)}
          fehler={wiederholungFalsch ? 'Die beiden Eingaben stimmen nicht überein.' : undefined}
          required
        />

        <div>
          <Knopf
            type="submit"
            disabled={laeuft || wiederholungFalsch || !altes || !neues || !wiederholung}
          >
            {laeuft ? 'Wird geändert …' : 'Passwort ändern'}
          </Knopf>
        </div>
      </form>
    </div>
  )
}
