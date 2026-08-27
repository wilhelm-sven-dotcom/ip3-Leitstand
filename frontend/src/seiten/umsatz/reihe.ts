/**
 * Rechenteile der Umsatzseite (PLAN §7 Phase 2).
 *
 * Getrennt von der Darstellung, weil sie sich so prüfen lassen: die Balkenreihe ist der Teil, in
 * dem sich ein Vorzeichen- oder Rundungsfehler am leichtesten versteckt und am spätesten auffällt.
 */

import { euroKurz, monat as monatText, monatKurz } from "@/format/formate";
import type { Monatswert } from "@/komponenten/MonthBars";

export type MonatAusApi = {
  monat: string;
  ist_netto: number;
  plan_netto: number;
  summe_netto: number;
  ist_anzahl: number;
  plan_anzahl: number;
};

/**
 * Monate der Schnittstelle in Balken übersetzen.
 *
 * Ist gefüllt, Plan als Kontur darüber – die Bildsprache aus `design/Komponenten.dc.html`. Die
 * Sprechblase trägt beide Beträge, weil die Höhe allein nur den Verlauf zeigt und nicht den Wert
 * (dafür ist die Tabelle darunter da).
 */
export function balkenreihe(
  monate: MonatAusApi[],
  heute: Date = new Date(),
): Monatswert[] {
  const laufend = `${heute.getFullYear()}-${String(heute.getMonth() + 1).padStart(2, "0")}`;
  return monate.map((m) => ({
    monat: m.monat,
    beschriftung: monatKurz(m.monat),
    betrag: m.ist_netto,
    planBetrag: m.plan_netto,
    aktuell: m.monat === laufend,
    titel: sprechblase(m),
  }));
}

/** Text der Sprechblase eines Monats – nur, was der Monat wirklich trägt. */
export function sprechblase(m: MonatAusApi): string {
  const teile: string[] = [monatText(m.monat)];
  if (m.ist_netto) teile.push(`Ist ${euroKurz(m.ist_netto)}`);
  if (m.plan_netto) teile.push(`Plan ${euroKurz(m.plan_netto)}`);
  if (!m.ist_netto && !m.plan_netto) teile.push("nichts geplant");
  return teile.join(" · ");
}

/**
 * Summe des Restjahres ab dem laufenden Monat.
 *
 * „Plan 2026" wäre missverständlich, solange die Hälfte des Jahres vorbei ist: was zählt, ist
 * das, was noch kommt. Für ein vergangenes Jahr ist das nichts, für ein künftiges alles.
 */
export function planRestjahr(
  monate: MonatAusApi[],
  jahr: number,
  heute: Date = new Date(),
): number {
  const laufendesJahr = heute.getFullYear();
  if (jahr < laufendesJahr) return 0;
  const ab = jahr > laufendesJahr ? 0 : heute.getMonth();
  return monate.slice(ab).reduce((summe, m) => summe + m.plan_netto, 0);
}

/**
 * Jahre der Auswahlliste: aus den Daten, dazu Vorjahr, laufendes und nächstes Jahr.
 *
 * Die Liste darf keine Sackgasse sein. In den Bestandsdaten steht nur 2026; wer im Dezember auf
 * das nächste Jahr schauen will, käme über eine Liste aus den Daten allein nicht hin.
 */
export function jahresauswahl(
  ausDenDaten: number[],
  gewaehlt: number,
  heute: Date = new Date(),
): number[] {
  const laufend = heute.getFullYear();
  return [
    ...new Set([...ausDenDaten, gewaehlt, laufend - 1, laufend, laufend + 1]),
  ].sort((a, b) => b - a);
}
