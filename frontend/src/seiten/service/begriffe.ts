/**
 * Beschriftungen für Anlagen und Fristen (PLAN §7 Phase 6).
 *
 * Wie in `seiten/projekte/begriffe.ts` und `seiten/cockpit/begriffe.ts`: die Schlüssel der API
 * sind technisch (`gewaehrleistung`, `ueberfaellig`), die Oberfläche spricht Deutsch. Getrennt
 * von den Komponenten, weil sich Text prüfen lässt und Text am ehesten falsch wird.
 */

import { datum } from "@/format/formate";

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
