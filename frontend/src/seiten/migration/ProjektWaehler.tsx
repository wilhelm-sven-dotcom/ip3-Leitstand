/**
 * Projektauswahl im Seitenpanel (PLAN §9).
 *
 * Für die Fälle, in denen kein Vorschlag passt. Die Liste zeigt nicht nur den Namen, sondern
 * Leistung, Auftragsdatum und Auftragswert: 23 Kundennamen der Teamliste kommen mehrfach vor,
 * und **nur an diesen Angaben** ist zu erkennen, welches der Projekte gemeint ist. Ein Wähler,
 * der zweimal „Huber, Pressath" anbietet, ist keine Hilfe.
 */

import { useMemo, useState } from "react";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Knopf } from "@/komponenten/Knopf";
import { datum, euro, leistung } from "@/format/formate";
import { passtZurSuche } from "@/format/vergleich";

export type Kandidat = {
  zeile: number;
  kunde: string;
  ort?: string | null;
  auftrag_vom?: string | null;
  ab_wert_netto?: number | null;
  pv_kwp?: string | null;
  pl_name?: string | null;
};

type Props = {
  offen: boolean;
  kundenteil: string;
  kandidaten: Kandidat[];
  /** Beträge nur zeigen, wenn der Nutzer sie sehen darf (PLAN §4). */
  darfWerteSehen: boolean;
  onWaehlen: (zeile: number) => void;
  onSchliessen: () => void;
};

function passt(kandidat: Kandidat, suche: string): boolean {
  // Die Leistung gehört in die durchsuchten Felder: zwei Projekte desselben Kunden
  // unterscheiden sich im Bestand oft nur über die kWp („Pöllath, Weiden 210,67 kWp").
  return passtZurSuche(
    suche,
    kandidat.kunde,
    kandidat.ort,
    kandidat.pl_name,
    kandidat.pv_kwp,
  );
}

export function ProjektWaehler({
  offen,
  kundenteil,
  kandidaten,
  darfWerteSehen,
  onWaehlen,
  onSchliessen,
}: Props) {
  const [suche, setSuche] = useState("");

  const gefiltert = useMemo(() => {
    const treffer = kandidaten.filter((k) => passt(k, suche));
    // Bei 530 Projekten würde eine vollständige Liste die Suche unbrauchbar machen.
    return treffer.slice(0, 40);
  }, [kandidaten, suche]);

  return (
    <DetailPanel
      offen={offen}
      titel="Projekt zuordnen"
      meta={<>Auftragsliste: {kundenteil}</>}
      onSchliessen={onSchliessen}
      fuss={
        <Knopf art="sekundaer" onClick={onSchliessen}>
          Abbrechen
        </Knopf>
      }
    >
      <FormRow
        label="Suche"
        type="search"
        value={suche}
        onChange={(ereignis) => setSuche(ereignis.target.value)}
        placeholder="Kunde, Ort, Projektleiter oder Leistung"
        hinweis={"Mehrere Wörter werden alle gesucht, z. B. „huber 210“."}
        autoFocus
      />

      {gefiltert.length === 0 ? (
        <EmptyState
          titel="Kein Projekt gefunden"
          text={
            "Andere Schreibweise versuchen – oder das Panel schließen und „als eigenes Projekt anlegen“ wählen."
          }
        />
      ) : (
        <ul className="waehler">
          {gefiltert.map((kandidat) => (
            <li key={kandidat.zeile}>
              <button
                type="button"
                className="waehler__eintrag"
                onClick={() => onWaehlen(kandidat.zeile)}
              >
                <span className="waehler__name">{kandidat.kunde}</span>
                <span className="waehler__meta">
                  {[
                    // Den Ort nur, wenn er nicht schon im Kundentext steht: „Pöllath, Weiden ·
                    // Weiden" liest sich schlechter, und die Liste ist zum Vergleichen da.
                    kandidat.ort && !kandidat.kunde.includes(kandidat.ort)
                      ? kandidat.ort
                      : null,
                    kandidat.pv_kwp ? leistung(Number(kandidat.pv_kwp)) : null,
                    kandidat.auftrag_vom ? datum(kandidat.auftrag_vom) : null,
                    darfWerteSehen && kandidat.ab_wert_netto
                      ? euro(kandidat.ab_wert_netto)
                      : null,
                    kandidat.pl_name,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {kandidaten.filter((k) => passt(k, suche)).length > gefiltert.length ? (
        <p className="waehler__hinweis">
          Es gibt weitere Treffer. Die Suche eingrenzen, damit die Auswahl
          überschaubar bleibt.
        </p>
      ) : null}
    </DetailPanel>
  );
}
