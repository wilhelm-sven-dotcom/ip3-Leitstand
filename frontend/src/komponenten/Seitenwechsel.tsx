/**
 * Seitenwechsel unter einer Liste (design/Projektliste.dc.html).
 *
 * Die Zählung steht links, die Knöpfe rechts – wie im Mockup („1–10 von 23 Projekten").
 * Gezählt wird ab 1, nicht ab 0: die Anzeige ist für Menschen, nicht für den Versatz.
 *
 * Bei einer einzigen Seite verschwindet die Leiste. Eine Leiste, die „1–6 von 6" und zwei graue
 * Knöpfe zeigt, kostet Platz und sagt nichts.
 */

import { Knopf } from "./Knopf";
import { anzahl as anzahlText, zahl } from "@/format/formate";

type Props = {
  /** Wie viele Einträge insgesamt zur Auswahl passen. */
  gesamt: number;
  versatz: number;
  anzahl: number;
  /**
   * Wort für die Einträge, Einzahl und Mehrzahl.
   *
   * Die Mehrzahl steht hier nach „von" und gehört deshalb in den **Dativ**: „von 530
   * Projekten", nicht „von 530 Projekte". Bei „Kunden" fallen beide Formen zusammen, bei
   * „Projekte" nicht – und genau das liest man sofort.
   */
  einheit: [string, string];
  onVersatz: (versatz: number) => void;
};

export function Seitenwechsel({
  gesamt,
  versatz,
  anzahl,
  einheit,
  onVersatz,
}: Props) {
  if (gesamt <= anzahl) return null;

  const von = versatz + 1;
  const bis = Math.min(versatz + anzahl, gesamt);
  const seite = Math.floor(versatz / anzahl) + 1;
  const seiten = Math.max(1, Math.ceil(gesamt / anzahl));

  return (
    <nav className="seitenwechsel" aria-label="Seiten">
      <span className="seitenwechsel__zaehlung">
        {zahl(von)}–{zahl(bis)} von {anzahlText(gesamt, einheit[0], einheit[1])}
      </span>
      <span className="seitenwechsel__knoepfe">
        <Knopf
          art="sekundaer"
          klein
          disabled={versatz === 0}
          onClick={() => onVersatz(Math.max(0, versatz - anzahl))}
        >
          Zurück
        </Knopf>
        <span className="seitenwechsel__seite">
          Seite {zahl(seite)} von {zahl(seiten)}
        </span>
        <Knopf
          art="sekundaer"
          klein
          disabled={bis >= gesamt}
          onClick={() => onVersatz(versatz + anzahl)}
        >
          Weiter
        </Knopf>
      </span>
    </nav>
  );
}
