/**
 * Projektdetail mit Reitern (design/Projektdetail.dc.html, PLAN §7 Phase 1).
 *
 * Was in Phase 1 gebaut ist: Übersicht mit Anlagendaten und der Zeitleiste der Meilensteine,
 * dazu der Zahlungsplan zum Lesen. Nachkalkulation (Phase 4) und Dokumente (Phase 6) stehen als
 * gesperrte Reiter da, damit sichtbar bleibt, was noch kommt.
 *
 * Bearbeitet wird im Seitenpanel: die Kopfzeile mit Nummer, Kunde und Status bleibt dabei
 * stehen, und man sieht, was man ändert.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { EmptyState } from "@/komponenten/EmptyState";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { ProjektStatusBadge } from "@/komponenten/ProjektStatusBadge";
import { StatusBadge } from "@/komponenten/StatusBadge";
import { Tabs } from "@/komponenten/Tabs";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import {
  anteil,
  datum as datumText,
  euro,
  kapazitaet,
  leistung,
  monat as monatText,
} from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { Meilensteine, type MeilensteinDaten } from "./Meilensteine";
import { ProjektFormular, type ProjektDaten } from "./ProjektFormular";
import {
  ANLAGENART_TEXT,
  UST_TEXT,
  kopfzeile,
  projektname,
  type Anlagenart,
} from "./begriffe";
import "./projekte.css";

type Zahlungsplanzeile = {
  id: number;
  pos_nr: number;
  bezeichnung: string;
  gewerk: string;
  art: string;
  betrag_netto: number;
  plan_monat?: string | null;
  migriert_gestellt?: boolean | null;
  berechnet: boolean;
};

const ART_TEXT: Record<string, string> = {
  abschlag: "Abschlag",
  schluss: "Schlussrechnung",
  einmal: "Einmalbetrag",
};

/**
 * Ab welcher Abweichung die Lücke zwischen Zahlungsplan und Auftragswert ausgewiesen wird.
 *
 * Dieselbe Toleranz wie im Import (`RUNDUNGSTOLERANZ_CENT` in app/migration/uebernahme.py):
 * Abschläge sind in der Auftragsliste als Prozentsätze gerechnet, da bleibt regelmäßig ein Cent
 * übrig. „Nicht verplant 0,01 €" in Akzent-Rot wäre ein Alarm über nichts.
 */
const RUNDUNGSTOLERANZ_CENT = 100;

const GEWERK_TEXT: Record<string, string> = {
  pv: "PV",
  speicher: "Speicher",
  ls: "Ladestation",
  service: "Service",
  nachtrag: "Nachtrag",
};

