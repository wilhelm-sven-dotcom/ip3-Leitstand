/**
 * Sitzungszustand der Oberfläche.
 *
 * Hält den angemeldeten Nutzer samt Berechtigungen und stellt `darf()` bereit. Wichtig:
 * **`darf()` ist eine Anzeigeentscheidung, keine Sperre.** Die Sperre sitzt im Backend an
 * jeder Route. Hier geht es darum, dass niemand einen Knopf sieht, den er nicht drücken kann
 * (PLAN §4, §14).
 *
 * Fehlt eine Berechtigung, wird das Element ausgeblendet, nicht ausgegraut
 * (design/README.md): eine ausgegraute Schaltfläche wirft die Frage auf, wie man sie
 * freischaltet.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ABGEMELDET_EREIGNIS, api, csrfTokenSetzen, fehlerAuslesen } from '@/api/client'
import type { ApiFehler } from '@/api/client'

export type AngemeldeterNutzer = {
  id: number
  name: string
  email: string
  rollen: string[]
  rechte: Record<string, string>
  muss_passwort_wechseln: boolean
  csrf_token: string
  sitzung_laeuft_ab: string
}

type SitzungZustand = {
  nutzer: AngemeldeterNutzer | null
  /** Solange true, ist noch nicht bekannt, ob eine Sitzung besteht. */
  laedt: boolean
  darf: (recht: string) => boolean
  /** `alle` oder `eigene`; ohne die Berechtigung `eigene` als engster Fall. */
  scope: (recht: string) => 'alle' | 'eigene'
  anmelden: (
    email: string,
    passwort: string,
    angemeldetBleiben: boolean,
  ) => Promise<{ ok: true } | { ok: false; fehler: ApiFehler }>
  abmelden: () => Promise<void>
  /** Nach einem Passwortwechsel: den Nutzer im Kontext erneuern. */
  nutzerSetzen: (nutzer: AngemeldeterNutzer) => void
}

const Kontext = createContext<SitzungZustand | null>(null)

export function SitzungProvider({ children }: { children: ReactNode }) {
  const [nutzer, setNutzer] = useState<AngemeldeterNutzer | null>(null)
  const [laedt, setLaedt] = useState(true)

  const nutzerSetzen = useCallback((neu: AngemeldeterNutzer) => {
    setNutzer(neu)
    csrfTokenSetzen(neu.csrf_token)
  }, [])

  // Beim Laden der Seite prüfen, ob eine Sitzung besteht. Das Cookie schickt der Browser
  // mit; die Oberfläche selbst weiß nichts davon (es ist httpOnly).
  useEffect(() => {
    let abgebrochen = false

    void (async () => {
      const { data } = await api.GET('/api/auth/ich')
      if (abgebrochen) return
      if (data) {
        nutzerSetzen(data as AngemeldeterNutzer)
      } else {
        setNutzer(null)
        csrfTokenSetzen(null)
      }
      setLaedt(false)
    })()

    return () => {
      abgebrochen = true
    }
  }, [nutzerSetzen])

  // Läuft die Sitzung während der Arbeit ab, meldet der Client das über ein Ereignis.
  useEffect(() => {
    const behandeln = () => {
      setNutzer(null)
      csrfTokenSetzen(null)
    }
    window.addEventListener(ABGEMELDET_EREIGNIS, behandeln)
    return () => window.removeEventListener(ABGEMELDET_EREIGNIS, behandeln)
  }, [])

  const anmelden = useCallback(
    async (email: string, passwort: string, angemeldetBleiben: boolean) => {
      const { data, error } = await api.POST('/api/auth/anmelden', {
        body: { email, passwort, angemeldet_bleiben: angemeldetBleiben },
      })
      if (data) {
        nutzerSetzen(data as AngemeldeterNutzer)
        return { ok: true } as const
      }
      return { ok: false, fehler: fehlerAuslesen(error) } as const
    },
    [nutzerSetzen],
  )

  const abmelden = useCallback(async () => {
    await api.POST('/api/auth/abmelden', {})
    setNutzer(null)
    csrfTokenSetzen(null)
  }, [])

  const wert = useMemo<SitzungZustand>(
    () => ({
      nutzer,
      laedt,
      darf: (recht: string) => Boolean(nutzer && recht in nutzer.rechte),
      scope: (recht: string) =>
        nutzer?.rechte[recht] === 'alle' ? ('alle' as const) : ('eigene' as const),
      anmelden,
      abmelden,
      nutzerSetzen,
    }),
    [nutzer, laedt, anmelden, abmelden, nutzerSetzen],
  )

  return <Kontext.Provider value={wert}>{children}</Kontext.Provider>
}

export function useSitzung(): SitzungZustand {
  const wert = useContext(Kontext)
  if (!wert) {
    throw new Error('useSitzung braucht einen SitzungProvider darüber.')
  }
  return wert
}
