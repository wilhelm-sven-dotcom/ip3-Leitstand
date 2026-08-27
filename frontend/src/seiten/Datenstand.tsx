/**
 * Datenstand-Leiste der Startseite (PLAN §2, §7).
 *
 * Bewusste Abweichung von den Mockups: dort gibt es keinen Systemstatus, PLAN §2 und §7
 * verlangen ihn aber ausdrücklich („stille Job-Ausfälle darf es nicht geben"). Umgesetzt im
 * Duktus des Designsystems – als ruhige Leiste, kein Alarmpaneel. Farbe bekommt nur, was nicht
 * in Ordnung ist; solange alles läuft, steht hier grauer Text.
 *
 * Siehe design/UMSETZUNG.md, Abweichung 2.
 */

import { useState } from 'react'
import { Knopf } from '@/komponenten/Knopf'
import { Meldung } from '@/komponenten/Meldung'
import { api, fehlerAuslesen } from '@/api/client'
import { datumZeit } from '@/format/formate'
import './datenstand.css'

type JobStatus = {
  schluessel: string
  bezeichnung: string
  beschreibung: string
  status: string
  text: string
  eingerichtet: boolean
  ab_phase: number
  letzter_lauf?: string | null
  letzter_erfolg?: string | null
  meldung?: string | null
}

type Systemstatus = {
  gesamtstatus: string
  jobs: JobStatus[]
  hinweise: string[]
  zeitplan_laeuft: boolean
  naechster_lauf?: string | null
}

type Props = {
  status: Systemstatus | null
  laedt: boolean
  fehler: boolean
  darfStarten: boolean
  neuLaden: () => void
}

/** Punktfarbe je Zustand. Kein Grün für „in Ordnung" – dort ist der Punkt ip³ Blau (PLAN §11). */
const PUNKTFARBE: Record<string, string> = {
  ok: 'var(--ip3-blau)',
  warnung: 'var(--akzent-rot)',
  fehler: 'var(--akzent-rot)',
  unbekannt: 'var(--linie-badge)',
}

export function Datenstand({ status, laedt, fehler, darfStarten, neuLaden }: Props) {
  const [laeuftJob, setLaeuftJob] = useState<string | null>(null)
  const [jobFehler, setJobFehler] = useState<string | null>(null)

  async function jobStarten(schluessel: string) {
    setLaeuftJob(schluessel)
    setJobFehler(null)
    const { error } = await api.POST('/api/systemstatus/jobs/{job}/starten', {
      params: { path: { job: schluessel } },
    })
    setLaeuftJob(null)
    if (error) {
      const ausgelesen = fehlerAuslesen(error)
      setJobFehler(`${ausgelesen.meldung} ${ausgelesen.naechster_schritt}`)
    }
    neuLaden()
  }

  if (fehler) {
    return (
      <section className="datenstand">
        <Meldung
          art="fehler"
          text="Der Datenstand ließ sich nicht abrufen."
          naechsterSchritt="Bitte die Seite neu laden. Bleibt es dabei, Sven informieren."
        />
      </section>
    )
  }

  if (laedt || !status) {
    return (
      <section className="datenstand">
        <div className="datenstand__kopf">
          <h2 className="datenstand__titel">Datenstand</h2>
        </div>
        <div className="datenstand__laedt">wird geladen …</div>
      </section>
    )
  }

  const eingerichtet = status.jobs.filter((job) => job.eingerichtet)
  const spaeter = status.jobs.filter((job) => !job.eingerichtet)

  return (
    <section className="datenstand">
      <div className="datenstand__kopf">
        <h2 className="datenstand__titel">Datenstand</h2>
        {status.naechster_lauf ? (
          <span className="datenstand__naechster">
            Nächster Lauf: {datumZeit(status.naechster_lauf)}
          </span>
        ) : status.zeitplan_laeuft ? null : (
          <span className="datenstand__naechster datenstand__naechster--warnung">
            Kein Zeitplan aktiv
          </span>
        )}
      </div>

      {status.hinweise.length > 0 ? (
        <div className="datenstand__hinweise">
          {status.hinweise.map((hinweis) => (
            <Meldung key={hinweis} art="hinweis" text={hinweis} />
          ))}
        </div>
      ) : null}

      {jobFehler ? (
        <div className="datenstand__hinweise">
          <Meldung art="fehler" text={jobFehler} />
        </div>
      ) : null}

      <ul className="datenstand__liste">
        {eingerichtet.map((job) => (
          <li key={job.schluessel} className="datenstand__zeile">
            <span
              className="datenstand__punkt"
              style={{ background: PUNKTFARBE[job.status] ?? 'var(--linie-badge)' }}
              aria-hidden="true"
            />
            <div className="datenstand__bezeichnung">
              {job.bezeichnung}
              <span className="datenstand__beschreibung">{job.beschreibung}</span>
            </div>
            <div
              className={
                job.status === 'ok'
                  ? 'datenstand__wert'
                  : 'datenstand__wert datenstand__wert--auffaellig'
              }
            >
              {job.text}
              {job.meldung && job.status !== 'ok' ? (
                <span className="datenstand__meldung">{job.meldung}</span>
              ) : null}
            </div>
            {darfStarten ? (
              <Knopf
                art="sekundaer"
                klein
                disabled={laeuftJob !== null}
                onClick={() => void jobStarten(job.schluessel)}
              >
                {laeuftJob === job.schluessel ? 'läuft …' : 'Jetzt ausführen'}
              </Knopf>
            ) : (
              <span />
            )}
          </li>
        ))}
      </ul>

      {spaeter.length > 0 ? (
        <p className="datenstand__spaeter">
          Kommt später: {spaeter.map((job) => `${job.bezeichnung} (Phase ${job.ab_phase})`).join(' · ')}
        </p>
      ) : null}
    </section>
  )
}
