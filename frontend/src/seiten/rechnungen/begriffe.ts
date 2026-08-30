/**
 * Beschriftungen und Ableitungen der Fakturierung.
 *
 * Getrennt von den Komponenten, weil hier nur Text und Rechnung steht und beides sich ohne
 * Browser prüfen lässt (`begriffe.test.ts`). Die Fachbegriffe stehen an **einer** Stelle: sonst
 * heißt derselbe Beleg auf der Liste anders als im Detail.
 */

import { NBSP, euro } from "@/format/formate";
import type { BadgeZustand } from "@/komponenten/StatusBadge";

export const BELEGARTEN = [
  "ab",
  "abschlag",
  "schluss",
  "service",
  "gutschrift",
  "storno",
] as const;
export type Belegart = (typeof BELEGARTEN)[number];

export const BELEG_STATUS = [
  "entwurf",
  "festgeschrieben",
  "storniert",
] as const;
export type Belegstatus = (typeof BELEG_STATUS)[number];

export const ART_TEXT: Record<Belegart, string> = {
  ab: "Auftragsbestätigung",
  abschlag: "Abschlagsrechnung",
  schluss: "Schlussrechnung",
  service: "Servicerechnung",
  gutschrift: "Gutschrift",
  storno: "Stornorechnung",
};

/** Kurzform für die Liste – die volle Bezeichnung sprengt dort die Spalte. */
export const ART_KURZ: Record<Belegart, string> = {
  ab: "AB",
  abschlag: "Abschlag",
  schluss: "Schluss",
  service: "Service",
  gutschrift: "Gutschrift",
  storno: "Storno",
};

export const UST_TEXT: Record<string, string> = {
  "19": "19 % Regelsatz",
  "0": "0 % nach § 12 Abs. 3 UStG",
  "13b": "§ 13b UStG – Steuerschuldnerschaft des Leistungsempfängers",
  gemischt: "gemischt – Satz je Position",
};

/**
 * Belegstatus als Badge-Zustand.
 *
 * Der Leitstand kennt genau drei Belegstatus, das Designsystem acht Badge-Zustände. Die
 * Zuordnung steht hier, damit nicht jede Seite eine eigene Farbe für „festgeschrieben" wählt.
 */
export function badgeZustand(status: string): BadgeZustand {
  if (status === "festgeschrieben") return "festgeschrieben";
  if (status === "storniert") return "storniert";
  return "entwurf";
}

/**
 * Titel eines Belegs, wie er auch auf dem PDF steht.
 *
 * Ein Abschlag trägt seine laufende Nummer – „3. Abschlagsrechnung" wie in der bisherigen
 * Word-Vorlage.
 */
export function belegtitel(art: string, abschlagNr?: number | null): string {
  const bezeichnung = ART_TEXT[art as Belegart] ?? "Beleg";
  if (art === "abschlag" && abschlagNr) return `${abschlagNr}. ${bezeichnung}`;
  return bezeichnung;
}

/** Überschrift der Belegzeile: Nummer, sonst der Hinweis, dass sie noch fehlt. */
export function belegnummer(nummer: string | null | undefined): string {
  return nummer ?? "Entwurf";
}

/**
 * Menge einer Position in deutscher Schreibweise.
 *
 * Die Schnittstelle liefert sie als Dezimaltext mit drei Nachkommastellen (`"1.000"`, `"2.500"`),
 * weil die Spalte `Numeric(12,3)` ist. Ungefiltert angezeigt liest sich `1.000` auf deutsch als
 * **tausend** – im Rundgang stand so bei einer Menge von 1 die Zahl 1.000 in der Tabelle.
 * Deshalb: überflüssige Nullen weg, Dezimalkomma statt Punkt.
 */
export function mengeText(menge: string | number): string {
  const zahl = Number(menge);
  if (!Number.isFinite(zahl)) return String(menge);
  const gerundet = Math.round(zahl * 1000) / 1000;
  return gerundet.toLocaleString("de-DE", { maximumFractionDigits: 3 });
}

export type Satzanteil = { satz: number; netto: number; ust: number };

/**
 * Summenzeilen des Belegs, in der Reihenfolge, in der sie auf dem Papier stehen.
 *
 * Rein aus den Werten des Servers gebildet – **nichts wird hier nachgerechnet**. Ein zweiter
 * Rechenweg im Frontend würde bei Rundungen irgendwann von der Rechnung abweichen, und dann
 * zeigte der Bildschirm etwas anderes als das PDF.
 */
