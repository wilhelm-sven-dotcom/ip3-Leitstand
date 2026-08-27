/**
 * Deutsche Zahlen-, Datums- und Einheitenformate (PLAN §6.10, §11).
 *
 * Zwei Dinge, die man hier leicht falsch macht:
 *
 * 1. **Beträge kommen als ganze Cent aus der Schnittstelle.** Wer sie mit `/ 100` in
 *    Gleitkomma umrechnet und dann rundet, bekommt bei großen Beträgen Abweichungen im
 *    letzten Cent. Deshalb wird hier auf ganzen Zahlen getrennt und der Rest angehängt.
 *
 * 2. **Vor der Einheit steht ein geschütztes Leerzeichen** (U+00A0), damit „1.250,00 €"
 *    nicht über einen Zeilenumbruch auseinandergerissen wird. Es ist unsichtbar, aber
 *    fachlich verlangt – dasselbe gilt für kWp, kWh und Prozent.
 */

/** Geschütztes Leerzeichen. Als Konstante, damit es im Quelltext sichtbar bleibt. */
export const NBSP = " ";

/** Minuszeichen (U+2212), nicht der Bindestrich: es steht auf der Höhe der Ziffern. */
export const MINUS = "−";

const zahlenformat = (min: number, max: number) =>
  new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });

/**
 * Cent-Betrag als Euro-Text: `125000` → `1.250,00 €`.
 *
 * @param mitZeichen ob das Währungszeichen angehängt wird
 */
export function euro(
  cent: number | null | undefined,
  mitZeichen = true,
): string {
  if (cent === null || cent === undefined) return "–";

  const negativ = cent < 0;
  const absolut = Math.abs(Math.trunc(cent));
  const ganze = Math.floor(absolut / 100);
  const rest = absolut % 100;

  const text = `${zahlenformat(0, 0).format(ganze)},${String(rest).padStart(2, "0")}`;
  const mitVorzeichen = negativ ? `${MINUS}${text}` : text;
  return mitZeichen ? `${mitVorzeichen}${NBSP}€` : mitVorzeichen;
}

/**
 * Große Beträge verkürzt: ab einer Million als `7,94 Mio. €` (PLAN §11).
 *
 * Für Kennzahlen und Diagrammbeschriftungen. In Tabellen und auf Belegen steht immer der
 * vollständige Betrag – dort zählt jeder Cent.
 */
export function euroKurz(cent: number | null | undefined): string {
  if (cent === null || cent === undefined) return "–";
  const euroWert = cent / 100;
  const absolut = Math.abs(euroWert);
  const vorzeichen = euroWert < 0 ? MINUS : "";

  if (absolut >= 1_000_000) {
    return `${vorzeichen}${zahlenformat(0, 2).format(absolut / 1_000_000)}${NBSP}Mio.${NBSP}€`;
  }
  if (absolut >= 10_000) {
    return `${vorzeichen}${zahlenformat(0, 0).format(absolut / 1000)}${NBSP}T€`;
  }
  return euro(cent);
}

/**
 * Eingegebener Euro-Betrag als ganze Cent: `"1.250,50"` → `125050`.
 *
 * Gegenstück zu :func:`euro`. Beträge sind im ganzen System Integer in Cent (CLAUDE.md
 * Regel 3), also muss die Umrechnung genau an einer Stelle stehen – in zwei Masken
 * nachgebaut wäre eine davon irgendwann falsch.
 *
 * Erlaubt sind deutsche und englische Schreibweise. Der Tausenderpunkt wird entfernt, das Komma
 * zum Dezimaltrennzeichen. `null` heißt „keine Zahl erkannt"; der Aufrufer entscheidet, ob das
 * ein leeres Feld (in Ordnung) oder eine Fehleingabe ist – hier wird **nicht** stillschweigend
 * eine Null daraus, denn 0,00 € ist eine Aussage und ein leeres Feld keine.
 */
