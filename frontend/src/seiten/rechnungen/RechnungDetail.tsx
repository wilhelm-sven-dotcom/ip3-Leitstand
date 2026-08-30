/**
 * Belegdetail: Kopf, Positionen, Summen, Absetzungsblock, Vorschau, Festschreiben.
 *
 * Die Seite bildet den Weg aus PLAN §10 ab: Entwurf ändern → Vorschau ansehen → festschreiben.
 * Danach ist nichts mehr änderbar; die Oberfläche zeigt dann keine Knöpfe, die zu einer
 * Fehlermeldung führen würden – die Sperre selbst sitzt im Server und in der Datenbank.
 *
 * **Gerechnet wird hier nichts.** Netto, Steuer je Satz, Absetzung und Zahlbetrag kommen fertig
 * vom Server; `summenzeilen` ordnet sie nur an. Ein zweiter Rechenweg im Frontend würde bei
 * Rundungen irgendwann vom PDF abweichen, und dann glaubte der Nutzer der falschen Zahl.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@/komponenten/ConfirmDialog";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { DetailPanel } from "@/komponenten/DetailPanel";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { PageTitle } from "@/komponenten/PageTitle";
import { StatusBadge } from "@/komponenten/StatusBadge";
import { Zusammenfassung } from "@/komponenten/Zusammenfassung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { NBSP, datum as datumText, euro } from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import {
  ART_TEXT,
  UST_TEXT,
  badgeZustand,
  belegnummer,
  belegtitel,
  mengeText,
  satzText,
  sperrgrund,
  summenzeilen,
  type Belegart,
  fehlendeUnterlagen,
} from "./begriffe";
import { PositionsFormular, type PositionsDaten } from "./PositionsFormular";
import "./rechnungen.css";

type Beleg = {
  id: number;
  rechnung_nr: string | null;
  art: string;
  status: string;
  projekt_nr: number | null;
  kunde_id: number;
  kunde_name: string;
  kunde_snapshot: Record<string, unknown> | null;
  abschlag_nr: number | null;
  datum: string;
  leistungszeitraum: string | null;
  faellig_am: string | null;
  ust_kz: string;
  betreff: string | null;
  anschreiben: string | null;
  schlusstext: string | null;
  netto: number;
  ust: number;
  brutto: number;
  absetzung_netto: number;
  absetzung_ust: number;
  zahlbetrag: number;
  ust_details: { satz: number; netto: number; ust: number }[];
  steuer_hinweise: string[];
  /** Pflichtunterlagen, die im Projektordner fehlen (Phase 7). Nur bei Schlussrechnungen. */
  fehlende_unterlagen: string[];
  positionen: {
    id: number;
    pos: number;
    bezeichnung: string;
    menge: string;
    einheit: string | null;
    ep_netto: number;
    ust_satz: number;
    netto: number;
  }[];
  absetzungen: {
    pos: number;
    rechnung_nr: string;
    datum: string;
    netto: number;
    ust_satz: number;
    ust: number;
    brutto: number;
  }[];
  hash: string | null;
  festgeschrieben_am: string | null;
  pdf_pfad: string | null;
  xml_pfad: string | null;
  storniert_durch_nr: string | null;
  aenderbar: boolean;
  stand: string;
};

