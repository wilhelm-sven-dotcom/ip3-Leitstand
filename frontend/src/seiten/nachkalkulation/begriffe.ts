/**
 * Begriffe und Rechenteile der Nachkalkulation (PLAN §7 Phase 4, §11).
 *
 * Alles hier ist reine Funktion ohne React – deshalb prüfbar, und deshalb liegt es getrennt.
 * Die Zahlen selbst kommen fertig vom Server (`app/dienste/nachkalkulation.py`); hier steht nur,
 * wie sie heißen und wie sie aussehen.
 *
 * **Kein Ampelgrün.** Das Corporate Design verbietet Grün ausdrücklich („bewusst ohne
 * Ampelgrün", PLAN §11). Die drei Zustände erscheinen deshalb in den Markenfarben: ip³ Blau für
 * „im Soll", Akzent-Rot als Kontur für „knapp", Akzent-Rot gefüllt für „unter Soll". Ohne
 * Sollmarge bleibt das Feld grau – geraten wird nicht.
 */

import { MINUS, NBSP, anteil, euro, zahl } from "@/format/formate";

export type Ampel = "im_soll" | "knapp" | "unter_soll" | "ohne_soll";

export const AMPEL_TEXT: Record<Ampel, string> = {
  im_soll: "Im Soll",
  knapp: "Knapp",
  unter_soll: "Unter Soll",
  ohne_soll: "Ohne Sollmarge",
};

/** Erklärt, was der Zustand bedeutet – als Titel am Element, nicht als Fließtext. */
export function ampelTitel(
  ampel: Ampel,
  margeSollPromille: number | null | undefined,
  abweichungPromille: number | null | undefined,
): string {
  if (ampel === "ohne_soll") {
    return "Für dieses Projekt gibt es keine Sollmarge aus dem Kalkulationsblatt.";
  }
  const soll = anteil((margeSollPromille ?? 0) / 10);
  if (abweichungPromille === null || abweichungPromille === undefined)
    return `Soll ${soll}`;
  const abstand = anteil(Math.abs(abweichungPromille) / 10);
  if (abweichungPromille >= 0)
    return `${abstand} über der Sollmarge von ${soll}`;
  return `${abstand} unter der Sollmarge von ${soll}`;
}

/** Die Quellen des Ist, in der Reihenfolge, in der sie im Balken stehen. */
export const IST_QUELLEN = [
  {
    schluessel: "ist_datev",
    text: "DATEV",
    erklaerung: "Projektbestelltes Material und Fremdleistungen",
  },
  {
    schluessel: "ist_stueckliste",
    text: "Lager",
    erklaerung: "Bewertete Lagerentnahmen aus der Stückliste",
  },
  {
    schluessel: "ist_timetac",
    text: "Stunden",
    erklaerung: "Eigenleistung: TimeTac-Stunden mal Verrechnungssatz",
  },
] as const;

/**
 * Marge als Text: `+51,4 %`. Ohne Erlös gibt es keine Marge, und dann steht dort auch nichts.
 *
 * Bewusst mit Vorzeichen: eine negative Marge ist die Zahl, wegen der man hinsieht.
 */
export function margeText(promille: number | null | undefined): string {
  if (promille === null || promille === undefined) return "–";
  const wert = promille / 10;
  const vorzeichen = wert > 0 ? "+" : wert < 0 ? MINUS : "";
  return `${vorzeichen}${zahl(Math.abs(wert), 1)}${NBSP}%`;
}

/** Abweichung zur Sollmarge in Prozentpunkten: `−4,0 %-Pkt.` */
export function abweichungText(promille: number | null | undefined): string {
  if (promille === null || promille === undefined) return "–";
  const wert = promille / 10;
  const vorzeichen = wert > 0 ? "+" : wert < 0 ? MINUS : "";
  return `${vorzeichen}${zahl(Math.abs(wert), 1)}${NBSP}%-Pkt.`;
}

