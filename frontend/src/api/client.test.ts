/**
 * API-Client: CSRF-Kopfzeile, Wiederholung und 401-Behandlung.
 *
 * Diese drei Punkte sind unsichtbar, solange sie funktionieren – und schwer zu finden, wenn
 * nicht. Ein fehlender CSRF-Kopf äußert sich als „Sicherheitsschlüssel fehlt" ohne erkennbaren
 * Grund; eine fehlende 401-Behandlung als Oberfläche, die leere Listen zeigt, statt zur
 * Anmeldung zu führen.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ABGEMELDET_EREIGNIS,
  csrfTokenLesen,
  csrfTokenSetzen,
  fehlerAuslesen,
  fetchMitSitzung,
} from './client'

const ECHTES_FETCH = globalThis.fetch

function antwort(status: number, koerper: unknown = {}): Response {
  return new Response(JSON.stringify(koerper), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('CSRF-Kopfzeile', () => {
  beforeEach(() => {
    csrfTokenSetzen('token-abc')
  })

  afterEach(() => {
    globalThis.fetch = ECHTES_FETCH
    csrfTokenSetzen(null)
    vi.restoreAllMocks()
  })

  it('wird bei schreibenden Anfragen mitgeschickt', async () => {
    const gefaelscht = vi.fn().mockResolvedValue(antwort(200))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    await fetchMitSitzung(new Request('http://test/api/projekte', { method: 'POST' }))

    const gesendet = gefaelscht.mock.calls[0]![0] as Request
    expect(gesendet.headers.get('X-CSRF-Token')).toBe('token-abc')
  })

  it.each(['PUT', 'PATCH', 'DELETE'])('wird auch bei %s mitgeschickt', async (methode) => {
    const gefaelscht = vi.fn().mockResolvedValue(antwort(200))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    await fetchMitSitzung(new Request('http://test/api/projekte/1', { method: methode }))

    const gesendet = gefaelscht.mock.calls[0]![0] as Request
    expect(gesendet.headers.get('X-CSRF-Token')).toBe('token-abc')
  })

  it('wird bei GET weggelassen', async () => {
    // Eine Leseanfrage ohne Sitzung soll nicht am fehlenden Token scheitern.
    const gefaelscht = vi.fn().mockResolvedValue(antwort(200))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    await fetchMitSitzung(new Request('http://test/api/projekte'))

    const gesendet = gefaelscht.mock.calls[0]![0] as Request
    expect(gesendet.headers.get('X-CSRF-Token')).toBeNull()
  })

  it('fehlt, solange kein Token bekannt ist', async () => {
    csrfTokenSetzen(null)
    const gefaelscht = vi.fn().mockResolvedValue(antwort(200))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    await fetchMitSitzung(new Request('http://test/api/projekte', { method: 'POST' }))

    const gesendet = gefaelscht.mock.calls[0]![0] as Request
    expect(gesendet.headers.get('X-CSRF-Token')).toBeNull()
  })
})

describe('Wiederholung bei ungültigem Token', () => {
  afterEach(() => {
    globalThis.fetch = ECHTES_FETCH
    csrfTokenSetzen(null)
    vi.restoreAllMocks()
  })

  it('lädt das Token nach und wiederholt genau einmal', async () => {
    csrfTokenSetzen('veraltet')
    const gefaelscht = vi
      .fn()
      // Erster Versuch: Token abgelehnt.
      .mockResolvedValueOnce(antwort(403, { code: 'csrf_ungueltig', meldung: 'ungültig' }))
      // Nachladen des Tokens.
      .mockResolvedValueOnce(antwort(200, { csrf_token: 'frisch' }))
      // Wiederholung.
      .mockResolvedValueOnce(antwort(200, { ok: true }))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    const ergebnis = await fetchMitSitzung(
      new Request('http://test/api/projekte', { method: 'POST' }),
    )

    expect(ergebnis.status).toBe(200)
    expect(gefaelscht).toHaveBeenCalledTimes(3)
    expect(csrfTokenLesen()).toBe('frisch')
    const wiederholung = gefaelscht.mock.calls[2]![0] as Request
    expect(wiederholung.headers.get('X-CSRF-Token')).toBe('frisch')
  })

  it('wiederholt nicht endlos', async () => {
    csrfTokenSetzen('veraltet')
    const gefaelscht = vi
      .fn()
      .mockResolvedValueOnce(antwort(403, { code: 'csrf_ungueltig', meldung: 'ungültig' }))
      .mockResolvedValueOnce(antwort(200, { csrf_token: 'frisch' }))
      .mockResolvedValue(antwort(403, { code: 'csrf_ungueltig', meldung: 'ungültig' }))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    const ergebnis = await fetchMitSitzung(
      new Request('http://test/api/projekte', { method: 'POST' }),
    )

    expect(ergebnis.status).toBe(403)
    // Ein Versuch, ein Nachladen, eine Wiederholung – nicht mehr.
    expect(gefaelscht).toHaveBeenCalledTimes(3)
  })

  it('wiederholt nicht bei einem anderen 403', async () => {
    // Eine fehlende Berechtigung ist kein Tokenproblem; eine Wiederholung wäre sinnlos.
    csrfTokenSetzen('token-abc')
    const gefaelscht = vi
      .fn()
      .mockResolvedValue(antwort(403, { code: 'keine_berechtigung', meldung: 'nein' }))
    globalThis.fetch = gefaelscht as unknown as typeof fetch

    await fetchMitSitzung(new Request('http://test/api/projekte', { method: 'POST' }))

    expect(gefaelscht).toHaveBeenCalledTimes(1)
  })
})

describe('401', () => {
  afterEach(() => {
    globalThis.fetch = ECHTES_FETCH
    csrfTokenSetzen(null)
    vi.restoreAllMocks()
  })

  it('löst das Abmelde-Ereignis aus und verwirft das Token', async () => {
    csrfTokenSetzen('token-abc')
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(antwort(401, { code: 'nicht_angemeldet' })) as unknown as typeof fetch

    const gemeldet = vi.fn()
    window.addEventListener(ABGEMELDET_EREIGNIS, gemeldet)
    await fetchMitSitzung(new Request('http://test/api/projekte'))
    window.removeEventListener(ABGEMELDET_EREIGNIS, gemeldet)

    expect(gemeldet).toHaveBeenCalledTimes(1)
    expect(csrfTokenLesen()).toBeNull()
  })
})

describe('fehlerAuslesen', () => {
  it('übernimmt einen Fehlerkörper des Backends', () => {
    const ausgelesen = fehlerAuslesen({
      code: 'beleg_festgeschrieben',
      meldung: 'Der Beleg ist festgeschrieben.',
      naechster_schritt: 'Storno erzeugen.',
      felder: { betrag: 'Zu hoch.' },
    })
    expect(ausgelesen.code).toBe('beleg_festgeschrieben')
    expect(ausgelesen.felder?.betrag).toBe('Zu hoch.')
  })

  it('liefert für Unerwartetes eine Meldung mit nächstem Schritt', () => {
    // Ein Proxy-Fehler oder eine HTML-Seite darf nicht als „undefined" auf dem Bildschirm landen.
    for (const eingabe of [undefined, null, 'kaputt', 42, {}, { fehler: 'irgendwas' }]) {
      const ausgelesen = fehlerAuslesen(eingabe)
      expect(ausgelesen.meldung.length).toBeGreaterThan(0)
      expect(ausgelesen.naechster_schritt.length).toBeGreaterThan(0)
    }
  })
})
