/**
 * Zuordnungsmaske der Bestandsübernahme (PLAN §7 Phase 1, PLAN §9).
 *
 * Die Auftragsliste kennt den Kunden nur als Freitext. Der Abgleich mit der Teamliste ordnet
 * eindeutige Treffer selbst zu; alles andere entscheidet hier ein Mensch. Der Grund steht im
 * Bestand: ein Ähnlichkeitsmaß auf dem Gesamttext liefert „Nachtmann, Weiden" auf „Hubmann,
 * Weiden" – zwei verschiedene Kunden, 550.000 € am falschen Projekt.
 *
 * Drei Entscheidungen der Maske, alle mit Absicht:
 *
 * * **Kein Vorschlag ist vorausgewählt.** Eine vorbelegte Maske wird durchgeklickt, und dann
 *   ist die Bestätigung wertlos.
 * * **Entschieden wird je Kunde, nicht je Zeile.** Die acht Abschläge eines Projekts gehören
 *   zusammen; achtmal dieselbe Frage lädt zum Wegklicken ein.
 * * **Die Übernahme ist ein Dialog mit Zahlen**, nicht ein Knopf. Sie lässt sich nicht
 *   zurücknehmen, und die Zahlen sind das, was bestätigt wird.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageTitle } from "@/komponenten/PageTitle";
import { KpiTile } from "@/komponenten/KpiTile";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { ConfirmDialog } from "@/komponenten/ConfirmDialog";
import { Zusammenfassung } from "@/komponenten/Zusammenfassung";
import { api, fehlerAuslesen } from "@/api/client";
import {
  anzahl,
  datum,
  datumZeit,
  euro,
  leistung,
  zahl,
} from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { ProjektWaehler, type Kandidat } from "./ProjektWaehler";
import {
  alleEntschieden,
  betragOffen,
  fortschritt,
  fuerSchnittstelle,
  leereEntscheidungen,
  type Entscheidungen,
  type Zuordnung as ZuordnungTyp,
} from "./entscheidungen";
import "./zuordnung.css";

type Befund = {
  datei: string;
  zeile: number;
  spalte: string;
  wert: string;
  meldung: string;
  schwere: string;
};

export function MigrationZuordnung() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const [entscheidungen, setEntscheidungen] =
    useState<Entscheidungen>(leereEntscheidungen);
  const [waehlerFuer, setWaehlerFuer] = useState<string | null>(null);
  const [dialogOffen, setDialogOffen] = useState(false);
  const [bestaetigt, setBestaetigt] = useState(false);
  const [alleBefunde, setAlleBefunde] = useState(false);

  const stand = useQuery({
    queryKey: ["migration", "stand"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/migration/stand");
      if (error) throw error;
      return data;
    },
  });

  const vorschau = useQuery({
    queryKey: ["migration", "vorschau"],
    // Erst laden, wenn feststeht, dass noch nicht migriert wurde: das Lesen beider Dateien
    // dauert und wäre sonst umsonst.
    enabled: stand.data?.migriert === false,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/migration/vorschau");
      if (error) throw error;
      return data;
    },
    staleTime: Infinity,
  });

  const uebernehmen = useMutation({
    mutationFn: async () => {
      const daten = vorschau.data;
      if (!daten) throw new Error("Vorschau fehlt");
      const { data, error } = await api.POST("/api/migration/uebernehmen", {
        body: {
          kennung: daten.kennung,
          entscheidungen: fuerSchnittstelle(
            daten.zuordnungen as ZuordnungTyp[],
            entscheidungen,
          ),
          offene_zulassen: false,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setDialogOffen(false);
      setBestaetigt(false);
      void abfragen.invalidateQueries({ queryKey: ["migration"] });
    },
  });

  const zuordnungen = (vorschau.data?.zuordnungen ?? []) as ZuordnungTyp[];
  const kandidaten = (vorschau.data?.kandidaten ?? []) as Kandidat[];
  const befunde = (vorschau.data?.befunde ?? []) as Befund[];
  const summen = vorschau.data?.kontrollsummen as Kontrollsummen | undefined;
  const darfWerte = darf("projekte.werte_lesen");

  const stufe = useMemo(
    () => fortschritt(zuordnungen, entscheidungen),
    [zuordnungen, entscheidungen],
  );
  const fertig = alleEntschieden(zuordnungen, entscheidungen);
  const offenerBetrag = betragOffen(zuordnungen, entscheidungen);

  const warnungen = befunde.filter((b) => b.schwere === "warnung");
  const sichtbareBefunde = alleBefunde ? befunde : warnungen;

  function entscheiden(kundenteil: string, wert: number | null | undefined) {
    setEntscheidungen((vorher) => {
      const naechster = { ...vorher };
      if (wert === undefined) delete naechster[kundenteil];
      else naechster[kundenteil] = wert;
      return naechster;
    });
  }

  if (stand.isLoading) {
    return (
      <>
        <PageTitle>Bestandsdaten übernehmen</PageTitle>
        <p className="lademeldung">wird geladen …</p>
      </>
    );
  }

  if (stand.isError) {
    const fehler = fehlerAuslesen(stand.error);
    return (
      <>
        <PageTitle>Bestandsdaten übernehmen</PageTitle>
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      </>
    );
  }

  if (stand.data?.migriert) {
    return <BereitsMigriert stand={stand.data} darfWerte={darfWerte} />;
  }

  return (
    <>
      <PageTitle meta="Einmaliger Vorgang. Danach ist der Leitstand führend, und die Excel-Dateien werden schreibgeschützt.">
        Bestandsdaten übernehmen
      </PageTitle>

      {vorschau.isLoading ? (
        <p className="lademeldung">Die Dateien werden gelesen …</p>
      ) : null}

      {vorschau.isError ? (
        <Meldung
          art="fehler"
          text={fehlerAuslesen(vorschau.error).meldung}
          naechsterSchritt={fehlerAuslesen(vorschau.error).naechster_schritt}
        />
      ) : null}

      {uebernehmen.isError ? (
        <Meldung
          art="fehler"
          text={fehlerAuslesen(uebernehmen.error).meldung}
          naechsterSchritt={fehlerAuslesen(uebernehmen.error).naechster_schritt}
        />
      ) : null}

      {summen ? (
        <>
          <Kontrollsummenreihe summen={summen} darfWerte={darfWerte} />
          <Summenwarnung summen={summen} />
        </>
      ) : null}

      {zuordnungen.length > 0 ? (
        <section className="karte zuordnung__karte">
          <header className="karte__kopf">
            <h2 className="karte__titel">Zuordnung der Auftragsliste</h2>
            <span className="zuordnung__fortschritt">
              {stufe.automatisch} eindeutig · {stufe.entschieden} von{" "}
              {stufe.gesamt} entschieden
            </span>
          </header>
          <Zuordnungstabelle
            zuordnungen={zuordnungen}
            entscheidungen={entscheidungen}
            kandidaten={kandidaten}
            darfWerte={darfWerte}
            onEntscheiden={entscheiden}
            onWaehler={setWaehlerFuer}
          />
        </section>
      ) : null}

      {befunde.length > 0 ? (
        <section className="karte zuordnung__karte">
          <header className="karte__kopf">
            <h2 className="karte__titel">
              Auffälligkeiten in den Dateien (
              {anzahl(warnungen.length, "Warnung", "Warnungen")},{" "}
              {anzahl(befunde.length - warnungen.length, "Hinweis", "Hinweise")}
              )
            </h2>
            <Knopf
              art="sekundaer"
              klein
              onClick={() => setAlleBefunde((v) => !v)}
            >
              {alleBefunde ? "nur Warnungen" : "alle anzeigen"}
            </Knopf>
          </header>
          <div className="karte__inhalt">
            <ul className="befunde">
              {sichtbareBefunde.map((befund, index) => (
                <li
                  key={`${befund.datei}-${befund.spalte}-${befund.zeile}-${index}`}
                  className={`befunde__eintrag befunde__eintrag--${befund.schwere}`}
                >
                  <span className="befunde__ort">
                    {befund.datei} {befund.spalte}
                    {befund.zeile}
                  </span>
                  <span className="befunde__meldung">{befund.meldung}</span>
                  <span className="befunde__wert">
                    Inhalt: {befund.wert || "(leer)"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {zuordnungen.length > 0 ? (
        <div className="zuordnung__fuss">
          <div className="zuordnung__fussmeldung">
            {fertig ? (
              "Alle Zuordnungen sind entschieden."
            ) : (
              <>
                Noch {stufe.gesamt - stufe.entschieden} von {stufe.gesamt} zu
                entscheiden
                {darfWerte ? <> ({euro(offenerBetrag)})</> : null}.
              </>
            )}
          </div>
          <Knopf
            disabled={!fertig || uebernehmen.isPending}
            onClick={() => setDialogOffen(true)}
          >
            Bestandsdaten übernehmen
          </Knopf>
        </div>
      ) : null}

      <ProjektWaehler
        offen={waehlerFuer !== null}
        kundenteil={waehlerFuer ?? ""}
        kandidaten={kandidaten}
        darfWerteSehen={darfWerte}
        onWaehlen={(zeile) => {
          if (waehlerFuer) entscheiden(waehlerFuer, zeile);
          setWaehlerFuer(null);
        }}
        onSchliessen={() => setWaehlerFuer(null)}
      />

      {summen ? (
        <ConfirmDialog
          offen={dialogOffen}
          titel="Bestandsdaten übernehmen"
          meta="Dieser Vorgang lässt sich nicht wiederholen."
          bestaetigungstext="Ich habe die Zuordnungen geprüft."
          bestaetigt={bestaetigt}
          onBestaetigtChange={setBestaetigt}
          bestaetigenText="Übernehmen"
          laeuft={uebernehmen.isPending}
          onBestaetigen={() => uebernehmen.mutate()}
          onAbbrechen={() => {
            setDialogOffen(false);
            setBestaetigt(false);
          }}
        >
          <Zusammenfassung
            zeilen={[
              { label: "Projekte", wert: zahl(summen.teamliste.projekte) },
              {
                label: "Zahlungsplanpositionen",
                wert: zahl(summen.auftragsliste.zeilen),
              },
              ...(darfWerte
                ? [
                    {
                      label: "Summe netto",
                      wert: euro(summen.auftragsliste.summe_netto_cent),
                    },
                    {
                      label: "davon als gestellt markiert",
                      wert: euro(summen.auftragsliste.summe_gestellt_cent),
                    },
                  ]
                : []),
              {
                label: "selbst entschieden",
                wert: `${stufe.entschieden} von ${stufe.gesamt}`,
                summe: true,
              },
            ]}
          />
        </ConfirmDialog>
      ) : null}

      {uebernehmen.data ? (
        <Uebernahmebericht bericht={uebernehmen.data} darfWerte={darfWerte} />
      ) : null}
    </>
  );
}

type Kontrollsummen = {
  auftragsliste: {
    datei: string;
    zeilen: number;
    summe_netto_cent: number;
    summe_gestellt_cent: number;
    zeilen_gestellt: number;
    summe_je_monat_cent: Record<string, number>;
    auftragssummen_ohne_zahlungsplan: number;
  };
  teamliste: {
    datei: string;
    projekte: number;
    summe_ab_wert_cent: number;
    projekte_mit_ab_wert: number;
    summe_pv_kwp: string;
    anzahl_je_status: Record<string, number>;
    meilensteine: number;
  };
  zuordnung: {
    kunden_je_art: Record<string, number>;
    zeilen_je_art: Record<string, number>;
    offen: number;
    offen_betrag_cent: number;
  };
  befunde: { warnung: number; hinweis: number };
  summenfehler_der_quelldateien: {
    datei: string;
    zelle: string;
    fehler: string;
  }[];
};

function Kontrollsummenreihe({
  summen,
  darfWerte,
}: {
  summen: Kontrollsummen;
  darfWerte: boolean;
}) {
  return (
    <div className="kpi-reihe">
      <KpiTile
        label="Projekte"
        wert={zahl(summen.teamliste.projekte)}
        zusatz={`${zahl(summen.teamliste.meilensteine)} Meilensteine`}
      />
      <KpiTile
        label="Zahlungsplanzeilen"
        wert={zahl(summen.auftragsliste.zeilen)}
        zusatz={`${zahl(summen.auftragsliste.zeilen_gestellt)} als gestellt markiert`}
      />
      {darfWerte ? (
        <>
          <KpiTile
            label="Summe Zahlungsplan"
            wert={euro(summen.auftragsliste.summe_netto_cent)}
            zusatz={`davon gestellt ${euro(summen.auftragsliste.summe_gestellt_cent)}`}
          />
          <KpiTile
            label="Auftragswert"
            wert={euro(summen.teamliste.summe_ab_wert_cent)}
            zusatz={`${zahl(summen.teamliste.projekte_mit_ab_wert)} Projekte mit Wert`}
          />
        </>
      ) : null}
    </div>
  );
}

/**
 * Hinweis auf die falschen Summenformeln der Quelldateien.
 *
 * Steht bewusst weit oben: die Zahlen der Kacheln weichen von denen ab, die in den Excel-Dateien
 * stehen, und ohne diese Erklärung sieht das wie ein Importfehler aus.
 */
