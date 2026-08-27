import { describe, expect, it } from "vitest";
import { NBSP } from "@/format/formate";
import {
  balkenreihe,
  jahresauswahl,
  planRestjahr,
  sprechblase,
  type MonatAusApi,
} from "./reihe";

function monat(monat: string, ist = 0, plan = 0): MonatAusApi {
  return {
    monat,
    ist_netto: ist,
    plan_netto: plan,
    summe_netto: ist + plan,
    ist_anzahl: ist ? 1 : 0,
    plan_anzahl: plan ? 1 : 0,
  };
}

const JAHR = Array.from({ length: 12 }, (_, i) =>
  monat(`2026-${String(i + 1).padStart(2, "0")}`),
);

describe("balkenreihe", () => {
  it("übersetzt Ist und Plan in einen gestapelten Balken", () => {
    const reihe = balkenreihe(
      [monat("2026-05", 28939834, 1000000)],
      new Date(2026, 7, 27),
    );
    expect(reihe[0]?.betrag).toBe(28939834);
    expect(reihe[0]?.planBetrag).toBe(1000000);
    expect(reihe[0]?.beschriftung).toBe("Mai");
  });

  it("hebt den laufenden Monat hervor", () => {
    const reihe = balkenreihe(JAHR, new Date(2026, 7, 27));
    expect(reihe.filter((b) => b.aktuell).map((b) => b.monat)).toEqual([
      "2026-08",
    ]);
  });

  it("hebt in einem anderen Jahr keinen Monat hervor", () => {
    const reihe = balkenreihe(JAHR, new Date(2025, 7, 27));
    expect(reihe.some((b) => b.aktuell)).toBe(false);
  });

  it("behält die Reihenfolge der zwölf Monate", () => {
    expect(balkenreihe(JAHR, new Date(2026, 0, 1)).map((b) => b.monat)).toEqual(
      JAHR.map((m) => m.monat),
    );
  });
});

describe("sprechblase", () => {
  // Vor der Einheit steht ein geschütztes Leerzeichen (PLAN §11) – deshalb hier
  // ausdrücklich NBSP und nicht das Leerzeichen der Tastatur.
  it("nennt beide Beträge", () => {
    expect(sprechblase(monat("2026-05", 28939834, 1000000))).toBe(
      `Mai 2026 · Ist 289${NBSP}T€ · Plan 10${NBSP}T€`,
    );
  });

  it("nennt nur, was da ist", () => {
    expect(sprechblase(monat("2026-09", 0, 50941208))).toBe(
      `September 2026 · Plan 509${NBSP}T€`,
    );
  });

  it("sagt bei einem leeren Monat, dass nichts geplant ist", () => {
    expect(sprechblase(monat("2026-01"))).toBe("Januar 2026 · nichts geplant");
  });
});

describe("planRestjahr", () => {
  const monate = [
    monat("2026-01", 0, 100),
    monat("2026-02", 0, 200),
    monat("2026-03", 0, 400),
    ...Array.from({ length: 9 }, (_, i) =>
      monat(`2026-${String(i + 4).padStart(2, "0")}`, 0, 8),
    ),
  ];

  it("zählt ab dem laufenden Monat", () => {
    // März 2026: der März zählt mit, Januar und Februar nicht.
    expect(planRestjahr(monate, 2026, new Date(2026, 2, 15))).toBe(400 + 9 * 8);
  });

  it("zählt für ein künftiges Jahr das ganze Jahr", () => {
    expect(planRestjahr(monate, 2026, new Date(2025, 11, 31))).toBe(
      100 + 200 + 400 + 9 * 8,
    );
  });

  it("zählt für ein vergangenes Jahr nichts – da kommt nichts mehr", () => {
    expect(planRestjahr(monate, 2025, new Date(2026, 5, 1))).toBe(0);
  });

  it("zählt im Dezember nur noch den Dezember", () => {
    expect(planRestjahr(monate, 2026, new Date(2026, 11, 31))).toBe(8);
  });
});

describe("jahresauswahl", () => {
  it("nimmt die Jahre aus den Daten und die drei um heute", () => {
    expect(jahresauswahl([2026], 2026, new Date(2026, 7, 27))).toEqual([
      2027, 2026, 2025,
    ]);
  });

  it("behält das gewählte Jahr, auch wenn es in den Daten fehlt", () => {
    expect(jahresauswahl([2026], 2030, new Date(2026, 7, 27))).toContain(2030);
  });

  it("zählt jedes Jahr nur einmal und absteigend", () => {
    const liste = jahresauswahl([2024, 2025, 2026], 2026, new Date(2026, 0, 1));
    expect(liste).toEqual([...new Set(liste)]);
    expect(liste).toEqual([...liste].sort((a, b) => b - a));
  });
});
