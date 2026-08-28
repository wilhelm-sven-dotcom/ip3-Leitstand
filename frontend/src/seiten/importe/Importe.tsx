/**
 * Importe und Daten (PLAN §8).
 *
 * Vier Quellen auf einer Seite: die einmalige Migration der Bestandsdateien und die drei
 * wiederkehrenden Importe der Phase 4. Für sie gibt es **kein Mockup** – Aufbau im Duktus der
 * Zuordnungsmaske (design/UMSETZUNG.md).
 *
 * Der Ablauf ist überall derselbe und aus gutem Grund umständlich: **erst ansehen, dann
 * übernehmen.** Die Vorschau liest die Dateien und schreibt nichts; sie liefert Kontrollsummen,
 * die Befunde und eine Kennung über den Inhalt. Die Übernahme schickt diese Kennung zurück.
 * Hat sich die Datei zwischenzeitlich geändert, wird der Lauf abgewiesen – sonst würde etwas
 * anderes geschrieben, als auf dem Schirm stand.
 *
 * TimeTac hat keine Vorschau: die Schnittstelle liefert keine Datei, die man vorher ansehen
 * könnte. Der Lauf ist dafür gefahrlos wiederholbar, er ersetzt seinen Zeitraum.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "@/komponenten/EmptyState";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { PageTitle } from "@/komponenten/PageTitle";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { datumZeit } from "@/format/formate";
import { ImportKarte } from "./ImportKarte";
import { LAUF_STATUS_TEXT, kontrollsummenZeilen } from "./begriffe";
import "./importe.css";

type Lauf = {
  id: number;
  quelle: string;
  datei: string | null;
  zeitraum: string | null;
  gestartet: string;
  beendet: string | null;
  status: string;
  ergebnis: Record<string, unknown> | null;
};

export function Importe() {
  const abfragen = useQueryClient();
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  const laeufe = useQuery({
    queryKey: ["importlaeufe"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/importe/laeufe", {
        params: { query: { anzahl: 15 } },
      });
      if (error) throw error;
      return (data ?? []) as Lauf[];
    },
  });

  const timetac = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/importe/timetac/holen", {});
      if (error) throw error;
      return data;
    },
    onSuccess: (antwort) => {
      setFehler(null);
      setMeldung(antwort?.meldung ?? null);
      void abfragen.invalidateQueries({ queryKey: ["importlaeufe"] });
      void abfragen.invalidateQueries({ queryKey: ["nachkalkulation"] });
    },
    onError: (ausfall) => {
      setMeldung(null);
      setFehler(fehlerAuslesen(ausfall));
    },
  });

  const fertig = () => {
    void abfragen.invalidateQueries({ queryKey: ["importlaeufe"] });
    void abfragen.invalidateQueries({ queryKey: ["nachkalkulation"] });
  };

  return (
    <>
      <PageTitle meta="Was der Leitstand aus den OneDrive-Ordnern und aus TimeTac liest">
        Importe & Daten
      </PageTitle>

      {fehler && (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      )}
      {meldung && <Meldung art="hinweis" text={meldung} />}

      <div className="import-karten">
        <ImportKarte
          quelle="datev"
          titel="DATEV-Kostenträger"
          herkunft="02_DATEV · kostentraeger_JJJJ-MM.csv"
          erklaerung="Projektbestelltes Material und Fremdleistungen, verdichtet auf Projekt, Monat und Konto. Jeder Lauf ersetzt seinen Monat."
          onFertig={fertig}
          onFehler={setFehler}
          onMeldung={setMeldung}
        />

        <ImportKarte
          quelle="kalkulation"
          titel="Kalkulationsblätter"
          herkunft="03_Kalkulation · Blatt EXPORT"
          erklaerung="Sollwerte und Stückliste je Projekt. Eine bestätigte Ist-Menge wird dabei nie überschrieben."
          onFertig={fertig}
          onFehler={setFehler}
          onMeldung={setMeldung}
        />

        <div className="import-karte">
          <h3>TimeTac-Stunden</h3>
          <p className="import-karte__herkunft">
            Schnittstelle · laufender und voriger Monat
          </p>
          <p className="import-karte__text">
            Eigenleistung: Stunden mal Verrechnungssatz. Ohne Vorschau – die
            Schnittstelle liefert keine Datei, die man vorher ansehen könnte.
            Der Lauf ist gefahrlos wiederholbar, er ersetzt seinen Zeitraum.
          </p>
          <div className="import-karte__fuss">
            <Knopf
              onClick={() => timetac.mutate()}
              disabled={timetac.isPending}
            >
              {timetac.isPending ? "wird geholt …" : "Stunden holen"}
            </Knopf>
          </div>
        </div>

        <div className="import-karte">
          <h3>Bestandsdaten</h3>
          <p className="import-karte__herkunft">
            Einmalig · Auftragsliste und Teamliste
          </p>
          <p className="import-karte__text">
            Die Übernahme der beiden Excel-Dateien beim Start des Leitstands.
            Sie läuft genau einmal; danach ist der Leitstand führend.
          </p>
          <div className="import-karte__fuss">
            <Link className="knopf knopf--sekundaer" to="/importe/migration">
              Zur Zuordnungsmaske
            </Link>
          </div>
        </div>
      </div>

      <h2 className="import-ueberschrift">Importprotokolle</h2>
      <p className="import-fuss">
        Jeder Lauf steht hier mit Zeitraum, Kontrollsummen und allem, was nicht
        gedeutet werden konnte. Ein Lauf mit Befunden gilt als „mit Anmerkung" –
        nicht als Fehler, aber auch nicht als glatter Erfolg.
      </p>

      {(laeufe.data ?? []).length === 0 ? (
        <EmptyState
          titel={
            laeufe.isLoading ? "wird geladen …" : "Noch kein Import gelaufen"
          }
          text={
            laeufe.isLoading
              ? "Einen Augenblick."
              : "Sobald der erste Lauf durch ist, steht hier, was er bewirkt hat."
          }
        />
      ) : (
        <ol className="lauf-liste">
          {(laeufe.data ?? []).map((lauf) => (
            <li key={lauf.id} className={`lauf lauf--${lauf.status}`}>
              <div className="lauf__kopf">
                <strong>{lauf.quelle}</strong>
                <span className={`lauf__status lauf__status--${lauf.status}`}>
                  {LAUF_STATUS_TEXT[lauf.status] ?? lauf.status}
                </span>
                <span className="lauf__zeit">{datumZeit(lauf.gestartet)}</span>
                {lauf.zeitraum && (
                  <span className="lauf__zeitraum">{lauf.zeitraum}</span>
                )}
              </div>
              <div className="lauf__datei">{lauf.datei ?? "–"}</div>
              <dl className="lauf__summen">
                {kontrollsummenZeilen(lauf.ergebnis).map((zeile) => (
                  <div key={zeile.text}>
                    <dt>{zeile.text}</dt>
                    <dd>{zeile.wert}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
