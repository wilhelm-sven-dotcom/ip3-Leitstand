/**
 * Rahmen um ein Bearbeitungsformular (design/Komponenten.dc.html).
 *
 * Bündelt, was jede Maske gleich braucht, damit es nicht je Seite neu entschieden wird:
 *
 * * **Ein `<form>` mit `onSubmit`**, damit die Eingabetaste speichert und Bildschirmleser das
 *   Formular als solches erkennen.
 * * **Die Fehlermeldung steht oben und trägt den nächsten Schritt.** Die Fehlerkörper des
 *   Backends haben die Form `{code, meldung, naechster_schritt}`; beides gehört auf den
 *   Bildschirm, sonst sitzt jemand davor und kommt nicht weiter (PLAN §14).
 * * **Speichern ist gesperrt, solange gespeichert wird.** Zweimal klicken darf nicht zweimal
 *   anlegen.
 */

import type { FormEvent, ReactNode } from "react";
import { Knopf } from "./Knopf";
import { Meldung } from "./Meldung";
import type { ApiFehler } from "@/api/client";

type Props = {
  children: ReactNode;
  /** Fehler des letzten Speicherversuchs, fertig ausgelesen. */
  fehler?: ApiFehler | null;
  laeuft?: boolean;
  /** Beschriftung des Speicherknopfs; „Speichern" ist der Regelfall. */
  speichernText?: string;
  /** Ohne diese Funktion gibt es keinen Abbrechen-Knopf. */
  onAbbrechen?: () => void;
  onSpeichern: () => void;
  /** Zusätzliche Aktionen links neben Speichern, z. B. „Deaktivieren". */
  weitereAktionen?: ReactNode;
  gesperrt?: boolean;
  /** Grund der Sperre – wird anstelle der Knöpfe gezeigt. */
  sperrgrund?: ReactNode;
};

export function Formular({
  children,
  fehler = null,
  laeuft = false,
  speichernText = "Speichern",
  onAbbrechen,
  onSpeichern,
  weitereAktionen,
  gesperrt = false,
  sperrgrund,
}: Props) {
  function abschicken(ereignis: FormEvent) {
    ereignis.preventDefault();
    if (!laeuft && !gesperrt) onSpeichern();
  }

  return (
    <form className="formular" onSubmit={abschicken} noValidate>
      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      <div className="formular__felder">{children}</div>

      {gesperrt ? (
        <div className="formular__sperre">{sperrgrund}</div>
      ) : (
        <div className="formular__aktionen">
          <span className="formular__weitere">{weitereAktionen}</span>
          {onAbbrechen ? (
            <Knopf art="sekundaer" onClick={onAbbrechen} disabled={laeuft}>
              Abbrechen
            </Knopf>
          ) : null}
          <button
            type="submit"
            className="knopf knopf--primaer"
            disabled={laeuft}
          >
            {laeuft ? "wird gespeichert …" : speichernText}
          </button>
        </div>
      )}
    </form>
  );
}
