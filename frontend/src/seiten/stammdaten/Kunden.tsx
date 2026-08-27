/**
 * Kundenliste und Bearbeitung (PLAN §7 Phase 1).
 *
 * Die Migration legt 475 Kunden an – die Liste blättert deshalb serverseitig und sucht dort
 * auch. Eine Suche im Browser über 25 geladene Zeilen würde den Rest nicht finden und wäre
 * schlimmer als keine.
 *
 * Bearbeitet wird im Seitenpanel: die Liste bleibt sichtbar, und wer zehn Kunden durchsieht,
 * verliert nicht bei jedem Klick den Zusammenhang.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageTitle } from "@/komponenten/PageTitle";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { EmptyState } from "@/komponenten/EmptyState";
import { FormRow } from "@/komponenten/FormRow";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { Seitenwechsel } from "@/komponenten/Seitenwechsel";
import { ConfirmDialog } from "@/komponenten/ConfirmDialog";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { anzahl as anzahlText, zahl } from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { KundeFormular, LEERER_KUNDE, type KundeDaten } from "./KundeFormular";
import {
  AnsprechpartnerListe,
  type PartnerDaten,
  type PartnerEingabe,
} from "./Ansprechpartner";
import "./stammdaten.css";

const JE_SEITE = 25;

type Zeile = {
  id: number;
  kunden_nr: number;
  name: string;
  zusatz?: string | null;
  ort?: string | null;
  typ: string;
  status: string;
  anzahl_projekte: number;
};

type Statusfilter = "aktiv" | "inaktiv" | "alle";

export function Kunden() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const darfSchreiben = darf("kunden.schreiben");

  const [suche, setSuche] = useState("");
  const [status, setStatus] = useState<Statusfilter>("aktiv");
  const [versatz, setVersatz] = useState(0);
  const [offeneId, setOffeneId] = useState<number | null>(null);
  const [neuOffen, setNeuOffen] = useState(false);
  const [zuLoeschen, setZuLoeschen] = useState<PartnerDaten | null>(null);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  // Bei geänderter Suche oder geändertem Filter zurück auf die erste Seite: sonst zeigt die
  // Liste „Seite 3 von 1" und bleibt leer.
  useEffect(() => setVersatz(0), [suche, status]);

  const liste = useQuery({
    queryKey: ["kunden", { suche, status, versatz }],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/kunden", {
        params: { query: { suche, status, versatz, anzahl: JE_SEITE } },
      });
      if (error) throw error;
      return data;
    },
  });

  const kunde = useQuery({
    queryKey: ["kunde", offeneId],
    enabled: offeneId !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/kunden/{kunde_id}", {
        params: { path: { kunde_id: offeneId as number } },
      });
      if (error) throw error;
      return data;
    },
  });

  function neuLaden() {
    void abfragen.invalidateQueries({ queryKey: ["kunden"] });
    if (offeneId !== null)
      void abfragen.invalidateQueries({ queryKey: ["kunde", offeneId] });
  }

  const speichern = useMutation({
    mutationFn: async (daten: KundeDaten) => {
      setFehler(null);
      const koerper = {
        name: daten.name,
        zusatz: daten.zusatz || null,
        strasse: daten.strasse || null,
        plz: daten.plz || null,
        ort: daten.ort || null,
        ust_id: daten.ust_id || null,
        typ: daten.typ as "b2b" | "b2c",
        zahlungsziel_tage: daten.zahlungsziel_tage ?? null,
        email: daten.email || null,
        telefon: daten.telefon || null,
        status: daten.status as "aktiv" | "inaktiv",
        bemerkung: daten.bemerkung || null,
      };
      if (daten.id && daten.stand) {
        const { data, error } = await api.PUT("/api/kunden/{kunde_id}", {
          params: { path: { kunde_id: daten.id } },
          body: { ...koerper, stand: daten.stand },
        });
        if (error) throw error;
        return data;
      }
      const { data, error } = await api.POST("/api/kunden", { body: koerper });
      if (error) throw error;
      return data;
    },
    onSuccess: (daten) => {
      neuLaden();
      setNeuOffen(false);
      if (daten) setOffeneId(daten.id);
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const partnerAnlegen = useMutation({
    mutationFn: async (eingabe: PartnerEingabe) => {
      setFehler(null);
      const { data, error } = await api.POST(
        "/api/kunden/{kunde_id}/ansprechpartner",
        {
          params: { path: { kunde_id: offeneId as number } },
          body: {
            name: eingabe.name,
            funktion: (eingabe.funktion || null) as
              | "technik"
              | "kaufmaennisch"
              | "sonstig"
              | null,
            telefon: eingabe.telefon || null,
            email: eingabe.email || null,
          },
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: neuLaden,
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const partnerAendern = useMutation({
    mutationFn: async ({
      id,
      eingabe,
    }: {
      id: number;
      eingabe: PartnerEingabe & { stand: string };
    }) => {
      setFehler(null);
      const { data, error } = await api.PUT(
        "/api/ansprechpartner/{partner_id}",
        {
          params: { path: { partner_id: id } },
          body: {
            name: eingabe.name,
            funktion: (eingabe.funktion || null) as
              | "technik"
              | "kaufmaennisch"
              | "sonstig"
              | null,
            telefon: eingabe.telefon || null,
            email: eingabe.email || null,
            stand: eingabe.stand,
          },
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: neuLaden,
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const partnerLoeschen = useMutation({
    mutationFn: async (partner: PartnerDaten) => {
      setFehler(null);
      const { error } = await api.DELETE("/api/ansprechpartner/{partner_id}", {
        params: { path: { partner_id: partner.id } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      setZuLoeschen(null);
      neuLaden();
    },
    onError: (f) => {
      setZuLoeschen(null);
      setFehler(fehlerAuslesen(f));
    },
  });

  const spalten: Spalte<Zeile>[] = [
    { kopf: "Nr.", zahl: true, zelle: (z) => z.kunden_nr, breite: "80px" },
    {
      kopf: "Kunde",
      hervorgehoben: true,
      zelle: (z) => (
        <>
          <span className="kunden__name">{z.name}</span>
          {z.zusatz ? <span className="kunden__zusatz">{z.zusatz}</span> : null}
        </>
      ),
    },
    { kopf: "Ort", zelle: (z) => z.ort ?? "–" },
    {
      kopf: "Art",
      zelle: (z) => (z.typ === "b2b" ? "Geschäftskunde" : "Privatkunde"),
    },
    { kopf: "Projekte", zahl: true, zelle: (z) => zahl(z.anzahl_projekte) },
    {
      kopf: "Status",
      zelle: (z) =>
        z.status === "aktiv" ? (
          ""
        ) : (
          <span className="kunden__inaktiv">inaktiv</span>
        ),
    },
  ];

  const eintraege = (liste.data?.eintraege ?? []) as Zeile[];
  const geladenerKunde = (kunde.data ?? null) as
    | (KundeDaten & { ansprechpartner: PartnerDaten[] })
    | null;
  const panelOffen = neuOffen || offeneId !== null;

  return (
    <>
      <PageTitle
        meta={
          liste.data
            ? anzahlText(liste.data.gesamt, "Kunde", "Kunden") +
              (status === "aktiv"
                ? " (aktiv)"
                : status === "inaktiv"
                  ? " (inaktiv)"
                  : "")
            : undefined
        }
        aktionen={
          darfSchreiben ? (
            <Knopf
              onClick={() => {
                setOffeneId(null);
                setNeuOffen(true);
                setFehler(null);
              }}
            >
              Neuer Kunde
            </Knopf>
          ) : null
        }
      >
        Kunden
      </PageTitle>

      <div className="filterleiste">
        <FormRow
          label="Suche"
          type="search"
          value={suche}
          onChange={(e) => setSuche(e.target.value)}
          placeholder="Name, Ort oder Kundennummer"
          hinweis={"Umlaute beliebig: „poellath“ findet Pöllath."}
          breit
        />
        <label className="auswahlzeile">
          <span className="auswahlzeile__label">Status</span>
          <select
            className="auswahlzeile__feld"
            value={status}
            onChange={(e) => setStatus(e.target.value as Statusfilter)}
          >
            <option value="aktiv">nur aktive</option>
            <option value="inaktiv">nur inaktive</option>
            <option value="alle">alle</option>
          </select>
        </label>
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
        onZeileKlick={(z) => {
          setNeuOffen(false);
          setOffeneId(z.id);
          setFehler(null);
        }}
        beschriftung="Kundenliste"
        istAktiv={(z) => z.id === offeneId}
        leer={
          liste.isLoading ? (
            <p className="lademeldung">wird geladen …</p>
          ) : (
            <EmptyState
              titel={suche ? "Kein Kunde gefunden" : "Noch keine Kunden"}
              text={
                suche
                  ? "Andere Schreibweise versuchen, oder den Statusfilter auf „alle“ stellen."
                  : "Kunden entstehen bei der Übernahme der Bestandsdaten oder werden hier angelegt."
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
          einheit={["Kunde", "Kunden"]}
          onVersatz={setVersatz}
        />
      ) : null}

      <DetailPanel
        offen={panelOffen}
        titel={neuOffen ? "Neuer Kunde" : (geladenerKunde?.name ?? "Kunde")}
        meta={
          !neuOffen && geladenerKunde ? (
            <>
              Kundennummer {geladenerKunde.kunden_nr}
              {geladenerKunde.anzahl_projekte
                ? ` · ${anzahlText(geladenerKunde.anzahl_projekte, "Projekt", "Projekte")}`
                : null}
            </>
          ) : null
        }
        onSchliessen={() => {
          setOffeneId(null);
          setNeuOffen(false);
          setFehler(null);
        }}
      >
        {neuOffen ? (
          <KundeFormular
            kunde={LEERER_KUNDE}
            laeuft={speichern.isPending}
            fehler={fehler}
            darfSchreiben={darfSchreiben}
            onSpeichern={(daten) => speichern.mutate(daten)}
            onAbbrechen={() => setNeuOffen(false)}
          />
        ) : kunde.isLoading ? (
          <p className="lademeldung">wird geladen …</p>
        ) : geladenerKunde ? (
          <>
            <KundeFormular
              kunde={geladenerKunde}
              laeuft={speichern.isPending}
              fehler={fehler}
              darfSchreiben={darfSchreiben}
              onSpeichern={(daten) => speichern.mutate(daten)}
              onAbbrechen={() => setOffeneId(null)}
            />
            <AnsprechpartnerListe
              partner={geladenerKunde.ansprechpartner}
              darfSchreiben={darfSchreiben}
              laeuft={partnerAnlegen.isPending || partnerAendern.isPending}
              fehler={null}
              onAnlegen={(eingabe) => partnerAnlegen.mutate(eingabe)}
              onAendern={(id, eingabe) =>
                partnerAendern.mutate({ id, eingabe })
              }
              onLoeschen={setZuLoeschen}
            />
          </>
        ) : null}
      </DetailPanel>

      <ConfirmDialog
        offen={zuLoeschen !== null}
        titel="Ansprechpartner löschen"
        meta={zuLoeschen?.name}
        bestaetigenText="Löschen"
        laeuft={partnerLoeschen.isPending}
        onBestaetigen={() => zuLoeschen && partnerLoeschen.mutate(zuLoeschen)}
        onAbbrechen={() => setZuLoeschen(null)}
      >
        <p className="dialogtext">
          Der Eintrag wird entfernt. Name und Kontaktdaten bleiben im
          Änderungsprotokoll nachvollziehbar.
        </p>
      </ConfirmDialog>
    </>
  );
}
