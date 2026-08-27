/**
 * Bearbeitungsformular eines Projekts (design/Projektdetail.dc.html, PLAN §5).
 *
 * Zwei Besonderheiten gegenüber der Kundenmaske:
 *
 * 1. **Der Auftragswert erscheint nur mit `projekte.werte_lesen`.** Ohne die Berechtigung
 *    kommt er nicht einmal in der Antwort vor – ein Feld dafür wäre also leer und würde beim
 *    Speichern den echten Wert überschreiben. Genau das weist das Backend ab (409).
 * 2. **Der Kunde wird gesucht, nicht ausgewählt.** Ein `<select>` mit 475 Einträgen ist
 *    unbenutzbar; das Suchfeld fragt dieselbe Kundenliste ab wie die Stammdatenmaske.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FormRow } from "@/komponenten/FormRow";
import { Formular } from "@/komponenten/Formular";
import { api } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { centAusText, euro } from "@/format/formate";
import {
  ANLAGENART_TEXT,
  ANLAGENARTEN,
  PROJEKT_STATUS,
  STATUS_TEXT,
  UST_TEXT,
} from "./begriffe";

export type ProjektDaten = {
  projekt_nr?: number;
  kunde_id: number;
  kunde?: string;
  bezeichnung?: string | null;
  typ: string;
  standort?: string | null;
  anlagenart?: string | null;
  pv_kwp?: number | null;
  wr_typ?: string | null;
  speicher_typ?: string | null;
  speicher_kwh?: number | null;
  ladestation?: string | null;
  auftrag_vom?: string | null;
  ab_wert_netto?: number | null;
  pl_name?: string | null;
  vertriebsweg?: string | null;
  ust_kz: string;
  status: string;
  bemerkung?: string | null;
  stand?: string;
};

export const LEERES_PROJEKT: ProjektDaten = {
  kunde_id: 0,
  typ: "projekt",
  ust_kz: "19",
  status: "beauftragt",
};

type Props = {
  projekt: ProjektDaten;
  laeuft: boolean;
  fehler: ApiFehler | null;
  darfSchreiben: boolean;
  darfWerte: boolean;
  onSpeichern: (daten: ProjektDaten) => void;
  onAbbrechen: () => void;
};

/** Kommazahl aus einem Eingabefeld: deutsches Komma zulassen, Leerfeld als `null`. */
function alsZahl(wert: string): number | null {
  const text = wert.trim().replace(",", ".");
  if (!text) return null;
  const zahl = Number(text);
  return Number.isFinite(zahl) ? zahl : null;
}

function centAlsText(cent: number | null | undefined): string {
  if (cent === null || cent === undefined) return "";
  return euro(cent, false);
}

