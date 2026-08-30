/**
 * Beschriftungen für Anlagen und Fristen (PLAN §7 Phase 6).
 *
 * Wie in `seiten/projekte/begriffe.ts` und `seiten/cockpit/begriffe.ts`: die Schlüssel der API
 * sind technisch (`gewaehrleistung`, `ueberfaellig`), die Oberfläche spricht Deutsch. Getrennt
 * von den Komponenten, weil sich Text prüfen lässt und Text am ehesten falsch wird.
 */

import { NBSP, datum, euro, monatKurz } from "@/format/formate";

const FRIST_TYPEN: Record<string, string> = {
  mastr: "MaStR-Registrierung",
  fertigmeldung: "Fertigmeldung",
  reservierung: "Netzanschluss-Reservierung",
  gewaehrleistung: "Gewährleistung",
  sonstig: "Sonstige Frist",
};

export function fristTyp(schluessel: string): string {
  return FRIST_TYPEN[schluessel] ?? schluessel;
}

/** Alle Typen mit Beschriftung – für die Auswahl beim Anlegen einer Frist. */
export function fristTypen(): { wert: string; text: string }[] {
  return Object.entries(FRIST_TYPEN).map(([wert, text]) => ({ wert, text }));
}

/**
 * Badge-Zustand zur Frist.
 *
 * Nur was überfällig ist, bekommt das gefüllte Akzent-Rot; was im Vorlauf liegt, den roten
 * Rand. Eine Gewährleistung, die in vier Jahren endet, steht blau da – sie in derselben Farbe
 * wie eine versäumte MaStR-Registrierung zu zeigen, würde das Signal wertlos machen.
 */
export function fristBadge(
  status: string,
): "ueberfaellig" | "frist" | "geplant" {
  if (status === "ueberfaellig") return "ueberfaellig";
  if (status === "faellig") return "frist";
  return "geplant";
}

const ZUSTAENDE: Record<string, string> = {
  ueberfaellig: "überfällig",
  faellig: "läuft ab",
  offen: "offen",
};

export function fristStatus(schluessel: string): string {
  return ZUSTAENDE[schluessel] ?? schluessel;
}

/**
 * Wie lange noch, in Worten: `in 12 Tagen`, `heute`, `seit 3 Tagen überfällig`.
 *
 * Ein Datum allein sagt zu wenig – „20.05.2030" beantwortet nicht die Frage, die man beim
 * Blick auf die Startseite hat. Ab einem Vierteljahr wird in Monaten gerechnet, weil
 * „in 1.284 Tagen" niemand einordnet.
 */
export function frist(tageBis: number): string {
  if (tageBis === 0) return "heute fällig";
  if (tageBis < 0) {
    const tage = Math.abs(tageBis);
    return tage === 1
      ? "seit gestern überfällig"
      : `seit ${tage} Tagen überfällig`;
  }
  if (tageBis === 1) return "morgen fällig";
  if (tageBis < 90) return `in ${tageBis} Tagen`;
  const monate = Math.round(tageBis / 30);
  if (monate < 24) return `in rund ${monate} Monaten`;
  return `in rund ${Math.round(tageBis / 365)} Jahren`;
}

/** Zusammenfassung über dem Widget: `2 überfällig, 3 laufen ab`. */
export function fristenZusatz(zaehlung: Record<string, number>): string {
  const teile: string[] = [];
  const ueberfaellig = zaehlung.ueberfaellig ?? 0;
  const faellig = zaehlung.faellig ?? 0;
  if (ueberfaellig) teile.push(`${ueberfaellig} überfällig`);
  if (faellig)
    teile.push(faellig === 1 ? "1 läuft ab" : `${faellig} laufen ab`);
  return teile.join(", ");
}

/**
 * Gewährleistung als lesbare Zeile: `bis 20.05.2030` oder der Hinweis, dass sie offen ist.
 *
 * Ohne Abnahmedatum gibt es kein Ende – und dann soll dort nicht „–" stehen, sondern warum.
 */
export function gewaehrleistung(ende: string | null | undefined): string {
  return ende ? `bis ${datum(ende)}` : "offen – Abnahmedatum fehlt";
}

