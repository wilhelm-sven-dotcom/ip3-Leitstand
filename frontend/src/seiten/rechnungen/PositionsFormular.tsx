/**
 * Position eines Belegs anlegen oder ändern.
 *
 * Der Betrag wird als Text eingegeben und mit `centAusText` in ganze Cent umgerechnet – nie über
 * Gleitkomma: `0,145 € * 100` ergäbe dort 14 statt 15 Cent (PLAN §5).
 *
 * Der Steuersatz ist vorbelegt aus dem Kennzeichen des Belegs und nur bei `gemischt` frei
 * wählbar. Bei allen anderen Kennzeichen wäre ein abweichender Satz ein Widerspruch zum Kopf des
 * Belegs, den die Festschreibung ohnehin zurückweist (PLAN §6.2).
 */

import { useState } from "react";
import { FormRow } from "@/komponenten/FormRow";
import { Formular } from "@/komponenten/Formular";
import { centAusText, euro } from "@/format/formate";
import { mengeText, satzText } from "./begriffe";

export type PositionsDaten = {
  bezeichnung: string;
  menge: string;
  einheit: string;
  ep_netto: number;
  ust_satz: number;
};

type Position = {
  id: number;
  bezeichnung: string;
  menge: string;
  einheit: string | null;
  ep_netto: number;
  ust_satz: number;
};

/** Sätze, die der Leitstand kennt (PLAN §6.2). Weitere brauchte es bisher nicht. */
const SAETZE = [190, 0];

const SATZ_JE_KENNZEICHEN: Record<string, number> = {
  "19": 190,
  "0": 0,
  "13b": 0,
};

export function PositionsFormular({
  position,
  ustKennzeichen,
  laeuft = false,
  onSpeichern,
  onLoeschen,
}: {
  position?: Position;
  ustKennzeichen: string;
  laeuft?: boolean;
  onSpeichern: (daten: PositionsDaten) => void;
  onLoeschen?: () => void;
}) {
  const vorgabeSatz = SATZ_JE_KENNZEICHEN[ustKennzeichen] ?? 190;
  const [bezeichnung, setBezeichnung] = useState(position?.bezeichnung ?? "");
  const [menge, setMenge] = useState(
    position ? mengeText(position.menge) : "1",
  );
  const [einheit, setEinheit] = useState(position?.einheit ?? "");
  const [betrag, setBetrag] = useState(
    position ? euro(position.ep_netto, false) : "",
  );
  const [satz, setSatz] = useState(position?.ust_satz ?? vorgabeSatz);
  const [fehler, setFehler] = useState<string | null>(null);

  const cent = centAusText(betrag);

  function speichern() {
    if (!bezeichnung.trim()) {
      setFehler("Die Bezeichnung darf nicht leer sein.");
      return;
    }
    if (cent === null) {
      setFehler("Der Einzelpreis ist keine gültige Zahl.");
      return;
    }
    setFehler(null);
    onSpeichern({
      bezeichnung: bezeichnung.trim(),
      menge: menge.trim() || "1",
      einheit: einheit.trim(),
      ep_netto: cent,
      ust_satz: ustKennzeichen === "gemischt" ? satz : vorgabeSatz,
    });
  }

  return (
    <Formular
      laeuft={laeuft}
      onSpeichern={speichern}
      weitereAktionen={
        onLoeschen ? (
          <button
            type="button"
            className="knopf knopf--sekundaer"
            onClick={onLoeschen}
          >
            Position entfernen
          </button>
        ) : null
      }
    >
      <FormRow
        label="Bezeichnung"
        breit
        value={bezeichnung}
        onChange={(e) => setBezeichnung(e.target.value)}
        fehler={fehler && !bezeichnung.trim() ? fehler : undefined}
      />
      <FormRow
        label="Menge"
        zahl
        value={menge}
        onChange={(e) => setMenge(e.target.value)}
        hinweis="Leer lassen für 1."
      />
      <FormRow
        label="Einheit"
        value={einheit}
        onChange={(e) => setEinheit(e.target.value)}
        hinweis="z. B. Stk, m, kWp – leer lassen, wenn es keine gibt."
      />
      <FormRow
        label="Einzelpreis netto (€)"
        zahl
        value={betrag}
        onChange={(e) => setBetrag(e.target.value)}
        fehler={fehler && cent === null ? fehler : undefined}
        hinweis={cent !== null ? euro(cent) : "Betrag in Euro, z. B. 91.875,00"}
      />

      <div className="formularzeile">
        <span className="formularzeile__label">Umsatzsteuer</span>
        {ustKennzeichen === "gemischt" ? (
          <select
            className="formularzeile__feld"
            value={satz}
            onChange={(e) => setSatz(Number(e.target.value))}
          >
            {SAETZE.map((s) => (
              <option key={s} value={s}>
                {satzText(s)}
              </option>
            ))}
          </select>
        ) : (
          <span className="formularzeile__hinweis">
            {satzText(vorgabeSatz)} – aus dem Steuerkennzeichen des Belegs. Für
            abweichende Sätze das Kennzeichen im Belegkopf auf „gemischt“
            stellen.
          </span>
        )}
      </div>
    </Formular>
  );
}
