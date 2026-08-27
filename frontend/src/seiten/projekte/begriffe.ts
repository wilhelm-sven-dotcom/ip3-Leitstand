/**
 * Beschriftungen und Gruppierung für Projekte (design/Projektliste.dc.html, PLAN §5).
 *
 * Die Schnittstelle liefert Schlüssel (`aufdach_speicher`, `montage_uk`), die Oberfläche zeigt
 * Text („Aufdach + Speicher", „Montage Unterkonstruktion"). Die Übersetzung steht hier an einer
 * Stelle statt in jeder Maske: Liste, Detail, Filter und Zeitleiste beschriften dieselbe Sache
 * sonst unterschiedlich.
 *
 * Die Reihenfolge der Meilensteine ist die des Bauablaufs, nicht die alphabetische – sie folgt
 * `MEILENSTEIN_TYPEN` im Backend, das seinerseits der Teamliste folgt (PLAN §9).
 */

export const PROJEKT_STATUS = [
  "angebot",
  "beauftragt",
  "in_bau",
  "abgeschlossen",
  "storniert",
] as const;

export type ProjektStatus = (typeof PROJEKT_STATUS)[number];

export const STATUS_TEXT: Record<ProjektStatus, string> = {
  angebot: "Angebot",
  beauftragt: "Beauftragt",
  in_bau: "In Bau",
  abgeschlossen: "Abgeschlossen",
  storniert: "Storniert",
};

export const ANLAGENARTEN = [
  "aufdach",
  "aufdach_speicher",
  "freiflaeche",
  "speicher",
  "ladestation",
  "sonstig",
] as const;

export type Anlagenart = (typeof ANLAGENARTEN)[number];

/** „Gewerk" im Mockup, „Anlagenart" im Datenmodell – die Auswahl ist dieselbe. */
export const ANLAGENART_TEXT: Record<Anlagenart, string> = {
  aufdach: "Aufdach",
  aufdach_speicher: "Aufdach + Speicher",
  freiflaeche: "Freifläche",
  speicher: "Speicher (BESS)",
  ladestation: "Ladestation",
  sonstig: "Sonstige",
};

export const UST_TEXT: Record<string, string> = {
  "19": "19 % (Regelfall)",
  "0": "0 % (steuerfrei)",
  "13b": "§ 13b UStG (Bauleistung)",
  gemischt: "gemischt",
};

/** Ein Abschnitt der Zeitleiste im Projektdetail. */
export type Meilensteingruppe = {
  titel: string;
  erlaeuterung: string;
  typen: readonly string[];
};

export const MEILENSTEIN_TEXT: Record<string, string> = {
  uebergabetermin: "Übergabetermin",
  freigabe_planung: "Freigabe Planung",
  plan_erstellt: "Plan erstellt",
  anmeldung_nb: "Anmeldung Netzbetreiber",
  mastr: "Marktstammdatenregister",
  fertigmeldung: "Fertigmeldung",
  zaehler: "Zähler gesetzt",
  abnahme: "Abnahme",
  montage_uk: "Montage Unterkonstruktion",
  montage_elektro: "Montage Elektro",
  zaehlerschrank: "Zählerschrank",
  lieferung_uk: "Lieferung Unterkonstruktion",
  lieferung_wr_pv: "Lieferung Wechselrichter PV",
  lieferung_wr_speicher: "Lieferung Wechselrichter Speicher",
  lieferung_speicher: "Lieferung Speicher",
  lieferung_wallbox: "Lieferung Wallbox",
  montage: "Montage (gesamt)",
  lieferung: "Lieferung (gesamt)",
  inbetriebnahme: "Inbetriebnahme",
};

export const MEILENSTEINGRUPPEN: Meilensteingruppe[] = [
  {
    titel: "Projektablauf",
    erlaeuterung:
      "Statusspalten der Teamliste – von der Übergabe bis zur Abnahme.",
    typen: [
      "uebergabetermin",
      "freigabe_planung",
      "plan_erstellt",
      "anmeldung_nb",
      "mastr",
      "fertigmeldung",
      "zaehler",
      "abnahme",
    ],
  },
  {
    titel: "Liefer- und Montagetermine",
    erlaeuterung:
      "Terminspalten der Teamliste. Sie lösen die Abschlagsvorschläge aus.",
    typen: [
      "lieferung_uk",
      "montage_uk",
      "lieferung_wr_pv",
      "lieferung_wr_speicher",
      "lieferung_speicher",
      "lieferung_wallbox",
      "montage_elektro",
      "zaehlerschrank",
    ],
  },
  {
    titel: "Zusammenfassende Schritte",
    erlaeuterung:
      "Für Projekte, die von Hand gepflegt werden und keine Zeilen der Teamliste haben.",
    typen: ["lieferung", "montage", "inbetriebnahme"],
  },
];

/** Alle Typen in der Reihenfolge des Bauablaufs – dieselbe wie im Backend. */
export const MEILENSTEIN_TYPEN: string[] = MEILENSTEINGRUPPEN.flatMap((g) => [
  ...g.typen,
]);

export function meilensteinText(typ: string): string {
  // Ein unbekannter Typ darf keine leere Zeile ergeben: dann steht wenigstens der Schlüssel da.
  return MEILENSTEIN_TEXT[typ] ?? typ;
}

/** Die drei Zustände aus Migration 0003: unbekannt, ausdrücklich offen, erledigt. */
export type Erledigt = null | false | true;

export const ERLEDIGT_TEXT: { wert: Erledigt; text: string }[] = [
  { wert: null, text: "keine Angabe" },
  { wert: false, text: "offen" },
  { wert: true, text: "erledigt" },
];

/**
 * Kurzbeschreibung eines Projekts für Kopfzeilen: Ort, Anlagenart, Leistung, Projektleitung.
 *
 * Leere Angaben fallen weg, statt als „–" mitgeschleppt zu werden – bei den migrierten
 * Projekten fehlt oft die Hälfte, und eine Kopfzeile aus vier Gedankenstrichen sagt nichts.
 */
export function kopfzeile(teile: (string | null | undefined)[]): string {
  return teile.filter((t): t is string => Boolean(t && t.trim())).join(" · ");
}

/**
 * Anzeigename eines Projekts.
 *
 * Die 530 migrierten Projekte haben keine Bezeichnung – die Bestandsdateien führen keine.
 * Dann steht der Kundenname dort, so wie es die zweite Beispielzeile des Mockups zeigt.
 */
export function projektname(
  bezeichnung: string | null | undefined,
  kunde: string,
): string {
  return bezeichnung?.trim() || kunde;
}
