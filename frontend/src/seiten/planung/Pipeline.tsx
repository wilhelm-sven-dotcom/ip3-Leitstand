/**
 * Angebotspipeline (PLAN §7 Phase 7).
 *
 * **Angebote, keine Aufträge.** Die Einordnung steht unter der Überschrift und kommt aus der
 * API, damit sie hier nicht wegfallen kann. Beide Summen stehen immer nebeneinander: nur die
 * gewichtete zu zeigen verschweigt das Risiko, nur die rohe die Wahrscheinlichkeit.
 *
 * Die Balken sind deshalb doppelt – die rohe Summe als Kontur, die gewichtete gefüllt darin.
 * In der Farbe `chart-4`, nicht in ip³ Blau: eine Erwartung sieht anders aus als ein Auftrag.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Knopf } from "@/komponenten/Knopf";
import { KpiTile } from "@/komponenten/KpiTile";
import { Meldung } from "@/komponenten/Meldung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { centAusText, euro, euroKurz, monatKurz } from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { angebotStatus, chance, mehrzahl, pipelineZusatz } from "./begriffe";
import "./planung.css";

type Angebotszeile = {
  id: number;
  angebot_nr?: string | null;
  kunde_name: string;
  bezeichnung?: string | null;
  summe_netto: number;
  wahrscheinlichkeit_promille: number;
  gewichtet_netto: number;
  erwarteter_monat?: string | null;
  status: string;
  projekt_nr?: number | null;
  bemerkung?: string | null;
  stand: string;
};

const LEER = {
  id: 0,
  angebot_nr: "",
  kunde_name: "",
  bezeichnung: "",
  summe: "",
  wahrscheinlichkeit: "50",
  erwarteter_monat: "",
  status: "offen",
  projekt_nr: "",
  bemerkung: "",
  stand: "",
};

export function Pipeline() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const darfSchreiben = darf("angebote.schreiben");

  const [status, setStatus] = useState("offen");
  // null heißt „der Server soll das Jahr wählen" – er nimmt das nächste mit offenen Angeboten.
  const [jahr, setJahr] = useState<number | null>(null);
  const [entwurf, setEntwurf] = useState<typeof LEER | null>(null);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  const liste = useQuery({
    queryKey: ["angebote", status],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/angebote", {
        params: { query: { status } },
      });
      if (error) throw error;
      return data;
    },
  });

  const verlauf = useQuery({
    queryKey: ["pipeline", jahr],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/angebote/pipeline", {
        params: { query: jahr === null ? {} : { jahr } },
      });
      if (error) throw error;
      return data;
    },
  });

  const speichern = useMutation({
    mutationFn: async (werte: typeof LEER) => {
      setFehler(null);
      const koerper = {
        kunde_name: werte.kunde_name,
        angebot_nr: werte.angebot_nr || null,
        bezeichnung: werte.bezeichnung || null,
        summe_netto: centAusText(werte.summe) ?? 0,
        wahrscheinlichkeit_promille: Math.round(
          Number(werte.wahrscheinlichkeit.replace(",", ".")) * 10,
        ),
        erwarteter_monat: werte.erwarteter_monat || null,
        status: werte.status as "offen" | "gewonnen" | "verloren",
        bemerkung: werte.bemerkung || null,
      };
      if (werte.id) {
        const { data, error } = await api.PUT("/api/angebote/{angebot_id}", {
          params: { path: { angebot_id: werte.id } },
          body: { ...koerper, stand: werte.stand },
        });
        if (error) throw error;
        return data;
      }
      const { data, error } = await api.POST("/api/angebote", {
        body: koerper,
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setEntwurf(null);
      void abfragen.invalidateQueries({ queryKey: ["angebote"] });
      void abfragen.invalidateQueries({ queryKey: ["pipeline"] });
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const spalten: Spalte<Angebotszeile>[] = [
    { kopf: "Kunde", zelle: (z) => z.kunde_name, hervorgehoben: true },
    { kopf: "Bezeichnung", zelle: (z) => z.bezeichnung ?? "–" },
    { kopf: "Nummer", zelle: (z) => z.angebot_nr ?? "–" },
    {
      kopf: "Summe netto (€)",
      zelle: (z) => euro(z.summe_netto, false),
      zahl: true,
    },
    {
      kopf: "Chance",
      zelle: (z) => chance(z.wahrscheinlichkeit_promille),
      zahl: true,
    },
    {
      kopf: "Gewichtet (€)",
      zelle: (z) => euro(z.gewichtet_netto, false),
      zahl: true,
    },
    { kopf: "Erwartet", zelle: (z) => z.erwarteter_monat ?? "unterminiert" },
    { kopf: "Status", zelle: (z) => angebotStatus(z.status) },
  ];

  const monate = verlauf.data?.monate ?? [];
  const groesster = Math.max(1, ...monate.map((m) => m.roh_netto));

  return (
    <div>
      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      <div className="planung__kopf">
        <h2 className="karte__titel">Pipeline</h2>
        {(verlauf.data?.jahre ?? []).length > 1 ? (
          <label className="auswahlzeile">
            <span className="auswahlzeile__label">Jahr</span>
            <select
              className="auswahlzeile__feld"
              value={verlauf.data?.jahr ?? ""}
              onChange={(e) => setJahr(Number(e.target.value))}
            >
              {(verlauf.data?.jahre ?? []).map((j) => (
                <option key={j} value={j}>
                  {j}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="planung__zusatz">{verlauf.data?.jahr}</span>
        )}
        <span className="planung__zusatz">
          {pipelineZusatz(
            verlauf.data?.roh_netto ?? 0,
            verlauf.data?.gewichtet_netto ?? 0,
          )}
        </span>
      </div>
      <p className="planung__einordnung">{verlauf.data?.einordnung}</p>

      {(verlauf.data?.hinweise ?? []).map((hinweis) => (
        <Meldung key={hinweis} art="hinweis" text={hinweis} />
      ))}

      <div className="kpi-reihe">
        <KpiTile
          label="Angeboten"
          wert={euroKurz(verlauf.data?.roh_netto ?? 0)}
          zusatz={mehrzahl(
            verlauf.data?.anzahl ?? 0,
            "offenes Angebot",
            "offene Angebote",
          )}
        />
        <KpiTile
          label="Gewichtet"
          wert={euroKurz(verlauf.data?.gewichtet_netto ?? 0)}
          zusatz="Summe mal Wahrscheinlichkeit"
        />
        <KpiTile
          label="Unterminiert"
          wert={euroKurz(verlauf.data?.unterminiert_roh ?? 0)}
          zusatz={`${mehrzahl(
            verlauf.data?.unterminiert_anzahl ?? 0,
            "Angebot",
            "Angebote",
          )} ohne erwarteten Monat`}
        />
      </div>

      {monate.length > 0 ? (
        <>
          <div className="pipeline">
            {monate.map((monat) => (
              <div key={monat.monat} className="pipeline__monat">
                <div
                  className="pipeline__saeule"
                  title={`${monat.monat}: ${euro(monat.roh_netto)} angeboten, ${euro(
                    monat.gewichtet_netto,
                  )} gewichtet`}
                >
                  <div
                    className="pipeline__roh"
                    style={{ height: (monat.roh_netto / groesster) * 100 }}
                  />
                  <div
                    className="pipeline__gewichtet"
                    style={{
                      height: (monat.gewichtet_netto / groesster) * 100,
                    }}
                  />
                </div>
                <span className="pipeline__beschriftung">
                  {monatKurz(monat.monat)}
                </span>
              </div>
            ))}
          </div>
          <p className="pipeline__legende">
            <span>
              <span className="pipeline__marke pipeline__marke--roh" />
              angeboten
            </span>
            <span>
              <span className="pipeline__marke pipeline__marke--gewichtet" />
              gewichtet
            </span>
          </p>
        </>
      ) : null}

      <div className="planung__kopf">
        <h2 className="karte__titel">Angebote</h2>
        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Status</span>
          <select
            className="auswahlzeile__feld"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="offen">offen</option>
            <option value="gewonnen">gewonnen</option>
            <option value="verloren">verloren</option>
            <option value="alle">alle</option>
          </select>
        </label>
        {darfSchreiben ? (
          <Knopf klein onClick={() => setEntwurf({ ...LEER })}>
            Angebot erfassen
          </Knopf>
        ) : null}
      </div>

      <DataTable
        spalten={spalten}
        zeilen={(liste.data?.angebote ?? []) as Angebotszeile[]}
        schluessel={(z) => z.id}
        onZeileKlick={
          darfSchreiben
            ? (z) =>
                setEntwurf({
                  id: z.id,
                  angebot_nr: z.angebot_nr ?? "",
                  kunde_name: z.kunde_name,
                  bezeichnung: z.bezeichnung ?? "",
                  summe: euro(z.summe_netto, false),
                  wahrscheinlichkeit: String(
                    z.wahrscheinlichkeit_promille / 10,
                  ).replace(".", ","),
                  erwarteter_monat: z.erwarteter_monat ?? "",
                  status: z.status,
                  projekt_nr: z.projekt_nr ? String(z.projekt_nr) : "",
                  bemerkung: z.bemerkung ?? "",
                  stand: z.stand,
                })
            : undefined
        }
        beschriftung="Angebote"
        leer={
          <EmptyState
            titel="Kein Angebot mit diesem Status."
            text={
              "Angebote kommen aus dem Angebots-Tool (Importe & Daten) oder werden hier von " +
              "Hand erfasst."
            }
          />
        }
      />

      {entwurf ? (
        <Angebotsmaske
          entwurf={entwurf}
          speichert={speichern.isPending}
          onAendern={setEntwurf}
          onSpeichern={() => speichern.mutate(entwurf)}
          onAbbrechen={() => {
            setEntwurf(null);
            setFehler(null);
          }}
        />
      ) : null}
    </div>
  );
}

function Angebotsmaske({
  entwurf,
  speichert,
  onAendern,
  onSpeichern,
  onAbbrechen,
}: {
  entwurf: typeof LEER;
  speichert: boolean;
  onAendern: (werte: typeof LEER) => void;
  onSpeichern: () => void;
  onAbbrechen: () => void;
}) {
  const setzen = (feld: keyof typeof LEER, wert: string) =>
    onAendern({ ...entwurf, [feld]: wert });
  const gewichtet =
    (centAusText(entwurf.summe) ?? 0) *
    (Number(entwurf.wahrscheinlichkeit.replace(",", ".")) / 100);

  return (
    <DetailPanel
      offen
      titel={entwurf.id ? entwurf.kunde_name : "Angebot erfassen"}
      meta={`gewichtet ${euro(Math.round(gewichtet))}`}
      onSchliessen={onAbbrechen}
      fuss={
        <Knopf
          onClick={onSpeichern}
          disabled={speichert || !entwurf.kunde_name.trim()}
        >
          Speichern
        </Knopf>
      }
    >
      <FormRow
        label="Kunde oder Interessent"
        value={entwurf.kunde_name}
        onChange={(e) => setzen("kunde_name", e.target.value)}
        hinweis="Ein Interessent braucht keinen Kundendatensatz."
      />
      <FormRow
        label="Bezeichnung"
        value={entwurf.bezeichnung}
        onChange={(e) => setzen("bezeichnung", e.target.value)}
      />
      <FormRow
        label="Angebotsnummer"
        value={entwurf.angebot_nr}
        onChange={(e) => setzen("angebot_nr", e.target.value)}
        hinweis="Aus dem Angebots-Tool. Daran erkennt ein erneuter Import dieselbe Zeile wieder."
      />
      <FormRow
        label="Angebotssumme netto (€)"
        zahl
        value={entwurf.summe}
        onChange={(e) => setzen("summe", e.target.value)}
      />
      <FormRow
        label="Wahrscheinlichkeit (%)"
        zahl
        value={entwurf.wahrscheinlichkeit}
        onChange={(e) => setzen("wahrscheinlichkeit", e.target.value)}
      />
      <FormRow
        label="Erwarteter Auftragsmonat"
        value={entwurf.erwarteter_monat}
        onChange={(e) => setzen("erwarteter_monat", e.target.value)}
        hinweis="Format JJJJ-MM, zum Beispiel 2027-03. Leer lassen, solange es offen ist."
      />
      <label className="auswahlzeile" style={{ marginTop: "var(--abstand-3)" }}>
        <span className="auswahlzeile__label">Status</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.status}
          onChange={(e) => setzen("status", e.target.value)}
        >
          <option value="offen">offen</option>
          <option value="verloren">verloren</option>
        </select>
      </label>
      <p
        className="planung__einordnung"
        style={{ marginTop: "var(--abstand-3)" }}
      >
        Gewonnen wird ein Angebot nicht hier, sondern indem das Projekt angelegt
        und am Angebot verknüpft wird – sonst stünde sein Wert weder in der
        Pipeline noch im Auftragsbestand.
      </p>
      <FormRow
        label="Bemerkung"
        value={entwurf.bemerkung}
        onChange={(e) => setzen("bemerkung", e.target.value)}
        breit
      />
    </DetailPanel>
  );
}
