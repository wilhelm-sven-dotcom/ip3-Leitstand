/**
 * Entscheidungslogik der Zuordnungsmaske (PLAN §9).
 *
 * Ausgelagert aus der Seite, damit sie prüfbar ist: hier hängt daran, welcher Betrag an welchem
 * Projekt landet. Der Falschtreffer, den der Abgleich im Bestand produziert hat, war
 * „Nachtmann, Weiden" auf „Hubmann, Weiden" – 550.000 € am falschen Projekt. Deshalb entscheidet
 * hier ein Mensch, und deshalb ist diese Datei getestet.
 */

/** Eine Zuordnung, wie die Vorschau sie liefert. */
export type Zuordnung = {
  kundenteil: string;
  zeilen: number[];
  betrag_netto: number;
  art: string;
  offen: boolean;
  projekt_zeile?: number | null;
  vorschlaege: { projekt_zeile: number; kunde: string; guete: number }[];
};

/**
 * Entscheidung zu einem Kunden.
 *
 * `undefined` heißt „noch nicht entschieden", `null` heißt ausdrücklich „als eigenes Projekt
 * anlegen". Die Unterscheidung ist wesentlich: ohne sie wäre eine bewusste Entscheidung nicht
 * von einer vergessenen zu trennen, und die Maske würde die Übernahme zu früh freigeben.
 */
export type Entscheidungen = Record<string, number | null | undefined>;

/** Zuordnungen, die eine Entscheidung brauchen und noch keine haben. */
export function offene(
  zuordnungen: Zuordnung[],
  entscheidungen: Entscheidungen,
): Zuordnung[] {
  return zuordnungen.filter(
    (z) => z.offen && entscheidungen[z.kundenteil] === undefined,
  );
}

/** Summe der Beträge, über die noch nicht entschieden ist. */
export function betragOffen(
  zuordnungen: Zuordnung[],
  entscheidungen: Entscheidungen,
): number {
  return offene(zuordnungen, entscheidungen).reduce(
    (summe, z) => summe + z.betrag_netto,
    0,
  );
}

/** Ob übernommen werden darf. */
export function alleEntschieden(
  zuordnungen: Zuordnung[],
  entscheidungen: Entscheidungen,
): boolean {
  return offene(zuordnungen, entscheidungen).length === 0;
}

/**
 * Was an die Schnittstelle geht.
 *
 * Nur Kunden, die eine Entscheidung brauchten: für die exakt zugeordneten schickt die Maske
 * nichts mit. Ein Eintrag ohne Entscheidung wird weggelassen, statt als `null` zu gelten –
 * `null` bedeutet „eigenes Projekt anlegen" und wäre hier eine stille Falschaussage.
 */
export function fuerSchnittstelle(
  zuordnungen: Zuordnung[],
  entscheidungen: Entscheidungen,
): Record<string, number | null> {
  const ergebnis: Record<string, number | null> = {};
  for (const zuordnung of zuordnungen) {
    if (!zuordnung.offen) continue;
    const entscheidung = entscheidungen[zuordnung.kundenteil];
    if (entscheidung === undefined) continue;
    ergebnis[zuordnung.kundenteil] = entscheidung;
  }
  return ergebnis;
}

/** Zählwerk für die Fußzeile: entschieden von zu entscheiden. */
export function fortschritt(
  zuordnungen: Zuordnung[],
  entscheidungen: Entscheidungen,
): { entschieden: number; gesamt: number; automatisch: number } {
  const zuEntscheiden = zuordnungen.filter((z) => z.offen);
  return {
    entschieden:
      zuEntscheiden.length - offene(zuordnungen, entscheidungen).length,
    gesamt: zuEntscheiden.length,
    automatisch: zuordnungen.length - zuEntscheiden.length,
  };
}

/**
 * Vorbelegung der Maske.
 *
 * Bewusst leer: der beste Vorschlag wird **nicht** vorausgewählt. Eine Maske, die schon
 * ausgefüllt ist, wird durchgeklickt – dann wäre die Bestätigung wertlos, und genau sie ist der
 * Schutz gegen den Falschtreffer.
 */
export function leereEntscheidungen(): Entscheidungen {
  return {};
}
