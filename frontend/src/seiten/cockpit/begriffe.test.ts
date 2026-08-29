import { describe, expect, it } from "vitest";
import {
  deckungZusatz,
  maßstab,
  reichtBis,
  reichweiteZusatz,
  stufen,
  zahlKurz,
} from "./begriffe";

const NBSP = "\u00A0"; // geschütztes Leerzeichen vor der Einheit (CD-Regel)

describe("stufen", () => {
  it("baut den Wasserfall vom Umsatz zur Überdeckung", () => {
    const reihe = stufen(61_240_000, 43_890_000, 14_800_000);

    expect(reihe.map((s) => s.name)).toEqual([
      "Umsatz",
      "Material & Fremdleistung",
      "Deckungsbeitrag",
      "Fixkosten",
      "Über-/Unterdeckung",
    ]);
    const [, material, db, , deckung] = reihe;
    expect(material?.betrag).toBe(-43_890_000);
    expect(db?.betrag).toBe(17_350_000);
    expect(deckung?.betrag).toBe(2_550_000);
  });

  it("setzt Abzüge auf den Wert auf, bei dem sie enden", () => {
    // Der schwebende Teil: der Materialbalken hängt am Deckungsbeitrag, nicht am Nullpunkt.
    const [, material, , fixkosten] = stufen(100, 40, 30);
    expect(material?.basis).toBe(60);
    expect(fixkosten?.basis).toBe(30);
  });

  it("zeigt eine Unterdeckung als negative Summe", () => {
    const deckung = stufen(100, 40, 90).at(-1);
    expect(deckung?.betrag).toBe(-30);
    expect(deckung?.summe).toBe(true);
  });
});

describe("maßstab", () => {
  it("nimmt den größten Balken einschließlich seiner Basis", () => {
    expect(maßstab(stufen(100, 40, 30))).toBe(100);
  });

  it("wird ohne Zahlen nicht null", () => {
    // Sonst teilte die Seite bei einem leeren Monat durch null.
    expect(maßstab(stufen(0, 0, 0))).toBe(1);
  });
});

describe("zahlKurz", () => {
  it("lässt die Null hinter dem Komma weg", () => {
    expect(zahlKurz(8)).toBe("8");
    expect(zahlKurz(7.5)).toBe("7,5");
  });
});

describe("reichweiteZusatz", () => {
  it("nennt beide Antworten (Entscheidung 26)", () => {
    const text = reichweiteZusatz(486_000_000, 61_000_000, 5.7);
    expect(text).toContain("Bestand");
    expect(text).toContain("Ø-Umsatz");
    expect(text).toContain("deckt 5,7 Monate Fixkosten");
  });

  it("lässt weg, was nicht zu rechnen ist", () => {
    const text = reichweiteZusatz(486_000_000, 0, null);
    expect(text).not.toContain("Ø-Umsatz");
    expect(text).not.toContain("Fixkosten");
  });
});

describe("reichtBis", () => {
  it("rechnet Monate auf einen Monatsnamen um", () => {
    // Monatsname und Jahr trennt ein normales Leerzeichen; das geschützte gilt Zahl + Einheit.
    expect(reichtBis("2026-08", 8)).toBe("April 2027");
  });

  it("bleibt im selben Jahr, wenn es passt", () => {
    expect(reichtBis("2026-01", 2)).toBe("März 2026");
  });

  it("gibt ohne Reichweite nichts aus", () => {
    expect(reichtBis("2026-08", null)).toBeNull();
    expect(reichtBis("2026-08", 0)).toBeNull();
  });
});

describe("deckungZusatz", () => {
  it("nennt Break-even und Marge", () => {
    const text = deckungZusatz(52_200_000, 283);
    expect(text).toContain("Break-even");
    expect(text).toContain(`28,3${NBSP}%`);
    (expect(text).not.toContain("+"), "eine Marge ist keine Veränderung");
  });

  it("sagt es, wenn die Marge fehlt", () => {
    expect(deckungZusatz(null, null)).toContain("kein Break-even");
  });
});
