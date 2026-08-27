/**
 * Zahlungsplan und Nachträge im Projektdetail (design/Projektdetail.dc.html, PLAN §6.12).
 *
 * Der wichtigste Gedanke der Maske: **gesperrte Positionen sind von Anfang an als gesperrt
 * gezeichnet.** Die Antwort der Schnittstelle trägt je Position einen `sperrgrund`; steht dort
 * etwas, zeigt die Zeile ein Schloss und das Panel den Grund samt Ausweg. Niemand soll erst beim
 * Speichern erfahren, dass er etwas nicht ändern darf.
 *
 * Zwei Sperren mit verschiedenen Auswegen:
 *
 * * **berechnet** – zu der Position gehört ein festgeschriebener Beleg. Ausweg: Storno, ab
 *   Phase 3.
 * * **migriert-gestellt** – die Rechnung wurde vor der Einführung des Leitstands gestellt, es
 *   gibt keinen Beleg zum Stornieren. Ausweg: das Kennzeichen ausdrücklich zurücknehmen. Das ist
 *   ein eigener Knopf mit Rückfrage, kein Nebeneffekt des Speicherns.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@/komponenten/ConfirmDialog";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Formular } from "@/komponenten/Formular";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { StatusBadge } from "@/komponenten/StatusBadge";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import {
  anteil,
  centAusText,
  euro,
  monat as monatText,
} from "@/format/formate";
import { MEILENSTEIN_TYPEN, meilensteinText } from "./begriffe";

/**
 * Ab welcher Abweichung die Deckungslücke ausgewiesen wird – dieselbe Toleranz wie im Import
 * (`RUNDUNGSTOLERANZ_CENT` in app/migration/uebernahme.py). Abschläge sind als Prozentsätze
 * gerechnet, da bleibt regelmäßig ein Cent übrig.
 */
const RUNDUNGSTOLERANZ_CENT = 100;

export const GEWERKE = ["pv", "speicher", "ls", "service", "nachtrag"] as const;
export const GEWERK_TEXT: Record<string, string> = {
  pv: "PV",
  speicher: "Speicher",
  ls: "Ladestation",
  service: "Service",
  nachtrag: "Nachtrag",
};

export const ARTEN = ["abschlag", "schluss", "einmal"] as const;
export const ART_TEXT: Record<string, string> = {
  abschlag: "Abschlag",
  schluss: "Schlussrechnung",
  einmal: "Einmalbetrag",
};

const NACHTRAG_STATUS = ["angeboten", "beauftragt", "berechnet"] as const;
const NACHTRAG_TEXT: Record<string, string> = {
  angeboten: "Angeboten",
  beauftragt: "Beauftragt",
  berechnet: "Berechnet",
};

export type Position = {
  id: number;
  pos_nr: number;
  bezeichnung: string;
  gewerk: string;
  art: string;
  betrag_netto: number;
  plan_monat?: string | null;
  trigger_status?: string | null;
  migriert_gestellt?: boolean | null;
  berechnet: boolean;
  quelle_migration?: string | null;
  stand: string;
  sperrgrund?: string | null;
};

export type NachtragZeile = {
  id: number;
  bezeichnung: string;
  betrag_netto: number;
  status: string;
  datum?: string | null;
  zaehlt_zum_soll: boolean;
  stand: string;
};

type Props = {
  projektNr: number;
  positionen: Position[];
  nachtraege: NachtragZeile[];
  abWertNetto?: number | null;
  sollNetto?: number | null;
  nachtraegeSumme?: number | null;
  deckungDifferenz?: number | null;
  darfSchreiben: boolean;
};

function centAlsText(cent: number | null | undefined): string {
  if (cent === null || cent === undefined) return "";
  return euro(cent, false);
}

type PositionEntwurf = {
  id?: number;
  bezeichnung: string;
  gewerk: string;
  art: string;
  betragText: string;
  plan_monat: string;
  trigger_status: string;
  stand?: string;
};

const LEERE_POSITION: PositionEntwurf = {
  bezeichnung: "",
  gewerk: "pv",
  art: "abschlag",
  betragText: "",
  plan_monat: "",
  trigger_status: "",
};

