/**
 * Umsatz und Forecast (PLAN §7 Phase 2).
 *
 * Die erste Seite, die eine Aussage macht statt Daten zu zeigen: was ist abgerechnet, was steht
 * noch aus, was ist vom Auftragsbestand offen. Für sie gibt es **kein Mockup** – Aufbau im Duktus
 * von Projektliste und Firmen-Cockpit (siehe design/UMSETZUNG.md).
 *
 * Drei Dinge, die die Seite ausdrücklich sagt, statt sie den Zahlen zu überlassen:
 *
 * 1. **Der Ist ist unvollständig.** Der Hinweis dazu kommt vom Server und verschwindet von
 *    selbst, sobald keine übernommenen Altpositionen mehr im Ist stecken (ab Phase 3).
 * 2. **Kachel und Diagramm sind nicht dieselbe Zahl.** Der Auftragsbestand rechnet über
 *    Auftragswerte, der Forecast über Zahlungsplanpositionen. Die Differenz steht als eigene
 *    Zeile darunter – bei den Altprojekten führt die Auftragsliste nur die offenen Abschläge.
 * 3. **Unterminierte Positionen fehlen im Verlauf.** Sie stehen in keiner Monatssäule und
 *    deshalb in einer eigenen Kachel; im Bestand sind das 689.698,50 €.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { KpiTile } from "@/komponenten/KpiTile";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { MonthBars } from "@/komponenten/MonthBars";
import { PageTitle } from "@/komponenten/PageTitle";
import { ProjektStatusBadge } from "@/komponenten/ProjektStatusBadge";
import { api, fehlerAuslesen } from "@/api/client";
import {
  anzahl as anzahlText,
  euro,
  euroKurz,
  monat as monatText,
  zahl,
} from "@/format/formate";
import {
  ANLAGENART_TEXT,
  ANLAGENARTEN,
  PROJEKT_STATUS,
  STATUS_TEXT,
  projektname,
} from "@/seiten/projekte/begriffe";
import {
  balkenreihe,
  jahresauswahl,
  planRestjahr,
  type MonatAusApi,
} from "./reihe";
import "@/seiten/projekte/projekte.css";
import "./umsatz.css";

/**
 * Projektnummern für einen Hinweistext – höchstens acht, dann eine Zahl.
 *
 * Eine Meldung mit neunzehn Nummern hintereinander liest niemand zu Ende; die vollständige
 * Auskunft steht in der Tabelle darüber.
 */
function nummernliste(
  zeilen: { projekt_nr: number }[],
  hoechstens = 8,
): string {
  const nummern = zeilen.map((z) => z.projekt_nr);
  if (nummern.length <= hoechstens) return `${nummern.join(", ")}.`;
  const rest = nummern.length - hoechstens;
  return `${nummern.slice(0, hoechstens).join(", ")} und ${zahl(rest)} weitere.`;
}

/**
 * Wie viele Projekte die Bestandstabelle zeigt, bevor sie auf Wunsch aufklappt.
 *
 * 87 laufende Projekte in einer Tabelle sind kein Überblick mehr. Die Summe steht darüber, die
 * größten Posten stehen oben – wer die ganze Liste braucht, klappt sie auf.
 */
const BESTAND_ZEILEN = 25;

type Bestandszeile = {
  projekt_nr: number;
  bezeichnung?: string | null;
  kunde: string;
  status: string;
  pl_name?: string | null;
  ab_wert_netto?: number | null;
  nachtraege_netto: number;
  soll_netto?: number | null;
  fakturiert_netto: number;
  rest_netto?: number | null;
  zahlungsplan_offen_netto: number;
};

