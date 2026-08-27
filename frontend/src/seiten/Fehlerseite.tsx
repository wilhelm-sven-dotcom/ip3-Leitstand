/**
 * Seite für unbekannte Adressen und unerwartete Fehler.
 *
 * Kein „404 Not Found": das sagt einer Buchhaltungskraft nichts. Stattdessen der Weg zurück.
 */

import { Link, useRouteError } from 'react-router-dom'
import { PageTitle } from '@/komponenten/PageTitle'
import { EmptyState } from '@/komponenten/EmptyState'

export function NichtGefunden() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-5)' }}>
      <PageTitle>Diese Seite gibt es nicht</PageTitle>
      <EmptyState
        titel="Die Adresse führt nirgendwohin."
        text="Möglicherweise ist ein Verweis veraltet oder die Seite kommt erst mit einer späteren Erweiterung."
        aktion={
          <Link className="knopf knopf--primaer knopf--klein" to="/">
            Zur Startseite
          </Link>
        }
      />
    </div>
  )
}

export function Fehlerseite() {
  const fehler = useRouteError()
  // Der technische Text nur in der Entwicklung – im Betrieb hilft er niemandem.
  const einzelheit =
    import.meta.env.DEV && fehler instanceof Error ? fehler.message : undefined

  return (
    <div style={{ padding: 'var(--abstand-6)' }}>
      <PageTitle>Etwas ist schiefgegangen</PageTitle>
      <div style={{ marginTop: 'var(--abstand-5)' }}>
        <EmptyState
          titel="Die Seite konnte nicht angezeigt werden."
          text={
            einzelheit ??
            'Bitte laden Sie die Seite neu. Bleibt es dabei, geben Sie Sven Bescheid – im Protokoll auf dem Host steht, was passiert ist.'
          }
          aktion={
            <button
              type="button"
              className="knopf knopf--primaer knopf--klein"
              onClick={() => window.location.reload()}
            >
              Seite neu laden
            </button>
          }
        />
      </div>
    </div>
  )
}