type NachtragEntwurf = {
  id?: number;
  bezeichnung: string;
  betragText: string;
  status: string;
  datum: string;
  stand?: string;
};

const LEERER_NACHTRAG: NachtragEntwurf = {
  bezeichnung: "",
  betragText: "",
  status: "angeboten",
  datum: "",
};

export function Zahlungsplan({
  projektNr,
  positionen,
  nachtraege,
  abWertNetto,
  sollNetto,
  nachtraegeSumme,
  deckungDifferenz,
  darfSchreiben,
}: Props) {
  const abfragen = useQueryClient();
  const [offenePosition, setOffenePosition] = useState<Position | null>(null);
  const [positionEntwurf, setPositionEntwurf] =
    useState<PositionEntwurf | null>(null);
  const [nachtragEntwurf, setNachtragEntwurf] =
    useState<NachtragEntwurf | null>(null);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);
  const [ruecknahme, setRuecknahme] = useState<Position | null>(null);
  const [zuLoeschen, setZuLoeschen] = useState<Position | null>(null);

  function neuLaden() {
    void abfragen.invalidateQueries({ queryKey: ["projekt", projektNr] });
    void abfragen.invalidateQueries({ queryKey: ["projekte"] });
  }

  function panelSchliessen() {
    setOffenePosition(null);
    setPositionEntwurf(null);
    setNachtragEntwurf(null);
    setFehler(null);
  }

  const positionSpeichern = useMutation({
    mutationFn: async (entwurf: PositionEntwurf) => {
      setFehler(null);
      const koerper = {
        bezeichnung: entwurf.bezeichnung,
        gewerk: entwurf.gewerk as (typeof GEWERKE)[number],
        art: entwurf.art as (typeof ARTEN)[number],
        betrag_netto: centAusText(entwurf.betragText) ?? 0,
        plan_monat: entwurf.plan_monat || null,
        trigger_status: (entwurf.trigger_status || null) as never,
      };
      if (entwurf.id && entwurf.stand) {
        const { data, error } = await api.PUT(
          "/api/zahlungsplan/{position_id}",
          {
            params: { path: { position_id: entwurf.id } },
            body: { ...koerper, stand: entwurf.stand },
          },
        );
        if (error) throw error;
        return data;
      }
      const { data, error } = await api.POST(
        "/api/projekte/{projekt_nr}/zahlungsplan",
        {
          params: { path: { projekt_nr: projektNr } },
          body: koerper,
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      panelSchliessen();
      neuLaden();
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const gestelltZuruecknehmen = useMutation({
    mutationFn: async (position: Position) => {
      setFehler(null);
      const { data, error } = await api.PUT(
        "/api/zahlungsplan/{position_id}/gestellt-zuruecknehmen",
        { params: { path: { position_id: position.id } } },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setRuecknahme(null);
      panelSchliessen();
      neuLaden();
    },
    onError: (f) => {
      setRuecknahme(null);
      setFehler(fehlerAuslesen(f));
    },
  });

  const positionLoeschen = useMutation({
    mutationFn: async (position: Position) => {
      setFehler(null);
      const { error } = await api.DELETE("/api/zahlungsplan/{position_id}", {
        params: { path: { position_id: position.id } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      setZuLoeschen(null);
      panelSchliessen();
      neuLaden();
    },
    onError: (f) => {
      setZuLoeschen(null);
      setFehler(fehlerAuslesen(f));
    },
  });

  const nachtragSpeichern = useMutation({
    mutationFn: async (entwurf: NachtragEntwurf) => {
      setFehler(null);
      const koerper = {
        bezeichnung: entwurf.bezeichnung,
        betrag_netto: centAusText(entwurf.betragText) ?? 0,
        status: entwurf.status as (typeof NACHTRAG_STATUS)[number],
        datum: entwurf.datum || null,
      };
      if (entwurf.id && entwurf.stand) {
        const { data, error } = await api.PUT("/api/nachtraege/{nachtrag_id}", {
          params: { path: { nachtrag_id: entwurf.id } },
          body: { ...koerper, stand: entwurf.stand },
        });
        if (error) throw error;
        return data;
      }
      const { data, error } = await api.POST(
        "/api/projekte/{projekt_nr}/nachtraege",
        {
          params: { path: { projekt_nr: projektNr } },
          body: koerper,
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      panelSchliessen();
      neuLaden();
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const nachtragLoeschen = useMutation({
    mutationFn: async (id: number) => {
      setFehler(null);
      const { error } = await api.DELETE("/api/nachtraege/{nachtrag_id}", {
        params: { path: { nachtrag_id: id } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      panelSchliessen();
      neuLaden();
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const summe = positionen.reduce((s, p) => s + p.betrag_netto, 0);
  const bezugswert = sollNetto ?? abWertNetto ?? 0;

  const spalten: Spalte<Position>[] = [
    { kopf: "Pos.", zahl: true, zelle: (p) => p.pos_nr, breite: "60px" },
    {
      kopf: "Bezeichnung",
      hervorgehoben: true,
      zelle: (p) => (
        <>
          <span className="projekte__name">
            {p.bezeichnung}
            {p.sperrgrund ? (
              <span
                className="zahlungsplan__schloss"
                title={p.sperrgrund}
                aria-label="gesperrt"
              >
                {" \u{1F512}"}
              </span>
            ) : null}
          </span>
          <span className="projekte__kunde">
            {ART_TEXT[p.art] ?? p.art} · {GEWERK_TEXT[p.gewerk] ?? p.gewerk}
            {p.trigger_status
              ? ` · Auslöser ${meilensteinText(p.trigger_status)}`
              : ""}
          </span>
        </>
      ),
    },
    {
      kopf: "Planmonat",
      zelle: (p) =>
        p.plan_monat ? (
          monatText(p.plan_monat)
        ) : (
          <span className="projekte__leer">unterminiert</span>
        ),
    },
    {
      kopf: "Anteil (%)",
      zahl: true,
      zelle: (p) =>
        bezugswert ? anteil((p.betrag_netto / bezugswert) * 100) : "–",
    },
    {
      kopf: "Betrag netto (€)",
      zahl: true,
      zelle: (p) => euro(p.betrag_netto, false),
    },
    {
      kopf: "Status",
      zelle: (p) =>
        p.berechnet ? (
          <StatusBadge zustand="festgeschrieben" />
        ) : p.migriert_gestellt ? (
          <StatusBadge zustand="gestellt" titel={p.sperrgrund ?? undefined} />
        ) : (
          <StatusBadge zustand="geplant" />
        ),
    },
  ];

  const nachtragSpalten: Spalte<NachtragZeile>[] = [
    { kopf: "Nachtrag", hervorgehoben: true, zelle: (n) => n.bezeichnung },
    {
      kopf: "Datum",
      zelle: (n) =>
        n.datum ? (
          new Date(n.datum).toLocaleDateString("de-DE")
        ) : (
          <span className="projekte__leer">–</span>
        ),
    },
    {
      kopf: "Status",
      zelle: (n) => (
        <>
          {NACHTRAG_TEXT[n.status] ?? n.status}
          {n.zaehlt_zum_soll ? null : (
            <span className="projekte__kunde">zählt nicht zum Soll</span>
          )}
        </>
      ),
    },
    {
      kopf: "Betrag netto (€)",
      zahl: true,
      zelle: (n) => euro(n.betrag_netto, false),
    },
  ];

  return (
    <>
      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      <div className="abschnittskopf">
        <h2 className="abschnittstitel">Zahlungsplan</h2>
        {darfSchreiben ? (
          <Knopf
            art="sekundaer"
            klein
            onClick={() => {
              setOffenePosition(null);
              setPositionEntwurf(LEERE_POSITION);
              setFehler(null);
            }}
          >
            Position hinzufügen
          </Knopf>
        ) : null}
      </div>

      <DataTable
        spalten={spalten}
        zeilen={positionen}
        schluessel={(p) => p.id}
        beschriftung="Zahlungsplan"
        istAktiv={(p) => p.id === offenePosition?.id}
        onZeileKlick={
          darfSchreiben
            ? (p) => {
                setFehler(null);
                setOffenePosition(p);
                setNachtragEntwurf(null);
                setPositionEntwurf(
                  p.sperrgrund
                    ? null
                    : {
                        id: p.id,
                        bezeichnung: p.bezeichnung,
                        gewerk: p.gewerk,
                        art: p.art,
                        betragText: centAlsText(p.betrag_netto),
                        plan_monat: p.plan_monat ?? "",
                        trigger_status: p.trigger_status ?? "",
                        stand: p.stand,
                      },
                );
              }
            : undefined
        }
        leer={
          <EmptyState
            titel="Kein Zahlungsplan"
            text={
              darfSchreiben
                ? "Positionen für Abschläge und die Schlussrechnung hier anlegen – aus ihnen entstehen ab Phase 3 die Rechnungen."
                : "Für dieses Projekt sind keine Zahlungsplanpositionen erfasst."
            }
            ohneZeichen
          />
        }
      />

      {positionen.length ? (
        <p className="summenzeile">
          Summe Zahlungsplan <span className="zahl">{euro(summe)}</span>
          {sollNetto !== null && sollNetto !== undefined ? (
            <>
              {" von "}
              <span className="zahl">{euro(sollNetto)}</span>
              {nachtraegeSumme ? " (Auftrag und beauftragte Nachträge)" : ""}
              {deckungDifferenz !== null &&
              deckungDifferenz !== undefined &&
              Math.abs(deckungDifferenz) > RUNDUNGSTOLERANZ_CENT ? (
                <>
                  {" · "}
                  <span className="summenzeile__luecke">
                    {deckungDifferenz > 0
                      ? "nicht verplant "
                      : "über dem Auftragswert "}
                    <span className="zahl">
                      {euro(Math.abs(deckungDifferenz))}
                    </span>
                  </span>
                </>
              ) : null}
            </>
          ) : null}
        </p>
      ) : null}

      <div className="abschnittskopf">
        <h2 className="abschnittstitel">Nachträge</h2>
        {darfSchreiben ? (
          <Knopf
            art="sekundaer"
            klein
            onClick={() => {
              setOffenePosition(null);
              setPositionEntwurf(null);
              setNachtragEntwurf(LEERER_NACHTRAG);
              setFehler(null);
            }}
          >
            Nachtrag hinzufügen
          </Knopf>
        ) : null}
      </div>

      <DataTable
        spalten={nachtragSpalten}
        zeilen={nachtraege}
        schluessel={(n) => n.id}
        beschriftung="Nachträge"
        onZeileKlick={
          darfSchreiben
            ? (n) => {
                setFehler(null);
                setOffenePosition(null);
                setPositionEntwurf(null);
                setNachtragEntwurf({
                  id: n.id,
                  bezeichnung: n.bezeichnung,
                  betragText: centAlsText(n.betrag_netto),
                  status: n.status,
                  datum: n.datum ?? "",
                  stand: n.stand,
                });
              }
            : undefined
        }
        leer={
          <EmptyState
            titel="Keine Nachträge"
            text="Beauftragte Nachträge erhöhen den Soll-Wert des Zahlungsplans."
            ohneZeichen
          />
        }
      />

      <h2 className="abschnittstitel">Belege</h2>
      <EmptyState
        titel="Rechnungen ab Phase 3"
        text="Belege werden im Leitstand ab Phase 3 erstellt und festgeschrieben. Positionen, die vorher abgerechnet wurden, sind oben als „Gestellt“ gekennzeichnet."
        ohneZeichen
      />

      {/* --- Panel: Position bearbeiten, anlegen oder als gesperrt erklären --- */}
      <DetailPanel
        offen={positionEntwurf !== null || offenePosition !== null}
        titel={
          positionEntwurf?.id || offenePosition
            ? `Position ${offenePosition?.pos_nr ?? ""}`
            : "Neue Position"
        }
        meta={offenePosition?.quelle_migration ?? undefined}
        onSchliessen={panelSchliessen}
      >
        {offenePosition?.sperrgrund ? (
          <div className="gesperrt">
            <Meldung art="hinweis" text={offenePosition.sperrgrund} />
            <dl className="datenblock datenblock--panel">
              <div>
                <dt>Bezeichnung</dt>
                <dd>{offenePosition.bezeichnung}</dd>
              </div>
              <div>
                <dt>Betrag netto</dt>
                <dd className="zahl">{euro(offenePosition.betrag_netto)}</dd>
              </div>
              <div>
                <dt>Planmonat</dt>
                <dd>
                  {offenePosition.plan_monat
                    ? monatText(offenePosition.plan_monat)
                    : "unterminiert"}
                </dd>
              </div>
            </dl>
            {offenePosition.migriert_gestellt && !offenePosition.berechnet ? (
              <>
                <p className="hinweistext">
                  Zum Korrigieren zuerst das Kennzeichen „gestellt“
                  zurücknehmen. Der Betrag zählt danach nicht mehr zum Umsatz
                  des Altbestands; beide Schritte stehen im Änderungsprotokoll.
                </p>
                <Knopf
                  art="sekundaer"
                  onClick={() => setRuecknahme(offenePosition)}
                >
                  Kennzeichen „gestellt“ zurücknehmen
                </Knopf>
              </>
            ) : (
              <p className="hinweistext">
                Änderungen sind nur über den Storno des Belegs möglich – die
                Fakturierung kommt mit Phase 3.
              </p>
            )}
          </div>
        ) : positionEntwurf ? (
          <Formular
            fehler={fehler}
            laeuft={positionSpeichern.isPending}
            onSpeichern={() => positionSpeichern.mutate(positionEntwurf)}
            onAbbrechen={panelSchliessen}
            weitereAktionen={
              positionEntwurf.id && offenePosition ? (
                <Knopf
                  art="sekundaer"
                  klein
                  onClick={() => setZuLoeschen(offenePosition)}
                >
                  Löschen
                </Knopf>
              ) : null
            }
          >
            <FormRow
              label="Bezeichnung"
              value={positionEntwurf.bezeichnung}
              onChange={(e) =>
                setPositionEntwurf({
                  ...positionEntwurf,
                  bezeichnung: e.target.value,
                })
              }
              hinweis="Steht ab Phase 3 auf der Rechnung, z. B. „2. Abschlag PV“."
              breit
            />
            <label className="auswahlzeile">
              <span className="auswahlzeile__label">Gewerk</span>
              <select
                className="auswahlzeile__feld"
                value={positionEntwurf.gewerk}
                onChange={(e) =>
                  setPositionEntwurf({
                    ...positionEntwurf,
                    gewerk: e.target.value,
                  })
                }
              >
                {GEWERKE.map((g) => (
                  <option key={g} value={g}>
                    {GEWERK_TEXT[g]}
                  </option>
                ))}
              </select>
            </label>
            <label className="auswahlzeile">
              <span className="auswahlzeile__label">Art</span>
              <select
                className="auswahlzeile__feld"
                value={positionEntwurf.art}
                onChange={(e) =>
                  setPositionEntwurf({
                    ...positionEntwurf,
                    art: e.target.value,
                  })
                }
              >
                {ARTEN.map((a) => (
                  <option key={a} value={a}>
                    {ART_TEXT[a]}
                  </option>
                ))}
              </select>
            </label>
            <FormRow
              label="Betrag netto (€)"
              zahl
              value={positionEntwurf.betragText}
              onChange={(e) =>
                setPositionEntwurf({
                  ...positionEntwurf,
                  betragText: e.target.value,
                })
              }
              placeholder="0,00"
            />
            <FormRow
              label="Planmonat"
              type="month"
              value={positionEntwurf.plan_monat}
              onChange={(e) =>
                setPositionEntwurf({
                  ...positionEntwurf,
                  plan_monat: e.target.value,
                })
              }
              hinweis="Leer lassen heißt „unterminiert“ – die Position erscheint im Forecast gesondert."
            />
            <label className="auswahlzeile">
              <span className="auswahlzeile__label">Auslöser</span>
              <select
                className="auswahlzeile__feld"
                value={positionEntwurf.trigger_status}
                onChange={(e) =>
                  setPositionEntwurf({
                    ...positionEntwurf,
                    trigger_status: e.target.value,
                  })
                }
              >
                <option value="">ohne Auslöser</option>
                {MEILENSTEIN_TYPEN.map((typ) => (
                  <option key={typ} value={typ}>
                    {meilensteinText(typ)}
                  </option>
                ))}
              </select>
              <span className="auswahlzeile__hinweis">
                Erreicht das Projekt diesen Schritt, erscheint die Position als
                Rechnungsvorschlag auf der Startseite. Nur ein Vorschlag –
                nichts wird automatisch verschickt.
              </span>
            </label>
          </Formular>
        ) : null}
      </DetailPanel>

      {/* --- Panel: Nachtrag --- */}
      <DetailPanel
        offen={nachtragEntwurf !== null}
        titel={nachtragEntwurf?.id ? "Nachtrag" : "Neuer Nachtrag"}
        onSchliessen={panelSchliessen}
      >
        {nachtragEntwurf ? (
          <Formular
            fehler={fehler}
            laeuft={nachtragSpeichern.isPending}
            onSpeichern={() => nachtragSpeichern.mutate(nachtragEntwurf)}
            onAbbrechen={panelSchliessen}
            weitereAktionen={
              nachtragEntwurf.id ? (
                <Knopf
                  art="sekundaer"
                  klein
                  onClick={() =>
                    nachtragLoeschen.mutate(nachtragEntwurf.id as number)
                  }
                >
                  Löschen
                </Knopf>
              ) : null
            }
          >
            <FormRow
              label="Bezeichnung"
              value={nachtragEntwurf.bezeichnung}
              onChange={(e) =>
                setNachtragEntwurf({
                  ...nachtragEntwurf,
                  bezeichnung: e.target.value,
                })
              }
              breit
            />
            <FormRow
              label="Betrag netto (€)"
              zahl
              value={nachtragEntwurf.betragText}
              onChange={(e) =>
                setNachtragEntwurf({
                  ...nachtragEntwurf,
                  betragText: e.target.value,
                })
              }
              hinweis="Eine entfallene Leistung wird als negativer Betrag erfasst."
            />
            <label className="auswahlzeile">
              <span className="auswahlzeile__label">Status</span>
              <select
                className="auswahlzeile__feld"
                value={nachtragEntwurf.status}
                onChange={(e) =>
                  setNachtragEntwurf({
                    ...nachtragEntwurf,
                    status: e.target.value,
                  })
                }
              >
                {NACHTRAG_STATUS.map((s) => (
                  <option key={s} value={s}>
                    {NACHTRAG_TEXT[s]}
                  </option>
                ))}
              </select>
              <span className="auswahlzeile__hinweis">
                Erst ab „Beauftragt“ zählt der Nachtrag zum Soll-Wert des
                Zahlungsplans.
              </span>
            </label>
            <FormRow
              label="Datum"
              type="date"
              value={nachtragEntwurf.datum}
              onChange={(e) =>
                setNachtragEntwurf({
                  ...nachtragEntwurf,
                  datum: e.target.value,
                })
              }
            />
          </Formular>
        ) : null}
      </DetailPanel>

      <ConfirmDialog
        offen={ruecknahme !== null}
        titel="Kennzeichen „gestellt“ zurücknehmen"
        meta={
          ruecknahme
            ? `Position ${ruecknahme.pos_nr} · ${euro(ruecknahme.betrag_netto)}`
            : ""
        }
        bestaetigenText="Zurücknehmen"
        laeuft={gestelltZuruecknehmen.isPending}
        onBestaetigen={() =>
          ruecknahme && gestelltZuruecknehmen.mutate(ruecknahme)
        }
        onAbbrechen={() => setRuecknahme(null)}
      >
        <p className="dialogtext">
          Der Betrag zählt danach nicht mehr als gestellter Umsatz des
          Altbestands, und die Position ist wieder bearbeitbar. Der Vorgang
          steht im Änderungsprotokoll.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        offen={zuLoeschen !== null}
        titel="Position löschen"
        meta={
          zuLoeschen
            ? `Position ${zuLoeschen.pos_nr} · ${zuLoeschen.bezeichnung}`
            : ""
        }
        bestaetigenText="Löschen"
        laeuft={positionLoeschen.isPending}
        onBestaetigen={() => zuLoeschen && positionLoeschen.mutate(zuLoeschen)}
        onAbbrechen={() => setZuLoeschen(null)}
      >
        <p className="dialogtext">
          Die Planung entfällt. Der Vorgang steht mit Betrag und Planmonat im
          Änderungsprotokoll.
        </p>
      </ConfirmDialog>
    </>
  );
}
