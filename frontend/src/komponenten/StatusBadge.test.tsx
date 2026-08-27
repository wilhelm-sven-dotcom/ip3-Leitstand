/**
 * Statusbadges: genau acht Zustände, alle mit deutscher Beschriftung, keiner grün.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BADGE_ZUSTAENDE, StatusBadge } from './StatusBadge'
import type { BadgeZustand } from './StatusBadge'

describe('StatusBadge', () => {
  it('kennt genau acht Zustände', () => {
    // Die Beschränkung ist Absicht (design/README.md): mehr Zustände kann niemand mehr
    // auf einen Blick unterscheiden.
    expect(BADGE_ZUSTAENDE).toHaveLength(8)
  })

  it.each(BADGE_ZUSTAENDE)('stellt „%s" mit deutscher Beschriftung dar', (zustand) => {
    render(<StatusBadge zustand={zustand} />)
    const element = document.querySelector(`.badge--${zustand}`)
    expect(element).not.toBeNull()
    expect(element?.textContent?.trim().length ?? 0).toBeGreaterThan(0)
  })

  it('beschriftet die Zustände wie im Designsystem', () => {
    const erwartet: Record<BadgeZustand, string> = {
      entwurf: 'Entwurf',
      geplant: 'Geplant',
      gestellt: 'Gestellt',
      festgeschrieben: 'Festgeschrieben',
      bezahlt: 'Bezahlt',
      ueberfaellig: 'Überfällig',
      frist: 'Frist bald fällig',
      storniert: 'Storniert',
    }
    for (const [zustand, text] of Object.entries(erwartet)) {
      const { unmount } = render(<StatusBadge zustand={zustand as BadgeZustand} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      unmount()
    }
  })

  it('erlaubt eine abweichende Beschriftung', () => {
    render(<StatusBadge zustand="frist" text="Gewährleistung endet in 14 Tagen" />)
    expect(screen.getByText('Gewährleistung endet in 14 Tagen')).toBeInTheDocument()
  })

  it('meldet einen unbekannten Zustand in der Entwicklung', () => {
    // Ein unbekannter Zustand soll auffallen, nicht als graues Kästchen durchgehen.
    expect(() =>
      render(<StatusBadge zustand={'erfunden' as BadgeZustand} />),
    ).toThrow(/Unbekannter Badge-Zustand/)
  })
})
