import { describe, expect, it } from "vitest";
import { befundeKurz, kontrollsummenZeilen } from "./begriffe";

describe("kontrollsummenZeilen", () => {
  it("beschriftet die bekannten Schlüssel deutsch", () => {
    const zeilen = kontrollsummenZeilen({
      kontrollsummen: {
        monat: "2026-07",
        buchungen: 4,
        summe_cent: 1695000,
        projekte: 2,
      },
    });
    expect(zeilen).toEqual([
      { text: "Monat", wert: "2026-07" },
      { text: "Buchungen", wert: "4" },
      { text: "Summe", wert: "16.950,00 €" },
      { text: "Projekte", wert: "2" },
    ]);
  });

  it("zieht den Block 'geschrieben' mit dazu", () => {
    const zeilen = kontrollsummenZeilen({
      kontrollsummen: { buchungen: 4 },
      geschrieben: { zeilen: 2, ersetzte_zeilen: 0 },
    });
    expect(zeilen.map((z) => z.text)).toEqual([
      "Buchungen",
      "Zeilen",
      "Ersetzt",
    ]);
  });

  it("zeigt unbekannte Schlüssel mit rohem Namen, statt sie zu verschlucken", () => {
    const zeilen = kontrollsummenZeilen({ kontrollsummen: { etwas_neues: 7 } });
    expect(zeilen).toEqual([{ text: "etwas_neues", wert: "7" }]);
  });

  it("zeigt Listen als Aufzählung", () => {
    const zeilen = kontrollsummenZeilen({
      kontrollsummen: { monate: ["2026-06", "2026-07"] },
    });
    expect(zeilen[0]?.wert).toBe("2026-06, 2026-07");
  });

  it("zeigt eine leere Liste als Strich", () => {
    const zeilen = kontrollsummenZeilen({ kontrollsummen: { monate: [] } });
    expect(zeilen[0]?.wert).toBe("–");
  });

  it("zählt die Befunde", () => {
    const zeilen = kontrollsummenZeilen({
      kontrollsummen: { buchungen: 1 },
      befunde: [{ meldung: "a" }, { meldung: "b" }],
    });
    expect(zeilen.at(-1)).toEqual({ text: "Befunde", wert: "2" });
  });

  it("zeigt die Meldung eines gescheiterten Laufs", () => {
    const zeilen = kontrollsummenZeilen({
      meldung: "TimeTac ist nicht erreichbar",
    });
    expect(zeilen).toEqual([
      { text: "Meldung", wert: "TimeTac ist nicht erreichbar" },
    ]);
  });

  it("verträgt ein leeres Protokoll", () => {
    expect(kontrollsummenZeilen(null)).toEqual([]);
    expect(kontrollsummenZeilen({})).toEqual([]);
  });

  it("nennt denselben Schlüssel nur einmal", () => {
    const zeilen = kontrollsummenZeilen({
      kontrollsummen: { projekte: 2 },
      geschrieben: { projekte: 2, zeilen: 4 },
    });
    expect(zeilen.filter((z) => z.text === "Projekte")).toHaveLength(1);
  });
});

describe("befundeKurz", () => {
  const befund = (n: number) => ({
    datei: "kostentraeger_2026-07.csv",
    zeile: n,
    spalte: "betrag",
    meldung: "Kein lesbarer Betrag",
  });

  it("zeigt höchstens fünf und zählt den Rest", () => {
    const { sichtbar, weitere } = befundeKurz(
      [1, 2, 3, 4, 5, 6, 7].map(befund),
    );
    expect(sichtbar).toHaveLength(5);
    expect(weitere).toBe(2);
  });

  it("zeigt alle, wenn es wenige sind", () => {
    const { sichtbar, weitere } = befundeKurz([1, 2].map(befund));
    expect(sichtbar).toHaveLength(2);
    expect(weitere).toBe(0);
  });
});
