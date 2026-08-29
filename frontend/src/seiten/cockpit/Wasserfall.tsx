/**
 * Wasserfall vom Umsatz zur Über-/Unterdeckung (design/Firmen-Cockpit.dc.html).
 *
 * Fünf Stufen, die Abzüge schwebend an dem Wert ansetzend, bei dem sie enden – die Aussage ist,
 * wo das Geld hingeht, und die sieht man nur so. Summenstufen stehen auf dem Nullpunkt.
 *
 * Farben nach PLAN §11: Summen in ip³ Blau, Abzüge in Akzent-Rot, eine Unterdeckung als
 * gefüllter roter Balken unter der Nulllinie. **Kein Grün** – das Corporate Design schließt
 * Ampelgrün ausdrücklich aus.
 *
 * Gezeichnet mit Rechtecken und nicht mit einer Diagrammbibliothek: fünf Balken rechtfertigen
 * keine Abhängigkeit, und die Beschriftung soll denselben Zahlenformaten folgen wie der Rest
 * der Anwendung.
 */

import type { CSSProperties } from "react";
import { euroKurz } from "@/format/formate";
import { maßstab, type Stufe } from "./begriffe";

type Props = {
  stufen: Stufe[];
  /** Break-even-Umsatz in Cent – als waagerechte Marke, wenn er ins Bild passt. */
  breakEvenCent?: number | null;
};

const HOEHE = 210;

export function Wasserfall({ stufen: reihe, breakEvenCent = null }: Props) {
  const skala = maßstab(reihe);
  const einheit = HOEHE / skala;

  return (
    <div className="wasserfall">
      {breakEvenCent !== null && breakEvenCent > 0 && breakEvenCent <= skala ? (
        <div
          className="wasserfall__marke"
          style={{ bottom: `${breakEvenCent * einheit}px` }}
        >
          <span>Break-even {euroKurz(breakEvenCent)} Umsatz</span>
        </div>
      ) : null}

      <div
        className="wasserfall__balken"
        style={{ "--saeulenhoehe": `${HOEHE}px` } as CSSProperties}
      >
        {reihe.map((stufe) => {
          const hoehe = Math.max(Math.abs(stufe.betrag) * einheit, 2);
          const unten =
            stufe.betrag < 0 ? Math.max(stufe.basis * einheit, 0) : 0;
          const negativ = stufe.betrag < 0;
          const art = stufe.summe
            ? negativ
              ? "unterdeckung"
              : "summe"
            : "abzug";
          return (
            <div className="wasserfall__spalte" key={stufe.name}>
              <div className="wasserfall__saeulenraum">
                {/* Die Beschriftung sitzt über *ihrem* Balken, nicht auf fester Höhe – sonst
                    verschwindet sie hinter der höchsten Säule. */}
                <div
                  className="wasserfall__wert"
                  style={{ bottom: `${unten + hoehe + 6}px` }}
                >
                  {negativ ? "−" : ""}
                  {euroKurz(Math.abs(stufe.betrag))}
                </div>
                <div
                  className={`wasserfall__saeule wasserfall__saeule--${art}`}
                  style={{ height: `${hoehe}px`, bottom: `${unten}px` }}
                  aria-hidden="true"
                />
              </div>
              <div className="wasserfall__name">{stufe.name}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
