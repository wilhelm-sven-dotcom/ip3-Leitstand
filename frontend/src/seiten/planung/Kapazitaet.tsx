/**
 * Wochenauslastung und Mannschaft (PLAN §7 Phase 7).
 *
 * Die Frage ist einfach: **Reicht die Mannschaft für das, was terminiert ist?** Die Seite
 * beantwortet sie Woche für Woche und sagt in derselben Ansicht, was an der Antwort unsicher
 * ist – unverplante Projekte, fehlende Sollstunden, Namen, die es in TimeTac gibt und hier
 * nicht.
 *
 * **Urlaub und Krankheit sind nicht abgebildet.** Der Hinweis steht als Einordnung unter der
 * Überschrift und kommt aus der API, damit die Oberfläche ihn nicht vergessen kann.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { DataTable } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { datum } from "@/format/formate";
import { STATUS_TEXT } from "@/seiten/projekte/begriffe";
import { useSitzung } from "@/sitzung/SitzungKontext";
import {
  auslastung,
  auslastungZusatz,
  kalenderwoche,
  kalenderwocheLang,
  satzgruppe,
  satzgruppen,
  stunden,
  wochenlage,
  wochenlageText,
} from "./begriffe";
import "./planung.css";

type Woche = {
  schluessel: string;
  beginn: string;
  bedarf: number;
  kapazitaet: number;
  rest: number;
  auslastung_promille: number | null;
  projekte: {
    projekt_nr: number;
    bezeichnung?: string | null;
    stunden: number;
  }[];
};

type Mitarbeiterzeile = {
  id: number;
  name: string;
  satzgruppe?: string | null;
  wochenstunden: number;
  aktiv: boolean;
  von?: string | null;
  bis?: string | null;
  stand: string;
};

const LEER = {
  id: 0,
  name: "",
  satzgruppe: "",
  wochenstunden: "38,5",
  aktiv: true,
  von: "",
  bis: "",
  stand: "",
};

export function Kapazitaet() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const darfSchreiben = darf("kapazitaet.schreiben");

  const [entwurf, setEntwurf] = useState<typeof LEER | null>(null);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  const kapazitaet = useQuery({
    queryKey: ["kapazitaet"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/kapazitaet");
      if (error) throw error;
      return data;
    },
  });

  const mannschaft = useQuery({
    queryKey: ["mitarbeiter"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mitarbeiter");
      if (error) throw error;
      return data;
    },
  });

  const speichern = useMutation({
    mutationFn: async (werte: typeof LEER) => {
      setFehler(null);
      const koerper = {
        name: werte.name,
        satzgruppe: (werte.satzgruppe || null) as never,
        wochenstunden: Number(werte.wochenstunden.replace(",", ".")) || 0,
        aktiv: werte.aktiv,
        von: werte.von || null,
        bis: werte.bis || null,
      };
      if (werte.id) {
        const { data, error } = await api.PUT(
          "/api/mitarbeiter/{mitarbeiter_id}",
          {
            params: { path: { mitarbeiter_id: werte.id } },
            body: { ...koerper, stand: werte.stand },
          },
        );
        if (error) throw error;
        return data;
      }
      const { data, error } = await api.POST("/api/mitarbeiter", {
        body: koerper,
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setEntwurf(null);
      void abfragen.invalidateQueries({ queryKey: ["mitarbeiter"] });
      void abfragen.invalidateQueries({ queryKey: ["kapazitaet"] });
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const wochen = (kapazitaet.data?.wochen ?? []) as Woche[];
  const schwelle = kapazitaet.data?.warnung_ab_promille ?? 900;
  const zusatz = auslastungZusatz(wochen, schwelle);
  const ueberbucht = wochen.some(
    (w) => wochenlage(w.auslastung_promille, schwelle) === "eng",
  );

  const spalten: Spalte<Mitarbeiterzeile>[] = [
    { kopf: "Name", zelle: (z) => z.name, hervorgehoben: true },
    { kopf: "Satzgruppe", zelle: (z) => satzgruppe(z.satzgruppe) },
    {
      kopf: "Wochenstunden",
      zelle: (z) => stunden(z.wochenstunden),
      zahl: true,
    },
    { kopf: "Im Haus", zelle: (z) => zeitraum(z.von, z.bis) },
    { kopf: "Status", zelle: (z) => (z.aktiv ? "aktiv" : "ausgeschieden") },
  ];

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
        <h2 className="karte__titel">Auslastung je Woche</h2>
        {zusatz ? (
          <span
            className={
              ueberbucht
                ? "planung__zusatz planung__zusatz--warnung"
                : "planung__zusatz"
            }
          >
            {zusatz}
          </span>
        ) : null}
      </div>
      <p className="planung__einordnung">{kapazitaet.data?.einordnung}</p>

      {(kapazitaet.data?.hinweise ?? []).map((hinweis) => (
        <Meldung key={hinweis} art="hinweis" text={hinweis} />
      ))}

      {wochen.length === 0 ? (
        <EmptyState
          titel="Noch keine Wochen zu zeigen."
          text="Sobald Projekte Montagetermine als Kalenderwoche tragen, steht hier die Auslastung."
        />
      ) : (
        <ul className="wochen">
          {wochen.map((woche) => (
            <Wochenzeile
              key={woche.schluessel}
              woche={woche}
              schwelle={schwelle}
            />
          ))}
        </ul>
      )}

      {(kapazitaet.data?.ohne_termin ?? []).length > 0 ? (
        <>
          <div className="planung__kopf">
            <h2 className="karte__titel">Ohne Montagetermin</h2>
            <span className="planung__zusatz">
              {stunden(kapazitaet.data?.stunden_ohne_termin)} unverplant
            </span>
          </div>
          <p className="planung__einordnung">
            Sollstunden ohne geplante Montagewoche: diese Arbeit fehlt in jeder
            Woche oben – die Auslastung ist damit zu günstig.
          </p>
          <ul className="wochen">
            {(kapazitaet.data?.ohne_termin ?? []).map((projekt) => (
              <li key={projekt.projekt_nr} className="wochen__zeile">
                <span className="wochen__kw">
                  <Link to={`/projekte/${projekt.projekt_nr}`}>
                    {projekt.projekt_nr}
                  </Link>
                </span>
                <span>{projekt.bezeichnung ?? "ohne Bezeichnung"}</span>
                <span className="wochen__zahlen">
                  {stunden(projekt.stunden)}
                </span>
                <span className="wochen__zahlen">
                  {statusText(projekt.status)}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <div className="planung__kopf">
        <h2 className="karte__titel">Mannschaft</h2>
        <span className="planung__zusatz">
          {stunden(wochen[0]?.kapazitaet)} in{" "}
          {kalenderwoche(wochen[0]?.schluessel ?? "")}
        </span>
        {darfSchreiben ? (
          <Knopf klein onClick={() => setEntwurf({ ...LEER })}>
            Mitarbeiter aufnehmen
          </Knopf>
        ) : null}
      </div>

      {(mannschaft.data?.ohne_datensatz ?? []).length > 0 ? (
        <Meldung
          art="hinweis"
          text={
            "In TimeTac buchen Namen, die hier fehlen: " +
            (mannschaft.data?.ohne_datensatz ?? []).join(", ") +
            "."
          }
          naechsterSchritt={
            "Ihre Stunden zählen in der Nachkalkulation, aber nicht in der Kapazität. Die " +
            "Schreibweise muss der in TimeTac entsprechen."
          }
        />
      ) : null}

      <DataTable
        spalten={spalten}
        zeilen={(mannschaft.data?.mitarbeiter ?? []) as Mitarbeiterzeile[]}
        schluessel={(z) => z.id}
        onZeileKlick={
          darfSchreiben
            ? (z) =>
                setEntwurf({
                  id: z.id,
                  name: z.name,
                  satzgruppe: z.satzgruppe ?? "",
                  wochenstunden: String(z.wochenstunden).replace(".", ","),
                  aktiv: z.aktiv,
                  von: z.von ?? "",
                  bis: z.bis ?? "",
                  stand: z.stand,
                })
            : undefined
        }
        beschriftung="Mannschaft"
        leer={
          <EmptyState
            titel="Noch keine Mitarbeiter erfasst."
            text={
              "Ohne sie gibt es keine Auslastung, nur den Bedarf. Die Schreibweise der Namen " +
              "muss der in TimeTac entsprechen."
            }
          />
        }
      />

      {entwurf ? (
        <Mitarbeitermaske
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

function statusText(schluessel: string): string {
  return STATUS_TEXT[schluessel as keyof typeof STATUS_TEXT] ?? schluessel;
}

function zeitraum(von?: string | null, bis?: string | null): string {
  if (!von && !bis) return "durchgehend";
  if (von && bis) return `${datum(von)} – ${datum(bis)}`;
  if (von) return `ab ${datum(von)}`;
  return `bis ${datum(bis)}`;
}

function Wochenzeile({ woche, schwelle }: { woche: Woche; schwelle: number }) {
  const lage = wochenlage(woche.auslastung_promille, schwelle);
  // Der Balken läuft nicht über 100 % hinaus, sondern färbt sich. Sonst müsste die Skala aller
  // Wochen mitwachsen und die Unterschiede darunter wären nicht mehr zu sehen.
  const breite = Math.min(100, (woche.auslastung_promille ?? 0) / 10);
  const klasse =
    lage === "eng"
      ? "wochen__fuellung wochen__fuellung--eng"
      : lage === "voll"
        ? "wochen__fuellung wochen__fuellung--voll"
        : "wochen__fuellung";

  return (
    <li className="wochen__zeile">
      <span className="wochen__kw">
        {kalenderwoche(woche.schluessel)}
        <span className="wochen__ab">ab {datum(woche.beginn)}</span>
      </span>
      <span
        className="wochen__balken"
        title={`${kalenderwocheLang(woche.schluessel)}: ${wochenlageText(lage)}`}
      >
        <span className={klasse} style={{ width: `${breite}%` }} />
        <span className="wochen__marke" style={{ left: "100%" }} />
      </span>
      <span className="wochen__zahlen">
        {stunden(woche.bedarf)} von {stunden(woche.kapazitaet)}
      </span>
      <span
        className={
          lage === "eng"
            ? "wochen__auslastung wochen__auslastung--eng"
            : "wochen__auslastung"
        }
      >
        {auslastung(woche.auslastung_promille)}
      </span>
      {woche.projekte.length > 0 ? (
        <span className="wochen__projekte">
          {woche.projekte
            .map((p) => `${p.projekt_nr} (${stunden(p.stunden)})`)
            .join(" · ")}
        </span>
      ) : null}
    </li>
  );
}

function Mitarbeitermaske({
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
  const setzen = (feld: keyof typeof LEER, wert: string | boolean) =>
    onAendern({ ...entwurf, [feld]: wert });

  return (
    <DetailPanel
      offen
      titel={entwurf.id ? entwurf.name : "Mitarbeiter aufnehmen"}
      meta={
        entwurf.id
          ? "Wer geht, wird auf „ausgeschieden“ gesetzt und nicht gelöscht."
          : "Der Name muss dem in TimeTac entsprechen."
      }
      onSchliessen={onAbbrechen}
      fuss={
        <Knopf
          onClick={onSpeichern}
          disabled={speichert || !entwurf.name.trim()}
        >
          Speichern
        </Knopf>
      }
    >
      <FormRow
        label="Name"
        value={entwurf.name}
        onChange={(e) => setzen("name", e.target.value)}
        hinweis="Schreibweise wie in TimeTac, üblicherweise „Nachname, Vorname“."
      />
      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Satzgruppe</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.satzgruppe}
          onChange={(e) => setzen("satzgruppe", e.target.value)}
        >
          <option value="">ohne Zuordnung</option>
          {satzgruppen().map((s) => (
            <option key={s.wert} value={s.wert}>
              {s.text}
            </option>
          ))}
        </select>
      </label>
      <FormRow
        label="Wochenstunden"
        zahl
        value={entwurf.wochenstunden}
        onChange={(e) => setzen("wochenstunden", e.target.value)}
        hinweis="Regelarbeitszeit ohne Urlaub und Krankheit."
      />
      <FormRow
        label="Im Haus ab"
        type="date"
        value={entwurf.von}
        onChange={(e) => setzen("von", e.target.value)}
        hinweis="Leer lassen, wenn schon immer."
      />
      <FormRow
        label="Im Haus bis"
        type="date"
        value={entwurf.bis}
        onChange={(e) => setzen("bis", e.target.value)}
        hinweis="Leer lassen, solange nichts feststeht."
      />
      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Status</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.aktiv ? "aktiv" : "aus"}
          onChange={(e) => setzen("aktiv", e.target.value === "aktiv")}
        >
          <option value="aktiv">aktiv</option>
          <option value="aus">ausgeschieden</option>
        </select>
      </label>
    </DetailPanel>
  );
}
