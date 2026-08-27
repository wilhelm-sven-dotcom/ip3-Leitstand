/**
 * Belegliste (PLAN §7 Phase 3).
 *
 * Es gibt kein Mockup für diese Seite – die Umsetzung folgt dem Duktus der Projektliste
 * (Filterleiste über der Tabelle, Zahlen rechtsbündig, Zeile öffnet das Detail), vermerkt in
 * `design/UMSETZUNG.md`.
 *
 * Zwei Dinge, die diese Liste von den anderen unterscheidet:
 *
 * 1. **Der Zahlbetrag steht neben dem Netto.** Bei einer Schlussrechnung sind das zwei
 *    verschiedene Zahlen – die Gesamtleistung und der Restbetrag nach Absetzung der Abschläge.
 *    Nur eine davon zu zeigen wäre je nach Belegart die falsche.
 * 2. **Entwürfe haben keine Nummer.** Statt einer leeren Spalte steht dort „Entwurf": die
 *    Nummer wird erst bei der Festschreibung vergeben, damit keine Lücken entstehen (PLAN §6.4).
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { Meldung } from "@/komponenten/Meldung";
import { PageTitle } from "@/komponenten/PageTitle";
import { Seitenwechsel } from "@/komponenten/Seitenwechsel";
import { StatusBadge } from "@/komponenten/StatusBadge";
import { api, fehlerAuslesen } from "@/api/client";
import {
  anzahl as anzahlText,
  datum as datumText,
  euro,
} from "@/format/formate";
import {
  ART_KURZ,
  BELEG_STATUS,
  BELEGARTEN,
  badgeZustand,
  belegnummer,
  type Belegart,
  type Belegstatus,
} from "./begriffe";
import "./rechnungen.css";

const JE_SEITE = 25;

const STATUS_TEXT: Record<Belegstatus, string> = {
  entwurf: "Entwürfe",
  festgeschrieben: "festgeschrieben",
  storniert: "storniert",
};

type Zeile = {
  id: number;
  rechnung_nr: string | null;
  art: string;
  status: string;
  datum: string;
  faellig_am: string | null;
  projekt_nr: number | null;
  kunde_name: string;
  betreff: string | null;
  netto: number;
  zahlbetrag: number;
  aenderbar: boolean;
};

export function Rechnungen() {
  const navigate = useNavigate();
  const [jahr, setJahr] = useState<string>("alle");
  const [art, setArt] = useState<string>("alle");
  const [status, setStatus] = useState<string>("alle");
  const [suche, setSuche] = useState("");
  const [seite, setSeite] = useState(1);

  const liste = useQuery({
    queryKey: ["rechnungen", { jahr, art, status, suche }],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/rechnungen", {
        params: {
          query: {
            ...(jahr !== "alle" ? { jahr: Number(jahr) } : {}),
            art: art as "alle",
            status: status as "alle",
            ...(suche.trim() ? { suche: suche.trim() } : {}),
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  const zeilen = (liste.data?.zeilen ?? []) as Zeile[];
  const sichtbar = zeilen.slice((seite - 1) * JE_SEITE, seite * JE_SEITE);

  const spalten: Spalte<Zeile>[] = [
    {
      kopf: "Belegnummer",
      hervorgehoben: true,
      zelle: (zeile) => (
        <span className="belegnummer">{belegnummer(zeile.rechnung_nr)}</span>
      ),
      // Breit genug für RE-JJJJ-NNNN in einer Zeile: umgebrochen liest sich eine
      // Belegnummer nicht mehr als eine.
      breite: "11rem",
    },
    {
      kopf: "Art",
      zelle: (zeile) => ART_KURZ[zeile.art as Belegart] ?? zeile.art,
      breite: "7rem",
    },
    { kopf: "Kunde", zelle: (zeile) => zeile.kunde_name, hervorgehoben: true },
    {
      kopf: "Projekt",
      zahl: true,
      zelle: (zeile) =>
        zeile.projekt_nr ? (
          <Link
            to={`/projekte/${zeile.projekt_nr}`}
            onClick={(e) => e.stopPropagation()}
          >
            {zeile.projekt_nr}
          </Link>
        ) : (
          "–"
        ),
      breite: "6rem",
    },
    {
      kopf: "Datum",
      zahl: true,
      zelle: (zeile) => datumText(zeile.datum),
      breite: "7rem",
    },
    {
      kopf: "Fällig",
      zahl: true,
      zelle: (zeile) => (zeile.faellig_am ? datumText(zeile.faellig_am) : "–"),
      breite: "7rem",
    },
    {
      kopf: "Netto (€)",
      zahl: true,
      zelle: (zeile) => euro(zeile.netto, false),
      breite: "8rem",
    },
    {
      kopf: "Zahlbetrag (€)",
      zahl: true,
      zelle: (zeile) => euro(zeile.zahlbetrag, false),
      breite: "9rem",
    },
    {
      kopf: "Status",
      zelle: (zeile) => <StatusBadge zustand={badgeZustand(zeile.status)} />,
      breite: "9rem",
    },
  ];

  const fehler = liste.error ? fehlerAuslesen(liste.error) : null;

  return (
    <div className="seite">
      <PageTitle
        meta={
          liste.data
            ? `${anzahlText(liste.data.anzahl, "Beleg", "Belege")} · ${euro(liste.data.summe_netto)} netto`
            : undefined
        }
      >
        Fakturierung
      </PageTitle>

      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      <div className="filterleiste">
        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Jahr</span>
          <select
            className="auswahlzeile__feld"
            value={jahr}
            onChange={(e) => {
              setJahr(e.target.value);
              setSeite(1);
            }}
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
          <span className="auswahlzeile__label">Belegart</span>
          <select
            className="auswahlzeile__feld"
            value={art}
            onChange={(e) => {
              setArt(e.target.value);
              setSeite(1);
            }}
          >
            <option value="alle">alle</option>
            {BELEGARTEN.map((a) => (
              <option key={a} value={a}>
                {ART_KURZ[a]}
              </option>
            ))}
          </select>
        </label>

        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Status</span>
          <select
            className="auswahlzeile__feld"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setSeite(1);
            }}
          >
            <option value="alle">alle</option>
            {BELEG_STATUS.map((s) => (
              <option key={s} value={s}>
                {STATUS_TEXT[s]}
              </option>
            ))}
          </select>
        </label>

        <label className="auswahlzeile auswahlzeile--weit">
          <span className="auswahlzeile__label">Suche</span>
          <input
            className="auswahlzeile__feld"
            type="search"
            value={suche}
            placeholder="Belegnummer, Betreff oder Kunde"
            onChange={(e) => {
              setSuche(e.target.value);
              setSeite(1);
            }}
          />
        </label>
      </div>

      <DataTable
        spalten={spalten}
        zeilen={sichtbar}
        schluessel={(zeile) => zeile.id}
        onZeileKlick={(zeile) => navigate(`/fakturierung/${zeile.id}`)}
        beschriftung="Belege"
        leer={
          <EmptyState
            titel={liste.isLoading ? "wird geladen …" : "Keine Belege"}
            text={
              liste.isLoading
                ? undefined
                : suche ||
                    jahr !== "alle" ||
                    art !== "alle" ||
                    status !== "alle"
                  ? "Zu diesen Filtern gibt es keinen Beleg. Filter zurücksetzen oder weiter fassen."
                  : "Belege entstehen am Projekt: im Zahlungsplan auf „Abschlag stellen“ oder über „Schlussrechnung erzeugen“."
            }
          />
        }
      />

      <Seitenwechsel
        gesamt={zeilen.length}
        versatz={(seite - 1) * JE_SEITE}
        anzahl={JE_SEITE}
        einheit={["Beleg", "Belegen"]}
        onVersatz={(versatz) => setSeite(Math.floor(versatz / JE_SEITE) + 1)}
      />
    </div>
  );
}