export function summenzeilen(beleg: {
  netto: number;
  ust: number;
  brutto: number;
  absetzung_netto: number;
  absetzung_ust: number;
  zahlbetrag: number;
  ust_details: Satzanteil[];
  art: string;
}): { beschriftung: string; betrag: number; hervorgehoben?: boolean }[] {
  const mehrere = beleg.ust_details.length > 1;
  const zeilen: {
    beschriftung: string;
    betrag: number;
    hervorgehoben?: boolean;
  }[] = [{ beschriftung: "Summe netto", betrag: beleg.netto }];
  for (const anteil of beleg.ust_details) {
    zeilen.push({
      beschriftung: mehrere
        ? `Umsatzsteuer ${satzText(anteil.satz)} auf ${euro(anteil.netto)}`
        : `Umsatzsteuer ${satzText(anteil.satz)}`,
      betrag: anteil.ust,
    });
  }
  const hatAbsetzung = beleg.absetzung_netto !== 0 || beleg.absetzung_ust !== 0;
  zeilen.push({
    beschriftung: hatAbsetzung
      ? "Gesamtbetrag brutto"
      : summenbezeichnung(beleg.art),
    betrag: beleg.brutto,
    hervorgehoben: !hatAbsetzung,
  });
  if (hatAbsetzung) {
    zeilen.push({
      beschriftung: "abzüglich Abschlagszahlungen netto",
      betrag: -beleg.absetzung_netto,
    });
    zeilen.push({
      beschriftung: "abzüglich darauf entfallende Umsatzsteuer",
      betrag: -beleg.absetzung_ust,
    });
    zeilen.push({
      beschriftung: summenbezeichnung(beleg.art),
      betrag: beleg.zahlbetrag,
      hervorgehoben: true,
    });
  }
  return zeilen;
}

export function summenbezeichnung(art: string): string {
  if (art === "ab") return "Auftragssumme brutto";
  if (art === "schluss") return "Restbetrag zur Zahlung";
  if (art === "gutschrift") return "Gutschriftsbetrag";
  if (art === "storno") return "Stornobetrag";
  return "Rechnungsbetrag brutto";
}

/**
 * Steuersatz aus Promille als Prozenttext: `190` → `19 %`.
 *
 * Eigene Funktion statt `prozent()` aus dem Formatmodul: das zeigt immer eine Nachkommastelle
 * („19,0 %"), auf einer Rechnung steht aber `19 %`. Das geschützte Leerzeichen kommt aus
 * derselben Konstante wie überall (PLAN §6.10).
 */
export function satzText(promille: number): string {
  const ganze = Math.trunc(promille / 10);
  const rest = promille % 10;
  return `${rest === 0 ? ganze : `${ganze},${rest}`}${NBSP}%`;
}

/**
 * Ob der Beleg noch bearbeitet werden darf, und wenn nicht: warum.
 *
 * Die Sperre selbst sitzt im Server und in der Datenbank (PLAN §6.4). Hier geht es nur darum,
 * dass die Oberfläche nicht Knöpfe anbietet, die zu einer Fehlermeldung führen.
 */
export function sperrgrund(status: string): string | null {
  if (status === "festgeschrieben") {
    return "Der Beleg ist festgeschrieben und damit unveränderbar. Eine Korrektur läuft über einen Storno oder eine Gutschrift.";
  }
  if (status === "storniert") {
    return "Der Beleg ist storniert. Für eine neue Abrechnung einen neuen Beleg erzeugen.";
  }
  return null;
}

/**
 * Deutsche Bezeichnungen der Projektunterlagen (Phase 7).
 *
 * Dieselbe Liste wie in `app/dienste/dokumente.py`. Der Datenbankschlüssel gehört nicht auf
 * den Bildschirm – dieselbe Lehre wie beim Projektstatus, der als `in_bau` dastand.
 */
export const UNTERLAGE_TEXT: Record<string, string> = {
  ab: "Auftragsbestätigung",
  abnahme: "Abnahmeprotokoll",
  anlagendoku: "Anlagendokumentation",
  konformitaet: "Konformitätserklärung",
  messkonzept: "Messkonzept",
  sonstig: "sonstige Unterlage",
};

export function unterlage(typ: string): string {
  return UNTERLAGE_TEXT[typ] ?? typ;
}

/**
 * Der Satz über fehlenden Pflichtunterlagen – im richtigen Numerus.
 *
 * „Im Projektordner fehlt das Abnahmeprotokoll." statt „1 Unterlagen fehlen": eine Meldung mit
 * falschem Numerus liest sich wie eine Maschinenausgabe und wird dann auch so behandelt.
 */
export function fehlendeUnterlagen(typen: string[]): string | null {
  if (typen.length === 0) return null;
  const namen = typen.map(unterlage);
  if (namen.length === 1) {
    return `Im Projektordner fehlt: ${namen[0]}.`;
  }
  return `Im Projektordner fehlen: ${namen.join(", ")}.`;
}