function Summenwarnung({ summen }: { summen: Kontrollsummen }) {
  if (summen.summenfehler_der_quelldateien.length === 0) return null;
  return (
    <Meldung
      text={
        <>
          Die Summenzellen der Excel-Dateien rechnen falsch. Der Leitstand
          rechnet über die Datenzeilen; die angezeigten Summen weichen deshalb
          von den gewohnten ab:
          <ul className="summenfehler">
            {summen.summenfehler_der_quelldateien.map((eintrag) => (
              <li key={`${eintrag.datei}-${eintrag.zelle}`}>
                <strong>
                  {eintrag.datei} {eintrag.zelle}
                </strong>{" "}
                – {eintrag.fehler}
              </li>
            ))}
          </ul>
        </>
      }
      naechsterSchritt="Die Formeln in den Excel-Dateien sollten unabhängig davon berichtigt werden, solange dort noch gearbeitet wird."
    />
  );
}

function Zuordnungstabelle({
  zuordnungen,
  entscheidungen,
  kandidaten,
  darfWerte,
  onEntscheiden,
  onWaehler,
}: {
  zuordnungen: ZuordnungTyp[];
  entscheidungen: Entscheidungen;
  kandidaten: Kandidat[];
  darfWerte: boolean;
  onEntscheiden: (kundenteil: string, wert: number | null | undefined) => void;
  onWaehler: (kundenteil: string) => void;
}) {
  // Nachschlagewerk für die Beschriftung der Vorschläge. Die Schnittstelle liefert zum Vorschlag
  // nur Name und Güte; die Merkmale, an denen sich gleichnamige Projekte unterscheiden, stehen
  // in der Kandidatenliste.
  const nachZeile = useMemo(
    () => new Map(kandidaten.map((k) => [k.zeile, k])),
    [kandidaten],
  );

  const spalten: Spalte<ZuordnungTyp>[] = [
    {
      kopf: "Kunde in der Auftragsliste",
      hervorgehoben: true,
      zelle: (z) => (
        <>
          <span className="zuordnung__kunde">{z.kundenteil}</span>
          <span className="zuordnung__zeilen">
            {anzahl(z.zeilen.length, "Zeile", "Zeilen")}
          </span>
        </>
      ),
    },
    ...(darfWerte
      ? [
          {
            kopf: "Betrag netto (€)",
            zahl: true,
            zelle: (z: ZuordnungTyp) => euro(z.betrag_netto, false),
          } satisfies Spalte<ZuordnungTyp>,
        ]
      : []),
    {
      kopf: "Zuordnung",
      breite: "46%",
      zelle: (z) => (
        <Entscheidungsfeld
          zuordnung={z}
          entscheidung={entscheidungen[z.kundenteil]}
          kandidaten={nachZeile}
          darfWerte={darfWerte}
          onEntscheiden={onEntscheiden}
          onWaehler={onWaehler}
        />
      ),
    },
  ];

  return (
    <DataTable
      spalten={spalten}
      zeilen={zuordnungen}
      schluessel={(z) => z.kundenteil}
      beschriftung="Zuordnung der Auftragsliste zu den Projekten"
    />
  );
}

