/**
 * Firmen-Cockpit (design/Firmen-Cockpit.dc.html, PLAN §7 Phase 5).
 *
 * Die Steuerungssicht der Geschäftsführung: vier Kennzahlen, der Wasserfall vom Umsatz zur
 * Über-/Unterdeckung, Reichweite und Fixkostendeckung, darunter der Monatsverlauf.
 *
 * Drei Dinge sagt die Seite ausdrücklich, statt sie den Zahlen zu überlassen:
 *
 * 1. **Es ist keine BWA.** Der Hinweis kommt vom Server und steht unter dem Titel – hier stehen
 *    Auftragswerte, kalkulatorische Sätze und Planzahlen neben Buchhaltungswerten.
 * 2. **Wo Zahlen fehlen, steht warum.** Fehlende Fixkosten, nicht zugeordnete Konten, eine dünne
 *    Margenbasis: alles kommt als Hinweis mit und wird nicht weggerundet.
 * 3. **Gestellt ist nicht bezahlt** (PLAN §6.7). Der Umschalter über dem Wasserfall macht den
 *    Unterschied sichtbar, statt ihn zu verwischen.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "@/komponenten/EmptyState";
import { KpiTile } from "@/komponenten/KpiTile";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { MonthBars } from "@/komponenten/MonthBars";
import { PageTitle } from "@/komponenten/PageTitle";
import { api, fehlerAuslesen } from "@/api/client";
import {
  anteil,
  euro,
  euroKurz,
  monat as monatText,
  monatKurz,
} from "@/format/formate";
import {
  BLOCK_REIHENFOLGE,
  BLOCK_TEXT,
  HERKUNFT_TEXT,
  deckungZusatz,
  reichtBis,
  reichweiteZusatz,
  stufen,
  zahlKurz,
} from "./begriffe";
import { Wasserfall } from "./Wasserfall";
import "./cockpit.css";

export function Cockpit() {
  // Ohne Vorgabe wählt der Server den jüngsten Monat mit Zahlen. Erst wenn geblättert wird,
  // steht hier einer – sonst zeigte die Seite beim Aufrufen den laufenden Monat, für den die
  // Kanzlei noch nichts geliefert haben kann.
  const [monat, setMonat] = useState<string | null>(null);
  const [basis, setBasis] = useState<"gestellt" | "bezahlt">("gestellt");

  const abfrage = useQuery({
    queryKey: ["cockpit", monat, basis],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cockpit", {
        params: { query: { ...(monat ? { monat } : {}), basis } },
      });
      if (error) throw error;
      return data;
    },
  });

  if (abfrage.isPending) {
    return (
      <>
        <PageTitle meta="wird geladen">Firmen-Cockpit</PageTitle>
        <EmptyState
          titel="Einen Augenblick"
          text="Die Zahlen werden zusammengestellt."
        />
      </>
    );
  }

  if (abfrage.isError || !abfrage.data) {
    const fehler = fehlerAuslesen(abfrage.error);
    return (
      <>
        <PageTitle>Firmen-Cockpit</PageTitle>
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      </>
    );
  }

  const daten = abfrage.data;
  const aktuell = daten.monate.find((m) => m.monat === daten.monat);
  const reihe = stufen(
    aktuell?.umsatz_netto ?? 0,
    aktuell?.variable_kosten ?? 0,
    aktuell?.fixkosten ?? 0,
  );
  const reichweite = daten.kennzahlen.reichweite;
  const bisWann = reichtBis(daten.monat, reichweite.umsatzmonate);
  const monatsliste = daten.verfuegbare_monate;
  const stelle = monatsliste.indexOf(daten.monat);

  return (
    <>
      <PageTitle meta={`Monatsansicht · ${monatText(daten.monat)}`}>
        Firmen-Cockpit
      </PageTitle>

      <p className="cockpit__einordnung">{daten.steuerungssicht}</p>

      <div className="cockpit__leiste">
        <div className="cockpit__monatswahl">
          <Knopf
            art="sekundaer"
            disabled={stelle <= 0}
            onClick={() => {
              const vorher = monatsliste[stelle - 1];
              if (vorher) setMonat(vorher);
            }}
            aria-label="Vorheriger Monat"
          >
            ‹
          </Knopf>
          <span className="cockpit__monat">{monatText(daten.monat)}</span>
          <Knopf
            art="sekundaer"
            disabled={stelle < 0 || stelle >= monatsliste.length - 1}
            onClick={() => {
              const naechster = monatsliste[stelle + 1];
              if (naechster) setMonat(naechster);
            }}
            aria-label="Nächster Monat"
          >
            ›
          </Knopf>
        </div>

        <div
          className="cockpit__umschalter"
          role="group"
          aria-label="Umsatzbasis"
        >
          <button
            type="button"
            className="cockpit__basis"
            aria-pressed={basis === "gestellt"}
            onClick={() => setBasis("gestellt")}
          >
            gestellt
          </button>
          <button
            type="button"
            className="cockpit__basis"
            aria-pressed={basis === "bezahlt"}
            onClick={() => setBasis("bezahlt")}
          >
            bezahlt
          </button>
        </div>
      </div>

      <div className="kpi-reihe">
        <KpiTile
          label={basis === "bezahlt" ? "Umsatz (bezahlt)" : "Umsatz"}
          wert={euro(aktuell?.umsatz_netto ?? 0)}
          zusatz={monatText(daten.monat)}
        />
        <KpiTile
          label="Deckungsbeitrag"
          wert={euro(aktuell?.deckungsbeitrag ?? 0)}
          zusatz={
            aktuell?.db_promille !== null && aktuell?.db_promille !== undefined
              ? `${anteil(aktuell.db_promille / 10)} vom Umsatz`
              : "ohne Umsatz keine Quote"
          }
        />
        <KpiTile
          label="Fixkosten"
          wert={euro(aktuell?.fixkosten ?? 0)}
          zusatz={
            HERKUNFT_TEXT[daten.fixkosten_herkunft] ?? daten.fixkosten_herkunft
          }
        />
        <KpiTile
          label={(aktuell?.deckung ?? 0) < 0 ? "Unterdeckung" : "Überdeckung"}
          wert={euro(aktuell?.deckung ?? 0)}
          negativ={(aktuell?.deckung ?? 0) < 0}
          zusatz={`kumuliert ${euro(daten.kumuliert)}`}
        />
      </div>

      {daten.hinweise.length > 0 ? (
        <div className="cockpit__hinweise">
          {daten.hinweise.map((hinweis) => (
            <Meldung art="hinweis" key={hinweis} text={hinweis} />
          ))}
        </div>
      ) : null}

      <section className="cockpit__block">
        <h2 className="cockpit__ueberschrift">Vom Umsatz zum Ergebnis</h2>
        <p className="cockpit__unterzeile">
          {monatText(daten.monat)} · Beträge in €
          {basis === "bezahlt" ? " · Zahlungseingang laut OPOS" : ""}
        </p>
        <Wasserfall
          stufen={reihe}
          breakEvenCent={daten.kennzahlen.break_even_netto}
        />
      </section>

      <div className="cockpit__paar">
        <section className="cockpit__block">
          <h2 className="cockpit__ueberschrift">Reichweite Auftragsbestand</h2>
          <div className="cockpit__grosszahl">
            {reichweite.umsatzmonate !== null
              ? zahlKurz(reichweite.umsatzmonate)
              : "–"}
            <span className="cockpit__einheit">Monate</span>
          </div>
          <p className="cockpit__unterzeile">
            {reichweiteZusatz(
              reichweite.bestand_netto,
              reichweite.durchschnittsumsatz,
              reichweite.fixkostenmonate,
            )}
            {bisWann ? ` — reicht bis ${bisWann}.` : ""}
          </p>
        </section>

        <section className="cockpit__block">
          <h2 className="cockpit__ueberschrift">
            Fixkostendeckung {monatText(daten.monat)}
          </h2>
          {aktuell?.fixkostendeckung_promille !== null &&
          aktuell?.fixkostendeckung_promille !== undefined ? (
            <div
              className={`cockpit__grosszahl${
                // Unter 100 % trägt der Deckungsbeitrag die Fixkosten nicht.
                aktuell.fixkostendeckung_promille < 1000
                  ? " cockpit__grosszahl--knapp"
                  : ""
              }`}
            >
              {anteil(aktuell.fixkostendeckung_promille / 10, 0)}
            </div>
          ) : (
            <p className="cockpit__leer">
              Für diesen Monat sind keine Fixkosten hinterlegt – ohne sie gibt
              es keine Deckungsquote.
            </p>
          )}
          <p className="cockpit__unterzeile">
            {deckungZusatz(
              daten.kennzahlen.break_even_netto,
              daten.kennzahlen.marge_promille,
            )}
          </p>
        </section>
      </div>

      {Object.keys(daten.fixkosten_je_block).length > 0 ? (
        <section className="cockpit__block">
          <h2 className="cockpit__ueberschrift">Fixkostenblock</h2>
          <p className="cockpit__unterzeile">
            {monatText(daten.monat)} · {HERKUNFT_TEXT[daten.fixkosten_herkunft]}
          </p>
          <table className="cockpit__tabelle">
            <thead>
              <tr>
                <th scope="col">Block</th>
                <th scope="col" className="cockpit__zahl">
                  Betrag
                </th>
              </tr>
            </thead>
            <tbody>
              {BLOCK_REIHENFOLGE.filter(
                (b) => b in daten.fixkosten_je_block,
              ).map((block) => (
                <tr
                  key={block}
                  className={block === "neutral" ? "cockpit__zeile--grau" : ""}
                >
                  <td>{BLOCK_TEXT[block] ?? block}</td>
                  <td className="cockpit__zahl">
                    {euro(daten.fixkosten_je_block[block] ?? 0)}
                  </td>
                </tr>
              ))}
              <tr className="cockpit__zeile--summe">
                <td>Summe</td>
                <td className="cockpit__zahl">
                  {euro(aktuell?.fixkosten ?? 0)}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="cockpit__block">
        <h2 className="cockpit__ueberschrift">Monatsverlauf {daten.jahr}</h2>
        <p className="cockpit__unterzeile">
          Deckungsbeitrag gegen Fixkosten · Ist{" "}
          {euroKurz(
            daten.monate.reduce((summe, m) => summe + m.deckungsbeitrag, 0),
          )}{" "}
          Deckungsbeitrag im Jahr
        </p>
        <MonthBars
          werte={daten.monate.map((m) => ({
            monat: m.monat,
            beschriftung: monatKurz(m.monat),
            betrag: Math.max(m.deckungsbeitrag, 0),
            planBetrag:
              m.fixkosten > m.deckungsbeitrag
                ? m.fixkosten - Math.max(m.deckungsbeitrag, 0)
                : 0,
            aktuell: m.monat === daten.monat,
            titel: `${monatText(m.monat)} · DB ${euroKurz(m.deckungsbeitrag)} · Fixkosten ${euroKurz(m.fixkosten)}`,
          }))}
        />
        <p className="cockpit__legende">
          Gefüllt: Deckungsbeitrag. Kontur darüber: der Teil der Fixkosten, den
          er nicht deckt.
        </p>
      </section>
    </>
  );
}
