import { describe, expect, it } from "vitest";
import { ordnerlage, unterlagenZusatz } from "./begriffe";

describe("ordnerlage", () => {
  it("nie geprüft ist kein Mangel", () => {
    // Sonst stünde für jedes neue Projekt eine Warnung da, die niemand abstellen kann.
    const lage = ordnerlage({ gefunden: false, dateien: 0, geprueft_am: null });
    expect(lage.art).toBe("neutral");
    expect(lage.text).toBe("Nie geprüft");
  });

  it("kein Ordner ist der Fehlerfall", () => {
    const lage = ordnerlage({
      gefunden: false,
      dateien: 0,
      geprueft_am: "2026-08-30",
    });
    expect(lage.art).toBe("fehler");
    expect(lage.text).toBe("Kein Ordner");
  });

  it("mehrdeutig geht vor allem anderen", () => {
    // Zwei Ordner mit derselben Nummer: der Scan hat einen genommen und weiß nicht, ob den
    // richtigen. Das ist wichtiger als die Zahl der Dateien darin.
    const lage = ordnerlage({
      gefunden: true,
      dateien: 12,
      mehrdeutig_mit: "/pfad/26001 alt",
      geprueft_am: "2026-08-30",
    });
    expect(lage.art).toBe("warnung");
    expect(lage.text).toBe("Mehrdeutig");
  });

  it("ein leerer Ordner ist etwas anderes als kein Ordner", () => {
    const lage = ordnerlage({
      gefunden: true,
      dateien: 0,
      geprueft_am: "2026-08-30",
    });
    expect(lage.art).toBe("warnung");
    expect(lage.text).toBe("Leer");
  });

  it("zählt Dateien im richtigen Numerus", () => {
    expect(
      ordnerlage({ gefunden: true, dateien: 1, geprueft_am: "2026-08-30" })
        .text,
    ).toBe("1 Datei");
    expect(
      ordnerlage({ gefunden: true, dateien: 7, geprueft_am: "2026-08-30" })
        .text,
    ).toBe("7 Dateien");
  });

  it("setzt ein geschütztes Leerzeichen vor die Einheit", () => {
    expect(
      ordnerlage({ gefunden: true, dateien: 3, geprueft_am: "2026-08-30" })
        .text,
    ).toContain(" ");
  });
});

describe("unterlagenZusatz", () => {
  const leer = {
    gesamt: 0,
    ohne_ordner: 0,
    unvollstaendig: 0,
    mehrdeutig: 0,
    nie_geprueft: 0,
  };

  it("sagt es, wenn noch kein Projekt sichtbar ist", () => {
    expect(unterlagenZusatz(leer)).toBe("Noch kein Projekt sichtbar.");
  });

  it("nennt den nächsten Schritt, solange nie gescannt wurde", () => {
    const text = unterlagenZusatz({ ...leer, gesamt: 5, nie_geprueft: 5 });
    expect(text).toContain("config.toml");
    expect(text).toContain("[pfade]");
  });

  it("lobt nicht, sondern stellt fest", () => {
    expect(unterlagenZusatz({ ...leer, gesamt: 3 })).toBe(
      "Alle geprüften Projektmappen sind vollständig.",
    );
  });

  it("schreibt Einzahl im Singular", () => {
    // „1 Projektmappen sind unvollständig" liest sich wie eine Maschinenausgabe.
    const text = unterlagenZusatz({ ...leer, gesamt: 3, unvollstaendig: 1 });
    expect(text).toContain("1 Projektmappe ist unvollständig");
    expect(text).not.toContain("1 Projektmappen");
  });

  it("schreibt Mehrzahl im Plural", () => {
    const text = unterlagenZusatz({ ...leer, gesamt: 9, unvollstaendig: 4 });
    expect(text).toContain("4 Projektmappen sind unvollständig");
  });

  it("verbindet mehrere Befunde mit und", () => {
    const text = unterlagenZusatz({
      ...leer,
      gesamt: 20,
      unvollstaendig: 2,
      ohne_ordner: 3,
      mehrdeutig: 1,
    });
    expect(text).toContain("2 Projektmappen sind unvollständig");
    expect(text).toContain("zu 3 Projekten wurde kein Ordner gefunden");
    expect(text).toContain("und 1 Projekt hat zwei Ordner");
    // Nur ein „und", der Rest bleibt Komma.
    expect(text.match(/ und /g)).toHaveLength(1);
  });

  it("beginnt den Satz groß", () => {
    const text = unterlagenZusatz({ ...leer, gesamt: 4, ohne_ordner: 2 });
    expect(text.charAt(0)).toBe("Z");
  });
});
