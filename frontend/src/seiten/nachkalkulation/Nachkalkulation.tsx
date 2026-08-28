/**
 * Nachkalkulation über alle Projekte (PLAN §7 Phase 4).
 *
 * Die Seite, die Sven die Frage beantwortet, die nach jedem Projekt offen bleibt: hat sich das
 * gelohnt. Für sie gibt es **kein Mockup** – Aufbau im Duktus der Projekt- und der Umsatzliste
 * (siehe design/UMSETZUNG.md).
 *
 * Drei Dinge, die die Seite ausdrücklich sagt statt sie den Zahlen zu überlassen:
 *
 * 1. **Die schwächste Marge steht oben.** Dort ist die Nachfrage fällig, nicht bei den
 *    Projekten, die gelaufen sind.
 * 2. **Ohne Kalkulationsblatt keine Ampel.** Für die migrierten Bestandsprojekte ist das der
 *    Regelfall; die Kachel sagt, wie viele es sind, statt sie als „im Soll" auszugeben.
 * 3. **Hinweise sind Teil der Zahl.** Ein Projekt mit Doppelbelastungsverdacht trägt seine
 *    Marke in der Liste – wer nur die Marge liest, liest die halbe Wahrheit (PLAN §6.5).
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { KpiTile } from "@/komponenten/KpiTile";
import { Meldung } from "@/komponenten/Meldung";
import { PageTitle } from "@/komponenten/PageTitle";
import { api, fehlerAuslesen } from "@/api/client";
import { euro, euroKurz } from "@/format/formate";
import { PROJEKT_STATUS, STATUS_TEXT } from "@/seiten/projekte/begriffe";
import { MargenAmpel } from "./MargenAmpel";
import {
  type Ampel,
  hinweisKurz,
  margeText,
  projektname,
  stundenText,
} from "./begriffe";
import "@/seiten/projekte/projekte.css";
import "./nachkalkulation.css";

type Zeile = {
  projekt_nr: number;
  bezeichnung: string | null;
  kunde: string;
  status: string;
  pl_name: string | null;
  erloes_netto: number | null;
  ist_gesamt: number;
  soll_gesamt: number | null;
  marge_netto: number | null;
  marge_promille: number | null;
  marge_soll_promille: number | null;
  abweichung_promille: number | null;
  stunden_ist: string;
  ampel: string;
  hinweise: { code: string; text: string }[];
};

const SORTIERUNGEN = [
  { wert: "marge", text: "Schwächste Marge zuerst" },
  { wert: "erloes", text: "Größter Erlös zuerst" },
  { wert: "ist", text: "Höchste Ist-Kosten zuerst" },
  { wert: "projekt_nr", text: "Projektnummer" },
] as const;

export function Nachkalkulation() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("alle");
  const [sortierung, setSortierung] = useState<string>("marge");
  const [nurMitHinweis, setNurMitHinweis] = useState(false);

  const abfrage = useQuery({
    queryKey: ["nachkalkulation", status, sortierung, nurMitHinweis],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/nachkalkulation", {
        params: {
          query: {
            status: status as never,
            sortierung: sortierung as never,
            nur_mit_hinweis: nurMitHinweis,
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  if (abfrage.isError) {
    const fehler = fehlerAuslesen(abfrage.error);
    return (
      <>
        <PageTitle>Nachkalkulation</PageTitle>
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      </>
    );
  }

  const daten = abfrage.data;
  const zeilen = (daten?.projekte ?? []) as Zeile[];

  const spalten: Spalte<Zeile>[] = [
    {
      kopf: "Projekt",
      hervorgehoben: true,
      zelle: (z) => (
        <>
          <strong>{z.projekt_nr}</strong>
          <span className="nk-zweitzeile">{projektname(z)}</span>
        </>
      ),
    },
    { kopf: "Kunde", zelle: (z) => z.kunde },
    {
      kopf: "Status",
      zelle: (z) =>
        STATUS_TEXT[z.status as keyof typeof STATUS_TEXT] ?? z.status,
    },
    {
      kopf: "Erlös (€)",
      zahl: true,
      zelle: (z) => (
        <span className="nk-zahl">{euro(z.erloes_netto, false)}</span>
      ),
    },
    {
      kopf: "Soll (€)",
      zahl: true,
      zelle: (z) => (
        <span className="nk-zahl">{euro(z.soll_gesamt, false)}</span>
      ),
    },
    {
      kopf: "Ist (€)",
      zahl: true,
      zelle: (z) => (
        <span className="nk-zahl">{euro(z.ist_gesamt, false)}</span>
      ),
    },
    {
      kopf: "Marge (€)",
      zahl: true,
      zelle: (z) => (
        <span
          className={`nk-zahl${(z.marge_netto ?? 0) < 0 ? " nk-zahl--negativ" : ""}`}
        >
          {euro(z.marge_netto, false)}
        </span>
      ),
    },
    {
      kopf: "Marge (%)",
      zahl: true,
      zelle: (z) => (
        <span
          className={`nk-zahl${(z.marge_promille ?? 0) < 0 ? " nk-zahl--negativ" : ""}`}
        >
          {margeText(z.marge_promille)}
        </span>
      ),
    },
    {
      kopf: "Gegen Soll",
      zelle: (z) => (
        <MargenAmpel
          ampel={z.ampel as Ampel}
          margeSollPromille={z.marge_soll_promille}
          abweichungPromille={z.abweichung_promille}
        />
      ),
    },
    {
      kopf: "Anmerkung",
      zelle: (z) =>
        z.hinweise.length === 0 ? (
          <span className="text-sekundaer">–</span>
        ) : (
          <span className="nk-marken">
            {z.hinweise.map((h) => (
              <span key={h.code} className="nk-marke" title={h.text}>
                {hinweisKurz(h.code)}
              </span>
            ))}
          </span>
        ),
    },
  ];

  return (
    <>
      <PageTitle meta="Erlös, Soll und Ist je Projekt – die Marge gegen die Kalkulation">
        Nachkalkulation
      </PageTitle>

      <div className="kpi-reihe">
        <KpiTile
          label="Erlös"
          wert={euroKurz(daten?.erloes_netto)}
          zusatz="Auftragswerte plus beauftragte Nachträge"
        />
        <KpiTile
          label="Ist-Kosten"
          wert={euroKurz(daten?.ist_netto)}
          zusatz="DATEV, Lagerentnahmen und Eigenleistung"
        />
        <KpiTile
          label="Marge"
          wert={euroKurz(daten?.marge_netto)}
          zusatz={`Über alle Projekte: ${margeText(daten?.marge_promille ?? null)}`}
          zusatzArt={(daten?.marge_promille ?? 0) < 0 ? "negativ" : "neutral"}
          negativ={(daten?.marge_netto ?? 0) < 0}
        />
        <KpiTile
          label="Ohne Kalkulationsblatt"
          wert={String(daten?.ohne_kalkulation ?? 0)}
          zusatz={`von ${daten?.anzahl ?? 0} Projekten – für sie gibt es keinen Soll-Ist-Vergleich`}
        />
      </div>

      {(daten?.mit_hinweis ?? 0) > 0 && !nurMitHinweis && (
        <Meldung
          art="hinweis"
          text={
            <>
              <strong>{daten?.mit_hinweis} Projekte mit Anmerkungen.</strong>{" "}
              Bei ihnen ist eine Zahl weniger wert, als sie aussieht – fehlender
              Auftragswert, fehlendes Kalkulationsblatt oder ein Verdacht auf
              doppelt gebuchtes Material.
            </>
          }
          naechsterSchritt={
            <button
              type="button"
              className="nk-verweis"
              onClick={() => setNurMitHinweis(true)}
            >
              Nur diese anzeigen
            </button>
          }
        />
      )}

      <div className="filterleiste">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="alle">alle</option>
            {PROJEKT_STATUS.map((s) => (
              <option key={s} value={s}>
                {STATUS_TEXT[s as keyof typeof STATUS_TEXT] ?? s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sortierung
          <select
            value={sortierung}
            onChange={(e) => setSortierung(e.target.value)}
          >
            {SORTIERUNGEN.map((s) => (
              <option key={s.wert} value={s.wert}>
                {s.text}
              </option>
            ))}
          </select>
        </label>
        <label className="filterleiste__schalter">
          <input
            type="checkbox"
            checked={nurMitHinweis}
            onChange={(e) => setNurMitHinweis(e.target.checked)}
          />
          Nur mit Anmerkung
        </label>
      </div>

      <DataTable
        spalten={spalten}
        zeilen={zeilen}
        schluessel={(z) => z.projekt_nr}
        onZeileKlick={(z) =>
          navigate(`/projekte/${z.projekt_nr}?reiter=nachkalkulation`)
        }
        beschriftung="Nachkalkulation je Projekt"
        leer={
          <EmptyState
            titel={
              abfrage.isLoading
                ? "wird geladen …"
                : "Keine Projekte in dieser Auswahl"
            }
            text={
              abfrage.isLoading
                ? "Einen Augenblick."
                : "Die Nachkalkulation zeigt beauftragte, laufende und abgeschlossene Projekte. Angebote und stornierte Projekte bleiben draußen."
            }
          />
        }
      />

      <p className="nk-fuss">
        {zeilen.length} von {daten?.anzahl ?? 0} Projekten. Stunden insgesamt:{" "}
        {stundenText(
          zeilen.reduce((summe, z) => summe + Number(z.stunden_ist ?? 0), 0),
        )}
        .
      </p>
    </>
  );
}
