/**
 * Anlagenregister mit Fristen und Servicehistorie (PLAN §7 Phase 6).
 *
 * Die Anlage ist der Bezugspunkt für alles nach dem Bau. Drei Fragen beantwortet diese Seite:
 *
 * * **Welche Anlagen haben keinen Wartungsvertrag?** Der Filter ist der Ausgangspunkt fürs
 *   Servicegeschäft – jede Zeile darin ist ein Kunde, dem einer angeboten werden kann.
 * * **Was läuft demnächst ab?** Die Fristenliste zeigt alles Anstehende, nicht nur die
 *   Handvoll vom Startseiten-Widget.
 * * **Was ist an dieser Anlage passiert?** Das Seitenpanel führt Fristen und Serviceaufträge
 *   zusammen.
 *
 * Anlagen entstehen beim Projektabschluss von selbst (PLAN §6.9); die Maske hier ist zum
 * **Pflegen** – MaStR-Nummer, Wartungsvertrag, Bemerkung – und für den Altbestand.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PageTitle } from "@/komponenten/PageTitle";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { Seitenwechsel } from "@/komponenten/Seitenwechsel";
import { StatusBadge } from "@/komponenten/StatusBadge";
import { Tabs } from "@/komponenten/Tabs";
import { Einspeisung } from "./Einspeisung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import {
  anzahl as anzahlText,
  datum,
  kapazitaet,
  leistung,
} from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import {
  anlagenZusatz,
  frist as fristText,
  fristBadge,
  fristTyp,
  gewaehrleistung,
} from "./begriffe";
import "./service.css";

const JE_SEITE = 25;

type Zeile = {
  id: number;
  kunde: string;
  standort?: string | null;
  pv_kwp?: number | null;
  speicher_kwh?: number | null;
  inbetriebnahme?: string | null;
  gewaehrleistung_ende?: string | null;
  wartungsvertrag: boolean;
  mastr_nr?: string | null;
  projekt_nr?: number | null;
};

type Reiter = "anlagen" | "fristen" | "einspeisung";

export function Anlagen() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const darfSchreiben = darf("anlagen.schreiben");
  // Eigene Erlöse sind dem Team entzogen (PLAN §4) – ohne das Recht gibt es den
  // Reiter gar nicht, statt ihn zu zeigen und dann 403 zu antworten.
  const darfEinspeisung = darf("einspeisung.lesen");

  const [reiter, setReiter] = useState<Reiter>("anlagen");
  const [suche, setSuche] = useState("");
  const [nurOhneVertrag, setNurOhneVertrag] = useState(false);
  const [seite, setSeite] = useState(1);
  const [offeneId, setOffeneId] = useState<number | null>(null);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  // Bei geänderter Suche oder geändertem Filter zurück auf die erste Seite.
  useEffect(() => setSeite(1), [suche, nurOhneVertrag]);

  const liste = useQuery({
    queryKey: ["anlagen", { suche, nurOhneVertrag, seite }],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/anlagen", {
        params: {
          query: {
            suche: suche || undefined,
            ohne_wartungsvertrag: nurOhneVertrag,
            seite,
            anzahl: JE_SEITE,
          },
        },
      });
      if (error) throw error;
      return data;
    },
  });

  const anlage = useQuery({
    queryKey: ["anlage", offeneId],
    enabled: offeneId !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/anlagen/{anlage_id}", {
        params: { path: { anlage_id: offeneId as number } },
      });
      if (error) throw error;
      return data;
    },
  });

  const fristen = useQuery({
    queryKey: ["fristen", "alle"],
    enabled: reiter === "fristen",
    queryFn: async () => {
      const { data, error } = await api.GET("/api/fristen");
      if (error) throw error;
      return data;
    },
  });

  const speichern = useMutation({
    mutationFn: async (werte: {
      mastr_nr: string;
      wartungsvertrag: boolean;
      bemerkung: string;
    }) => {
      setFehler(null);
      const stand = anlage.data;
      if (!stand) throw new Error("kein Stand");
      const { data, error } = await api.PUT("/api/anlagen/{anlage_id}", {
        params: { path: { anlage_id: stand.id } },
        body: {
          kunde_id: stand.kunde_id,
          standort: stand.standort ?? null,
          pv_kwp: stand.pv_kwp ?? null,
          speicher_kwh: stand.speicher_kwh ?? null,
          inbetriebnahme: stand.inbetriebnahme ?? null,
          abnahme_datum: stand.abnahme_datum ?? null,
          gewaehrleistung_ende: stand.gewaehrleistung_ende ?? null,
          wartungsvertrag: werte.wartungsvertrag,
          mastr_nr: werte.mastr_nr || null,
          bemerkung: werte.bemerkung || null,
          stand: stand.stand,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      void abfragen.invalidateQueries({ queryKey: ["anlagen"] });
      void abfragen.invalidateQueries({ queryKey: ["anlage", offeneId] });
      void abfragen.invalidateQueries({ queryKey: ["fristen"] });
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const erledigen = useMutation({
    mutationFn: async ({ id, erledigt }: { id: number; erledigt: boolean }) => {
      setFehler(null);
      const { error } = await api.POST("/api/fristen/{frist_id}/erledigt", {
        params: { path: { frist_id: id }, query: { erledigt } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      void abfragen.invalidateQueries({ queryKey: ["fristen"] });
      void abfragen.invalidateQueries({ queryKey: ["anlage", offeneId] });
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const spalten: Spalte<Zeile>[] = [
    { kopf: "Standort", zelle: (z) => z.standort ?? "–", hervorgehoben: true },
    { kopf: "Kunde", zelle: (z) => z.kunde },
    { kopf: "Leistung (kWp)", zelle: (z) => leistung(z.pv_kwp), zahl: true },
    {
      kopf: "Speicher (kWh)",
      zelle: (z) => kapazitaet(z.speicher_kwh),
      zahl: true,
    },
    {
      kopf: "Inbetriebnahme",
      zelle: (z) => datum(z.inbetriebnahme),
      zahl: true,
    },
    {
      kopf: "Gewährleistung bis",
      zelle: (z) =>
        z.gewaehrleistung_ende ? datum(z.gewaehrleistung_ende) : "offen",
      zahl: true,
    },
    {
      kopf: "Wartung",
      zelle: (z) => (z.wartungsvertrag ? "Vertrag" : "–"),
    },
  ];

  return (
    <div>
      <PageTitle
        meta={
          // Nur auf dem Anlagenreiter: „0 Anlagen im Register" über einer Liste eigener
          // Anlagen wäre schlicht falsch – die Zahl gehört zum Kundenregister.
          reiter === "anlagen" && liste.data
            ? `${anzahlText(liste.data.gesamt, "Anlage", "Anlagen")} im Register`
            : undefined
        }
      >
        Service &amp; Anlagen
      </PageTitle>

      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      <Tabs
        reiter={[
          { schluessel: "anlagen", beschriftung: "Anlagen" },
          { schluessel: "fristen", beschriftung: "Fristen" },
          ...(darfEinspeisung
            ? [{ schluessel: "einspeisung", beschriftung: "Eigene Anlagen" }]
            : []),
        ]}
        aktiv={reiter}
        onWechsel={(s) => setReiter(s as Reiter)}
      />

      {reiter === "anlagen" ? (
        <>
          <div className="filterleiste">
            <label className="auswahlzeile">
              <span className="auswahlzeile__label">Suche</span>
              <input
                className="auswahlzeile__feld"
                type="search"
                value={suche}
                onChange={(e) => setSuche(e.target.value)}
                placeholder="Standort, Kunde oder MaStR-Nummer"
              />
            </label>

            <label className="auswahlzeile">
              <span className="auswahlzeile__label">Wartungsvertrag</span>
              <select
                className="auswahlzeile__feld"
                value={nurOhneVertrag ? "ohne" : "alle"}
                onChange={(e) => setNurOhneVertrag(e.target.value === "ohne")}
              >
                <option value="alle">alle Anlagen</option>
                <option value="ohne">nur ohne Wartungsvertrag</option>
              </select>
            </label>
          </div>

          <DataTable
            spalten={spalten}
            zeilen={(liste.data?.anlagen ?? []) as Zeile[]}
            schluessel={(z) => z.id}
            onZeileKlick={(z) => setOffeneId(z.id)}
            istAktiv={(z) => z.id === offeneId}
            beschriftung="Anlagenregister"
            leer={
              <EmptyState
                titel={
                  nurOhneVertrag || suche
                    ? "Keine Anlage passt zu diesem Filter."
                    : "Noch keine Anlage im Register."
                }
                text={
                  nurOhneVertrag || suche
                    ? "Filter zurücksetzen oder anders suchen."
                    : "Eine Anlage entsteht, sobald ein Projekt auf „abgeschlossen“ wechselt. " +
                      "Anlagen aus der Zeit davor lassen sich von Hand erfassen."
                }
              />
            }
          />

          <Seitenwechsel
            gesamt={liste.data?.gesamt ?? 0}
            versatz={(seite - 1) * JE_SEITE}
            anzahl={JE_SEITE}
            einheit={["Anlage", "Anlagen"]}
            onVersatz={(versatz) =>
              setSeite(Math.floor(versatz / JE_SEITE) + 1)
            }
          />
        </>
      ) : reiter === "fristen" ? (
        <Fristenliste
          zeilen={fristen.data?.fristen ?? []}
          laedt={fristen.isLoading}
          darfSchreiben={darfSchreiben}
          onErledigen={(id, erledigt) => erledigen.mutate({ id, erledigt })}
        />
      ) : (
        <Einspeisung />
      )}

      <Anlagenblatt
        offen={offeneId !== null}
        daten={
          anlage.data
            ? {
                ...anlage.data,
                fristen: anlage.data.fristen ?? [],
                servicehistorie: anlage.data.servicehistorie ?? [],
              }
            : null
        }
        darfSchreiben={darfSchreiben}
        speichert={speichern.isPending}
        onSpeichern={(werte) => speichern.mutate(werte)}
        onErledigen={(id, erledigt) => erledigen.mutate({ id, erledigt })}
        onSchliessen={() => {
          setOffeneId(null);
          setFehler(null);
        }}
      />
    </div>
  );
}

type Fristzeile = {
  id: number;
  typ: string;
  bezeichnung: string;
  faellig_am: string;
  status: string;
  tage_bis: number;
  betreff: string;
  kunde?: string | null;
  erledigt_am?: string | null;
};

function Fristenliste({
  zeilen,
  laedt,
  darfSchreiben,
  onErledigen,
}: {
  zeilen: Fristzeile[];
  laedt: boolean;
  darfSchreiben: boolean;
  onErledigen: (id: number, erledigt: boolean) => void;
}) {
  if (laedt) return null;
  if (zeilen.length === 0) {
    return (
      <EmptyState
        titel="Keine offene Frist."
        text={
          "Gewährleistungen entstehen beim Projektabschluss, MaStR-Fristen aus dem " +
          "Inbetriebnahmedatum. Fertigmeldungen und Reservierungen werden von Hand erfasst."
        }
      />
    );
  }

  return (
    <ul className="fristen">
      {zeilen.map((f) => (
        <li key={f.id} className="fristen__zeile">
          <div className="fristen__marke">
            <StatusBadge
              zustand={fristBadge(f.status)}
              text={fristText(f.tage_bis)}
              titel={`fällig am ${datum(f.faellig_am)}`}
            />
          </div>
          <div className="fristen__text">
            <div className="fristen__titel">
              {fristTyp(f.typ)} · {f.betreff}
            </div>
            <div className="fristen__meta">
              {f.kunde ? `${f.kunde} · ` : ""}
              {f.bezeichnung} · fällig {datum(f.faellig_am)}
            </div>
          </div>
          {darfSchreiben ? (
            <Knopf
              klein
              art="sekundaer"
              onClick={() => onErledigen(f.id, true)}
            >
              Erledigt
            </Knopf>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

type Blatt = {
  id: number;
  kunde: string;
  standort?: string | null;
  pv_kwp?: number | null;
  speicher_kwh?: number | null;
  inbetriebnahme?: string | null;
  abnahme_datum?: string | null;
  gewaehrleistung_ende?: string | null;
  wartungsvertrag: boolean;
  mastr_nr?: string | null;
  bemerkung?: string | null;
  projekt_nr?: number | null;
  fristen: Fristzeile[];
  servicehistorie: {
    projekt_nr: number;
    bezeichnung?: string | null;
    status: string;
    auftrag_vom?: string | null;
  }[];
};

function Anlagenblatt({
  offen,
  daten,
  darfSchreiben,
  speichert,
  onSpeichern,
  onErledigen,
  onSchliessen,
}: {
  offen: boolean;
  daten: Blatt | null;
  darfSchreiben: boolean;
  speichert: boolean;
  onSpeichern: (werte: {
    mastr_nr: string;
    wartungsvertrag: boolean;
    bemerkung: string;
  }) => void;
  onErledigen: (id: number, erledigt: boolean) => void;
  onSchliessen: () => void;
}) {
  const [mastrNr, setMastrNr] = useState("");
  const [wartungsvertrag, setWartungsvertrag] = useState(false);
  const [bemerkung, setBemerkung] = useState("");

  // Die Felder folgen dem geladenen Datensatz; ohne das stünde beim Öffnen der zweiten Anlage
  // noch die MaStR-Nummer der ersten im Feld.
  useEffect(() => {
    setMastrNr(daten?.mastr_nr ?? "");
    setWartungsvertrag(daten?.wartungsvertrag ?? false);
    setBemerkung(daten?.bemerkung ?? "");
  }, [daten?.id, daten?.mastr_nr, daten?.wartungsvertrag, daten?.bemerkung]);

  if (!daten) return null;

  return (
    <DetailPanel
      offen={offen}
      titel={daten.standort ?? `Anlage ${daten.id}`}
      meta={
        <>
          {daten.kunde} ·{" "}
          {anlagenZusatz(daten.inbetriebnahme, daten.wartungsvertrag)}
          {daten.projekt_nr ? (
            <>
              {" · aus Projekt "}
              <Link to={`/projekte/${daten.projekt_nr}`}>
                {daten.projekt_nr}
              </Link>
            </>
          ) : null}
        </>
      }
      onSchliessen={onSchliessen}
      fuss={
        darfSchreiben ? (
          <Knopf
            onClick={() =>
              onSpeichern({ mastr_nr: mastrNr, wartungsvertrag, bemerkung })
            }
            disabled={speichert}
          >
            Speichern
          </Knopf>
        ) : null
      }
    >
      <div className="anlagenblatt__abschnitt">
        <h3 className="anlagenblatt__ueberschrift">Anlage</h3>
        <dl style={{ margin: 0 }}>
          <div className="anlagenblatt__kennwert">
            <dt>Leistung</dt>
            <dd>{leistung(daten.pv_kwp)}</dd>
          </div>
          <div className="anlagenblatt__kennwert">
            <dt>Speicher</dt>
            <dd>{kapazitaet(daten.speicher_kwh)}</dd>
          </div>
          <div className="anlagenblatt__kennwert">
            <dt>Abnahme</dt>
            <dd>{datum(daten.abnahme_datum)}</dd>
          </div>
          <div className="anlagenblatt__kennwert">
            <dt>Gewährleistung</dt>
            <dd>{gewaehrleistung(daten.gewaehrleistung_ende)}</dd>
          </div>
        </dl>
      </div>

      <div className="anlagenblatt__abschnitt">
        <h3 className="anlagenblatt__ueberschrift">Fristen</h3>
        {daten.fristen.length === 0 ? (
          <p className="fristen__meta">Keine Frist erfasst.</p>
        ) : (
          <ul className="anlagenblatt__liste">
            {daten.fristen.map((f) => (
              <li
                key={f.id}
                className={
                  "anlagenblatt__eintrag" +
                  (f.erledigt_am ? " anlagenblatt__eintrag--erledigt" : "")
                }
              >
                <span>
                  {fristTyp(f.typ)}
                  <br />
                  <span className="fristen__meta">
                    {f.erledigt_am
                      ? `erledigt am ${datum(f.erledigt_am)}`
                      : fristText(f.tage_bis)}
                  </span>
                </span>
                <span className="anlagenblatt__wann">
                  {datum(f.faellig_am)}
                  {darfSchreiben && !f.erledigt_am ? (
                    <>
                      {" "}
                      <Knopf
                        klein
                        art="sekundaer"
                        onClick={() => onErledigen(f.id, true)}
                      >
                        Erledigt
                      </Knopf>
                    </>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="anlagenblatt__abschnitt">
        <h3 className="anlagenblatt__ueberschrift">Serviceaufträge</h3>
        {daten.servicehistorie.length === 0 ? (
          <p className="fristen__meta">
            Noch kein Serviceauftrag. Ein neuer entsteht als Projekt vom Typ
            „Service“ mit Bezug auf diese Anlage.
          </p>
        ) : (
          <ul className="anlagenblatt__liste">
            {daten.servicehistorie.map((s) => (
              <li key={s.projekt_nr} className="anlagenblatt__eintrag">
                <span>
                  <Link to={`/projekte/${s.projekt_nr}`}>{s.projekt_nr}</Link>
                  {s.bezeichnung ? ` · ${s.bezeichnung}` : ""}
                </span>
                <span className="anlagenblatt__wann">
                  {datum(s.auftrag_vom)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {darfSchreiben ? (
        <div className="anlagenblatt__abschnitt">
          <h3 className="anlagenblatt__ueberschrift">Pflegen</h3>
          <FormRow
            label="MaStR-Nummer"
            value={mastrNr}
            onChange={(e) => setMastrNr(e.target.value)}
            hinweis="Sobald sie eingetragen ist, gilt die Registrierungsfrist als erfüllt."
          />
          <label
            className="auswahlzeile"
            style={{ marginTop: "var(--abstand-3)" }}
          >
            <span className="auswahlzeile__label">Wartungsvertrag</span>
            <select
              className="auswahlzeile__feld"
              value={wartungsvertrag ? "ja" : "nein"}
              onChange={(e) => setWartungsvertrag(e.target.value === "ja")}
            >
              <option value="nein">kein Vertrag</option>
              <option value="ja">Vertrag vorhanden</option>
            </select>
          </label>
          <FormRow
            label="Bemerkung"
            value={bemerkung}
            onChange={(e) => setBemerkung(e.target.value)}
            breit
          />
        </div>
      ) : null}
    </DetailPanel>
  );
}
