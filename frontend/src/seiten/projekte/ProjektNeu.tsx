/**
 * Neues Projekt anlegen (PLAN §3, §7 Phase 1).
 *
 * Als eigene Seite und nicht im Seitenpanel: hier sind mehr Felder auszufüllen als in einer
 * Liste Platz haben, und der Kunde wird gesucht. Die Projektnummer vergibt der Server aus dem
 * Auftragsjahr – sie steht erst nach dem Speichern fest und wird deshalb nicht angezeigt.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { PageTitle } from "@/komponenten/PageTitle";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { useSitzung } from "@/sitzung/SitzungKontext";
import {
  ProjektFormular,
  LEERES_PROJEKT,
  type ProjektDaten,
} from "./ProjektFormular";
import type { Anlagenart } from "./begriffe";
import "./projekte.css";

export function ProjektNeu() {
  const navigate = useNavigate();
  const { darf } = useSitzung();
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  const anlegen = useMutation({
    mutationFn: async (daten: ProjektDaten) => {
      setFehler(null);
      if (!daten.kunde_id) {
        throw {
          code: "kunde_fehlt",
          meldung: "Ohne Kunden lässt sich kein Projekt anlegen.",
          naechster_schritt:
            "Den Kunden im Suchfeld eingeben und aus der Liste wählen. Fehlt er, zuerst unter Stammdaten anlegen.",
        };
      }
      const { data, error } = await api.POST("/api/projekte", {
        body: {
          kunde_id: daten.kunde_id,
          bezeichnung: daten.bezeichnung || null,
          typ: daten.typ as "projekt" | "service",
          standort: daten.standort || null,
          anlagenart: (daten.anlagenart || null) as Anlagenart | null,
          pv_kwp: daten.pv_kwp ?? null,
          wr_typ: daten.wr_typ || null,
          speicher_typ: daten.speicher_typ || null,
          speicher_kwh: daten.speicher_kwh ?? null,
          ladestation: daten.ladestation || null,
          auftrag_vom: daten.auftrag_vom || null,
          ab_wert_netto: daten.ab_wert_netto ?? null,
          pl_name: daten.pl_name || null,
          vertriebsweg: daten.vertriebsweg || null,
          ust_kz: daten.ust_kz as "19" | "0" | "13b" | "gemischt",
          status: daten.status as
            | "angebot"
            | "beauftragt"
            | "in_bau"
            | "abgeschlossen"
            | "storniert",
          bemerkung: daten.bemerkung || null,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (daten) => {
      if (daten) navigate(`/projekte/${daten.projekt_nr}`);
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  return (
    <>
      <Link to="/projekte" className="zurueck">
        ← Projekte
      </Link>
      <PageTitle meta="Die Projektnummer wird beim Speichern aus dem Auftragsjahr gebildet.">
        Neues Projekt
      </PageTitle>
      <div className="projektformular">
        <ProjektFormular
          projekt={LEERES_PROJEKT}
          laeuft={anlegen.isPending}
          fehler={fehler}
          darfSchreiben={darf("projekte.schreiben")}
          darfWerte={darf("projekte.werte_lesen")}
          onSpeichern={(daten) => anlegen.mutate(daten)}
          onAbbrechen={() => navigate("/projekte")}
        />
      </div>
    </>
  );
}
