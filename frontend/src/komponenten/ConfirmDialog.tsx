/**
 * Bestätigungsdialog (design/Festschreiben.dc.html).
 *
 * Für Vorgänge, die sich nicht zurücknehmen lassen – in erster Linie die Festschreibung einer
 * Rechnung. Drei Vorkehrungen, die alle einen Grund haben:
 *
 * * **Die Zusammenfassung zeigt die Zahlen**, die bestätigt werden. Wer nur „Wirklich
 *   festschreiben?" liest, bestätigt ohne zu prüfen.
 * * **Die Pflicht-Checkbox** schaltet den Knopf erst frei. Das verhindert das versehentliche
 *   Auslösen mit der Eingabetaste.
 * * **Escape schließt, Enter bestätigt nicht.** Ein Dialog, den man mit der Eingabetaste
 *   auslösen kann, ist bei einem unwiderruflichen Vorgang eine Falle.
 *
 * Der Fokus bleibt im Dialog, solange er offen ist (Fokus-Falle), und liegt beim Öffnen auf
 * dem Abbrechen-Knopf – nicht auf dem Bestätigen.
 */

import { useCallback, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { Knopf } from './Knopf'

type Props = {
  offen: boolean
  titel: string
  meta?: ReactNode
  /** Die Zusammenfassung – üblicherweise `<Zusammenfassung>`-Zeilen. */
  children: ReactNode
  /** Text der Pflicht-Checkbox. Ohne Text gibt es keine Checkbox (für einfache Rückfragen). */
  bestaetigungstext?: string
  bestaetigt?: boolean
  onBestaetigtChange?: (wert: boolean) => void
  bestaetigenText: string
  /** Akzent-Rot für unwiderrufliche Vorgänge. */
  unwiderruflich?: boolean
  laeuft?: boolean
  onBestaetigen: () => void
  onAbbrechen: () => void
}

const FOKUSSIERBAR =
  'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'

export function ConfirmDialog({
  offen,
  titel,
  meta,
  children,
  bestaetigungstext,
  bestaetigt = false,
  onBestaetigtChange,
  bestaetigenText,
  unwiderruflich = false,
  laeuft = false,
  onBestaetigen,
  onAbbrechen,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const abbrechenRef = useRef<HTMLButtonElement>(null)

  const tastendruck = useCallback(
    (ereignis: KeyboardEvent) => {
      if (ereignis.key === 'Escape') {
        ereignis.preventDefault()
        onAbbrechen()
        return
      }
      if (ereignis.key !== 'Tab' || !dialogRef.current) return

      // Fokus-Falle: Tab am Ende springt zum Anfang und umgekehrt. Ohne sie landet der
      // Fokus hinter dem Dialog, wo man nichts sieht und trotzdem etwas auslösen kann.
      const elemente = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(FOKUSSIERBAR),
      ).filter((element) => element.offsetParent !== null)
      if (elemente.length === 0) return

      const erstes = elemente[0]!
      const letztes = elemente[elemente.length - 1]!
      if (ereignis.shiftKey && document.activeElement === erstes) {
        ereignis.preventDefault()
        letztes.focus()
      } else if (!ereignis.shiftKey && document.activeElement === letztes) {
        ereignis.preventDefault()
        erstes.focus()
      }
    },
    [onAbbrechen],
  )

  useEffect(() => {
    if (!offen) return
    document.addEventListener('keydown', tastendruck)
    // Fokus auf Abbrechen, nicht auf Bestätigen: der harmlose Weg ist der voreingestellte.
    abbrechenRef.current?.focus()
    // Der Hintergrund soll nicht mitscrollen, solange der Dialog offen ist.
    const vorherigesOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', tastendruck)
      document.body.style.overflow = vorherigesOverflow
    }
  }, [offen, tastendruck])

  if (!offen) return null

  const freigeschaltet = bestaetigungstext ? bestaetigt : true

  return (
    <div
      className="dialog-grund"
      onMouseDown={(ereignis) => {
        // Klick auf den Grund schließt – aber nur, wenn er dort begonnen hat. Sonst schließt
        // ein Textmarkieren im Dialog den Dialog.
        if (ereignis.target === ereignis.currentTarget) onAbbrechen()
      }}
    >
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-titel"
        ref={dialogRef}
      >
        <div className="dialog__kopf">
          <h2 className="dialog__titel" id="dialog-titel">
            {titel}
            <span className="seitentitel__punkt">.</span>
          </h2>
          {meta ? <div className="dialog__meta">{meta}</div> : null}
        </div>

        <div className="dialog__inhalt">
          {children}
          {bestaetigungstext ? (
            <label className="bestaetigung">
              <input
                type="checkbox"
                checked={bestaetigt}
                onChange={(ereignis) => onBestaetigtChange?.(ereignis.target.checked)}
              />
              {bestaetigungstext}
            </label>
          ) : null}
        </div>

        <div className="dialog__fuss">
          <Knopf art="sekundaer" klein onClick={onAbbrechen} ref={abbrechenRef}>
            Abbrechen
          </Knopf>
          <Knopf
            art={unwiderruflich ? 'festschreiben' : 'primaer'}
            klein
            disabled={!freigeschaltet || laeuft}
            onClick={onBestaetigen}
          >
            {laeuft ? 'Bitte warten …' : bestaetigenText}
          </Knopf>
        </div>
      </div>
    </div>
  )
}
