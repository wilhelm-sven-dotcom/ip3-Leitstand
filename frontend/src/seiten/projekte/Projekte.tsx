/**
 * Projektliste (design/Projektliste.dc.html, PLAN §7 Phase 1).
 *
 * Zwei Dinge unterscheiden diese Liste von der Kundenliste:
 *
 * 1. **Beträge sind an eine eigene Berechtigung gebunden** (`projekte.werte_lesen`, PLAN §4).
 *    Die Spalte „Auftragswert" verschwindet dann ganz – nicht als leere Spalte, sondern als
 *    keine. Dass die Antwort die Werte auch bei direktem Aufruf nicht enthält, prüft das
 *    Backend; hier geht es nur darum, keine sinnlose Spalte zu zeichnen.
 * 2. **Die Filterwerte kommen aus den Daten.** Ein Jahr ohne Projekte gehört nicht in die
 *    Auswahlliste, und die Projektleiternamen stehen so in der Teamliste, wie sie dort stehen.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageTitle } from "@/komponenten/PageTitle";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { ProjektStatusBadge } from "@/komponenten/ProjektStatusBadge";
import { Seitenwechsel } from "@/komponenten/Seitenwechsel";
import { api, fehlerAuslesen } from "@/api/client";
import { anzahl as anzahlText, euroKurz, zahl } from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import {
  ANLAGENART_TEXT,
  ANLAGENARTEN,
  PROJEKT_STATUS,
  STATUS_TEXT,
  projektname,
  type Anlagenart,
} from "./begriffe";
import "./projekte.css";

const JE_SEITE = 25;

type Zeile = {
  id: number;
  projekt_nr: number;
  bezeichnung?: string | null;
  kunde: string;
  standort?: string | null;
  anlagenart?: string | null;
  pv_kwp?: number | null;
  speicher_kwh?: number | null;
  status: string;
  pl_name?: string | null;
  ab_wert_netto?: number | null;
};

export function Projekte() {
  const { darf } = useSitzung();
  const navigate = useNavigate();
  const darfWerte = darf("projekte.werte_lesen");

  const [suche, setSuche] = useState("");
  const [jahr, setJahr] = useState<string>("alle");
  const [status, setStatus] = useState("alle");
  const [projektleiter, setProjektleiter] = useState("alle");
  const [anlagenart, setAnlagenart] = useState("alle");
  const [versatz, setVersatz] = useState(0);

  useEffect(
    () => setVersatz(0),
    [suche, jahr, status, projektleiter, anlagenart],
  );

  const liste = useQuery({
    queryKey: [
      "projekte",
      { suche, jahr, status, projektleiter, anlagenart, versatz },
    ],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/projekte", {
        params: {
          query: {
            suche,
            status,
            projektleiter,
            anlagenart,
            versatz,
            anzahl: JE_SEITE,
            ...(jahr === "alle" ? {} : { jahr: Number(jahr) }),
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  const eintraege = (liste.data?.eintraege ?? []) as Zeile[];

  const spalten: Spalte<Zeile>[] = [
    { kopf: "Nr.", zahl: true, zelle: (z) => z.projekt_nr, breite: "80px" },
    {
      kopf: "Projekt",
      hervorgehoben: true,
      zelle: (z) => (
        <>
          <span className="projekte__name">
            {projektname(z.bezeichnung, z.kunde)}
          </span>
          {/* Der Kunde steht nur dann zusätzlich darunter, wenn oben etwas anderes steht –
              sonst zweimal derselbe Text. */}
          {z.bezeichnung?.trim() ? (
            <span className="projekte__kunde">{z.kunde}</span>
          ) : null}
        </>
      ),
    },
    { kopf: "Ort", zelle: (z) => z.standort ?? "–" },
    {
      kopf: "Gewerk",
      zelle: (z) =>
        z.anlagenart ? (
          (ANLAGENART_TEXT[z.anlagenart as Anlagenart] ?? z.anlagenart)
        ) : (
          <span className="projekte__leer">ohne Angabe</span>
        ),
    },
    {
      kopf: "Leistung (kWp)",
      zahl: true,
      zelle: (z) => (z.pv_kwp ? zahl(z.pv_kwp, 1) : "–"),
    },
    {
      kopf: "Speicher (kWh)",
      zahl: true,
      zelle: (z) => (z.speicher_kwh ? zahl(z.speicher_kwh, 1) : "–"),
    },
    ...(darfWerte
      ? [
          {
            kopf: "Auftragswert (€)",
            zahl: true,
            zelle: (z: Zeile) =>
              z.ab_wert_netto === null || z.ab_wert_netto === undefined
                ? "–"
                : zahl(Math.round(z.ab_wert_netto / 100)),
          },
        ]
      : []),
    { kopf: "Status", zelle: (z) => <ProjektStatusBadge status={z.status} /> },
    { kopf: "PL", zelle: (z) => z.pl_name ?? "–" },
  ];

  const jahrText = jahr === "alle" ? "" : ` im Jahr ${jahr}`;

  return (
    <>
      <PageTitle
        meta={
          liste.data ? (
            <>
              {anzahlText(liste.data.gesamt, "Projekt", "Projekte")}
              {jahrText}
              {liste.data.auftragsvolumen ? (
                <>
                  {" · Auftragsvolumen "}
                  {euroKurz(liste.data.auftragsvolumen)}
                </>
              ) : null}
            </>
          ) : undefined
        }
        aktionen={
          darf("projekte.schreiben") ? (
            <>
              <Knopf
                art="sekundaer"
                onClick={() => navigate("/projekte/projektleiter")}
              >
                Projektleiter zuordnen
              </Knopf>
              <Knopf onClick={() => navigate("/projekte/neu")}>
                Neues Projekt
              </Knopf>
            </>
          ) : null
        }
      >
        Projekte
      </PageTitle>

      <div className="filterleiste">
        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Jahr</span>
          <select
            className="auswahlzeile__feld"
            value={jahr}
            onChange={(e) => setJahr(e.target.value)}
          >
            <option value="alle">alle Jahre</option>
            {(liste.data?.jahre ?? []).map((j) => (
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
            {(liste.data?.projektleiter ?? []).map((p) => (
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

        <FormRow
          label="Suche"
          type="search"
          value={suche}
          onChange={(e) => setSuche(e.target.value)}
          placeholder="Nummer, Kunde, Ort oder Name"
          hinweis={"Umlaute beliebig: „poellath“ findet Pöllath."}
          breit
        />
      </div>

      {liste.isError ? (
        <Meldung
          art="fehler"
          text={fehlerAuslesen(liste.error).meldung}
          naechsterSchritt={fehlerAuslesen(liste.error).naechster_schritt}
        />
      ) : null}

      <DataTable
        spalten={spalten}
        zeilen={eintraege}
        schluessel={(z) => z.id}
        onZeileKlick={(z) => navigate(`/projekte/${z.projekt_nr}`)}
        beschriftung="Projektliste"
        leer={
          liste.isLoading ? (
            <p className="lademeldung">wird geladen …</p>
          ) : (
            <EmptyState
              titel={
                suche || jahr !== "alle" || status !== "alle"
                  ? "Kein Projekt gefunden"
                  : "Noch keine Projekte"
              }
              text={
                suche || jahr !== "alle" || status !== "alle"
                  ? "Die Filter zurücksetzen oder eine andere Schreibweise versuchen."
                  : "Projekte entstehen bei der Übernahme der Bestandsdaten oder werden hier angelegt."
              }
            />
          )
        }
      />

      {liste.data ? (
        <Seitenwechsel
          gesamt={liste.data.gesamt}
          versatz={liste.data.versatz}
          anzahl={liste.data.anzahl}
          einheit={["Projekt", "Projekten"]}
          onVersatz={setVersatz}
        />
      ) : null}
    </>
  );
}
