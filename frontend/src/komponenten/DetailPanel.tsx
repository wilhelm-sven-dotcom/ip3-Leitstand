/**
 * Seitenpanel, 420 px (design/README.md, design/Projektdetail.dc.html).
 *
 * Für Details und Bearbeitung neben der Liste: die Liste bleibt sichtbar, der Zusammenhang geht
 * nicht verloren. Ein eigener Bildschirm je Datensatz würde bei 530 Projekten dauernd hin und
 * her springen.
 *
 * Die Fokus-Falle ist dieselbe wie im `ConfirmDialog` und aus demselben Grund: solange das Panel
 * offen ist, darf die Tabulatortaste nicht dahinter geraten – sonst tippt jemand in ein Feld,
 * das er nicht sieht. Escape schließt; das ist bei einem Panel unkritisch, weil nichts
 * unwiderruflich ist.
 */

import { useCallback, useEffect, useRef } from "react";
import type { ReactNode } from "react";

type Props = {
  offen: boolean;
  titel: string;
  /** Zweite Zeile im Kopf: Nummer, Status, Ort – was die Zeile eindeutig macht. */
  meta?: ReactNode;
  children: ReactNode;
  /** Knopfzeile am Fuß. Ohne Inhalt gibt es keinen Fuß. */
  fuss?: ReactNode;
  onSchliessen: () => void;
};

const FOKUSSIERBAR =
  "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), " +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function DetailPanel({
  offen,
  titel,
  meta,
  children,
  fuss,
  onSchliessen,
}: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const schliessen = useRef<HTMLButtonElement>(null);

  const tastatur = useCallback(
    (ereignis: KeyboardEvent) => {
      if (ereignis.key === "Escape") {
        ereignis.preventDefault();
        onSchliessen();
        return;
      }
      if (ereignis.key !== "Tab" || !panel.current) return;

      const elemente = Array.from(
        panel.current.querySelectorAll<HTMLElement>(FOKUSSIERBAR),
      ).filter((element) => element.offsetParent !== null);
      if (elemente.length === 0) return;

      const erstes = elemente[0]!;
      const letztes = elemente[elemente.length - 1]!;
      if (ereignis.shiftKey && document.activeElement === erstes) {
        ereignis.preventDefault();
        letztes.focus();
      } else if (!ereignis.shiftKey && document.activeElement === letztes) {
        ereignis.preventDefault();
        erstes.focus();
      }
    },
    [onSchliessen],
  );

  useEffect(() => {
    if (!offen) return;
    document.addEventListener("keydown", tastatur);
    // Der Fokus startet auf dem Schließen-Knopf: von dort geht es mit Tab in den Inhalt, und
    // wer nur schauen wollte, kommt mit einem Tastendruck wieder heraus.
    schliessen.current?.focus();
    return () => document.removeEventListener("keydown", tastatur);
  }, [offen, tastatur]);

  if (!offen) return null;

  return (
    <>
      <div
        className="panel-schleier"
        onClick={onSchliessen}
        aria-hidden="true"
      />
      <aside
        className="panel"
        role="dialog"
        aria-modal="true"
        aria-label={titel}
        ref={panel}
      >
        <header className="panel__kopf">
          <div>
            <h2 className="panel__titel">{titel}</h2>
            {meta ? <div className="panel__meta">{meta}</div> : null}
          </div>
          <button
            type="button"
            className="panel__schliessen"
            onClick={onSchliessen}
            ref={schliessen}
            aria-label="Panel schließen"
          >
            ×
          </button>
        </header>
        <div className="panel__inhalt">{children}</div>
        {fuss ? <footer className="panel__fuss">{fuss}</footer> : null}
      </aside>
    </>
  );
}
