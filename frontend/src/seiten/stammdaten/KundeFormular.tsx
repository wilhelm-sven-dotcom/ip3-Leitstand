/**
 * Bearbeitungsformular eines Kunden im Seitenpanel (PLAN §7 Phase 1).
 *
 * Der gelesene Stand (`stand`) geht unverändert zurück an die Schnittstelle. Weicht er beim
 * Speichern ab, kommt eine Konfliktmeldung statt eines stillen Überschreibens – die Maske muss
 * ihn also mitführen, auch wenn er nirgends sichtbar ist.
 */

import { useEffect, useState } from "react";
import { FormRow } from "@/komponenten/FormRow";
import { Formular } from "@/komponenten/Formular";
import { Knopf } from "@/komponenten/Knopf";
import type { ApiFehler } from "@/api/client";

export type KundeDaten = {
  id?: number;
  kunden_nr?: number;
  name: string;
  zusatz?: string | null;
  strasse?: string | null;
  plz?: string | null;
  ort?: string | null;
  ust_id?: string | null;
  typ: string;
  zahlungsziel_tage?: number | null;
  email?: string | null;
  telefon?: string | null;
  status: string;
  bemerkung?: string | null;
  stand?: string;
  anzahl_projekte?: number;
};

export const LEERER_KUNDE: KundeDaten = {
  name: "",
  typ: "b2c",
  status: "aktiv",
};

type Props = {
  kunde: KundeDaten;
  laeuft: boolean;
  fehler: ApiFehler | null;
  darfSchreiben: boolean;
  onSpeichern: (daten: KundeDaten) => void;
  onAbbrechen: () => void;
};

export function KundeFormular({
  kunde,
  laeuft,
  fehler,
  darfSchreiben,
  onSpeichern,
  onAbbrechen,
}: Props) {
  const [entwurf, setEntwurf] = useState<KundeDaten>(kunde);

  // Wechselt der geöffnete Kunde, muss der Entwurf mitwechseln – sonst stehen im Formular die
  // Daten des vorher geöffneten.
  useEffect(() => setEntwurf(kunde), [kunde]);

  function feld<K extends keyof KundeDaten>(name: K, wert: KundeDaten[K]) {
    setEntwurf((vorher) => ({ ...vorher, [name]: wert }));
  }

  const inaktiv = entwurf.status === "inaktiv";

  return (
    <Formular
      fehler={fehler}
      laeuft={laeuft}
      onSpeichern={() => onSpeichern(entwurf)}
      onAbbrechen={onAbbrechen}
      gesperrt={!darfSchreiben}
      sperrgrund={
        "Zum Bearbeiten fehlt die Berechtigung „Kunden und Ansprechpartner pflegen“."
      }
      weitereAktionen={
        kunde.id ? (
          <Knopf
            art="sekundaer"
            onClick={() =>
              onSpeichern({ ...entwurf, status: inaktiv ? "aktiv" : "inaktiv" })
            }
            disabled={laeuft}
          >
            {inaktiv ? "Wieder aktivieren" : "Deaktivieren"}
          </Knopf>
        ) : null
      }
    >
      <FormRow
        label="Name"
        value={entwurf.name}
        onChange={(e) => feld("name", e.target.value)}
        required
        hinweis="Firmenname oder Nachname, so wie er auf der Rechnung stehen soll."
      />
      <FormRow
        label="Zusatz"
        value={entwurf.zusatz ?? ""}
        onChange={(e) => feld("zusatz", e.target.value)}
        hinweis="Rechtsform, Abteilung oder eine zweite Zeile der Anschrift."
      />
      <FormRow
        label="Straße und Hausnummer"
        value={entwurf.strasse ?? ""}
        onChange={(e) => feld("strasse", e.target.value)}
      />
      <div className="formular__zeile-paar">
        <FormRow
          label="PLZ"
          value={entwurf.plz ?? ""}
          onChange={(e) => feld("plz", e.target.value)}
          zahl
        />
        <FormRow
          label="Ort"
          value={entwurf.ort ?? ""}
          onChange={(e) => feld("ort", e.target.value)}
          breit
        />
      </div>

      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Art</span>
        <select
          className="auswahlzeile__feld"
          value={entwurf.typ}
          onChange={(e) => feld("typ", e.target.value)}
        >
          <option value="b2c">Privatkunde</option>
          <option value="b2b">Geschäftskunde</option>
        </select>
        <span className="auswahlzeile__hinweis">
          Geschäftskunden bekommen ab Phase 3 eine Rechnung mit eingebettetem
          XML (ZUGFeRD).
        </span>
      </label>

      <FormRow
        label="Umsatzsteuer-Identifikationsnummer"
        value={entwurf.ust_id ?? ""}
        onChange={(e) => feld("ust_id", e.target.value)}
        hinweis="Nur bei Geschäftskunden; steht auf der Rechnung."
      />
      <FormRow
        label="E-Mail"
        type="email"
        value={entwurf.email ?? ""}
        onChange={(e) => feld("email", e.target.value)}
      />
      <FormRow
        label="Telefon"
        value={entwurf.telefon ?? ""}
        onChange={(e) => feld("telefon", e.target.value)}
      />
      <FormRow
        label="Zahlungsziel (Tage)"
        type="number"
        value={entwurf.zahlungsziel_tage ?? ""}
        onChange={(e) =>
          feld(
            "zahlungsziel_tage",
            e.target.value === "" ? null : Number(e.target.value),
          )
        }
        zahl
        hinweis="Leer lassen für den Standard aus der Konfiguration."
      />
      <FormRow
        label="Bemerkung"
        value={entwurf.bemerkung ?? ""}
        onChange={(e) => feld("bemerkung", e.target.value)}
      />
    </Formular>
  );
}
