/**
 * Normalisierung für Suche und Vergleich.
 *
 * Gegenstück zu ``vergleichsform`` in ``backend/app/migration/vokabular.py`` – beide Seiten
 * müssen gleich vergleichen, sonst findet die Suche etwas anderes als der Abgleich.
 *
 * Der Grund ist praktisch: in der Oberpfalz heißen Kunden Pöllath, Hößl, Vohenstrauß und
 * Püllersreuth. Wer bei 530 Projekten sucht, tippt „poellath" oder „hossl" – eine Suche, die
 * darauf nichts findet, ist keine Suche. Umlaute werden deshalb aufgelöst, nicht nur
 * kleingeschrieben.
 */

const ERSETZUNGEN: [RegExp, string][] = [
  [/ä/g, "ae"],
  [/ö/g, "oe"],
  [/ü/g, "ue"],
  [/ß/g, "ss"],
];

/** Umlaute und ß auflösen, Akzente entfernen, kleinschreiben. */
export function ohneUmlaute(text: string): string {
  let ergebnis = text.toLowerCase();
  for (const [muster, ersatz] of ERSETZUNGEN) {
    ergebnis = ergebnis.replace(muster, ersatz);
  }
  // Zerlegen und die Akzentzeichen wegwerfen – fängt é, ç und Ähnliches ab.
  return ergebnis.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

/**
 * Vergleichsform: nur Kleinbuchstaben, Ziffern und einfache Leerzeichen.
 *
 * Klammerzusätze fallen weg, weil die Teamliste dort Hinweise wie „(ip³ Ing.)" führt, die in
 * der Auftragsliste fehlen.
 */
export function vergleichsform(text: string): string {
  return ohneUmlaute(text.replace(/\(.*?\)/g, " "))
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Zweite Schreibweise: Umlaut ohne Punkte, also ö → o statt ö → oe.
 *
 * Beim Tippen fällt der Umlaut häufiger ganz weg, als dass er aufgelöst wird: „Pollath",
 * „Hossl", „Grafenwohr". Die Suche prüft deshalb beide Formen. Der Abgleich der beiden
 * Bestandsdateien im Backend tut das **nicht** – dort geht es um zwei gepflegte Datensätze, und
 * eine lockerere Regel würde dort Falschtreffer erzeugen. Hier tippt ein Mensch, das ist ein
 * anderer Fall.
 */
function ohnePunkte(text: string): string {
  return text
    .toLowerCase()
    .replace(/ä/g, "a")
    .replace(/ö/g, "o")
    .replace(/ü/g, "u")
    .replace(/ß/g, "ss")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Ob alle Wörter der Suche in den Feldern vorkommen – in beliebiger Reihenfolge.
 *
 * Wortweise und nicht als ganze Zeichenfolge: „ertl vohenstrauss" soll den Kunden finden, auch
 * wenn zwischen Name und Ort ein Komma steht. Die Reihenfolge ist frei, weil niemand weiß, ob
 * Name oder Ort zuerst notiert wurde. Geprüft wird gegen beide Umlautschreibweisen, damit
 * „poellath" und „pollath" denselben Kunden finden.
 */
export function passtZurSuche(
  suche: string,
  ...felder: (string | null | undefined)[]
): boolean {
  const zusammen = felder.filter(Boolean).join(" ");
  const formen = [vergleichsform(zusammen), ohnePunkte(zusammen)];

  for (const normalisieren of [vergleichsform, ohnePunkte]) {
    const worte = normalisieren(suche).split(" ").filter(Boolean);
    if (worte.length === 0) return true;
    if (formen.some((text) => worte.every((wort) => text.includes(wort))))
      return true;
  }
  return false;
}
