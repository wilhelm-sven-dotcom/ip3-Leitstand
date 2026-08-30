/**
 * Wörter für die Unterlagenübersicht (PLAN §7 Phase 7).
 *
 * Hier steht, wie ein Ordnerbefund heißt und was die Zahlen darüber bedeuten. Getrennt von der
 * Komponente, damit sich beides ohne Browser prüfen lässt.
 */

/** Geschütztes Leerzeichen vor Einheiten (PLAN §11). */
const NBSP = " ";

export type Ordnerbefund = {
  gefunden: boolean;
  dateien: number;
  mehrdeutig_mit?: string | null;
  geprueft_am?: string | null;
};

export type Lage = {
  art: "neutral" | "warnung" | "fehler" | "erfolg";
  text: string;
};

/**
 * Wie der Ordner eines Projekts dasteht.
 *
 * Die drei Zustände führen zu drei verschiedenen Handgriffen und dürfen deshalb nicht in einer
 * Meldung zusammenfallen. „Nie geprüft" ist ausdrücklich **kein** Mangel: es ist nur nichts
 * bekannt, und eine Warnung dafür wäre nach zweimal Ansehen tot.
 */
export function ordnerlage(befund: Ordnerbefund): Lage {
  if (!befund.geprueft_am) {
    return { art: "neutral", text: "nie geprüft" };
  }
  if (befund.mehrdeutig_mit) {
    return { art: "warnung", text: "mehrdeutig" };
  }
  if (!befund.gefunden) {
    return { art: "fehler", text: "kein Ordner" };
  }
  if (befund.dateien === 0) {
    return { art: "warnung", text: "leer" };
  }
  return {
    art: "erfolg",
    text: `${befund.dateien}${NBSP}${befund.dateien === 1 ? "Datei" : "Dateien"}`,
  };
}

export type Uebersicht = {
  gesamt: number;
  ohne_ordner: number;
  unvollstaendig: number;
  mehrdeutig: number;
  nie_geprueft: number;
};

/**
 * Der Satz unter den Kennzahlen – im richtigen Numerus und mit dem nächsten Schritt.
 *
 * „1 Projekt hat" statt „1 Projekte haben": eine Meldung mit falschem Numerus liest sich wie
 * eine Maschinenausgabe und wird dann auch so behandelt.
 */
export function unterlagenZusatz(werte: Uebersicht): string {
  if (werte.gesamt === 0) {
    return "Noch kein Projekt sichtbar.";
  }
  if (werte.nie_geprueft === werte.gesamt) {
    return (
      "Für keines dieser Projekte lief der Scan bisher. Er läuft nachts, sobald in der " +
      "config.toml unter [pfade] ein Projektordner steht."
    );
  }

  const teile: string[] = [];
  if (werte.unvollstaendig > 0) {
    teile.push(
      werte.unvollstaendig === 1
        ? "1 Projektmappe ist unvollständig"
        : `${werte.unvollstaendig} Projektmappen sind unvollständig`,
    );
  }
  if (werte.ohne_ordner > 0) {
    teile.push(
      werte.ohne_ordner === 1
        ? "zu 1 Projekt wurde kein Ordner gefunden"
        : `zu ${werte.ohne_ordner} Projekten wurde kein Ordner gefunden`,
    );
  }
  if (werte.mehrdeutig > 0) {
    teile.push(
      werte.mehrdeutig === 1
        ? "1 Projekt hat zwei Ordner mit derselben Nummer"
        : `${werte.mehrdeutig} Projekte haben zwei Ordner mit derselben Nummer`,
    );
  }

  if (teile.length === 0) {
    return "Alle geprüften Projektmappen sind vollständig.";
  }
  const satz = teile.join(", ").replace(/,([^,]*)$/, " und$1");
  return (
    `${satz.charAt(0).toUpperCase()}${satz.slice(1)}. ` +
    "Ein fehlender Ordner ist fast immer ein Namensproblem – die Projektnummer muss im " +
    "Ordnernamen stehen."
  );
}