export function RechnungDetail() {
  const { belegId } = useParams();
  const nummer = Number(belegId);
  const navigate = useNavigate();
  const abfragen = useQueryClient();
  const { darf } = useSitzung();

  const [fehler, setFehler] = useState<ApiFehler | null>(null);
  const [hinweis, setHinweis] = useState<string | null>(null);
  const [positionOffen, setPositionOffen] = useState<number | "neu" | null>(
    null,
  );
  const [festschreibenOffen, setFestschreibenOffen] = useState(false);
  const [bestaetigt, setBestaetigt] = useState(false);
  const [vorschauOffen, setVorschauOffen] = useState(false);

  const beleg = useQuery({
    queryKey: ["rechnung", nummer],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/rechnungen/{beleg_id}", {
        params: { path: { beleg_id: nummer } },
      });
      if (error) throw error;
      return data as unknown as Beleg;
    },
  });

  function neuLaden() {
    void abfragen.invalidateQueries({ queryKey: ["rechnung", nummer] });
    void abfragen.invalidateQueries({ queryKey: ["rechnungen"] });
    void abfragen.invalidateQueries({ queryKey: ["zahlungsplan"] });
  }

  const festschreiben = useMutation({
    mutationFn: async () => {
      setFehler(null);
      const { data, error } = await api.POST(
        "/api/rechnungen/{beleg_id}/festschreiben",
        {
          params: { path: { beleg_id: nummer } },
          // Fehlen Unterlagen im Projektordner, verlangt der Server eine ausdrückliche
          // Bestätigung. Der Haken im Dialog ist sie – der Text darüber sagt, was fehlt.
          body: { unterlagen_bestaetigt: true },
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: (daten) => {
      setFestschreibenOffen(false);
      setBestaetigt(false);
      // Die Ablage kann scheitern, ohne dass der Beleg ungültig wird. Der Server sagt das
      // ausdrücklich; verschwiegen wüsste niemand, dass das PDF fehlt.
      setHinweis(
        (daten as { ablage_offen?: string | null }).ablage_offen ??
          `Beleg ${(daten as { beleg: { rechnung_nr: string } }).beleg.rechnung_nr} ist festgeschrieben.`,
      );
      neuLaden();
    },
    onError: (e) => setFehler(fehlerAuslesen(e)),
  });

  const positionLoeschen = useMutation({
    mutationFn: async (positionId: number) => {
      setFehler(null);
      const { error } = await api.DELETE(
        "/api/rechnungen/{beleg_id}/positionen/{position_id}",
        { params: { path: { beleg_id: nummer, position_id: positionId } } },
      );
      if (error) throw error;
    },
    onSuccess: neuLaden,
    onError: (e) => setFehler(fehlerAuslesen(e)),
  });

  const positionSpeichern = useMutation({
    mutationFn: async (daten: PositionsDaten & { id?: number }) => {
      setFehler(null);
      const rumpf = {
        bezeichnung: daten.bezeichnung,
        menge: daten.menge,
        einheit: daten.einheit || null,
        ep_netto: daten.ep_netto,
        ust_satz: daten.ust_satz,
      };
      if (daten.id) {
        const { error } = await api.PUT(
          "/api/rechnungen/{beleg_id}/positionen/{position_id}",
          {
            params: { path: { beleg_id: nummer, position_id: daten.id } },
            body: rumpf,
          },
        );
        if (error) throw error;
        return;
      }
      const { error } = await api.POST(
        "/api/rechnungen/{beleg_id}/positionen",
        {
          params: { path: { beleg_id: nummer } },
          body: rumpf,
        },
      );
      if (error) throw error;
    },
    onSuccess: () => {
      setPositionOffen(null);
      neuLaden();
    },
    onError: (e) => setFehler(fehlerAuslesen(e)),
  });

  const stornieren = useMutation({
    mutationFn: async () => {
      setFehler(null);
      const { data, error } = await api.POST(
        "/api/rechnungen/{beleg_id}/storno",
        {
          params: { path: { beleg_id: nummer } },
          body: {},
        },
      );
      if (error) throw error;
      return data as unknown as Beleg;
    },
    onSuccess: (neuer) => navigate(`/fakturierung/${neuer.id}`),
    onError: (e) => setFehler(fehlerAuslesen(e)),
  });

  if (beleg.isLoading) {
    return <div className="seite">wird geladen …</div>;
  }
  if (beleg.error || !beleg.data) {
    const geladen = fehlerAuslesen(beleg.error);
    return (
      <div className="seite">
        <Meldung
          art="fehler"
          text={geladen.meldung}
          naechsterSchritt={geladen.naechster_schritt}
        />
        <Link to="/fakturierung">← Fakturierung</Link>
      </div>
    );
  }

  const daten = beleg.data;
  const gesperrt = sperrgrund(daten.status);
  const darfAendern = darf("rechnungen.erstellen") && daten.aenderbar;
  const zeilen = summenzeilen(daten);

  const spalten: Spalte<Beleg["positionen"][number]>[] = [
    { kopf: "Pos.", zahl: true, zelle: (p) => p.pos, breite: "4rem" },
    { kopf: "Bezeichnung", hervorgehoben: true, zelle: (p) => p.bezeichnung },
    {
      kopf: "Menge",
      zahl: true,
      zelle: (p) =>
        `${mengeText(p.menge)}${p.einheit ? `${NBSP}${p.einheit}` : ""}`,
      breite: "7rem",
    },
    {
      kopf: "Einzelpreis (€)",
      zahl: true,
      zelle: (p) => euro(p.ep_netto, false),
      breite: "9rem",
    },
    {
      kopf: "USt",
      zahl: true,
      zelle: (p) => satzText(p.ust_satz),
      breite: "5rem",
    },
    {
      kopf: "Betrag netto (€)",
      zahl: true,
      zelle: (p) => euro(p.netto, false),
      breite: "10rem",
    },
  ];

  return (
    <div className="seite">
      <Link to="/fakturierung" className="zurueck">
        ← Fakturierung
      </Link>

      <PageTitle
        meta={
          <span>
            {belegnummer(daten.rechnung_nr)} · {daten.kunde_name}
            {daten.projekt_nr ? (
              <>
                {" · "}
                <Link to={`/projekte/${daten.projekt_nr}`}>
                  Projekt {daten.projekt_nr}
                </Link>
              </>
            ) : null}
          </span>
        }
        aktionen={
          <div className="knopfzeile">
            <Knopf art="sekundaer" onClick={() => setVorschauOffen((o) => !o)}>
              {vorschauOffen ? "Vorschau schließen" : "PDF-Vorschau"}
            </Knopf>
            {darfAendern && darf("rechnungen.festschreiben") ? (
              <Knopf
                art="festschreiben"
                onClick={() => {
                  setBestaetigt(false);
                  setFestschreibenOffen(true);
                }}
              >
                Festschreiben
              </Knopf>
            ) : null}
            {daten.status === "festgeschrieben" &&
            darf("rechnungen.stornieren") ? (
              <Knopf art="sekundaer" onClick={() => stornieren.mutate()}>
                Stornobeleg erzeugen
              </Knopf>
            ) : null}
          </div>
        }
      >
        {belegtitel(daten.art, daten.abschlag_nr)}
      </PageTitle>

      <div className="belegkopf">
        <StatusBadge zustand={badgeZustand(daten.status)} />
        {daten.storniert_durch_nr ? (
          <span className="belegkopf__hinweis">
            storniert durch {daten.storniert_durch_nr}
          </span>
        ) : null}
      </div>

      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}
      {hinweis ? <Meldung text={hinweis} /> : null}
      {gesperrt ? <Meldung text={gesperrt} /> : null}

      <div className="belegdaten">
        <dl>
          <dt>Belegart</dt>
          <dd>{ART_TEXT[daten.art as Belegart] ?? daten.art}</dd>
          <dt>Belegdatum</dt>
          <dd className="zahl">{datumText(daten.datum)}</dd>
          <dt>Leistungszeitraum</dt>
          <dd>{daten.leistungszeitraum ?? "– fehlt noch –"}</dd>
          <dt>Fällig am</dt>
          <dd className="zahl">
            {daten.faellig_am ? datumText(daten.faellig_am) : "–"}
          </dd>
          <dt>Umsatzsteuer</dt>
          <dd>{UST_TEXT[daten.ust_kz] ?? daten.ust_kz}</dd>
          {daten.festgeschrieben_am ? (
            <>
              <dt>Festgeschrieben</dt>
              <dd className="zahl">{datumText(daten.festgeschrieben_am)}</dd>
              <dt>Prüfsumme</dt>
              <dd className="zahl belegdaten__hash">{daten.hash}</dd>
            </>
          ) : null}
          {daten.pdf_pfad ? (
            <>
              <dt>Ablage</dt>
              <dd className="belegdaten__pfad">{daten.pdf_pfad}</dd>
            </>
          ) : null}
        </dl>
      </div>

      <section className="belegabschnitt">
        <div className="belegabschnitt__kopf">
          <h2>Positionen</h2>
          {darfAendern ? (
            <Knopf klein onClick={() => setPositionOffen("neu")}>
              Position hinzufügen
            </Knopf>
          ) : null}
        </div>
        <DataTable
          spalten={spalten}
          zeilen={daten.positionen}
          schluessel={(p) => p.id}
          onZeileKlick={darfAendern ? (p) => setPositionOffen(p.id) : undefined}
          beschriftung="Belegpositionen"
          leer={
            <p className="hinweiszeile">
              Noch keine Position. Ein Beleg ohne Position lässt sich nicht
              festschreiben.
            </p>
          }
        />
      </section>

      <div className="summenblock">
        {zeilen.map((zeile) => (
          <div
            key={zeile.beschriftung}
            className={`summenblock__zeile${zeile.hervorgehoben ? " summenblock__zeile--summe" : ""}`}
          >
            <span>{zeile.beschriftung}</span>
            <span className="zahl">{euro(zeile.betrag)}</span>
          </div>
        ))}
      </div>

      {daten.absetzungen.length ? (
        <section className="belegabschnitt">
          <h2>Bereits berechnete Abschlagszahlungen (§ 14 Abs. 5 UStG)</h2>
          <DataTable
            spalten={[
              {
                kopf: "Rechnung",
                zelle: (a) => a.rechnung_nr,
                hervorgehoben: true,
              },
              { kopf: "Datum", zahl: true, zelle: (a) => datumText(a.datum) },
              {
                kopf: "Netto (€)",
                zahl: true,
                zelle: (a) => euro(a.netto, false),
              },
              {
                kopf: "USt-Satz",
                zahl: true,
                zelle: (a) => satzText(a.ust_satz),
              },
              {
                kopf: "Umsatzsteuer (€)",
                zahl: true,
                zelle: (a) => euro(a.ust, false),
              },
              {
                kopf: "Brutto (€)",
                zahl: true,
                zelle: (a) => euro(a.brutto, false),
              },
            ]}
            zeilen={daten.absetzungen}
            schluessel={(a) => a.pos}
            beschriftung="Abgesetzte Abschlagszahlungen"
          />
        </section>
      ) : null}

      {daten.steuer_hinweise.length ? (
        <div className="steuerhinweise">
          {daten.steuer_hinweise.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      ) : null}

      {vorschauOffen ? (
        <section className="belegabschnitt">
          <h2>Vorschau</h2>
          <iframe
            className="belegvorschau"
            title={`Vorschau ${belegnummer(daten.rechnung_nr)}`}
            src={`/api/rechnungen/${daten.id}/vorschau`}
          />
        </section>
      ) : null}

      <DetailPanel
        offen={positionOffen !== null}
        titel={
          positionOffen === "neu" ? "Position hinzufügen" : "Position ändern"
        }
        onSchliessen={() => setPositionOffen(null)}
      >
        {positionOffen !== null ? (
          <PositionsFormular
            position={
              positionOffen === "neu"
                ? undefined
                : daten.positionen.find((p) => p.id === positionOffen)
            }
            ustKennzeichen={daten.ust_kz}
            laeuft={positionSpeichern.isPending}
            onSpeichern={(werte) =>
              positionSpeichern.mutate({
                ...werte,
                ...(positionOffen === "neu" ? {} : { id: positionOffen }),
              })
            }
            onLoeschen={
              positionOffen === "neu"
                ? undefined
                : () => {
                    positionLoeschen.mutate(positionOffen);
                    setPositionOffen(null);
                  }
            }
          />
        ) : null}
      </DetailPanel>

      <ConfirmDialog
        offen={festschreibenOffen}
        titel={`${belegtitel(daten.art, daten.abschlag_nr)} festschreiben`}
        meta={`${daten.kunde_name}${daten.projekt_nr ? ` · Projekt ${daten.projekt_nr}` : ""}`}
        bestaetigungstext="Ich habe die Zusammenfassung geprüft und will den Beleg festschreiben."
        bestaetigt={bestaetigt}
        onBestaetigtChange={setBestaetigt}
        bestaetigenText="Jetzt festschreiben"
        unwiderruflich
        laeuft={festschreiben.isPending}
        onBestaetigen={() => festschreiben.mutate()}
        onAbbrechen={() => setFestschreibenOffen(false)}
      >
        <Zusammenfassung
          zeilen={[
            {
              label: "Rechnungsnummer",
              wert: "wird bei der Festschreibung vergeben",
            },
            { label: "Belegdatum", wert: datumText(daten.datum) },
            {
              label: "Leistungszeitraum",
              wert: daten.leistungszeitraum ?? "– fehlt noch –",
            },
            {
              label: "Fällig am",
              wert: daten.faellig_am ? datumText(daten.faellig_am) : "–",
            },
            ...zeilen.map((zeile) => ({
              label: zeile.beschriftung,
              wert: euro(zeile.betrag),
              summe: zeile.hervorgehoben,
            })),
          ]}
        />
        {daten.fehlende_unterlagen.length > 0 ? (
          <p className="dialoghinweis dialoghinweis--achtung">
            {fehlendeUnterlagen(daten.fehlende_unterlagen)} Der Scan sieht nur
            Dateinamen – liegt die Unterlage auf Papier oder unter einem anderen
            Namen vor, ist alles in Ordnung. Wer hier bestätigt, schreibt trotz
            der Lücke fest; das wird im Änderungsprotokoll vermerkt.
          </p>
        ) : null}
        <p className="dialoghinweis">
          Festschreiben ist unumkehrbar. Der Beleg erhält die nächste freie
          Nummer und kann danach nur noch per Stornobeleg korrigiert werden.
        </p>
      </ConfirmDialog>
    </div>
  );
}