export function ProjektDetail() {
  const { projektNr } = useParams();
  const nummer = Number(projektNr);
  const abfragen = useQueryClient();
  const { darf } = useSitzung();
  const darfWerte = darf("projekte.werte_lesen");

  const [reiter, setReiter] = useState("uebersicht");
  const [bearbeiten, setBearbeiten] = useState(false);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  const projekt = useQuery({
    queryKey: ["projekt", nummer],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/projekte/{projekt_nr}", {
        params: { path: { projekt_nr: nummer } },
      });
      if (error) throw error;
      return data;
    },
  });

  function neuLaden() {
    void abfragen.invalidateQueries({ queryKey: ["projekt", nummer] });
    void abfragen.invalidateQueries({ queryKey: ["projekte"] });
  }

  const speichern = useMutation({
    mutationFn: async (daten: ProjektDaten) => {
      setFehler(null);
      const { data, error } = await api.PUT("/api/projekte/{projekt_nr}", {
        params: { path: { projekt_nr: nummer } },
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
          stand: daten.stand as string,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setBearbeiten(false);
      neuLaden();
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const termine = useMutation({
    mutationFn: async (stand: MeilensteinDaten[]) => {
      setFehler(null);
      const { data, error } = await api.PUT(
        "/api/projekte/{projekt_nr}/meilensteine",
        {
          params: { path: { projekt_nr: nummer } },
          body: stand.map((m) => ({
            typ: m.typ as never,
            geplant_kw: m.geplant_kw || null,
            erledigt: m.erledigt ?? null,
            erledigt_am: m.erledigt_am || null,
            bemerkung: m.bemerkung || null,
          })),
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: neuLaden,
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  if (projekt.isLoading) return <p className="lademeldung">wird geladen …</p>;

  if (projekt.isError) {
    const ausgelesen = fehlerAuslesen(projekt.error);
    return (
      <>
        <Link to="/projekte" className="zurueck">
          ← Projekte
        </Link>
        <Meldung
          art="fehler"
          text={ausgelesen.meldung}
          naechsterSchritt={ausgelesen.naechster_schritt}
        />
      </>
    );
  }

  const p = projekt.data;
  if (!p) return null;

  const positionen = (p.zahlungsplan ?? []) as Zahlungsplanzeile[];
  const spalten: Spalte<Zahlungsplanzeile>[] = [
    { kopf: "Pos.", zahl: true, zelle: (z) => z.pos_nr, breite: "60px" },
    {
      kopf: "Bezeichnung",
      hervorgehoben: true,
      zelle: (z) => (
        <>
          <span className="projekte__name">{z.bezeichnung}</span>
          <span className="projekte__kunde">
            {ART_TEXT[z.art] ?? z.art} · {GEWERK_TEXT[z.gewerk] ?? z.gewerk}
          </span>
        </>
      ),
    },
    {
      kopf: "Planmonat",
      zelle: (z) =>
        z.plan_monat ? (
          monatText(z.plan_monat)
        ) : (
          <span className="projekte__leer">unterminiert</span>
        ),
    },
    {
      kopf: "Anteil (%)",
      zahl: true,
      zelle: (z) =>
        p.ab_wert_netto
          ? anteil((z.betrag_netto / p.ab_wert_netto) * 100)
          : "–",
    },
    {
      kopf: "Betrag netto (€)",
      zahl: true,
      zelle: (z) => euro(z.betrag_netto, false),
    },
    {
      kopf: "Status",
      zelle: (z) =>
        z.berechnet ? (
          <StatusBadge zustand="festgeschrieben" />
        ) : z.migriert_gestellt ? (
          <StatusBadge
            zustand="gestellt"
            titel="Vor der Einführung des Leitstands gestellt – Betrag und Monat sind gesperrt."
          />
        ) : (
          <StatusBadge zustand="geplant" />
        ),
    },
  ];

  const summe = positionen.reduce((s, z) => s + z.betrag_netto, 0);
  const luecke = (p.ab_wert_netto ?? 0) - summe;

  return (
    <>
      <Link to="/projekte" className="zurueck">
        ← Projekte
      </Link>

      <div className="projektkopf">
        <div>
          <h1 className="seitentitel">
            {p.projekt_nr} · {projektname(p.bezeichnung, p.kunde)}
            <span className="seitentitel__punkt">.</span>
          </h1>
          <div className="projektkopf__meta">
            <ProjektStatusBadge status={p.status} />
            <span>
              {kopfzeile([
                p.standort,
                p.anlagenart
                  ? (ANLAGENART_TEXT[p.anlagenart as Anlagenart] ??
                    p.anlagenart)
                  : null,
                p.pv_kwp ? leistung(p.pv_kwp) : null,
                p.speicher_kwh ? kapazitaet(p.speicher_kwh) : null,
                p.pl_name ? `Projektleitung ${p.pl_name}` : null,
              ])}
            </span>
          </div>
        </div>
        {darf("projekte.schreiben") ? (
          <Knopf
            onClick={() => {
              setFehler(null);
              setBearbeiten(true);
            }}
          >
            Projekt bearbeiten
          </Knopf>
        ) : null}
      </div>

      <Tabs
        reiter={[
          { schluessel: "uebersicht", beschriftung: "Übersicht" },
          {
            schluessel: "zahlungsplan",
            beschriftung: "Zahlungsplan & Rechnungen",
          },
          {
            schluessel: "nachkalkulation",
            beschriftung: "Nachkalkulation",
            spaeter: "ab Phase 4",
          },
          {
            schluessel: "dokumente",
            beschriftung: "Dokumente & Fristen",
            spaeter: "ab Phase 6",
          },
        ]}
        aktiv={reiter}
        onWechsel={setReiter}
        rechts={
          darfWerte &&
          p.ab_wert_netto !== null &&
          p.ab_wert_netto !== undefined ? (
            <>
              Auftragswert netto{" "}
              <span className="zahl">{euro(p.ab_wert_netto)}</span>
            </>
          ) : null
        }
      />

      {reiter === "uebersicht" ? (
        <>
          <dl className="datenblock">
            <div>
              <dt>Kunde</dt>
              <dd>{p.kunde}</dd>
            </div>
            <div>
              <dt>Standort</dt>
              <dd>{p.standort ?? "–"}</dd>
            </div>
            <div>
              <dt>Anlagenart</dt>
              <dd>
                {p.anlagenart
                  ? (ANLAGENART_TEXT[p.anlagenart as Anlagenart] ??
                    p.anlagenart)
                  : "ohne Angabe"}
              </dd>
            </div>
            <div>
              <dt>Leistung</dt>
              <dd className="zahl">{p.pv_kwp ? leistung(p.pv_kwp) : "–"}</dd>
            </div>
            <div>
              <dt>Speicher</dt>
              <dd className="zahl">
                {p.speicher_kwh ? kapazitaet(p.speicher_kwh) : "–"}
              </dd>
            </div>
            <div>
              <dt>Speichertyp</dt>
              <dd>{p.speicher_typ ?? "–"}</dd>
            </div>
            <div>
              <dt>Wechselrichter</dt>
              <dd>{p.wr_typ ?? "–"}</dd>
            </div>
            <div>
              <dt>Ladestation</dt>
              <dd>{p.ladestation ?? "–"}</dd>
            </div>
            <div>
              <dt>Auftrag vom</dt>
              <dd>{datumText(p.auftrag_vom) || "–"}</dd>
            </div>
            <div>
              <dt>Umsatzsteuer</dt>
              <dd>{UST_TEXT[p.ust_kz] ?? p.ust_kz}</dd>
            </div>
            <div>
              <dt>Vertriebsweg</dt>
              <dd>{p.vertriebsweg ?? "–"}</dd>
            </div>
            {p.quelle_migration ? (
              <div>
                <dt>Herkunft</dt>
                <dd className="datenblock__herkunft">{p.quelle_migration}</dd>
              </div>
            ) : null}
          </dl>

          {p.bemerkung ? <p className="bemerkung">{p.bemerkung}</p> : null}

          <h2 className="abschnittstitel">Termine</h2>
          <Meilensteine
            meilensteine={(p.meilensteine ?? []) as MeilensteinDaten[]}
            darfSchreiben={darf("meilensteine.schreiben")}
            laeuft={termine.isPending}
            fehler={fehler}
            onSpeichern={(stand) => termine.mutate(stand)}
          />
        </>
      ) : null}

      {reiter === "zahlungsplan" ? (
        !darfWerte ? (
          <EmptyState
            titel="Keine Beträge sichtbar"
            text="Zum Ansehen von Auftragswerten und Zahlungsplan fehlt die Berechtigung „Auftragswerte und Zahlungsplanbeträge ansehen“."
          />
        ) : (
          <>
            <DataTable
              spalten={spalten}
              zeilen={positionen}
              schluessel={(z) => z.id}
              beschriftung="Zahlungsplan"
              leer={
                <EmptyState
                  titel="Kein Zahlungsplan"
                  text="Für dieses Projekt sind keine Zahlungsplanpositionen erfasst."
                />
              }
            />
            {positionen.length ? (
              <p className="summenzeile">
                Summe Zahlungsplan <span className="zahl">{euro(summe)}</span>
                {p.ab_wert_netto ? (
                  <>
                    {" von "}
                    <span className="zahl">{euro(p.ab_wert_netto)}</span>
                    {Math.abs(luecke) > RUNDUNGSTOLERANZ_CENT ? (
                      <>
                        {" · "}
                        <span className="summenzeile__luecke">
                          {luecke > 0
                            ? "nicht verplant "
                            : "über dem Auftragswert "}
                          <span className="zahl">{euro(Math.abs(luecke))}</span>
                        </span>
                      </>
                    ) : null}
                  </>
                ) : null}
              </p>
            ) : null}
            <h2 className="abschnittstitel">Belege</h2>
            <EmptyState
              titel="Rechnungen ab Phase 3"
              text="Belege werden im Leitstand ab Phase 3 erstellt und festgeschrieben. Positionen, die vorher abgerechnet wurden, sind oben als „Gestellt“ gekennzeichnet."
              ohneZeichen
            />
          </>
        )
      ) : null}

      <DetailPanel
        offen={bearbeiten}
        titel={`Projekt ${p.projekt_nr}`}
        meta={projektname(p.bezeichnung, p.kunde)}
        onSchliessen={() => {
          setBearbeiten(false);
          setFehler(null);
        }}
      >
        <ProjektFormular
          projekt={p as unknown as ProjektDaten}
          laeuft={speichern.isPending}
          fehler={fehler}
          darfSchreiben={darf("projekte.schreiben")}
          darfWerte={darfWerte}
          onSpeichern={(daten) => speichern.mutate(daten)}
          onAbbrechen={() => setBearbeiten(false)}
        />
      </DetailPanel>

      {/* Gelöscht wird nicht: Projekte wechseln auf 'storniert' (CLAUDE.md Regel 5), und der
          Status steht im Formular. Die Reiter für Phase 4 und 6 sind gesperrt und können
          deshalb nie aktiv werden – sie brauchen hier keinen Zweig. */}
    </>
  );
}