export function ProjektFormular({
  projekt,
  laeuft,
  fehler,
  darfSchreiben,
  darfWerte,
  onSpeichern,
  onAbbrechen,
}: Props) {
  const [entwurf, setEntwurf] = useState<ProjektDaten>(projekt);
  const [wertText, setWertText] = useState(centAlsText(projekt.ab_wert_netto));
  const [kundensuche, setKundensuche] = useState("");

  useEffect(() => {
    setEntwurf(projekt);
    setWertText(centAlsText(projekt.ab_wert_netto));
  }, [projekt]);

  const kunden = useQuery({
    queryKey: ["kunden-auswahl", kundensuche],
    enabled: kundensuche.trim().length >= 2,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/kunden", {
        params: { query: { suche: kundensuche, status: "aktiv", anzahl: 20 } },
      });
      if (error) throw error;
      return data;
    },
  });

  function feld<K extends keyof ProjektDaten>(name: K, wert: ProjektDaten[K]) {
    setEntwurf((vorher) => ({ ...vorher, [name]: wert }));
  }

  const neu = !projekt.projekt_nr;

  return (
    <Formular
      fehler={fehler}
      laeuft={laeuft}
      onSpeichern={() =>
        onSpeichern({
          ...entwurf,
          ab_wert_netto: darfWerte
            ? centAusText(wertText)
            : entwurf.ab_wert_netto,
        })
      }
      onAbbrechen={onAbbrechen}
      gesperrt={!darfSchreiben}
      sperrgrund={
        "Zum Bearbeiten fehlt die Berechtigung „Projekte anlegen und bearbeiten“."
      }
    >
      {neu ? (
        <>
          <FormRow
            label="Kunde suchen"
            type="search"
            value={kundensuche}
            onChange={(e) => setKundensuche(e.target.value)}
            placeholder="Name oder Ort"
            hinweis={
              entwurf.kunde_id
                ? undefined
                : "Mindestens zwei Zeichen; danach den Kunden aus der Liste wählen."
            }
            breit
          />
          <label className="auswahlzeile auswahlzeile--breit">
            <span className="auswahlzeile__label">Kunde</span>
            <select
              className="auswahlzeile__feld"
              value={entwurf.kunde_id || ""}
              onChange={(e) => feld("kunde_id", Number(e.target.value))}
            >
              <option value="">bitte wählen</option>
              {(kunden.data?.eintraege ?? []).map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                  {k.ort ? `, ${k.ort}` : ""} · {k.kunden_nr}
                </option>
              ))}
            </select>
          </label>
        </>
      ) : (
        <FormRow label="Kunde" value={projekt.kunde ?? ""} readOnly disabled />
      )}

      <FormRow
        label="Bezeichnung"
        value={entwurf.bezeichnung ?? ""}
        onChange={(e) => feld("bezeichnung", e.target.value)}
        placeholder="z. B. Freiflächenanlage Kirchendemenreuth"
        hinweis="Leer lassen ist in Ordnung – dann steht der Kundenname in der Liste."
        breit
      />

      <FormRow
        label="Standort"
        value={entwurf.standort ?? ""}
        onChange={(e) => feld("standort", e.target.value)}
        breit
      />

      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Anlagenart</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.anlagenart ?? ""}
          onChange={(e) => feld("anlagenart", e.target.value || null)}
        >
          <option value="">ohne Angabe</option>
          {ANLAGENARTEN.map((a) => (
            <option key={a} value={a}>
              {ANLAGENART_TEXT[a]}
            </option>
          ))}
        </select>
      </label>

      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Status</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.status}
          onChange={(e) => feld("status", e.target.value)}
        >
          {PROJEKT_STATUS.map((s) => (
            <option key={s} value={s}>
              {STATUS_TEXT[s]}
            </option>
          ))}
        </select>
      </label>

      <FormRow
        label="Leistung (kWp)"
        zahl
        value={entwurf.pv_kwp ?? ""}
        onChange={(e) => feld("pv_kwp", alsZahl(e.target.value))}
      />

      <FormRow
        label="Speicher (kWh)"
        zahl
        value={entwurf.speicher_kwh ?? ""}
        onChange={(e) => feld("speicher_kwh", alsZahl(e.target.value))}
      />

      <FormRow
        label="Wechselrichter"
        value={entwurf.wr_typ ?? ""}
        onChange={(e) => feld("wr_typ", e.target.value)}
      />

      <FormRow
        label="Speichertyp"
        value={entwurf.speicher_typ ?? ""}
        onChange={(e) => feld("speicher_typ", e.target.value)}
        hinweis="Produktbezeichnung, z. B. „2x BYD HVM 22.1“."
      />

      <FormRow
        label="Ladestation"
        value={entwurf.ladestation ?? ""}
        onChange={(e) => feld("ladestation", e.target.value)}
      />

      <FormRow
        label="Auftrag vom"
        type="date"
        value={entwurf.auftrag_vom ?? ""}
        onChange={(e) => feld("auftrag_vom", e.target.value || null)}
        hinweis={neu ? "Bestimmt die Projektnummer (Jahr)." : undefined}
      />

      {darfWerte ? (
        <FormRow
          label="Auftragswert netto (€)"
          zahl
          value={wertText}
          onChange={(e) => setWertText(e.target.value)}
          placeholder="0,00"
          hinweis="Netto, ohne Umsatzsteuer."
        />
      ) : null}

      <FormRow
        label="Projektleitung"
        value={entwurf.pl_name ?? ""}
        onChange={(e) => feld("pl_name", e.target.value)}
        hinweis="Name wie in der Teamliste."
      />

      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Umsatzsteuer</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.ust_kz}
          onChange={(e) => feld("ust_kz", e.target.value)}
        >
          {Object.entries(UST_TEXT).map(([wert, text]) => (
            <option key={wert} value={wert}>
              {text}
            </option>
          ))}
        </select>
      </label>

      <FormRow
        label="Vertriebsweg"
        value={entwurf.vertriebsweg ?? ""}
        onChange={(e) => feld("vertriebsweg", e.target.value)}
      />

      <FormRow
        label="Bemerkung"
        value={entwurf.bemerkung ?? ""}
        onChange={(e) => feld("bemerkung", e.target.value)}
        breit
      />
    </Formular>
  );
}
