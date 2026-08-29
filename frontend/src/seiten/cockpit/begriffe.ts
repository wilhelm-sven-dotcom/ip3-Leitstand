/**
 * Begriffe und Ableitungen des Firmen-Cockpits (PLAN §7 Phase 5).
 *
 * Die Rechenwege stehen im Backend (`app/dienste/cockpit.py`) – hier steht nur, wie die Zahlen
 * heißen und wie aus ihnen die Balken des Wasserfalls werden. Getrennt von der Seite, damit
 * beides für sich prüfbar bleibt.
 */

import { euroKurz, monat as monatText, prozent } from "@/format/formate";

/** Die Blöcke des Fixkostenausweises in der Reihenfolge, in der sie ausgewiesen werden. */
export const BLOCK_TEXT: Record<string, string> = {
  personal: "Personal",
  raum: "Raum",
  fahrzeuge: "Fahrzeuge",
  versicherung: "Versicherungen",
  werbung: "Werbung",
  zins: "Zinsen und Gebühren",
  sonstiges: "Sonstiges",
  neutral: "Neutral (zählt nicht)",
};

export const BLOCK_REIHENFOLGE = [
  "personal",
  "raum",
  "fahrzeuge",
  "versicherung",
  "werbung",
  "zins",
  "sonstiges",
  "neutral",
];

/** Woher die Fixkosten eines Monats stammen. */
export const HERKUNFT_TEXT: Record<string, string> = {
  susa: "aus der Buchhaltung",
  plan: "Planwerte",
  keine: "nicht hinterlegt",
};

export const STATUS_TEXT: Record<string, string> = {
  offen: "offen",
  ueberfaellig: "überfällig",
  bezahlt: "bezahlt",
  bezahlt_mit_abzug: "bezahlt mit Abzug",
  ohne_stand: "ohne Stand",
};

export type Stufe = {
  /** Beschriftung unter dem Balken. */
  name: string;
  /** Betrag in Cent. Bei Abzügen negativ. */
  betrag: number;
  /** Summenstufe (Deckungsbeitrag, Überdeckung) statt Zu- oder Abgang. */
  summe: boolean;
  /** Wo der Balken beginnt – für den schwebenden Teil des Wasserfalls. */
  basis: number;
};

/**
 * Die fünf Stufen vom Umsatz zur Über-/Unterdeckung.
 *
 * Ein Wasserfall und keine fünf einzelnen Säulen: die Aussage ist, wo das Geld hingeht, und die
 * sieht man nur, wenn die Abzüge an der Stelle ansetzen, an der der vorige Wert aufhört.
 */
export function stufen(
  umsatz: number,
  variableKosten: number,
  fixkosten: number,
): Stufe[] {
  const deckungsbeitrag = umsatz - variableKosten;
  const deckung = deckungsbeitrag - fixkosten;
  return [
    { name: "Umsatz", betrag: umsatz, summe: true, basis: 0 },
    {
      name: "Material & Fremdleistung",
      betrag: -variableKosten,
      summe: false,
      basis: deckungsbeitrag,
    },
    { name: "Deckungsbeitrag", betrag: deckungsbeitrag, summe: true, basis: 0 },
    { name: "Fixkosten", betrag: -fixkosten, summe: false, basis: deckung },
    { name: "Über-/Unterdeckung", betrag: deckung, summe: true, basis: 0 },
  ];
}

/**
 * Größter Betrag im Wasserfall – der Maßstab für die Balkenhöhen.
 *
 * Mindestens 1, damit ein Monat ganz ohne Zahlen keine Division durch null ergibt.
 */
export function maßstab(reihe: Stufe[]): number {
  return Math.max(
    1,
    ...reihe.map((s) => Math.abs(s.betrag) + Math.abs(s.basis)),
  );
}

/**
 * Text der Reichweitenkachel (Entscheidung 26 von Sven).
 *
 * Die große Zahl beantwortet „wie lange reicht die Arbeit", die Unterzeile „wie lange trägt der
 * Bestand die Firma". Beide sind berechtigt und meinen Verschiedenes.
 */
export function reichweiteZusatz(
  bestandCent: number,
  durchschnittCent: number,
  fixkostenmonate: number | null,
): string {
  const teile = [`Bestand ${euroKurz(bestandCent)}`];
  if (durchschnittCent > 0) {
    teile.push(`Ø-Umsatz ${euroKurz(durchschnittCent)} je Monat`);
  }
  if (fixkostenmonate !== null) {
    teile.push(`deckt ${zahlKurz(fixkostenmonate)} Monate Fixkosten`);
  }
  return teile.join(" · ");
}

/** Eine Monatszahl wie `8` oder `7,5` – ohne unnötige Null hinter dem Komma. */
export function zahlKurz(wert: number): string {
  return Number.isInteger(wert)
    ? String(wert)
    : wert.toFixed(1).replace(".", ",");
}

/**
 * Bis wann der Auftragsbestand reicht, als Monatsangabe.
 *
 * `null`, wenn es keinen Durchschnittsumsatz gibt – dann wäre jede Angabe erfunden.
 */
export function reichtBis(
  abMonat: string,
  monate: number | null,
): string | null {
  if (monate === null || monate <= 0) return null;
  const [jahr, nummer] = abMonat.split("-").map(Number);
  if (!jahr || !nummer) return null;
  const gesamt = nummer - 1 + Math.floor(monate);
  const ziel = `${jahr + Math.floor(gesamt / 12)}-${String((gesamt % 12) + 1).padStart(2, "0")}`;
  return monatText(ziel);
}

/**
 * Kurztext zur Fixkostendeckung, z. B. `117 % · Break-even bei 522 T€ Monatsumsatz`.
 *
 * Ohne Marge kein Break-even: eine Division durch eine Marge von null ergäbe eine unendliche
 * Umsatzschwelle, und die auszuweisen hülfe niemandem.
 */
export function deckungZusatz(
  breakEvenCent: number | null,
  margePromille: number | null,
): string {
  if (breakEvenCent === null || margePromille === null) {
    return "Ohne Marge lässt sich kein Break-even rechnen.";
  }
  return `Break-even bei ${euroKurz(breakEvenCent)} Monatsumsatz (Marge ${prozent(margePromille, 1, true).replace("+", "")})`;
}