export function Umsatz() {
  const navigate = useNavigate();
  const [jahr, setJahr] = useState<number>(new Date().getFullYear());
  const [status, setStatus] = useState("alle");
  const [projektleiter, setProjektleiter] = useState("alle");
  const [anlagenart, setAnlagenart] = useState("alle");
  const [alleProjekte, setAlleProjekte] = useState(false);

  const monate = useQuery({
    queryKey: ["umsatz-monate", { jahr, status, projektleiter, anlagenart }],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/umsatz/monate", {
        params: {
          query: {
            jahr,
            status: status as never,
            projektleiter,
            anlagenart: anlagenart as never,
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  const bestand = useQuery({
    queryKey: ["umsatz-bestand", { projektleiter, anlagenart }],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/umsatz/auftragsbestand", {
        params: { query: { projektleiter, anlagenart: anlagenart as never } },
      });
      if (error) throw error;
      return data;
    },
  });

  // Wählt jemand ein Jahr, das es in den Daten nicht mehr gibt, bleibt die Auswahl trotzdem
  // gültig: die Antwort liefert zwölf leere Monate, und das ist eine Auskunft.
  const jahre = monate.data?.jahre ?? [];
  useEffect(() => {
    if (
      jahre.length &&
      !jahre.includes(jahr) &&
      jahr === new Date().getFullYear()
    ) {
      // Nur beim ersten Laden nachziehen – sonst überschriebe die Antwort die Wahl des Nutzers.
      setJahr(jahre[0] as number);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jahre.length]);

  const monatsliste = (monate.data?.monate ?? []) as MonatAusApi[];
  const rest = planRestjahr(monatsliste, jahr);
  const unterminiert = monate.data?.unterminiert;

  const monatsspalten: Spalte<MonatAusApi>[] = [
    { kopf: "Monat", hervorgehoben: true, zelle: (m) => monatText(m.monat) },
    {
      kopf: "Ist (€)",
      zahl: true,
      zelle: (m) => (m.ist_netto ? euro(m.ist_netto, false) : "–"),
    },
    {
      kopf: "Plan (€)",
      zahl: true,
      zelle: (m) => (m.plan_netto ? euro(m.plan_netto, false) : "–"),
    },
    {
      kopf: "Summe (€)",
      zahl: true,
      zelle: (m) => (m.summe_netto ? euro(m.summe_netto, false) : "–"),
    },
    {
      kopf: "Positionen",
      zahl: true,
      zelle: (m) =>
        m.ist_anzahl + m.plan_anzahl ? zahl(m.ist_anzahl + m.plan_anzahl) : "–",
    },
  ];

  const bestandsspalten: Spalte<Bestandszeile>[] = [
    { kopf: "Nr.", zahl: true, zelle: (z) => z.projekt_nr, breite: "80px" },
    {
      kopf: "Projekt",
      hervorgehoben: true,
      zelle: (z) => (
        <>
          <span className="projekte__name">
            {projektname(z.bezeichnung, z.kunde)}
          </span>
          {z.bezeichnung?.trim() ? (
            <span className="projekte__kunde">{z.kunde}</span>
          ) : null}
        </>
      ),
    },
    { kopf: "Status", zelle: (z) => <ProjektStatusBadge status={z.status} /> },
    { kopf: "PL", zelle: (z) => z.pl_name ?? "–" },
    {
      kopf: "Soll (€)",
      zahl: true,
      zelle: (z) =>
        z.soll_netto === null || z.soll_netto === undefined ? (
          <span className="projekte__leer">fehlt</span>
        ) : (
          euro(z.soll_netto, false)
        ),
    },
    {
      kopf: "Abgerechnet (€)",
      zahl: true,
      zelle: (z) =>
        z.fakturiert_netto ? euro(z.fakturiert_netto, false) : "–",
    },
    {
      kopf: "Offen (€)",
      zahl: true,
      zelle: (z) =>
        z.rest_netto === null || z.rest_netto === undefined ? (
          "–"
        ) : z.rest_netto < 0 ? (
          <span className="negativ">{euro(z.rest_netto, false)}</span>
        ) : (
          euro(z.rest_netto, false)
        ),
    },
    {
      kopf: "Im Plan (€)",
      zahl: true,
      zelle: (z) =>
        z.zahlungsplan_offen_netto
          ? euro(z.zahlungsplan_offen_netto, false)
          : "–",
    },
  ];

  const fehler = monate.isError
    ? fehlerAuslesen(monate.error)
    : bestand.isError
      ? fehlerAuslesen(bestand.error)
      : null;

  return (
    <>
      <PageTitle
        meta={
          monate.data ? (
            <>
              {jahr} · Ist {euroKurz(monate.data.ist_netto)} · Plan{" "}
              {euroKurz(monate.data.plan_netto)}
            </>
          ) : undefined
        }
      >
        Umsatz &amp; Forecast
      </PageTitle>

      <div className="filterleiste">
        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Jahr</span>
          <select
            className="auswahlzeile__feld"
            value={String(jahr)}
            onChange={(e) => setJahr(Number(e.target.value))}
          >
            {/* Die Jahre aus den Daten, dazu Vorjahr, laufendes und nächstes Jahr: sonst wäre
                die Liste eine Sackgasse – in den Bestandsdaten steht nur 2026, und wer im
                Dezember auf das nächste Jahr schauen will, käme nicht hin. Das gewählte Jahr
                bleibt in der Liste, auch wenn es in den Daten nicht vorkommt. */}
            {jahresauswahl(jahre, jahr).map((j) => (
              <option key={j} value={String(j)}>
                {j}
              </option>
            ))}
          </select>
        </label>

        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Status</span>
          <select
            className="auswahlzeile__feld"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="alle">alle</option>
            {PROJEKT_STATUS.map((s) => (
              <option key={s} value={s}>
                {STATUS_TEXT[s]}
              </option>
            ))}
          </select>
        </label>

        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Projektleiter</span>
          <select
            className="auswahlzeile__feld"
            value={projektleiter}
            onChange={(e) => setProjektleiter(e.target.value)}
          >
            <option value="alle">alle</option>
            {(monate.data?.projektleiter ?? []).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Gewerk</span>
          <select
            className="auswahlzeile__feld"
            value={anlagenart}
            onChange={(e) => setAnlagenart(e.target.value)}
          >
            <option value="alle">alle</option>
            {ANLAGENARTEN.map((a) => (
              <option key={a} value={a}>
                {ANLAGENART_TEXT[a]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      <div className="kpi-reihe">
        <KpiTile
          label={`Ist ${jahr}`}
          wert={euro(monate.data?.ist_netto ?? 0)}
          zusatz="abgerechnet oder im Altbestand als gestellt gekennzeichnet"
        />
        <KpiTile
          label="Plan Restjahr"
          wert={euro(rest)}
          zusatz={`von ${euro(monate.data?.plan_netto ?? 0)} im ganzen Jahr`}
        />
        <KpiTile
          label="Auftragsbestand"
          wert={euro(bestand.data?.bestand_netto ?? 0)}
          zusatz={
            bestand.data
              ? `${anzahlText(bestand.data.projekte?.length ?? 0, "laufendes Projekt", "laufende Projekte")}`
              : undefined
          }
        />
        <KpiTile
          label="Unterminiert"
          wert={euro(unterminiert?.summe_netto ?? 0)}
          zusatz={
            unterminiert?.anzahl
              ? `${anzahlText(unterminiert.anzahl, "Position", "Positionen")} ohne Planmonat`
              : "alle Positionen haben einen Planmonat"
          }
          zusatzArt={unterminiert?.summe_netto ? "negativ" : "neutral"}
        />
      </div>

      {(monate.data?.hinweise ?? []).map((hinweis) => (
        <Meldung key={hinweis} art="hinweis" text={hinweis} />
      ))}

      <h2 className="abschnittstitel">Jahresverlauf {jahr}</h2>
      <div className="verlauf">
        {monate.isLoading ? (
          <p className="lademeldung">wird geladen …</p>
        ) : (
          <>
            <MonthBars werte={balkenreihe(monatsliste)} hoehe={120} />
            <p className="verlauf__legende">
              <span className="verlauf__marke verlauf__marke--ist" /> Ist
              <span className="verlauf__marke verlauf__marke--plan" /> Plan
              {unterminiert?.summe_netto ? (
                <span className="verlauf__ausserhalb">
                  Nicht im Verlauf: {euro(unterminiert.summe_netto)} ohne
                  Planmonat
                </span>
              ) : null}
            </p>
          </>
        )}
      </div>

      <DataTable
        spalten={monatsspalten}
        zeilen={monatsliste}
        schluessel={(m) => m.monat}
        beschriftung={`Monatssummen ${jahr}`}
        leer={<EmptyState titel="Keine Monatswerte" ohneZeichen />}
      />

      <div className="abschnittskopf">
        <h2 className="abschnittstitel">Auftragsbestand</h2>
        {(bestand.data?.projekte?.length ?? 0) > BESTAND_ZEILEN ? (
          <Knopf
            art="sekundaer"
            klein
            onClick={() => setAlleProjekte((v) => !v)}
          >
            {alleProjekte
              ? `nur die größten ${BESTAND_ZEILEN}`
              : `alle ${zahl(bestand.data?.projekte?.length ?? 0)} anzeigen`}
          </Knopf>
        ) : null}
      </div>
      {bestand.data ? (
        <p className="summenzeile">
          Offen <span className="zahl">{euro(bestand.data.bestand_netto)}</span>
          {" · im Zahlungsplan verplant "}
          <span className="zahl">
            {euro(bestand.data.zahlungsplan_offen_netto)}
          </span>
          {bestand.data.nicht_verplant_netto ? (
            <>
              {" · "}
              <span className="summenzeile__luecke">
                {bestand.data.nicht_verplant_netto > 0
                  ? "noch nicht verplant "
                  : "über dem Auftragswert verplant "}
                <span className="zahl">
                  {euro(Math.abs(bestand.data.nicht_verplant_netto))}
                </span>
              </span>
            </>
          ) : null}
        </p>
      ) : null}

      <DataTable
        spalten={bestandsspalten}
        zeilen={
          (alleProjekte
            ? (bestand.data?.projekte ?? [])
            : (bestand.data?.projekte ?? []).slice(
                0,
                BESTAND_ZEILEN,
              )) as Bestandszeile[]
        }
        schluessel={(z) => z.projekt_nr}
        onZeileKlick={(z) => navigate(`/projekte/${z.projekt_nr}`)}
        beschriftung="Auftragsbestand je Projekt"
        leer={
          bestand.isLoading ? (
            <p className="lademeldung">wird geladen …</p>
          ) : (
            <EmptyState
              titel="Kein laufendes Projekt"
              text="Zum Auftragsbestand zählen Projekte im Status „Beauftragt“ und „In Bau“."
            />
          )
        }
      />

      {bestand.data?.zu_pruefen?.length ? (
        <Meldung
          art="hinweis"
          text={
            `Bei ${anzahlText(bestand.data.zu_pruefen.length, "Projekt", "Projekten")} ist ` +
            `mehr abgerechnet als beauftragt: ${nummernliste(bestand.data.zu_pruefen)}`
          }
          naechsterSchritt="Dort stimmt vermutlich der Auftragswert nicht. Im Projekt nachsehen und den Wert ergänzen."
        />
      ) : null}

      {bestand.data?.ohne_auftragswert?.length ? (
        <Meldung
          art="hinweis"
          text={
            `${anzahlText(bestand.data.ohne_auftragswert.length, "Projekt", "Projekte")} ohne ` +
            `Auftragswert: ${nummernliste(bestand.data.ohne_auftragswert)} ` +
            `Sie tragen nichts zum Auftragsbestand bei` +
            (bestand.data.ohne_auftragswert.some(
              (p) => p.zahlungsplan_offen_netto,
            )
              ? `, haben aber ${euro(
                  bestand.data.ohne_auftragswert.reduce(
                    (s, p) => s + p.zahlungsplan_offen_netto,
                    0,
                  ),
                )} im Zahlungsplan.`
              : ".")
          }
          naechsterSchritt="Den Auftragswert im Projekt nachtragen – dann zählt das Projekt im Bestand mit."
        />
      ) : null}
    </>
  );
}
