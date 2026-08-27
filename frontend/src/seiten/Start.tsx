/**
 * Startseite (design/Start.dc.html).
 *
 * Die Startseite ist der Arbeitsvorrat: was heute zu tun ist. In Phase 0 gibt es dafür noch
 * keine Daten – Projekte, Rechnungsvorschläge und Fristen entstehen in den Phasen 1 bis 6.
 * Statt einer leeren Fläche stehen hier Leerzustände, die den nächsten Schritt benennen, und
 * der **Datenstand**: wann die Sicherung zuletzt lief und wann Daten zuletzt eingelesen wurden.
 *
 * Der Datenstand ist der Grund, warum diese Seite in Phase 0 überhaupt etwas zeigt: PLAN §2
 * verlangt, dass ein ausgefallener nächtlicher Lauf auffällt. Ein Werkzeug, das seine eigenen
 * Störungen verschweigt, ist im Ernstfall wertlos.
 */

import { useQuery } from '@tanstack/react-query'
import { PageTitle } from '@/komponenten/PageTitle'
import { EmptyState } from '@/komponenten/EmptyState'
import { Datenstand } from '@/seiten/Datenstand'
import { useSitzung } from '@/sitzung/SitzungKontext'
import { api } from '@/api/client'
import { begruessung, vorname, wochentagDatum } from '@/format/formate'

export function Start() {
  const { nutzer, darf } = useSitzung()

  const status = useQuery({
    queryKey: ['systemstatus'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/systemstatus')
      if (error) throw error
      return data
    },
    enabled: darf('systemstatus.lesen'),
    // Der Datenstand ändert sich nachts, nicht im Minutentakt.
    staleTime: 5 * 60 * 1000,
  })

  const heute = new Date()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-6)' }}>
      <div>
        <div className="seitentitel__meta" style={{ marginBottom: 6 }}>
          {wochentagDatum(heute)}
        </div>
        <PageTitle meta={nutzer ? begruessung(vorname(nutzer.name), heute) : undefined}>
          Start
        </PageTitle>
      </div>

      <section>
        <h2 className="karte__titel" style={{ marginBottom: 'var(--abstand-3)' }}>
          Heute wichtig
        </h2>
        <EmptyState
          titel="Noch keine Vorgänge."
          text={
            'Der Arbeitsvorrat füllt sich, sobald Projekte und Zahlungspläne im Leitstand ' +
            'stehen. Die Übernahme der Bestandsdaten ist der nächste Schritt.'
          }
        />
      </section>

      {darf('systemstatus.lesen') ? (
        <Datenstand
          status={status.data ?? null}
          laedt={status.isLoading}
          fehler={status.isError}
          darfStarten={darf('admin.jobs')}
          neuLaden={() => void status.refetch()}
        />
      ) : null}
    </div>
  )
}
