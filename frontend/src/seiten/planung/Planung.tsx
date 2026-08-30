/**
 * Kapazität und Pipeline (PLAN §7 Phase 7).
 *
 * Zwei Reiter, zwei Berechtigungen: die Wochenauslastung zeigt Stunden und geht das Team an,
 * die Angebotssummen sind Beträge und tun das nicht (PLAN §4). Wer nur `kapazitaet.lesen` hat,
 * sieht den Pipeline-Reiter gar nicht – ausgegraute Reiter gibt es nicht (design/README.md).
 */

import { useState } from "react";
import { PageTitle } from "@/komponenten/PageTitle";
import { Tabs } from "@/komponenten/Tabs";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { Kapazitaet } from "./Kapazitaet";
import { Pipeline } from "./Pipeline";
import "./planung.css";

export function Planung() {
  const { darf } = useSitzung();
  const darfAngebote = darf("angebote.lesen");
  const [reiter, setReiter] = useState("kapazitaet");

  const reiterliste = [
    { schluessel: "kapazitaet", beschriftung: "Kapazität" },
    ...(darfAngebote
      ? [{ schluessel: "pipeline", beschriftung: "Pipeline" }]
      : []),
  ];
  const aktiv = reiterliste.some((r) => r.schluessel === reiter)
    ? reiter
    : "kapazitaet";

  return (
    <div>
      <PageTitle meta="Was ansteht und was kommen könnte">
        Kapazität &amp; Pipeline
      </PageTitle>

      {reiterliste.length > 1 ? (
        <Tabs reiter={reiterliste} aktiv={aktiv} onWechsel={setReiter} />
      ) : null}

      {aktiv === "pipeline" && darfAngebote ? <Pipeline /> : <Kapazitaet />}
    </div>
  );
}
