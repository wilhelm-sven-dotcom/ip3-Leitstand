/**
 * Datentabelle (design/Komponenten.dc.html).
 *
 * Regeln aus dem Designsystem, hier festgeschrieben, damit sie nicht je Seite neu entschieden
 * werden: Kopf in ip³ Blau und beim Scrollen stehenbleibend, Zebrastreifen, Zahlen
 * rechtsbündig in Space Grotesk, **Einheit im Spaltenkopf statt in jeder Zelle**. Letzteres
 * ist mehr als Kosmetik: eine Spalte „Betrag netto (€)" mit reinen Zahlen liest sich
 * spaltenweise, eine mit 40-mal „€" nicht.
 */

import type { ReactNode } from 'react'

export type Spalte<T> = {
  /** Beschriftung samt Einheit in Klammern, z. B. „Leistung (kWp)". */
  kopf: string
  /** Zellinhalt, fertig formatiert. */
  zelle: (zeile: T) => ReactNode
  /** Zahlenspalte: rechtsbündig, Space Grotesk, Tabellenziffern. */
  zahl?: boolean
  /** Hervorgehoben: die Spalte, an der man die Zeile erkennt (Kunde, Bezeichnung). */
  hervorgehoben?: boolean
  breite?: string
}

type Props<T> = {
  spalten: Spalte<T>[]
  zeilen: T[]
  /** Eindeutiger Schlüssel je Zeile. */
  schluessel: (zeile: T) => string | number
  /** Zeile anklickbar machen – öffnet üblicherweise das Seitenpanel. */
  onZeileKlick?: (zeile: T) => void
  /** Wird anstelle der Tabelle gezeigt, wenn keine Zeilen vorliegen. */
  leer?: ReactNode
  /** Beschriftung für Bildschirmleser, wenn die Tabelle keine sichtbare Überschrift hat. */
  beschriftung?: string
}

export function DataTable<T>({
  spalten,
  zeilen,
  schluessel,
  onZeileKlick,
  leer,
  beschriftung,
}: Props<T>) {
  if (zeilen.length === 0 && leer) {
    return <>{leer}</>
  }

  return (
    <div className="tabelle-huelle">
      <div className="tabelle-scroll">
        <table className="tabelle">
          {beschriftung ? <caption className="nur-vorlesen">{beschriftung}</caption> : null}
          <thead>
            <tr>
              {spalten.map((spalte) => (
                <th
                  key={spalte.kopf}
                  className={spalte.zahl ? 'rechts' : undefined}
                  style={spalte.breite ? { width: spalte.breite } : undefined}
                  scope="col"
                >
                  {spalte.kopf}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {zeilen.map((zeile) => (
              <tr
                key={schluessel(zeile)}
                onClick={onZeileKlick ? () => onZeileKlick(zeile) : undefined}
                style={onZeileKlick ? { cursor: 'pointer' } : undefined}
              >
                {spalten.map((spalte) => {
                  const klassen: string[] = []
                  if (spalte.zahl) klassen.push('zahl', 'rechts')
                  if (spalte.hervorgehoben) klassen.push('hervorgehoben')
                  return (
                    <td key={spalte.kopf} className={klassen.join(' ') || undefined}>
                      {spalte.zelle(zeile)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
