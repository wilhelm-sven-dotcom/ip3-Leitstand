/**
 * API-Client des Leitstands.
 *
 * Aufgebaut auf `openapi-fetch` mit den Typen aus `schema.d.ts`, die aus der
 * OpenAPI-Spezifikation des Backends erzeugt werden. Eine geänderte Route bricht damit die
 * Übersetzung, statt erst im Betrieb aufzufallen.
 *
 * Drei Aufgaben, die dieser Client zusätzlich übernimmt:
 *
 * 1. **CSRF-Token bei schreibenden Anfragen.** `openapi-fetch` schickt es nicht von sich aus.
 *    Bei GET wird es weggelassen: eine Leseanfrage ohne Sitzung soll nicht daran scheitern.
 *    Das Token liegt im Speicher, nicht im `localStorage` – dort wäre es für Skripte lesbar.
 *
 * 2. **Ein Wiederholungsversuch bei ungültigem Token.** Nach einem Neuladen der Seite oder
 *    einem Passwortwechsel hat die Oberfläche unter Umständen ein veraltetes Token. Dann wird
 *    es einmal nachgeladen und die Anfrage wiederholt – statt dem Nutzer einen Fehler zu
 *    zeigen, den er nicht versteht.
 *
 * 3. **401 löst ein Ereignis aus.** Der Sitzungskontext hört darauf und führt zur
 *    Anmeldeseite. Ohne diese Stelle müsste jede Seite den Fall selbst behandeln.
 */

import createClient from 'openapi-fetch'
import type { paths } from './schema'

/** Fehlerkörper des Backends (PLAN §14). */
export type ApiFehler = {
  code: string
  meldung: string
  naechster_schritt: string
  felder?: Record<string, string>
}

/** Ereignisname für „nicht mehr angemeldet". */
export const ABGEMELDET_EREIGNIS = 'ip3:abgemeldet'

const UNSICHERE_METHODEN = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const CSRF_KOPFZEILE = 'X-CSRF-Token'

// Im Speicher, nicht im localStorage: dort überlebt es das Schließen des Browsers und ist für
// jedes Skript der Seite lesbar. Nach einem Neuladen wird es über /api/auth/csrf nachgeladen.
let csrfToken: string | null = null

export function csrfTokenSetzen(token: string | null): void {
  csrfToken = token
}

export function csrfTokenLesen(): string | null {
  return csrfToken
}

async function csrfTokenNachladen(): Promise<string | null> {
  try {
    const antwort = await fetch('/api/auth/csrf', { credentials: 'same-origin' })
    if (!antwort.ok) return null
    const koerper = (await antwort.json()) as { csrf_token?: string }
    csrfToken = koerper.csrf_token ?? null
    return csrfToken
  } catch {
    return null
  }
}

function abgemeldetMelden(): void {
  csrfToken = null
  window.dispatchEvent(new CustomEvent(ABGEMELDET_EREIGNIS))
}

/**
 * `fetch`-Ersatz mit CSRF-Kopfzeile, Wiederholung und 401-Behandlung.
 *
 * Wird `openapi-fetch` untergeschoben, damit jede Anfrage darüber läuft – auch die, die
 * später hinzukommen.
 */
export async function fetchMitSitzung(eingabe: Request): Promise<Response> {
  const methode = eingabe.method.toUpperCase()
  const braucht = UNSICHERE_METHODEN.has(methode)

  const anfrage = braucht && csrfToken ? kopfzeileSetzen(eingabe, csrfToken) : eingabe
  let antwort = await fetch(anfrage)

  // Ungültiges oder fehlendes Token: einmal nachladen und wiederholen. Nur einmal – sonst
  // entsteht bei einem echten Problem eine Endlosschleife.
  if (braucht && antwort.status === 403) {
    const koerper = await antwort
      .clone()
      .json()
      .catch(() => null)
    if (koerper && (koerper as ApiFehler).code === 'csrf_ungueltig') {
      const frisch = await csrfTokenNachladen()
      if (frisch) {
        antwort = await fetch(kopfzeileSetzen(eingabe, frisch))
      }
    }
  }

  if (antwort.status === 401) {
    abgemeldetMelden()
  }

  return antwort
}

function kopfzeileSetzen(anfrage: Request, token: string): Request {
  const kopf = new Headers(anfrage.headers)
  kopf.set(CSRF_KOPFZEILE, token)
  return new Request(anfrage, { headers: kopf })
}

export const api = createClient<paths>({
  baseUrl: '',
  credentials: 'same-origin',
  fetch: fetchMitSitzung,
})

/**
 * Fehlerkörper aus einer Antwort holen, mit Rückfallebene.
 *
 * Kommt etwas Unerwartetes zurück – ein Proxy-Fehler, eine HTML-Seite –, entsteht daraus
 * trotzdem eine Meldung mit nächstem Schritt, statt „undefined" auf dem Bildschirm.
 */
export function fehlerAuslesen(fehler: unknown): ApiFehler {
  if (
    fehler &&
    typeof fehler === 'object' &&
    'meldung' in fehler &&
    typeof (fehler as ApiFehler).meldung === 'string'
  ) {
    const bekannt = fehler as ApiFehler
    return {
      code: bekannt.code ?? 'unbekannt',
      meldung: bekannt.meldung,
      naechster_schritt: bekannt.naechster_schritt ?? 'Bitte erneut versuchen.',
      ...(bekannt.felder ? { felder: bekannt.felder } : {}),
    }
  }
  return {
    code: 'unbekannt',
    meldung: 'Die Anfrage ist fehlgeschlagen.',
    naechster_schritt:
      'Bitte die Seite neu laden und erneut versuchen. Bleibt es dabei, Sven informieren.',
  }
}