const WAEHLEN = "__waehlen__";
const NEU = "__neu__";
const OFFEN = "__offen__";

/**
 * Beschriftung eines Vorschlags.
 *
 * Der Name allein genügt nicht: im Bestand gibt es dreimal „Ertl, Vohenstrauß" und zweimal
 * „Lautenbacher, Neusorg". Eine Auswahl mit gleichlautenden Einträgen ist keine Auswahl.
 * Deshalb kommen Leistung, Auftragsdatum und – wer sie sehen darf – der Auftragswert dazu.
 */
function vorschlagsbeschriftung(
  name: string,
  guete: number,
  kandidat: Kandidat | undefined,
  darfWerte: boolean,
): string {
  const merkmale = [
    kandidat?.pv_kwp ? leistung(Number(kandidat.pv_kwp)) : null,
    kandidat?.auftrag_vom ? datum(kandidat.auftrag_vom) : null,
    darfWerte && kandidat?.ab_wert_netto ? euro(kandidat.ab_wert_netto) : null,
  ].filter(Boolean);
  const zusatz = merkmale.length > 0 ? ` · ${merkmale.join(" · ")}` : "";
  return `${name}${zusatz} · Ähnlichkeit ${Math.round(guete)}`;
}

function Entscheidungsfeld({
  zuordnung,
  entscheidung,
  kandidaten,
  darfWerte,
  onEntscheiden,
  onWaehler,
}: {
  zuordnung: ZuordnungTyp;
  entscheidung: number | null | undefined;
  kandidaten: Map<number, Kandidat>;
  darfWerte: boolean;
  onEntscheiden: (kundenteil: string, wert: number | null | undefined) => void;
  onWaehler: (kundenteil: string) => void;
}) {
  if (!zuordnung.offen) {
    return (
      <span className="zuordnung__fest">
        eindeutig zugeordnet · Teamliste Zeile {zuordnung.projekt_zeile}
      </span>
    );
  }

  const wert =
    entscheidung === undefined
      ? OFFEN
      : entscheidung === null
        ? NEU
        : String(entscheidung);
  const ausserhalb =
    typeof entscheidung === "number" &&
    !zuordnung.vorschlaege.some((v) => v.projekt_zeile === entscheidung);

  return (
    <div className="zuordnung__entscheidung">
      <select
        className="zuordnung__auswahl"
        value={wert}
        aria-label={`Zuordnung für ${zuordnung.kundenteil}`}
        onChange={(ereignis) => {
          const gewaehlt = ereignis.target.value;
          if (gewaehlt === OFFEN)
            onEntscheiden(zuordnung.kundenteil, undefined);
          else if (gewaehlt === NEU) onEntscheiden(zuordnung.kundenteil, null);
          else if (gewaehlt === WAEHLEN) onWaehler(zuordnung.kundenteil);
          else onEntscheiden(zuordnung.kundenteil, Number(gewaehlt));
        }}
      >
        <option value={OFFEN}>– noch nicht entschieden –</option>
        {zuordnung.vorschlaege.map((vorschlag) => (
          <option key={vorschlag.projekt_zeile} value={vorschlag.projekt_zeile}>
            {vorschlagsbeschriftung(
              vorschlag.kunde,
              vorschlag.guete,
              kandidaten.get(vorschlag.projekt_zeile),
              darfWerte,
            )}
          </option>
        ))}
        {ausserhalb ? (
          <option value={entscheidung}>
            Teamliste Zeile {entscheidung} (selbst gewählt)
          </option>
        ) : null}
        <option value={WAEHLEN}>anderes Projekt suchen …</option>
        <option value={NEU}>als eigenes Projekt anlegen</option>
      </select>
      {zuordnung.vorschlaege.length === 0 ? (
        <span className="zuordnung__hinweis">
          kein ähnliches Projekt gefunden – suchen oder neu anlegen
        </span>
      ) : null}
    </div>
  );
}

