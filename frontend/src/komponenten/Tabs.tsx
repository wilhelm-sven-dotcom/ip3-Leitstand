/**
 * Reiter im Projektdetail (design/Projektdetail.dc.html).
 *
 * Reiter, die es noch nicht gibt, werden **gezeigt und als „ab Phase n" gekennzeichnet**, statt
 * sie zu verstecken. Das Mockup führt vier Reiter; wer nur einen sieht, hält den Rest für
 * verloren. Ein gesperrter Reiter ist ein `<button disabled>` mit `title` – keine Fläche, die
 * nach Klick aussieht und nichts tut.
 */

import type { ReactNode } from "react";

export type Reiter = {
  schluessel: string;
  beschriftung: string;
  /** Gesetzt: der Reiter ist noch nicht gebaut, der Text nennt die Phase. */
  spaeter?: string;
};

type Props = {
  reiter: Reiter[];
  aktiv: string;
  onWechsel: (schluessel: string) => void;
  /** Rechts in der Reiterzeile, z. B. der Auftragswert. */
  rechts?: ReactNode;
};

export function Tabs({ reiter, aktiv, onWechsel, rechts }: Props) {
  return (
    <div className="reiter" role="tablist">
      {reiter.map((r) => (
        <button
          key={r.schluessel}
          type="button"
          role="tab"
          aria-selected={r.schluessel === aktiv}
          className={
            r.schluessel === aktiv
              ? "reiter__knopf reiter__knopf--aktiv"
              : "reiter__knopf"
          }
          disabled={Boolean(r.spaeter)}
          title={r.spaeter}
          onClick={() => onWechsel(r.schluessel)}
        >
          {r.beschriftung}
          {r.spaeter ? (
            <span className="reiter__spaeter">{r.spaeter}</span>
          ) : null}
        </button>
      ))}
      {rechts ? <div className="reiter__rechts">{rechts}</div> : null}
    </div>
  );
}
