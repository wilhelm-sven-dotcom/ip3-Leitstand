/**
 * Zeitleiste der Meilensteine im Projektdetail (PLAN §6.8, Migration 0003).
 *
 * Drei Zustände je Schritt, und der Unterschied ist fachlich:
 *
 * * **keine Angabe** (`null`) – über den Schritt ist nichts bekannt. So kommen die migrierten
 *   Projekte aus der Teamliste, wo eine leere Zelle keine Aussage ist.
 * * **offen** (`false`) – der Schritt ist ausdrücklich noch nicht erledigt.
 * * **erledigt** (`true`) – mit Datum, wo eines bekannt ist. Die Teamliste kreuzt ohne Datum;
 *   ein erfundenes Datum wäre eine Falschangabe, deshalb bleibt es dann leer.
 *
 * Gespeichert wird der ganze Block in einem Zug: die Zeitleiste bearbeitet mehrere Schritte
 * hintereinander, und ein Aufruf je Häkchen ergäbe zehn Protokolleinträge für einen Vorgang.
 */

import { useEffect, useState } from "react";
import { Formular } from "@/komponenten/Formular";
import type { ApiFehler } from "@/api/client";
import { datum as datumText } from "@/format/formate";
import { ERLEDIGT_TEXT, MEILENSTEINGRUPPEN, meilensteinText } from "./begriffe";

export type MeilensteinDaten = {
  typ: string;
  geplant_kw?: string | null;
  erledigt?: boolean | null;
  erledigt_am?: string | null;
  bemerkung?: string | null;
};

type Props = {
  meilensteine: MeilensteinDaten[];
  darfSchreiben: boolean;
  laeuft: boolean;
  fehler: ApiFehler | null;
  onSpeichern: (stand: MeilensteinDaten[]) => void;
};

type Stand = Record<string, MeilensteinDaten>;

function ausListe(meilensteine: MeilensteinDaten[]): Stand {
  const stand: Stand = {};
  for (const m of meilensteine) stand[m.typ] = { ...m };
  return stand;
}

/** Wert des Auswahlfelds für die drei Zustände – `''` steht für „keine Angabe". */
function alsAuswahl(wert: boolean | null | undefined): string {
  if (wert === true) return "true";
  if (wert === false) return "false";
  return "";
}

function ausAuswahl(wert: string): boolean | null {
  if (wert === "true") return true;
  if (wert === "false") return false;
  return null;
}

export function Meilensteine({
  meilensteine,
  darfSchreiben,
  laeuft,
  fehler,
  onSpeichern,
}: Props) {
  const [stand, setStand] = useState<Stand>(() => ausListe(meilensteine));
  const [geaendert, setGeaendert] = useState(false);

  // Nach dem Speichern oder beim Wechsel auf ein anderes Projekt den Stand des Servers
  // übernehmen. Ohne das zeigte die Maske weiter die alten Werte.
  useEffect(() => {
    setStand(ausListe(meilensteine));
    setGeaendert(false);
  }, [meilensteine]);

  function setzen(typ: string, aenderung: Partial<MeilensteinDaten>) {
    setStand((vorher) => ({
      ...vorher,
      [typ]: { typ, ...vorher[typ], ...aenderung },
    }));
    setGeaendert(true);
  }

  /**
   * Es werden nur Schritte gesendet, über die etwas gesagt wird. Eine leere Zeile mitzusenden
   * würde 21 Meilensteinzeilen je Projekt anlegen, von denen 10 nichts aussagen.
   */
  function gefuellte(): MeilensteinDaten[] {
    return Object.values(stand).filter(
      (m) =>
        m.geplant_kw || m.erledigt !== null || m.erledigt_am || m.bemerkung,
    );
  }

  const inhalt = MEILENSTEINGRUPPEN.map((gruppe) => (
    <fieldset className="zeitleiste__gruppe" key={gruppe.titel}>
      <legend className="zeitleiste__legende">{gruppe.titel}</legend>
      {/* Der Hinweis auf die Schreibweise steht einmal je Gruppe. Als Platzhalter in jedem der
          19 Felder wäre er neunzehnmal derselbe graue Text – Unruhe ohne Nutzen. */}
      <p className="zeitleiste__erlaeuterung">
        {gruppe.erlaeuterung}
        {darfSchreiben ? " Woche als „KW 38“ oder „38/26“." : ""}
      </p>
      <table className="zeitleiste">
        <thead>
          <tr>
            <th scope="col">Schritt</th>
            <th scope="col">Geplant (KW)</th>
            <th scope="col">Zustand</th>
            <th scope="col">Erledigt am</th>
          </tr>
        </thead>
        <tbody>
          {gruppe.typen.map((typ) => {
            const eintrag = stand[typ] ?? { typ };
            const zustand = alsAuswahl(eintrag.erledigt);
            return (
              <tr
                key={typ}
                className={
                  eintrag.erledigt === true
                    ? "zeitleiste__zeile--erledigt"
                    : undefined
                }
              >
                <th scope="row" className="zeitleiste__schritt">
                  {meilensteinText(typ)}
                </th>
                <td>
                  {darfSchreiben ? (
                    <input
                      className="zeitleiste__feld"
                      type="text"
                      value={eintrag.geplant_kw ?? ""}
                      aria-label={`Geplante Woche für ${meilensteinText(typ)}`}
                      onChange={(e) =>
                        setzen(typ, { geplant_kw: e.target.value })
                      }
                    />
                  ) : (
                    (eintrag.geplant_kw ?? "–")
                  )}
                </td>
                <td>
                  {darfSchreiben ? (
                    <select
                      className="zeitleiste__feld"
                      value={zustand}
                      aria-label={`Zustand von ${meilensteinText(typ)}`}
                      onChange={(e) =>
                        setzen(typ, { erledigt: ausAuswahl(e.target.value) })
                      }
                    >
                      {ERLEDIGT_TEXT.map((z) => (
                        <option key={String(z.wert)} value={alsAuswahl(z.wert)}>
                          {z.text}
                        </option>
                      ))}
                    </select>
                  ) : (
                    (ERLEDIGT_TEXT.find(
                      (z) => z.wert === (eintrag.erledigt ?? null),
                    )?.text ?? "keine Angabe")
                  )}
                </td>
                <td>
                  {darfSchreiben ? (
                    <input
                      className="zeitleiste__feld"
                      type="date"
                      value={eintrag.erledigt_am ?? ""}
                      aria-label={`Erledigt am für ${meilensteinText(typ)}`}
                      onChange={(e) =>
                        setzen(typ, {
                          erledigt_am: e.target.value || null,
                          // Ein Datum ohne Häkchen wäre widersprüchlich.
                          erledigt: e.target.value ? true : eintrag.erledigt,
                        })
                      }
                    />
                  ) : (
                    datumText(eintrag.erledigt_am) || "–"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </fieldset>
  ));

  if (!darfSchreiben) {
    return (
      <div className="zeitleiste__huelle">
        {inhalt}
        <p className="hinweistext">
          Zum Ändern der Termine fehlt die Berechtigung „Termine und Status
          pflegen“.
        </p>
      </div>
    );
  }

  return (
    <div className="zeitleiste__huelle">
      <Formular
        fehler={fehler}
        laeuft={laeuft}
        speichernText={geaendert ? "Termine speichern" : "Gespeichert"}
        onSpeichern={() => onSpeichern(gefuellte())}
      >
        {inhalt}
      </Formular>
    </div>
  );
}
