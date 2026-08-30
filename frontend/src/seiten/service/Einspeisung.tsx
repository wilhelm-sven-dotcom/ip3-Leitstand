/**
 * Vergütungs-Controlling der eigenen Bestandsanlagen (PLAN §7 Phase 7).
 *
 * Eine Frage: **kommt für den eingespeisten Strom das an, was ankommen müsste?** Der Leitstand
 * rechnet die Erwartung aus den hinterlegten Sätzen und stellt sie der Abrechnung des
 * Netzbetreibers gegenüber.
 *
 * Zwei Dinge stehen deshalb über den Zahlen und nicht in einer Fußnote:
 *
 * * Es ist eine **Kontrollrechnung, keine Buchung**. Verbindlich bleibt die Abrechnung.
 * * Ohne hinterlegten Vergütungssatz gibt es **keine Erwartung** – und das ist etwas anderes
 *   als 0,00 €. Eine Null läse sich als „nichts zu erwarten", und genau diese Anlage wäre dann
 *   die, bei der niemand nachsieht.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { KpiTile } from "@/komponenten/KpiTile";
import { Meldung } from "@/komponenten/Meldung";
import { api } from "@/api/client";
import { euro, monatKurz, zahl } from "@/format/formate";
import { abweichungText, verguetungsart, zahlungslage } from "./begriffe";

type Monat = {
  monat: string;
  kwh: number;
  erwartet_cent: number | null;
  abgerechnet_cent: number;
  abweichung_cent: number | null;
  abweichung_promille: number | null;
  bezahlt_am?: string | null;
  offen: boolean;
};

type Anlagenbild = {
  anlage_id: number;
  bezeichnung: string;
  verguetungsart: string;
  verguetung_ct_kwh: number | null;
  kwh_gesamt: number;
  erwartet_cent: number;
  abgerechnet_cent: number;
  offen_cent: number;
  monate: Monat[];
  hinweise: string[];
};

const MONATE_ZURUECK = 12;

export function Einspeisung() {
  const [offeneId, setOffeneId] = useState<number | null>(null);

  const bild = useQuery({
    queryKey: ["einspeisung", MONATE_ZURUECK],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/einspeisung", {
        params: { query: { monate: MONATE_ZURUECK } },
      });
      if (error) throw error;
      return data;
    },
  });

  const anlagen = (bild.data?.anlagen ?? []) as Anlagenbild[];
  const offen = anlagen.find((a) => a.anlage_id === offeneId) ?? null;

  const spalten: Spalte<Anlagenbild>[] = [
    { kopf: "Anlage", hervorgehoben: true, zelle: (a) => a.bezeichnung },
    {
      kopf: "Vergütung",
      zelle: (a) => verguetungsart(a.verguetungsart, a.verguetung_ct_kwh),
    },
    {
      kopf: "Menge (kWh)",
      zahl: true,
      zelle: (a) => zahl(a.kwh_gesamt, 0),
    },
    {
      kopf: "Erwartet",
      zahl: true,
      zelle: (a) =>
        a.verguetung_ct_kwh === null ? "–" : euro(a.erwartet_cent),
    },
    { kopf: "Abgerechnet", zahl: true, zelle: (a) => euro(a.abgerechnet_cent) },
    {
      kopf: "Offen",
      zahl: true,
      zelle: (a) =>
        a.offen_cent === 0 ? (
          "–"
        ) : (
          <span className="einspeisung__offen">{euro(a.offen_cent)}</span>
        ),
    },
  ];

  const monatsspalten: Spalte<Monat>[] = [
    { kopf: "Monat", hervorgehoben: true, zelle: (m) => monatKurz(m.monat) },
    { kopf: "kWh", zahl: true, zelle: (m) => zahl(m.kwh, 0) },
    {
      kopf: "Erwartet",
      zahl: true,
      zelle: (m) => (m.erwartet_cent === null ? "–" : euro(m.erwartet_cent)),
    },
    { kopf: "Abgerechnet", zahl: true, zelle: (m) => euro(m.abgerechnet_cent) },
    {
      kopf: "Abweichung",
      zahl: true,
      zelle: (m) => {
        const text = abweichungText(m.abweichung_cent, m.abweichung_promille);
        return text.auffaellig ? (
          <span className="einspeisung__abweichung">{text.text}</span>
        ) : (
          text.text
        );
      },
    },
    {
      kopf: "Zahlung",
      zelle: (m) => {
        const lage = zahlungslage(m);
        return (
          <span className={`zahlungslage zahlungslage--${lage.art}`}>
            {lage.text}
          </span>
        );
      },
    },
  ];

  const daten = bild.data;

  return (
    <>
      {daten ? (
        <p className="einspeisung__einordnung">{daten.einordnung}</p>
      ) : null}

      {(daten?.hinweise ?? []).map((text) => (
        <Meldung key={text} art="hinweis" text={text} />
      ))}

      {daten ? (
        <div className="kpi-reihe">
          <KpiTile
            label="Erwartet"
            wert={euro(daten.erwartet_cent)}
            zusatz={`${monatKurz(daten.von)} bis ${monatKurz(daten.bis)}`}
          />
          <KpiTile label="Abgerechnet" wert={euro(daten.abgerechnet_cent)} />
          <KpiTile
            label="Noch nicht bezahlt"
            wert={euro(daten.offen_cent)}
            negativ={daten.offen_cent > 0}
          />
        </div>
      ) : null}

      <DataTable
        spalten={spalten}
        zeilen={anlagen}
        schluessel={(a) => a.anlage_id}
        onZeileKlick={(a) =>
          setOffeneId(a.anlage_id === offeneId ? null : a.anlage_id)
        }
        istAktiv={(a) => a.anlage_id === offeneId}
        beschriftung="Eigene Bestandsanlagen"
        leer={
          <EmptyState
            titel="Keine eigene Anlage erfasst."
            text={
              "Eigene Anlagen werden hier gepflegt, nicht aus Projekten abgeleitet – sie " +
              "gehören keinem Kunden. Ohne sie lässt sich keine Abrechnung zuordnen."
            }
          />
        }
      />

      {offen ? (
        <section className="einspeisung__monate">
          <h3 className="einspeisung__ueberschrift">{offen.bezeichnung}</h3>
          {offen.hinweise.map((text) => (
            <Meldung key={text} art="hinweis" text={text} />
          ))}
          <DataTable
            spalten={monatsspalten}
            zeilen={offen.monate}
            schluessel={(m) => m.monat}
            beschriftung={`Abrechnungsmonate ${offen.bezeichnung}`}
            leer={
              <EmptyState
                titel="Für diese Anlage liegt noch keine Abrechnung vor."
                text="Abrechnungen kommen aus der Datei des Netzbetreibers oder werden von Hand erfasst."
              />
            }
          />
        </section>
      ) : null}
    </>
  );
}
