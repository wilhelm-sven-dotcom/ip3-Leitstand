/**
 * Statusbadge – genau acht Zustände, überall gleich (design/README.md).
 *
 * Die Beschränkung auf acht ist Absicht: sobald jede Seite eigene Zustände erfindet, kann
 * niemand mehr auf einen Blick lesen, was ein Badge bedeutet. Ein unbekannter Zustand fällt
 * deshalb in der Entwicklung mit einer Meldung auf, statt still als graues Kästchen
 * durchzugehen.
 */

export type BadgeZustand =
  | 'entwurf'
  | 'geplant'
  | 'gestellt'
  | 'festgeschrieben'
  | 'bezahlt'
  | 'ueberfaellig'
  | 'frist'
  | 'storniert'

const BESCHRIFTUNG: Record<BadgeZustand, string> = {
  entwurf: 'Entwurf',
  geplant: 'Geplant',
  gestellt: 'Gestellt',
  festgeschrieben: 'Festgeschrieben',
  bezahlt: 'Bezahlt',
  ueberfaellig: 'Überfällig',
  frist: 'Frist bald fällig',
  storniert: 'Storniert',
}

export const BADGE_ZUSTAENDE = Object.keys(BESCHRIFTUNG) as BadgeZustand[]

type Props = {
  zustand: BadgeZustand
  /** Abweichende Beschriftung, wenn der Zusammenhang eine genauere Angabe verlangt. */
  text?: string
  titel?: string
}

export function StatusBadge({ zustand, text, titel }: Props) {
  const beschriftung = BESCHRIFTUNG[zustand]

  if (!beschriftung) {
    // In der Entwicklung laut, im Betrieb still: eine Fehlermeldung auf dem Bildschirm
    // wäre für den Nutzer nutzlos.
    if (import.meta.env.DEV) {
      throw new Error(
        `Unbekannter Badge-Zustand: ${zustand}. Erlaubt sind: ${BADGE_ZUSTAENDE.join(', ')}. ` +
          'Neue Zustände gehören zuerst ins Designsystem (design/Komponenten.dc.html).',
      )
    }
    return null
  }

  return (
    <span className={`badge badge--${zustand}`} title={titel}>
      {text ?? beschriftung}
    </span>
  )
}