export function centAusText(wert: string | null | undefined): number | null {
  if (wert === null || wert === undefined) return null;
  // Das Minuszeichen aus `zahl()` (U+2212) mit einlesen: sonst scheitert genau der Weg
  // „anzeigen, bearbeiten, speichern" bei negativen Beträgen.
  const roh = wert.trim().replace(/\s|€/g, "").replace(MINUS, "-");
  if (!roh) return null;

  // Deutsches Format: Punkt trennt Tausender, Komma die Dezimalstellen. Fehlt das Komma, wird
  // der Punkt als Dezimaltrennzeichen gelesen ('1250.50') – so tippen manche.
  const deutsch = roh.includes(",");
  const bereinigt = deutsch
    ? roh.replace(/\./g, "").replace(",", ".")
    : roh.replace(/,/g, "");
  const treffer = /^(-?)(\d*)(?:\.(\d*))?$/.exec(bereinigt);
  if (!treffer || (!treffer[2] && !treffer[3])) return null;

  // Gerechnet wird auf ganzen Zahlen, nicht über `Number(x) * 100`: `0,145 * 100` ergibt in
  // Gleitkomma 14,499999999999998 und würde auf 14 statt auf 15 Cent gerundet. Bei Geld ist
  // das der Fehler, den PLAN §6.11 ausdrücklich ausschließt.
  const vorzeichen = treffer[1] === "-" ? -1 : 1;
  const euroTeil = treffer[2] || "0";
  const nachkomma = (treffer[3] ?? "").padEnd(3, "0");
  const cent = Number(euroTeil) * 100 + Number(nachkomma.slice(0, 2));
  // Kaufmännisch runden: ab einem halben Cent aufwärts.
  const aufrunden = Number(nachkomma[2]) >= 5 ? 1 : 0;
  return vorzeichen * (cent + aufrunden);
}

/**
 * Zahl mit deutschen Trennzeichen: `5695` → `5.695`.
 *
 * `Intl.NumberFormat` liefert für negative Werte den ASCII-Bindestrich; hier wird daraus das
 * Minuszeichen (U+2212). Der Bindestrich sitzt tiefer und ist kürzer als die Ziffern – in einer
 * Spalte mit Tabellenziffern fällt das auf. Die Ersetzung steht in dieser einen Funktion, damit
 * alle darauf aufbauenden Formate sie erben.
 */
export function zahl(
  wert: number | null | undefined,
  nachkommastellen = 0,
): string {
  if (wert === null || wert === undefined) return "–";
  return zahlenformat(nachkommastellen, nachkommastellen)
    .format(wert)
    .replace("-", MINUS);
}

/**
 * Zahl mit Einheit und geschütztem Leerzeichen: `5695, 'kWp'` → `5.695 kWp`.
 *
 * Fachschreibweisen: kWp, MWp, kWh, MWh, kW, MW, kVA (PLAN §11).
 */
export function mitEinheit(
  wert: number | null | undefined,
  einheit: string,
  nachkommastellen = 1,
): string {
  if (wert === null || wert === undefined) return "–";
  return `${zahl(wert, nachkommastellen)}${NBSP}${einheit}`;
}

/** Leistung in kWp, ab 1000 kWp in MWp: `5695` → `5,695 MWp`. */
export function leistung(kwp: number | null | undefined): string {
  if (kwp === null || kwp === undefined) return "–";
  if (Math.abs(kwp) >= 1000) return mitEinheit(kwp / 1000, "MWp", 3);
  return mitEinheit(kwp, "kWp", 1);
}

/** Speicherkapazität in kWh, ab 1000 kWh in MWh. */
export function kapazitaet(kwh: number | null | undefined): string {
  if (kwh === null || kwh === undefined) return "–";
  if (Math.abs(kwh) >= 1000) return mitEinheit(kwh / 1000, "MWh", 3);
  return mitEinheit(kwh, "kWh", 1);
}

/**
 * Prozentangabe: `18.5` → `18,5 %`.
 *
 * `promille` für Werte, die als Promille aus der Schnittstelle kommen (Steuersätze,
 * Sollmargen): `190` → `19,0 %`.
 */
