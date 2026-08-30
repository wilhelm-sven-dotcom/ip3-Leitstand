/**
 * Projektordner und ihre Unterlagen (PLAN §7 Phase 7).
 *
 * Eine Frage: **welche Projektmappe ist unvollständig?** Die Antwort ist ein Hinweis, keine
 * Feststellung – der Scan sieht nur Dateinamen. Was auf Papier im Regal liegt oder unter einem
 * anderen Namen abgelegt ist, fehlt hier zu Unrecht, und deshalb steht das über der Tabelle
 * und nicht in einer Fußnote.
 *
 * Drei Zustände, die die Liste auseinanderhält, weil sie zu drei verschiedenen Handgriffen
 * führen:
 *
 * * **nie geprüft** – der Scan lief für dieses Projekt noch nicht. Es fehlt nichts, es ist nur
 *   nichts bekannt.
 * * **kein Ordner** – fast immer ein Namensproblem: Tippfehler in der Nummer, Ordner im Archiv.
 * * **Ordner da, Unterlage fehlt** – die einzige echte Lücke in der Mappe.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PageTitle } from "@/komponenten/PageTitle";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { KpiTile } from "@/komponenten/KpiTile";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { anzahl, datum } from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { STATUS_TEXT } from "@/seiten/projekte/begriffe";
import { ordnerlage, unterlagenZusatz } from "./begriffe";
import "./unterlagen.css";

type Unterlage = {
  typ: string;
  bezeichnung: string;
  vorhanden: boolean;
  pflicht: boolean;
  pfad?: string | null;
};

type Zeile = {
  projekt_id: number;
  projekt_nr: number;
  projekt_bezeichnung?: string | null;
  status: string;
  gefunden: boolean;
  pfad?: string | null;
  dateien: number;
  mehrdeutig_mit?: string | null;
  geprueft_am?: string | null;
  unterlagen: Unterlage[];
  fehlende_pflicht: string[];
};

export function Unterlagen() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const darfScannen = darf("importe.ausfuehren");

  const [nurUnvollstaendig, setNurUnvollstaendig] = useState(false);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);
  const [hinweis, setHinweis] = useState<string | null>(null);

  const uebersicht = useQuery({
    queryKey: ["unterlagen", { nurUnvollstaendig }],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/unterlagen", {
        params: { query: { nur_unvollstaendig: nurUnvollstaendig } },
      });
      if (error) throw error;
      return data;
    },
  });

  const scannen = useMutation({
    mutationFn: async () => {
      setFehler(null);
      setHinweis(null);
      const { data, error } = await api.POST("/api/unterlagen/scannen", {});
      if (error) throw error;
      return data;
    },
    onSuccess: (daten) => {
      setHinweis(daten?.meldung ?? null);
      void abfragen.invalidateQueries({ queryKey: ["unterlagen"] });
    },
    onError: (e) => setFehler(fehlerAuslesen(e)),
  });

  const spalten: Spalte<Zeile>[] = [
    {
      kopf: "Projekt",
      hervorgehoben: true,
      zelle: (z) => (
        <Link to={`/projekte/${z.projekt_nr}`} className="verweis">
          {z.projekt_nr}
        </Link>
      ),
    },
    {
      kopf: "Bezeichnung",
      zelle: (z) => z.projekt_bezeichnung ?? "–",
    },
    {
      kopf: "Status",
      zelle: (z) =>
        STATUS_TEXT[z.status as keyof typeof STATUS_TEXT] ?? z.status,
    },
    {
      kopf: "Ordner",
      zelle: (z) => {
        const lage = ordnerlage(z);
        return (
          <span className={`ordnerlage ordnerlage--${lage.art}`}>
            {lage.text}
          </span>
        );
      },
    },
    {
      kopf: "Unterlagen",
      zelle: (z) =>
        // Ohne Ordner lässt sich über einzelne Unterlagen nichts sagen – dann fünf Marken
        // zu zeigen, von denen eine rot ist, behauptet mehr als der Scan weiß, und die
        // Kennzahl darüber zählt dieses Projekt zu Recht nicht mit.
        !z.geprueft_am || !z.gefunden ? (
          <span className="unterlagen__leer">–</span>
        ) : (
          <ul className="unterlagen__marken">
            {z.unterlagen.map((u) => (
              <li
                key={u.typ}
                className={[
                  "unterlagen__marke",
                  u.vorhanden
                    ? "unterlagen__marke--da"
                    : "unterlagen__marke--fehlt",
                  u.pflicht ? "unterlagen__marke--pflicht" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                title={
                  u.vorhanden
                    ? (u.pfad ?? u.bezeichnung)
                    : `${u.bezeichnung} fehlt`
                }
              >
                {u.bezeichnung}
              </li>
            ))}
          </ul>
        ),
    },
    {
      kopf: "Geprüft",
      zelle: (z) => (z.geprueft_am ? datum(z.geprueft_am) : "noch nie"),
    },
  ];

  const daten = uebersicht.data;
  const zeilen = (daten?.ordner ?? []) as Zeile[];

  return (
    <div className="seite">
      <PageTitle
        meta={
          daten
            ? `${anzahl(daten.gesamt, "Projekt", "Projekte")} sichtbar`
            : undefined
        }
      >
        Unterlagen
      </PageTitle>

      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}
      {hinweis ? <Meldung art="hinweis" text={hinweis} /> : null}

      {daten ? (
        <p className="unterlagen__einordnung">{daten.einordnung}</p>
      ) : null}

      {daten ? (
        <div className="kpi-reihe">
          <KpiTile label="Ohne Ordner" wert={String(daten.ohne_ordner)} />
          <KpiTile
            label="Pflichtdoku fehlt"
            wert={String(daten.unvollstaendig)}
            negativ={daten.unvollstaendig > 0}
          />
          <KpiTile label="Nie geprüft" wert={String(daten.nie_geprueft)} />
          <KpiTile label="Mehrdeutig" wert={String(daten.mehrdeutig)} />
        </div>
      ) : null}

      {daten ? (
        <p className="unterlagen__zusatz">{unterlagenZusatz(daten)}</p>
      ) : null}

      <div className="filterleiste">
        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Anzeigen</span>
          <select
            className="auswahlzeile__feld"
            value={nurUnvollstaendig ? "unvollstaendig" : "alle"}
            onChange={(e) =>
              setNurUnvollstaendig(e.target.value === "unvollstaendig")
            }
          >
            <option value="alle">alle Projekte</option>
            <option value="unvollstaendig">
              nur mit fehlender Pflichtdoku
            </option>
          </select>
        </label>

        {darfScannen ? (
          <Knopf
            art="sekundaer"
            onClick={() => scannen.mutate()}
            disabled={scannen.isPending}
          >
            {scannen.isPending ? "Wird geprüft …" : "Jetzt prüfen"}
          </Knopf>
        ) : null}
      </div>

      <DataTable
        spalten={spalten}
        zeilen={zeilen}
        schluessel={(z) => z.projekt_id}
        beschriftung="Projektordner"
        leer={
          <EmptyState
            titel={
              nurUnvollstaendig
                ? "Keine Projektmappe ist unvollständig."
                : "Noch kein Projekt sichtbar."
            }
            text={
              nurUnvollstaendig
                ? "Entweder liegt überall alles vor, oder der Scan lief für diese Projekte noch nicht."
                : "Sobald Projekte angelegt sind, erscheint hier ihr Ordnerbefund."
            }
          />
        }
      />
    </div>
  );
}
