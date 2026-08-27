/**
 * Projektleiter den Nutzerkonten zuordnen (PLAN §4, §9).
 *
 * Der Grund für eine eigene Maske: nach der Migration steht in den 530 Projekten ein Vorname
 * aus der Teamliste („Stefan", „Günther") und kein Konto. Damit greift der Sichtbarkeits-Scope
 * `eigene` nicht – er vergleicht die Nutzer-ID. Ein Auswahlfeld je Projekt wären 530
 * Entscheidungen; hier sind es elf, je Name eine, wirksam für alle Projekte dieses Namens.
 *
 * Der Name bleibt stehen. Er ist der Herkunftsnachweis aus der Teamliste; wäre er überschrieben,
 * ließe sich die Zuordnung später nicht mehr prüfen.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageTitle } from "@/komponenten/PageTitle";
import { EmptyState } from "@/komponenten/EmptyState";
import { Formular } from "@/komponenten/Formular";
import { Meldung } from "@/komponenten/Meldung";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import { anzahl as anzahlText } from "@/format/formate";
import "./projekte.css";

/** `''` steht für „kein Konto" – ein `<select>` kann kein `null` tragen. */
type Auswahl = Record<string, string>;

export function Projektleiter() {
  const abfragen = useQueryClient();
  const [auswahl, setAuswahl] = useState<Auswahl>({});
  const [fehler, setFehler] = useState<ApiFehler | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);

  const uebersicht = useQuery({
    queryKey: ["projektleiter"],
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/projekte/projektleiter/uebersicht",
      );
      if (error) throw error;
      return data;
    },
  });

  // Die Auswahl folgt dem Serverstand. Bei mehreren Konten für einen Namen bleibt das Feld
  // leer – dann ist uneinheitlich zugeordnet, und die Maske soll nicht eines der beiden
  // stillschweigend zur Wahrheit machen.
  useEffect(() => {
    if (!uebersicht.data) return;
    const stand: Auswahl = {};
    for (const name of uebersicht.data.namen) {
      const konten = name.user_ids ?? [];
      // Genau ein Konto und kein Projekt ohne Konto: eindeutig zugeordnet.
      stand[name.pl_name] =
        konten.length === 1 && name.ohne_konto === 0 ? String(konten[0]) : "";
    }
    setAuswahl(stand);
  }, [uebersicht.data]);

  const zuordnen = useMutation({
    mutationFn: async () => {
      setFehler(null);
      setMeldung(null);
      const zuordnungen: Record<string, number | null> = {};
      for (const [name, wert] of Object.entries(auswahl)) {
        zuordnungen[name] = wert ? Number(wert) : null;
      }
      const { data, error } = await api.PUT(
        "/api/projekte/projektleiter/zuordnen",
        {
          body: { zuordnungen },
        },
      );
      if (error) throw error;
      return data;
    },
    onSuccess: (daten) => {
      setMeldung(daten?.meldung ?? null);
      void abfragen.invalidateQueries({ queryKey: ["projektleiter"] });
      void abfragen.invalidateQueries({ queryKey: ["projekte"] });
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

  const namen = uebersicht.data?.namen ?? [];
  const konten = uebersicht.data?.konten ?? [];
  const offen = namen.filter((n) => n.ohne_konto > 0).length;

  return (
    <>
      <Link to="/projekte" className="zurueck">
        ← Projekte
      </Link>

      <PageTitle
        meta={
          uebersicht.data
            ? `${anzahlText(namen.length, "Name", "Namen")} aus der Teamliste` +
              (offen ? ` · ${offen} noch ohne Konto` : " · alle zugeordnet")
            : undefined
        }
      >
        Projektleiter zuordnen
      </PageTitle>

      <p className="hinweistext">
        Die Zuordnung wirkt auf <strong>alle</strong> Projekte des jeweiligen
        Namens. Sie entscheidet, wer bei eingeschränkter Sichtbarkeit welche
        Projekte sieht; der Name aus der Teamliste bleibt als Herkunftsnachweis
        stehen.
      </p>

      {uebersicht.isError ? (
        <Meldung
          art="fehler"
          text={fehlerAuslesen(uebersicht.error).meldung}
          naechsterSchritt={fehlerAuslesen(uebersicht.error).naechster_schritt}
        />
      ) : null}

      {meldung ? <Meldung art="hinweis" text={meldung} /> : null}

      {uebersicht.isLoading ? (
        <p className="lademeldung">wird geladen …</p>
      ) : namen.length === 0 ? (
        <EmptyState
          titel="Keine Projektleiternamen"
          text="In den Projekten ist noch kein Projektleiter eingetragen."
        />
      ) : (
        <Formular
          fehler={fehler}
          laeuft={zuordnen.isPending}
          speichernText="Zuordnung übernehmen"
          onSpeichern={() => zuordnen.mutate()}
        >
          <table className="zuordnungstabelle">
            <thead>
              <tr>
                <th scope="col">Name in der Teamliste</th>
                <th scope="col" className="rechts">
                  Projekte
                </th>
                <th scope="col">Nutzerkonto</th>
              </tr>
            </thead>
            <tbody>
              {namen.map((name) => (
                <tr key={name.pl_name}>
                  <th scope="row">{name.pl_name}</th>
                  <td className="zahl rechts">{name.anzahl_projekte}</td>
                  <td>
                    <select
                      className="auswahlzeile__feld"
                      value={auswahl[name.pl_name] ?? ""}
                      aria-label={`Nutzerkonto für ${name.pl_name}`}
                      onChange={(e) =>
                        setAuswahl((vorher) => ({
                          ...vorher,
                          [name.pl_name]: e.target.value,
                        }))
                      }
                    >
                      <option value="">kein Konto</option>
                      {konten.map((k) => (
                        <option key={k.id} value={String(k.id)}>
                          {k.name} · {k.email}
                        </option>
                      ))}
                    </select>
                    {(name.user_ids ?? []).length > 1 ? (
                      <span className="zuordnungstabelle__warnung">
                        uneinheitlich zugeordnet – die Auswahl setzt alle
                        Projekte gleich
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Formular>
      )}
    </>
  );
}