/** Anlagenzeile in einem Satz: `29,7 kWp · 20 kWh · in Betrieb seit 12.05.2026`. */
export function anlagenZusatz(
  inbetriebnahme: string | null | undefined,
  wartungsvertrag: boolean,
): string {
  const teile: string[] = [];
  if (inbetriebnahme) teile.push(`in Betrieb seit ${datum(inbetriebnahme)}`);
  teile.push(wartungsvertrag ? "mit Wartungsvertrag" : "ohne Wartungsvertrag");
  return teile.join(" · ");
}

/* ------------------------------------------------------------------------------------------
 * Eigene Bestandsanlagen und ihre Vergütung (Phase 7)
 * ---------------------------------------------------------------------------------------- */

/**
 * Wie eine Anlage vergütet wird, samt Satz.
 *
 * Der Satz gehört dazu, weil er die Erwartung erklärt: eine Abweichung ist fast immer ein
 * falsch abgeschriebener Satz, und wer ihn nicht sieht, sucht an der falschen Stelle.
 */
export function verguetungsart(
  art: string,
  satz: number | null,
  entgelt: number | null = null,
): string {
  const name =
    art === "direktvermarktung" ? "Direktvermarktung" : "Einspeisung";
  if (satz === null) {
    return `${name} · Satz fehlt`;
  }
  // Bei Direktvermarktung steht hier der Satz **nach** Abzug des Vermarkterentgelts – also
  // der, mit dem die Erwartung daneben gerechnet ist. Den anzulegenden Wert anzuzeigen und
  // mit einem anderen zu rechnen wäre der schlimmere Fehler: wer nachrechnet, käme auf eine
  // andere Zahl und misstraute danach der ganzen Ansicht.
  const wirksam =
    art === "direktvermarktung" && entgelt ? satz - entgelt : satz;
  const gerundet = wirksam.toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
  const zusatz =
    art === "direktvermarktung" && entgelt
      ? ` (${satz.toLocaleString("de-DE", { minimumFractionDigits: 2 })} abzgl. Entgelt)`
      : "";
  return `${name} · ${gerundet}${NBSP}ct/kWh${zusatz}`;
}

/** „Sep 2025 bis Aug 2026" – ohne Jahreszahl liest sich ein Zwölfmonatsfenster wie Unsinn. */
export function zeitraumText(von: string, bis: string): string {
  return `${monatMitJahr(von)} bis ${monatMitJahr(bis)}`;
}

function monatMitJahr(wert: string): string {
  if (!wert || wert.length !== 7) return "–";
  return `${monatKurz(wert)}${NBSP}${wert.slice(0, 4)}`;
}

/**
 * Die Abweichung als Text, und ob sie auffällt.
 *
 * Ohne Erwartung gibt es keine Abweichung – dann steht ein Strich da und nicht „0,00 €".
 * Der Unterschied ist der zwischen „stimmt" und „lässt sich nicht sagen".
 */
export function abweichungText(
  cent: number | null,
  promille: number | null,
): { text: string; auffaellig: boolean } {
  if (cent === null) {
    return { text: "–", auffaellig: false };
  }
  if (cent === 0) {
    return { text: "stimmt", auffaellig: false };
  }
  const vorzeichen = cent > 0 ? "+" : "−";
  const betrag = euro(Math.abs(cent));
  const anteil =
    promille === null
      ? ""
      : ` (${vorzeichen}${(Math.abs(promille) / 10).toLocaleString("de-DE", {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        })}${NBSP}%)`;
  // Auffällig ist erst, was der Server über der Toleranz führt – die Farbe soll etwas bedeuten.
  return {
    text: `${vorzeichen}${betrag}${anteil}`,
    auffaellig: promille !== null && Math.abs(promille) > 20,
  };
}

/** Ob eine abgerechnete Gutschrift bezahlt ist. */
export function zahlungslage(monat: {
  bezahlt_am?: string | null;
  offen: boolean;
  abgerechnet_cent: number;
}): { art: "erfolg" | "warnung" | "neutral"; text: string } {
  if (monat.bezahlt_am) {
    return { art: "erfolg", text: `bezahlt ${datum(monat.bezahlt_am)}` };
  }
  if (monat.abgerechnet_cent === 0) {
    return { art: "neutral", text: "–" };
  }
  return { art: "warnung", text: "offen" };
}
