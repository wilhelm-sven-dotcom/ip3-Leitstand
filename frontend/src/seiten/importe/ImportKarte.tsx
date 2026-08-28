/**
 * Eine Importquelle mit Vorschau und Übernahme (PLAN §8).
 *
 * Der Ablauf ist absichtlich zweistufig: erst ansehen, dann übernehmen. Die Übernahme schickt
 * die Kennung der Vorschau zurück; hat sich die Datei zwischenzeitlich geändert, weist der
 * Server sie ab. Deshalb behält die Karte die Vorschau, bis sie übernommen oder verworfen ist –
 * ein neuer Vorschauabruf ergäbe eine neue Kennung und würde die Prüfung wirkungslos machen.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Knopf } from "@/komponenten/Knopf";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { befundeKurz, kontrollsummenZeilen } from "./begriffe";

type Befund = {
  datei: string;
  zeile: number;
  spalte: string;
  wert: string;
  meldung: string;
  schwere: string;
};

type Vorschau = {
  quelle: string;
  kennung: string;
  dateien: string[];
  zeitraum: string | null;
  kontrollsummen: Record<string, unknown>;
  befunde: Befund[];
  hinweise: string[];
};

type Props = {
  quelle: "datev" | "kalkulation";
  titel: string;
  herkunft: string;
  erklaerung: string;
  onFertig: () => void;
  onFehler: (fehler: ApiFehler | null) => void;
  onMeldung: (meldung: string | null) => void;
};

export function ImportKarte({
  quelle,
  titel,
  herkunft,
  erklaerung,
  onFertig,
  onFehler,
  onMeldung,
}: Props) {
  const [vorschau, setVorschau] = useState<Vorschau | null>(null);

  const ansehen = useMutation({
    mutationFn: async () => {
      const pfad =
        quelle === "datev"
          ? "/api/importe/datev/vorschau"
          : "/api/importe/kalkulation/vorschau";
      const { data, error } = await api.GET(
        pfad as "/api/importe/datev/vorschau",
        {},
      );
      if (error) throw error;
      return data as unknown as Vorschau;
    },
    onSuccess: (daten) => {
      onFehler(null);
      onMeldung(null);
      setVorschau(daten);
    },
    onError: (ausfall) => {
      setVorschau(null);
      onMeldung(null);
      onFehler(fehlerAuslesen(ausfall));
    },
  });

  const uebernehmen = useMutation({
    mutationFn: async (kennung: string) => {
      const pfad =
        quelle === "datev"
          ? "/api/importe/datev/uebernehmen"
          : "/api/importe/kalkulation/uebernehmen";
      const { data, error } = await api.POST(
        pfad as "/api/importe/datev/uebernehmen",
        {
          body: { kennung },
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: (antwort) => {
      onFehler(null);
      onMeldung(antwort?.meldung ?? null);
      setVorschau(null);
      onFertig();
    },
    onError: (ausfall) => {
      onMeldung(null);
      onFehler(fehlerAuslesen(ausfall));
    },
  });

  const summen = vorschau
    ? kontrollsummenZeilen({ kontrollsummen: vorschau.kontrollsummen })
    : [];
  const befunde = vorschau
    ? befundeKurz(vorschau.befunde)
    : { sichtbar: [], weitere: 0 };

  return (
    <div className="import-karte">
      <h3>{titel}</h3>
      <p className="import-karte__herkunft">{herkunft}</p>
      <p className="import-karte__text">{erklaerung}</p>

      {vorschau && (
        <div className="vorschau">
          <div className="vorschau__dateien">
            {vorschau.dateien.length === 0
              ? "Keine Datei gefunden"
              : vorschau.dateien.join(", ")}
            {vorschau.zeitraum && (
              <span className="vorschau__zeitraum">{vorschau.zeitraum}</span>
            )}
          </div>
          <dl className="vorschau__summen">
            {summen.map((zeile) => (
              <div key={zeile.text}>
                <dt>{zeile.text}</dt>
                <dd>{zeile.wert}</dd>
              </div>
            ))}
          </dl>
          {vorschau.hinweise.map((hinweis) => (
            <p key={hinweis} className="vorschau__hinweis">
              {hinweis}
            </p>
          ))}
          {vorschau.befunde.length > 0 && (
            <div className="vorschau__befunde">
              <strong>{vorschau.befunde.length} Befunde</strong>
              <ul>
                {befunde.sichtbar.map((b) => (
                  <li key={`${b.datei}|${b.zeile}|${b.spalte}|${b.meldung}`}>
                    <code>
                      {b.datei} {b.spalte}
                      {b.zeile > 0 ? b.zeile : ""}
                    </code>{" "}
                    {b.meldung}
                  </li>
                ))}
              </ul>
              {befunde.weitere > 0 && (
                <p className="vorschau__mehr">
                  … und {befunde.weitere} weitere. Alle stehen nach der
                  Übernahme im Importprotokoll.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="import-karte__fuss">
        {vorschau ? (
          <>
            <Knopf art="sekundaer" onClick={() => setVorschau(null)}>
              Verwerfen
            </Knopf>{" "}
            <Knopf
              onClick={() => uebernehmen.mutate(vorschau.kennung)}
              disabled={uebernehmen.isPending}
            >
              {uebernehmen.isPending ? "wird übernommen …" : "Übernehmen"}
            </Knopf>
          </>
        ) : (
          <Knopf
            art="sekundaer"
            onClick={() => ansehen.mutate()}
            disabled={ansehen.isPending}
          >
            {ansehen.isPending ? "wird gelesen …" : "Vorschau ansehen"}
          </Knopf>
        )}
      </div>
    </div>
  );
}
