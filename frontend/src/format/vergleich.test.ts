import { describe, expect, it } from "vitest";
import { ohneUmlaute, passtZurSuche, vergleichsform } from "./vergleich";

describe("ohneUmlaute", () => {
  it("löst deutsche Umlaute auf", () => {
    expect(ohneUmlaute("Pöllath")).toBe("poellath");
    expect(ohneUmlaute("Hößl")).toBe("hoessl");
    expect(ohneUmlaute("Vohenstrauß")).toBe("vohenstrauss");
    expect(ohneUmlaute("Püllersreuth")).toBe("puellersreuth");
  });

  it("entfernt Akzente", () => {
    expect(ohneUmlaute("Nicolella café")).toBe("nicolella cafe");
  });
});

describe("vergleichsform", () => {
  it("wirft Satzzeichen und Klammerzusätze weg", () => {
    expect(vergleichsform("Ertl, Vohenstrauß")).toBe("ertl vohenstrauss");
    expect(vergleichsform("Bethge, Speichersdorf (ip³ Ing.)")).toBe(
      "bethge speichersdorf",
    );
    expect(vergleichsform("TSV Waldershof e.V.")).toBe("tsv waldershof e v");
  });

  it("behält Ziffern", () => {
    expect(vergleichsform("Volksfestplatz Weiden 2")).toBe(
      "volksfestplatz weiden 2",
    );
  });
});

describe("passtZurSuche", () => {
  it("findet auch, wenn ohne Umlaute getippt wird", () => {
    // Der eigentliche Zweck: 530 Projekte, und niemand tippt „Pöllath" mit Umlaut.
    // Beide Schreibweisen müssen gehen – aufgelöst (oe) und ohne Punkte (o).
    expect(passtZurSuche("poellath", "Pöllath, Weiden")).toBe(true);
    expect(passtZurSuche("pollath", "Pöllath, Weiden")).toBe(true);
    expect(passtZurSuche("hoessl grafenwoehr", "Hößl, Grafenwöhr")).toBe(true);
    expect(passtZurSuche("hossl grafenwohr", "Hößl, Grafenwöhr")).toBe(true);
    expect(
      passtZurSuche("ertl vohenstrauss", "Ertl, Vohenstrauß", "Vohenstrauß"),
    ).toBe(true);
    expect(passtZurSuche("puellersreuth", "Hausner, Püllersreuth")).toBe(true);
    expect(passtZurSuche("pullersreuth", "Hausner, Püllersreuth")).toBe(true);
  });

  it("findet in beliebiger Reihenfolge", () => {
    expect(passtZurSuche("vohenstrauss ertl", "Ertl, Vohenstrauß")).toBe(true);
  });

  it("verlangt alle Wörter", () => {
    expect(passtZurSuche("ertl waldau", "Ertl, Vohenstrauß")).toBe(false);
  });

  it("sucht über mehrere Felder", () => {
    expect(
      passtZurSuche("guenther weiden", "Winter, Weiden", null, "Günther"),
    ).toBe(true);
  });

  it("leere Suche findet alles", () => {
    expect(passtZurSuche("", "irgendwas")).toBe(true);
    expect(passtZurSuche("   ", "irgendwas")).toBe(true);
  });

  it("übergeht leere Felder", () => {
    expect(passtZurSuche("ertl", "Ertl, Vohenstrauß", null, undefined)).toBe(
      true,
    );
  });
});
