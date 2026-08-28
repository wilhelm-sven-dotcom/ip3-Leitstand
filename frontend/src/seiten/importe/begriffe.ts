/**
 * Begriffe und Aufbereitung für die Importseite (PLAN §8).
 *
 * Reine Funktionen ohne React – deshalb prüfbar. Die Kontrollsummen kommen als offenes
 * JSON-Objekt aus dem Importprotokoll (`importlaeufe.ergebnis`); hier bekommen sie deutsche
 * Beschriftungen und eine feste Reihenfolge, damit zwei Läufe derselben Quelle vergleichbar
 * untereinander stehen.
 */

import { euro, zahl } from "@/format/formate";

export const LAUF_STATUS_TEXT: Record<string, string> = {
  laeuft: "läuft",
  erfolg: "Erfolg",
  warnung: "Mit Anmerkung",
  fehler: "Fehler",
};

export const QUELLE_TEXT: Record<string, string> = {
  datev: "DATEV-Kostenträger",
  timetac: "TimeTac-Stunden",
  kalkulation: "Kalkulationsblätter",
  migration: "Bestandsdaten",
};

/**
 * Beschriftung und Aufbereitung je Kontrollsummen-Schlüssel.
 *
 * Was hier nicht steht, wird trotzdem gezeigt – mit dem rohen Schlüssel. Einen unbekannten
 * Wert wegzulassen wäre die schlechtere Wahl: dann fehlte er stillschweigend, und niemand
 * käme darauf, im Protokoll nachzusehen.
 */
const BESCHRIFTUNG: Record<string, { text: string; art?: "geld" | "zahl" }> = {
  monat: { text: "Monat" },
  monate: { text: "Monate" },
  buchungen: { text: "Buchungen", art: "zahl" },
  summe_cent: { text: "Summe", art: "geld" },
  projekte: { text: "Projekte", art: "zahl" },
  konten: { text: "Konten", art: "zahl" },
  nicht_uebernommen: { text: "Nicht übernommen", art: "zahl" },
  blaetter: { text: "Blätter", art: "zahl" },
  uebernommen: { text: "Übernommen", art: "zahl" },
  positionen: { text: "Positionen", art: "zahl" },
  lagerpositionen: { text: "davon Lager", art: "zahl" },
  soll_gesamt_cent: { text: "Soll gesamt", art: "geld" },
  stunden: { text: "Stunden" },
  stundenzeilen: { text: "Stundenzeilen", art: "zahl" },
  kostenzeilen: { text: "Kostenzeilen", art: "zahl" },
  mitarbeiter: { text: "Mitarbeiter", art: "zahl" },
  herkunft: { text: "Herkunft" },
  datei: { text: "Datei" },
  zeilen: { text: "Zeilen", art: "zahl" },
  ersetzte_zeilen: { text: "Ersetzt", art: "zahl" },
};

export type Summenzeile = { text: string; wert: string };

function wertText(schluessel: string, wert: unknown): string {
  const eintrag = BESCHRIFTUNG[schluessel];
  if (Array.isArray(wert)) return wert.length === 0 ? "–" : wert.join(", ");
  if (wert === null || wert === undefined) return "–";
  if (eintrag?.art === "geld" && typeof wert === "number") return euro(wert);
  if (eintrag?.art === "zahl" && typeof wert === "number") return zahl(wert, 0);
  return String(wert);
}

/**
 * Die Kontrollsummen eines Importlaufs als beschriftete Zeilen.
 *
 * Verschachtelte Blöcke (`kontrollsummen`, `geschrieben`) werden flach gezogen: auf einer
 * Karte zählt, was ein Lauf bewirkt hat, nicht wie das JSON aufgebaut ist.
 */
export function kontrollsummenZeilen(
  ergebnis: Record<string, unknown> | null | undefined,
): Summenzeile[] {
  if (!ergebnis) return [];
  const zeilen: Summenzeile[] = [];
  const gesehen = new Set<string>();

  const aufnehmen = (block: unknown) => {
    if (!block || typeof block !== "object" || Array.isArray(block)) return;
    for (const [schluessel, wert] of Object.entries(
      block as Record<string, unknown>,
    )) {
      if (gesehen.has(schluessel)) continue;
      if (typeof wert === "object" && wert !== null && !Array.isArray(wert))
        continue;
      gesehen.add(schluessel);
      zeilen.push({
        text: BESCHRIFTUNG[schluessel]?.text ?? schluessel,
        wert: wertText(schluessel, wert),
      });
    }
  };

  aufnehmen(ergebnis.kontrollsummen);
  aufnehmen(ergebnis.geschrieben);

  const befunde = ergebnis.befunde;
  if (Array.isArray(befunde) && befunde.length > 0) {
    zeilen.push({ text: "Befunde", wert: zahl(befunde.length, 0) });
  }
  const meldung = ergebnis.meldung;
  if (typeof meldung === "string") {
    zeilen.push({ text: "Meldung", wert: meldung });
  }
  return zeilen;
}

/**
 * Die Befunde eines Laufs, gekürzt auf das, was auf eine Karte passt.
 *
 * Die vollständige Liste steht im Protokoll. Zwanzig Zeilen unter einer Karte liest niemand;
 * dass es mehr sind, muss aber dastehen.
 */
export function befundeKurz(
  befunde: { datei: string; zeile: number; spalte: string; meldung: string }[],
  grenze = 5,
): { sichtbar: typeof befunde; weitere: number } {
  return {
    sichtbar: befunde.slice(0, grenze),
    weitere: Math.max(0, befunde.length - grenze),
  };
}