/** Stundenzahl mit Einheit: `120,50 h`. */
export function stundenText(wert: number | string | null | undefined): string {
  if (wert === null || wert === undefined || wert === "") return "–";
  const zahlenwert = typeof wert === "string" ? Number(wert) : wert;
  if (Number.isNaN(zahlenwert)) return "–";
  return `${zahl(zahlenwert, 2)}${NBSP}h`;
}

export type Istanteil = {
  schluessel: string;
  text: string;
  erklaerung: string;
  betrag: number;
  /** Anteil am Ist in Prozent, für die Balkenbreite. */
  anteil: number;
};

/**
 * Die drei Ist-Quellen als Balkenanteile.
 *
 * Ist der Ist null, sind alle Anteile null – kein Balken, keine Division durch null. Quellen
 * ohne Betrag bleiben in der Liste: dass aus einer Quelle nichts kam, ist eine Auskunft
 * (PLAN §6.5).
 */
export function istAnteile(zeile: {
  ist_datev: number;
  ist_stueckliste: number;
  ist_timetac: number;
  ist_gesamt: number;
}): Istanteil[] {
  return IST_QUELLEN.map((quelle) => {
    const betrag = zeile[quelle.schluessel as keyof typeof zeile] as number;
    return {
      schluessel: quelle.schluessel,
      text: quelle.text,
      erklaerung: quelle.erklaerung,
      betrag,
      anteil: zeile.ist_gesamt === 0 ? 0 : (betrag / zeile.ist_gesamt) * 100,
    };
  });
}

export type Summenzeile = {
  text: string;
  wert: string;
  stark?: boolean;
  hinweis?: string;
};

/**
 * Der Rechenweg als Zeilen: Erlös minus Ist ergibt die Marge.
 *
 * Vier Zeilen statt einer Kachel, weil die Marge sonst eine Behauptung wäre. Wer sie in Frage
 * stellt, soll den Weg dorthin ohne Nachfrage sehen können.
 */
export function rechenweg(zeile: {
  ab_wert_netto: number | null;
  nachtraege_netto: number;
  erloes_netto: number | null;
  ist_gesamt: number;
  marge_netto: number | null;
  marge_promille: number | null;
}): Summenzeile[] {
  const zeilen: Summenzeile[] = [
    { text: "Auftragswert", wert: euro(zeile.ab_wert_netto) },
  ];
  if (zeile.nachtraege_netto !== 0) {
    zeilen.push({
      text: "Beauftragte Nachträge",
      wert: euro(zeile.nachtraege_netto),
    });
  }
  zeilen.push({ text: "Erlös", wert: euro(zeile.erloes_netto), stark: true });
  zeilen.push({
    text: "Ist-Kosten",
    wert: `${MINUS}${euro(zeile.ist_gesamt, false)}${NBSP}€`,
  });
  zeilen.push({
    text: "Marge",
    wert:
      zeile.marge_netto === null
        ? "–"
        : `${euro(zeile.marge_netto)} (${margeText(zeile.marge_promille)})`,
    stark: true,
    hinweis:
      zeile.erloes_netto === null
        ? "Ohne Auftragswert lässt sich keine Marge rechnen."
        : undefined,
  });
  return zeilen;
}

/**
 * Kurzform der Hinweise für die Übersichtsliste.
 *
 * In der Tabelle ist kein Platz für drei Sätze; der volle Text steht im Projekt. Die Reihenfolge
 * bleibt die des Servers – dort ist sie nach Gewicht sortiert.
 */
export const HINWEIS_KURZ: Record<string, string> = {
  ohne_auftragswert: "Kein Auftragswert",
  ohne_kalkulation: "Kein Kalkulationsblatt",
  doppelbelastung_verdacht: "Material doppelt?",
  material_fehlt: "Material fehlt",
  mengen_ist_offen: "Mengen offen",
};

export function hinweisKurz(code: string): string {
  return HINWEIS_KURZ[code] ?? code;
}

/** Projektname für Listen: Bezeichnung, sonst der Kunde. */
export function projektname(zeile: {
  bezeichnung: string | null;
  kunde: string;
}): string {
  return zeile.bezeichnung?.trim() || zeile.kunde;
}
