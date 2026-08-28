/**
 * Reiter „Nachkalkulation" im Projektdetail (PLAN §7 Phase 4).
 *
 * Hier steht der Rechenweg vollständig da: Erlös, Ist je Quelle, Soll aus dem Kalkulationsblatt
 * und die Marge. Wer die Zahl in Frage stellt, soll den Weg dorthin ohne Nachfrage sehen –
 * deshalb der Block mit vier Zeilen statt einer großen Kachel.
 *
 * Die Aufgliederung nach Quelle ist keine Verzierung: sie ist die einzige Stelle, an der
 * auffällt, wenn Material fehlt oder doppelt gebucht ist (PLAN §6.5).
 */

import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/komponenten/DataTable";
import type { Spalte } from "@/komponenten/DataTable";
import { EmptyState } from "@/komponenten/EmptyState";
import { Meldung } from "@/komponenten/Meldung";
import { api, fehlerAuslesen } from "@/api/client";
import { euro, zahl } from "@/format/formate";
import { MargenAmpel } from "./MargenAmpel";
import { MengenIstFormular } from "./MengenIstFormular";
import {
  type Ampel,
  istAnteile,
  margeText,
  rechenweg,
  stundenText,
} from "./begriffe";
import "./nachkalkulation.css";

type Stundenzeile = {
  monat: string;
  mitarbeiter: string;
  stunden: string;
  satz: number;
  betrag: number;
};

type Stuecklistenzeile = {
  artikel_nr: string | null;
  bezeichnung: string;
  menge_soll: string;
  menge_ist: string | null;
  ek_preis: number | null;
  quelle: string;
  gewerk: string | null;
  bewertet_betrag: number | null;
};

type Props = {
  projektNr: number;
  darfSchreiben: boolean;
};