/**
 * Ansicht nach der Übernahme.
 *
 * Zeigt, was der Lauf angelegt hat, und – wichtiger – wo der Zahlungsplan nicht zum
 * Auftragswert passt. Die Auftragsliste führt nur die offenen Positionen; bei Altprojekten
 * fehlt der in früheren Jahren berechnete Teil. Diese Lücke wird ausgewiesen und nicht
 * gefüllt (Entscheidung Svens, docs/OFFENE-PUNKTE.md Nr. 11).
 */
function BereitsMigriert({
  stand,
  darfWerte,
}: {
  stand: {
    importlauf_id?: number | null;
    status?: string | null;
    beendet?: string | null;
    dateien?: string | null;
    ergebnis?: Record<string, unknown> | null;
  };
  darfWerte: boolean;
}) {
  const ergebnis = stand.ergebnis as
    | {
        angelegt?: Record<string, number>;
        ab_luecken?: {
          projekt_nr: number;
          ab_wert_cent: number;
          zahlungsplan_cent: number;
          differenz_cent: number;
        }[];
        gewerk_abgeleitet?: unknown[];
        nicht_uebernommen?: unknown[];
      }
    | null
    | undefined;
  const angelegt = ergebnis?.angelegt ?? {};
  const luecken = ergebnis?.ab_luecken ?? [];

  return (
    <>
      <PageTitle
        meta={`Übernommen am ${datumZeit(stand.beendet)} · Importprotokoll Nr. ${stand.importlauf_id}`}
      >
        Bestandsdaten übernommen
      </PageTitle>

      <Meldung
        text="Die Bestandsdaten sind übernommen. Ein zweiter Lauf ist nicht möglich – er würde alles doppelt anlegen."
        naechsterSchritt={`Quelldateien: ${stand.dateien ?? "unbekannt"}. Sie sollten jetzt schreibgeschützt werden; ab hier ist der Leitstand führend.`}
      />

      <div className="kpi-reihe">
        <KpiTile label="Projekte" wert={zahl(angelegt.projekte ?? 0)} />
        <KpiTile label="Kunden" wert={zahl(angelegt.kunden ?? 0)} />
        <KpiTile label="Meilensteine" wert={zahl(angelegt.meilensteine ?? 0)} />
        <KpiTile
          label="Zahlungsplan"
          wert={zahl(angelegt.zahlungsplan ?? 0)}
          zusatz={
            darfWerte && angelegt.zahlungsplan_summe_cent
              ? euro(angelegt.zahlungsplan_summe_cent)
              : `${zahl(angelegt.zahlungsplan_gestellt ?? 0)} als gestellt`
          }
        />
      </div>

      {luecken.length > 0 ? (
        <section className="karte zuordnung__karte">
          <header className="karte__kopf">
            <h2 className="karte__titel">
              Projekte, deren Zahlungsplan nicht zum Auftragswert passt (
              {luecken.length})
            </h2>
          </header>
          <div className="karte__inhalt">
            <p className="zuordnung__erklaerung">
              Die Auftragsliste führt nur die offenen Positionen. Bei
              Altprojekten ist der Rest in früheren Jahren berechnet worden und
              liegt dem Leitstand nicht vor. Die Differenz wird ausgewiesen,
              aber nicht durch eine erfundene Position geschlossen.
            </p>
            <DataTable
              spalten={[
                {
                  kopf: "Projekt",
                  hervorgehoben: true,
                  zelle: (l) => l.projekt_nr,
                },
                ...(darfWerte
                  ? [
                      {
                        kopf: "Auftragswert (€)",
                        zahl: true,
                        zelle: (l: (typeof luecken)[number]) =>
                          euro(l.ab_wert_cent, false),
                      },
                      {
                        kopf: "Zahlungsplan (€)",
                        zahl: true,
                        zelle: (l: (typeof luecken)[number]) =>
                          euro(l.zahlungsplan_cent, false),
                      },
                      {
                        kopf: "Differenz (€)",
                        zahl: true,
                        zelle: (l: (typeof luecken)[number]) =>
                          euro(l.differenz_cent, false),
                      },
                    ]
                  : []),
              ]}
              zeilen={luecken}
              schluessel={(l) => l.projekt_nr}
              beschriftung="Projekte mit unvollständigem Zahlungsplan"
            />
          </div>
        </section>
      ) : null}
    </>
  );
}

/** Bericht direkt nach einer Übernahme in dieser Sitzung. */
function Uebernahmebericht({
  bericht,
  darfWerte,
}: {
  bericht: {
    projekte: number;
    kunden: number;
    zahlungsplan: number;
    zahlungsplan_summe_netto: number;
    meilensteine: number;
    meldung: string;
  };
  darfWerte: boolean;
}) {
  return (
    <Meldung
      text={bericht.meldung}
      naechsterSchritt={
        darfWerte
          ? `Angelegt: ${zahl(bericht.projekte)} Projekte, ${zahl(bericht.kunden)} Kunden, ${zahl(bericht.meilensteine)} Meilensteine, ${zahl(bericht.zahlungsplan)} Zahlungsplanpositionen über ${euro(bericht.zahlungsplan_summe_netto)}.`
          : `Angelegt: ${zahl(bericht.projekte)} Projekte, ${zahl(bericht.kunden)} Kunden, ${zahl(bericht.meilensteine)} Meilensteine.`
      }
    />
  );
}
