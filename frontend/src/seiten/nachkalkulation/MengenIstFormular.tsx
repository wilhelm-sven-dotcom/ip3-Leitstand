/**
 * Maske „Mengen-Ist bestätigen" (PLAN §7 Phase 4, §6.5).
 *
 * Nur Lagerpositionen: bei projektbestelltem Material sagt die DATEV-Buchung, was es gekostet
 * hat – die Menge ist dort ohne Belang, und ein Eingabefeld dafür würde nur nahelegen, dass sie
 * in die Bewertung eingeht.
 *
 * Bestätigen heißt bewerten: mit dem Speichern rechnet der Server sofort den Wert der
 * Lagerentnahme und schreibt ihn als Ist-Kosten. Eine bestätigte Menge ohne Bewertung wäre eine
 * Nachkalkulation, die zu gut aussieht.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { euro, zahl } from "@/format/formate";
import "./nachkalkulation.css";

type Position = {
  id: number;
  artikel_nr: string | null;
  bezeichnung: string;
  menge_soll: string;
  menge_ist: string | null;
  ek_preis: number | null;
  quelle: string;
  stand: string;
};

type Props = {
  projektNr: number;
  darfSchreiben: boolean;
};

export function MengenIstFormular({ projektNr, darfSchreiben }: Props) {
  const abfragen = useQueryClient();
  const [offen, setOffen] = useState(false);
  const [eingaben, setEingaben] = useState<Record<number, string>>({});
  const [fehler, setFehler] = useState<ApiFehler | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);

  const liste = useQuery({
    queryKey: ["stueckliste", projektNr],
    enabled: offen,
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/projekte/{projekt_nr}/stueckliste",
        {
          params: { path: { projekt_nr: projektNr } },
        },
      );
      if (error) throw error;
      return data as Position[];
    },
  });

  const speichern = useMutation({
    mutationFn: async (positionen: Position[]) => {
      const { data, error } = await api.POST(
        "/api/projekte/{projekt_nr}/mengen-ist",
        {
          params: { path: { projekt_nr: projektNr } },
          body: {
            positionen: positionen.map((p) => ({
              id: p.id,
              menge_ist: eingaben[p.id] ?? p.menge_ist ?? p.menge_soll,
              stand: p.stand,
            })),
          },
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: (antwort) => {
      setFehler(null);
      setMeldung(antwort?.meldung ?? null);
      setEingaben({});
      void abfragen.invalidateQueries({ queryKey: ["stueckliste", projektNr] });
      void abfragen.invalidateQueries({ queryKey: ["nachkalkulation"] });
    },
    onError: (ausfall) => {
      setMeldung(null);
      setFehler(fehlerAuslesen(ausfall));
    },
  });

  if (!darfSchreiben) return null;

  if (!offen) {
    return (
      <div className="mengen-fuss">
        <span className="nk-fuss">
          Die Lagerentnahmen werden mit der kalkulierten Menge bewertet, solange
          nichts anderes bestätigt ist.
        </span>
        <Knopf art="sekundaer" onClick={() => setOffen(true)}>
          Mengen-Ist bestätigen
        </Knopf>
      </div>
    );
  }

  const lager = (liste.data ?? []).filter((p) => p.quelle === "lager");

  return (
    <div className="nk-abschnitt">
      {fehler && (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      )}
      {meldung && <Meldung art="hinweis" text={meldung} />}

      <table className="datentabelle mengen-tabelle">
        <thead>
          <tr>
            <th>Artikel</th>
            <th>Bezeichnung</th>
            <th className="zahl">Soll</th>
            <th className="zahl">EK (€)</th>
            <th className="zahl">Gezählte Menge</th>
          </tr>
        </thead>
        <tbody>
          {lager.map((p) => (
            <tr key={p.id}>
              <td>{p.artikel_nr ?? "–"}</td>
              <td>{p.bezeichnung}</td>
              <td className="zahl">{zahl(Number(p.menge_soll), 3)}</td>
              <td className="zahl">{euro(p.ek_preis, false)}</td>
              <td className="zahl">
                <input
                  type="number"
                  step="0.001"
                  min="0"
                  inputMode="decimal"
                  aria-label={`Gezählte Menge für ${p.bezeichnung}`}
                  value={eingaben[p.id] ?? p.menge_ist ?? p.menge_soll}
                  onChange={(e) =>
                    setEingaben((alt) => ({ ...alt, [p.id]: e.target.value }))
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mengen-fuss">
        <span className="nk-fuss">
          Mit dem Speichern wird die Lagerentnahme sofort bewertet und als
          Ist-Kosten gebucht.
        </span>
        <span>
          <Knopf art="sekundaer" onClick={() => setOffen(false)}>
            Abbrechen
          </Knopf>{" "}
          <Knopf
            onClick={() => speichern.mutate(lager)}
            disabled={speichern.isPending || lager.length === 0}
          >
            {speichern.isPending
              ? "wird gespeichert …"
              : "Bestätigen und bewerten"}
          </Knopf>
        </span>
      </div>
    </div>
  );
}