export function prozent(
  wert: number | null | undefined,
  nachkommastellen = 1,
  promille = false,
): string {
  if (wert === null || wert === undefined) return "–";
  const anteil = promille ? wert / 10 : wert;
  const vorzeichen = anteil > 0 ? "+" : "";
  return `${vorzeichen}${zahl(anteil, nachkommastellen)}${NBSP}%`;
}

/** Prozentangabe ohne Pluszeichen – für Anteile, bei denen keine Veränderung gemeint ist. */
export function anteil(
  wert: number | null | undefined,
  nachkommastellen = 1,
): string {
  if (wert === null || wert === undefined) return "–";
  return `${zahl(wert, nachkommastellen)}${NBSP}%`;
}

/** Datum als `TT.MM.JJJJ`. Nimmt ein ISO-Datum oder ein Date. */
export function datum(wert: string | Date | null | undefined): string {
  if (!wert) return "–";
  const zeitpunkt = typeof wert === "string" ? new Date(wert) : wert;
  if (Number.isNaN(zeitpunkt.getTime())) return "–";
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(zeitpunkt);
}

/** Datum mit Uhrzeit: `27.08.2026, 14:30`. Zeitpunkte kommen in UTC und werden hier lokal. */
export function datumZeit(wert: string | Date | null | undefined): string {
  if (!wert) return "–";
  const zeitpunkt = typeof wert === "string" ? new Date(wert) : wert;
  if (Number.isNaN(zeitpunkt.getTime())) return "–";
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(zeitpunkt);
}

/** Wochentag und Datum: `Mittwoch, 27.08.2026` – für den Kopf der Startseite. */
export function wochentagDatum(wert: string | Date | null | undefined): string {
  if (!wert) return "–";
  const zeitpunkt = typeof wert === "string" ? new Date(wert) : wert;
  if (Number.isNaN(zeitpunkt.getTime())) return "–";
  const wochentag = new Intl.DateTimeFormat("de-DE", {
    weekday: "long",
  }).format(zeitpunkt);
  return `${wochentag}, ${datum(zeitpunkt)}`;
}

const MONATSNAMEN = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

/** Monat `'2026-09'` → `September 2026`. */
export function monat(wert: string | null | undefined): string {
  if (!wert || wert.length !== 7) return "unterminiert";
  const jahr = wert.slice(0, 4);
  const nummer = Number(wert.slice(5, 7));
  const name = MONATSNAMEN[nummer - 1];
  if (!name) return wert;
  return `${name} ${jahr}`;
}

/** Monat `'2026-09'` → `Sep` – für Diagrammbeschriftungen. */
export function monatKurz(wert: string | null | undefined): string {
  if (!wert || wert.length !== 7) return "–";
  const name = MONATSNAMEN[Number(wert.slice(5, 7)) - 1];
  return name ? name.slice(0, 3) : "–";
}

/**
 * Begrüßung nach Tageszeit – wie im Startseiten-Mockup („Guten Morgen, Sven").
 *
 * Grenzen bewusst großzügig: um 11:30 sagt niemand mehr „Guten Morgen", um 17:00 noch
 * nicht „Guten Abend".
 */
export function begruessung(vorname: string, jetzt: Date = new Date()): string {
  const stunde = jetzt.getHours();
  if (stunde < 11) return `Guten Morgen, ${vorname}.`;
  if (stunde < 18) return `Guten Tag, ${vorname}.`;
  return `Guten Abend, ${vorname}.`;
}

/** Vorname aus einem vollständigen Namen. */
export function vorname(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/**
 * Anzahl mit passendem Substantiv: `1, 'Projekt', 'Projekte'` → `1 Projekt`.
 *
 * Deutsche Oberflächen brauchen das oft; ein „1 Projekte" fällt sofort auf.
 */
export function anzahl(
  wert: number,
  einzahl: string,
  mehrzahl: string,
): string {
  return `${zahl(wert)} ${wert === 1 ? einzahl : mehrzahl}`;
}