export function ProjektNachkalkulation({ projektNr, darfSchreiben }: Props) {
  const abfrage = useQuery({
    queryKey: ["nachkalkulation", projektNr],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/nachkalkulation/{projekt_nr}",
        {
          params: { path: { projekt_nr: projektNr } },
        },
      );
      if (error) throw error;
      return data;
    },
  });

  if (abfrage.isLoading) return <p className="nk-fuss">wird geladen …</p>;

  if (abfrage.isError) {
    const fehler = fehlerAuslesen(abfrage.error);
    return (
      <Meldung
        art="fehler"
        text={fehler.meldung}
        naechsterSchritt={fehler.naechster_schritt}
      />
    );
  }

  const daten = abfrage.data;
  if (!daten) return null;
  const p = daten.projekt;
  const stunden = (daten.stunden ?? []) as Stundenzeile[];
  const stueckliste = (daten.stueckliste ?? []) as Stuecklistenzeile[];
  const anteile = istAnteile(p);

  const stundenspalten: Spalte<Stundenzeile>[] = [
    { kopf: "Monat", zelle: (z) => z.monat },
    { kopf: "Mitarbeiter", hervorgehoben: true, zelle: (z) => z.mitarbeiter },
    {
      kopf: "Stunden (h)",
      zahl: true,
      zelle: (z) => zahl(Number(z.stunden), 2),
    },
    { kopf: "Satz (€/h)", zahl: true, zelle: (z) => euro(z.satz, false) },
    { kopf: "Betrag (€)", zahl: true, zelle: (z) => euro(z.betrag, false) },
  ];

  const stuecklistenspalten: Spalte<Stuecklistenzeile>[] = [
    { kopf: "Artikel", zelle: (z) => z.artikel_nr ?? "–" },
    { kopf: "Bezeichnung", hervorgehoben: true, zelle: (z) => z.bezeichnung },
    { kopf: "Soll", zahl: true, zelle: (z) => zahl(Number(z.menge_soll), 3) },
    {
      kopf: "Ist",
      zahl: true,
      zelle: (z) =>
        z.menge_ist === null ? (
          <span className="text-sekundaer" title="Noch nicht gezählt">
            –
          </span>
        ) : (
          zahl(Number(z.menge_ist), 3)
        ),
    },
    { kopf: "EK (€)", zahl: true, zelle: (z) => euro(z.ek_preis, false) },
    {
      kopf: "Quelle",
      zelle: (z) =>
        z.quelle === "lager" ? (
          "Lager"
        ) : (
          <span title="Kommt über die DATEV-Kostenträger ins Ist, nicht über den Einkaufspreis">
            Projektbestellt
          </span>
        ),
    },
    {
      kopf: "Bewertet (€)",
      zahl: true,
      zelle: (z) =>
        z.bewertet_betrag === null ? (
          <span className="text-sekundaer">–</span>
        ) : (
          euro(z.bewertet_betrag, false)
        ),
    },
  ];

  return (
    <>
      {p.hinweise.length > 0 && (
        <div className="nk-hinweise">
          {p.hinweise.map((h) => (
            <div key={h.code} className="nk-hinweis">
              <span className="nk-hinweis__marke" aria-hidden="true">
                !
              </span>
              <span>{h.text}</span>
            </div>
          ))}
        </div>
      )}

      <div className="nk-spalten">
        <div>
          <h3>Rechenweg</h3>
          <div className="rechenweg">
            {rechenweg(p).map((zeile) => (
              <div
                key={zeile.text}
                className={`rechenweg__zeile${zeile.stark ? " rechenweg__zeile--stark" : ""}`}
              >
                <span>{zeile.text}</span>
                <span className="rechenweg__wert">{zeile.wert}</span>
              </div>
            ))}
            {rechenweg(p).find((z) => z.hinweis) && (
              <div className="rechenweg__hinweis">
                {rechenweg(p).find((z) => z.hinweis)?.hinweis}
              </div>
            )}
            <div className="rechenweg__zeile">
              <span>Gegen die Sollmarge</span>
              <MargenAmpel
                ampel={p.ampel as Ampel}
                margeSollPromille={p.marge_soll_promille}
                abweichungPromille={p.abweichung_promille}
              />
            </div>
            {p.fakturiert_netto !== p.erloes_netto && (
              <div className="rechenweg__hinweis">
                Fakturiert sind bislang {euro(p.fakturiert_netto)} – der Erlös
                rechnet mit dem Auftragswert, nicht mit dem, was schon gestellt
                ist.
              </div>
            )}
          </div>
        </div>

        <div>
          <h3>Ist-Kosten nach Quelle</h3>
          <div className="istbalken">
            {anteile.map((a) => (
              <div
                key={a.schluessel}
                className={`istbalken__teil istbalken__teil--${a.schluessel}`}
                style={{ width: `${a.anteil}%` }}
                title={`${a.text}: ${euro(a.betrag)}`}
              />
            ))}
          </div>
          <div className="istlegende">
            {anteile.map((a) => (
              <span key={a.schluessel} title={a.erklaerung}>
                <span
                  className={`istlegende__punkt istbalken__teil--${a.schluessel}`}
                  aria-hidden="true"
                />
                {a.text}
                <span className="istlegende__betrag">{euro(a.betrag)}</span>
              </span>
            ))}
          </div>

          {p.soll_gesamt !== null && p.soll_gesamt !== undefined && (
            <div
              className="rechenweg"
              style={{ marginTop: "var(--abstand-4)" }}
            >
              <div className="rechenweg__zeile">
                <span>Soll aus der Kalkulation</span>
                <span className="rechenweg__wert">{euro(p.soll_gesamt)}</span>
              </div>
              <div className="rechenweg__zeile">
                <span>Abweichung Soll zu Ist</span>
                <span className="rechenweg__wert">
                  {euro(p.soll_ist_abweichung)}
                </span>
              </div>
              <div className="rechenweg__zeile">
                <span>Stunden Soll zu Ist</span>
                <span className="rechenweg__wert">
                  {stundenText(p.soll_stunden)} → {stundenText(p.stunden_ist)}
                </span>
              </div>
              <div className="rechenweg__zeile">
                <span>Sollmarge</span>
                <span className="rechenweg__wert">
                  {margeText(p.marge_soll_promille)}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="nk-abschnitt">
        <h3>Stückliste</h3>
        <DataTable
          spalten={stuecklistenspalten}
          zeilen={stueckliste}
          schluessel={(z) => `${z.artikel_nr ?? ""}|${z.bezeichnung}`}
          beschriftung="Stückliste des Projekts"
          leer={
            <EmptyState
              titel="Keine Stückliste"
              text="Sie entsteht aus dem Kalkulationsblatt in 03_Kalkulation."
              ohneZeichen
            />
          }
        />
        {stueckliste.some((z) => z.quelle === "lager") && (
          <MengenIstFormular
            projektNr={projektNr}
            darfSchreiben={darfSchreiben}
          />
        )}
      </div>

      <div className="nk-abschnitt">
        <h3>Arbeitsstunden</h3>
        <DataTable
          spalten={stundenspalten}
          zeilen={stunden}
          schluessel={(z) => `${z.monat}|${z.mitarbeiter}`}
          beschriftung="Arbeitsstunden des Projekts"
          leer={
            <EmptyState
              titel="Keine Stunden erfasst"
              text="Sie kommen aus TimeTac; der nächtliche Lauf holt den laufenden und den vorigen Monat."
              ohneZeichen
            />
          }
        />
      </div>
    </>
  );
}
