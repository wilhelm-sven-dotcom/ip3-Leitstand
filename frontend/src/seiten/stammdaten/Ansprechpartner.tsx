/**
 * Ansprechpartner eines Kunden, im Panel unter den Stammdaten.
 *
 * Bewusst kein eigener Bildschirm: ein Ansprechpartner ohne seinen Kunden ist bedeutungslos.
 * Anlegen und Ändern laufen in derselben schmalen Zeile – bei drei Feldern lohnt kein Formular
 * mit Panel im Panel.
 */

import { useState } from "react";
import { Knopf } from "@/komponenten/Knopf";
import { FormRow } from "@/komponenten/FormRow";
import { Meldung } from "@/komponenten/Meldung";
import type { ApiFehler } from "@/api/client";

export type PartnerDaten = {
  id: number;
  name: string;
  funktion?: string | null;
  telefon?: string | null;
  email?: string | null;
  bemerkung?: string | null;
  stand: string;
};

export type PartnerEingabe = {
  name: string;
  funktion?: string | null;
  telefon?: string | null;
  email?: string | null;
};

const FUNKTIONEN: [string, string][] = [
  ["", "ohne Angabe"],
  ["technik", "Technik"],
  ["kaufmaennisch", "Kaufmännisch"],
  ["sonstig", "Sonstiges"],
];

function funktionstext(wert: string | null | undefined): string {
  return FUNKTIONEN.find(([k]) => k === (wert ?? ""))?.[1] ?? "ohne Angabe";
}

type Props = {
  partner: PartnerDaten[];
  darfSchreiben: boolean;
  laeuft: boolean;
  fehler: ApiFehler | null;
  onAnlegen: (eingabe: PartnerEingabe) => void;
  onAendern: (id: number, eingabe: PartnerEingabe & { stand: string }) => void;
  onLoeschen: (partner: PartnerDaten) => void;
};

export function AnsprechpartnerListe({
  partner,
  darfSchreiben,
  laeuft,
  fehler,
  onAnlegen,
  onAendern,
  onLoeschen,
}: Props) {
  const [neu, setNeu] = useState<PartnerEingabe | null>(null);
  const [bearbeitet, setBearbeitet] = useState<PartnerDaten | null>(null);

  return (
    <section className="partner">
      <header className="partner__kopf">
        <h3 className="partner__titel">Ansprechpartner</h3>
        {darfSchreiben && !neu ? (
          <Knopf art="sekundaer" klein onClick={() => setNeu({ name: "" })}>
            Hinzufügen
          </Knopf>
        ) : null}
      </header>

      {fehler ? (
        <Meldung
          art="fehler"
          text={fehler.meldung}
          naechsterSchritt={fehler.naechster_schritt}
        />
      ) : null}

      {partner.length === 0 && !neu ? (
        <p className="partner__leer">Noch kein Ansprechpartner erfasst.</p>
      ) : null}

      <ul className="partner__liste">
        {partner.map((eintrag) =>
          bearbeitet?.id === eintrag.id ? (
            <li
              key={eintrag.id}
              className="partner__eintrag partner__eintrag--offen"
            >
              <PartnerFelder
                werte={bearbeitet}
                onWert={(feld, wert) =>
                  setBearbeitet({ ...bearbeitet, [feld]: wert })
                }
              />
              <div className="partner__aktionen">
                <Knopf
                  art="sekundaer"
                  klein
                  onClick={() => setBearbeitet(null)}
                  disabled={laeuft}
                >
                  Abbrechen
                </Knopf>
                <Knopf
                  klein
                  disabled={laeuft || !bearbeitet.name.trim()}
                  onClick={() => {
                    onAendern(eintrag.id, {
                      name: bearbeitet.name,
                      funktion: bearbeitet.funktion || null,
                      telefon: bearbeitet.telefon || null,
                      email: bearbeitet.email || null,
                      stand: eintrag.stand,
                    });
                    setBearbeitet(null);
                  }}
                >
                  Übernehmen
                </Knopf>
              </div>
            </li>
          ) : (
            <li key={eintrag.id} className="partner__eintrag">
              <div>
                <span className="partner__name">{eintrag.name}</span>
                <span className="partner__meta">
                  {[
                    funktionstext(eintrag.funktion),
                    eintrag.telefon,
                    eintrag.email,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              {darfSchreiben ? (
                <div className="partner__aktionen">
                  <Knopf
                    art="sekundaer"
                    klein
                    onClick={() => setBearbeitet(eintrag)}
                  >
                    Ändern
                  </Knopf>
                  <Knopf
                    art="sekundaer"
                    klein
                    onClick={() => onLoeschen(eintrag)}
                  >
                    Löschen
                  </Knopf>
                </div>
              ) : null}
            </li>
          ),
        )}

        {neu ? (
          <li className="partner__eintrag partner__eintrag--offen">
            <PartnerFelder
              werte={neu}
              onWert={(feld, wert) => setNeu({ ...neu, [feld]: wert })}
            />
            <div className="partner__aktionen">
              <Knopf
                art="sekundaer"
                klein
                onClick={() => setNeu(null)}
                disabled={laeuft}
              >
                Abbrechen
              </Knopf>
              <Knopf
                klein
                disabled={laeuft || !neu.name.trim()}
                onClick={() => {
                  onAnlegen(neu);
                  setNeu(null);
                }}
              >
                Anlegen
              </Knopf>
            </div>
          </li>
        ) : null}
      </ul>
    </section>
  );
}

function PartnerFelder({
  werte,
  onWert,
}: {
  werte: PartnerEingabe;
  onWert: (feld: keyof PartnerEingabe, wert: string) => void;
}) {
  return (
    <div className="partner__felder">
      <FormRow
        label="Name"
        value={werte.name}
        onChange={(e) => onWert("name", e.target.value)}
        required
      />
      <label className="auswahlzeile">
        <span className="auswahlzeile__label">Funktion</span>
        <select
          className="auswahlzeile__feld"
          value={werte.funktion ?? ""}
          onChange={(e) => onWert("funktion", e.target.value)}
        >
          {FUNKTIONEN.map(([wert, text]) => (
            <option key={wert} value={wert}>
              {text}
            </option>
          ))}
        </select>
      </label>
      <FormRow
        label="Telefon"
        value={werte.telefon ?? ""}
        onChange={(e) => onWert("telefon", e.target.value)}
      />
      <FormRow
        label="E-Mail"
        type="email"
        value={werte.email ?? ""}
        onChange={(e) => onWert("email", e.target.value)}
      />
    </div>
  );
}
