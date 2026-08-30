/**
 * Beschriftungen für Kapazität und Pipeline (PLAN §7 Phase 7).
 *
 * Wie in den anderen `begriffe.ts`: die Schlüssel der API sind technisch, die Oberfläche
 * spricht Deutsch. Getrennt von den Komponenten, weil sich Text prüfen lässt – und Text am
 * ehesten falsch wird.
 */

import { NBSP, anteil, euro, zahl } from "@/format/formate";

const SATZGRUPPEN: Record<string, string> = {
  monteur: "Monteur",
  obermonteur: "Obermonteur",
  elektriker: "Elektriker",
  planung: "Planung",
};

export function satzgruppe(schluessel: string | null | undefined): string {
  if (!schluessel) return "ohne Zuordnung";
  return SATZGRUPPEN[schluessel] ?? schluessel;
}

export function satzgruppen(): { wert: string; text: string }[] {
  return Object.entries(SATZGRUPPEN).map(([wert, text]) => ({ wert, text }));
}

/** Kalenderwoche kurz: `2026-W36` → `KW 36`. */
export function kalenderwoche(schluessel: string): string {
  const woche = schluessel.split("W")[1];
  return woche ? `KW${NBSP}${Number(woche)}` : schluessel;
}

/** Kalenderwoche mit Jahr, für Titel und Tooltips: `KW 36/2026`. */
export function kalenderwocheLang(schluessel: string): string {
  const [jahr, woche] = schluessel.split("-W");
  return jahr && woche ? `KW${NBSP}${Number(woche)}/${jahr}` : schluessel;
}

/** Stunden mit deutschem Dezimalkomma und geschütztem Leerzeichen: `38,5 h`. */
export function stunden(wert: number | null | undefined): string {
  if (wert === null || wert === undefined) return "–";
  // Ganze Stunden ohne Nachkommastellen: „160 h" liest sich besser als „160,00 h".
  const stellen = Number.isInteger(wert) ? 0 : 1;
  return `${zahl(wert, stellen)}${NBSP}h`;
}

const ENG = "eng";
const FREI = "frei";
const VOLL = "voll";

/**
 * Wie eine Woche dasteht – gemessen an der Warnschwelle aus der Konfiguration.
 *
 * Drei Stufen und keine Ampel: Grün gibt es im Corporate Design nicht, und eine freie Woche
 * ist auch keine gute Nachricht, sondern eine Beobachtung.
 */
export function wochenlage(
  auslastungPromille: number | null,
  warnungAbPromille: number,
): typeof ENG | typeof FREI | typeof VOLL | null {
  if (auslastungPromille === null) return null;
  if (auslastungPromille > 1000) return ENG;
  if (auslastungPromille >= warnungAbPromille) return VOLL;
  return FREI;
}

export function wochenlageText(lage: ReturnType<typeof wochenlage>): string {
  if (lage === ENG) return "überbucht";
  if (lage === VOLL) return "voll";
  if (lage === FREI) return "Luft";
  return "keine Mannschaft erfasst";
}

/** Auslastung als Prozenttext, `–` ohne Mannschaft. */
export function auslastung(promille: number | null): string {
  return promille === null ? "–" : anteil(promille / 10, 0);
}

/**
 * Zusammenfassung über der Wochenliste: `3 von 13 Wochen überbucht`.
 *
 * Die Zahl der überbuchten Wochen ist die eine Auskunft, für die man auf die Seite geht.
 */
export function auslastungZusatz(
  wochen: { auslastung_promille: number | null }[],
  warnungAbPromille: number,
): string {
  if (wochen.length === 0) return "";
  const ueberbucht = wochen.filter(
    (w) => wochenlage(w.auslastung_promille, warnungAbPromille) === ENG,
  ).length;
  if (ueberbucht === 0) return `keine der ${wochen.length} Wochen überbucht`;
  return `${ueberbucht} von ${wochen.length} Wochen überbucht`;
}

/** Wahrscheinlichkeit aus Promille als Prozenttext: `60 %`. */
export function chance(promille: number): string {
  return anteil(promille / 10, 0);
}

const ANGEBOT_STATUS: Record<string, string> = {
  offen: "offen",
  gewonnen: "gewonnen",
  verloren: "verloren",
};

export function angebotStatus(schluessel: string): string {
  return ANGEBOT_STATUS[schluessel] ?? schluessel;
}

/**
 * Die Pipeline in einem Satz: `1,25 Mio. € angeboten, davon 750.000,00 € gewichtet`.
 *
 * Beide Zahlen nebeneinander, immer. Nur die gewichtete zu nennen verschweigt das Risiko,
 * nur die rohe die Wahrscheinlichkeit.
 */
export function pipelineZusatz(rohCent: number, gewichtetCent: number): string {
  return `${euro(rohCent)} angeboten, davon ${euro(gewichtetCent)} gewichtet`;
}

/**
 * `1 Angebot`, `3 Angebote` – Zahl und Wort im gleichen Numerus.
 *
 * Eine Zeile mit falschem Numerus („1 offene Angebote") liest sich wie eine Maschinenausgabe
 * und wird dann auch so behandelt: überlesen. Dieselbe Regel wie in `app/formate.py`.
 */
export function mehrzahl(
  wert: number,
  einzahl: string,
  mehrzahlform: string,
): string {
  return wert === 1 ? `1 ${einzahl}` : `${zahl(wert)} ${mehrzahlform}`;
}
