/**
 * Prüfungen an den Beschriftungen.
 *
 * Der wichtigste Test ist der Abgleich mit dem Backend: kommt dort ein Meilensteintyp oder eine
 * Anlagenart hinzu, fehlt hier die Beschriftung – und in der Maske stünde plötzlich
 * `lieferung_wallbox` statt „Lieferung Wallbox". Das fällt sonst erst dem Nutzer auf.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import {
  ANLAGENART_TEXT,
  ANLAGENARTEN,
  MEILENSTEIN_TEXT,
  MEILENSTEIN_TYPEN,
  MEILENSTEINGRUPPEN,
  STATUS_TEXT,
  PROJEKT_STATUS,
  kopfzeile,
  meilensteinText,
  projektname,
} from "./begriffe";

function schluesselAusBackend(name: string): string[] {
  const quelle = readFileSync("../backend/app/modelle/projekte.py", "utf-8");
  const treffer = quelle.match(new RegExp(`${name} = \\(([^)]*)\\)`));
  if (!treffer)
    throw new Error(`${name} nicht in app/modelle/projekte.py gefunden`);
  return [...(treffer[1] ?? "").matchAll(/"([a-z_0-9]+)"/g)].map(
    (m) => m[1] as string,
  );
}

describe("Abgleich mit dem Backend", () => {
  it("kennt alle Meilensteintypen", () => {
    expect([...MEILENSTEIN_TYPEN].sort()).toEqual(
      schluesselAusBackend("MEILENSTEIN_TYPEN").sort(),
    );
  });

  it("kennt alle Anlagenarten", () => {
    expect([...ANLAGENARTEN].sort()).toEqual(
      schluesselAusBackend("ANLAGENARTEN").sort(),
    );
  });

  it("kennt alle Projektstatus", () => {
    expect([...PROJEKT_STATUS].sort()).toEqual(
      schluesselAusBackend("PROJEKT_STATUS").sort(),
    );
  });
});

describe("Beschriftungen", () => {
  it("hat für jeden Typ einen Text", () => {
    for (const typ of MEILENSTEIN_TYPEN) {
      expect(MEILENSTEIN_TEXT[typ], typ).toBeTruthy();
    }
    for (const art of ANLAGENARTEN)
      expect(ANLAGENART_TEXT[art], art).toBeTruthy();
    for (const status of PROJEKT_STATUS)
      expect(STATUS_TEXT[status], status).toBeTruthy();
  });

  it("nennt jeden Typ genau einmal", () => {
    expect(new Set(MEILENSTEIN_TYPEN).size).toBe(MEILENSTEIN_TYPEN.length);
  });

  it("zeigt einen unbekannten Typ als Schlüssel statt als Leerstelle", () => {
    expect(meilensteinText("grundsteinlegung")).toBe("grundsteinlegung");
  });

  it("gruppiert vollständig", () => {
    const inGruppen = MEILENSTEINGRUPPEN.flatMap((g) => [...g.typen]);
    expect(inGruppen.sort()).toEqual([...MEILENSTEIN_TYPEN].sort());
  });
});

describe("kopfzeile", () => {
  it("verbindet mit Mittelpunkt", () => {
    expect(kopfzeile(["Weiden", "Aufdach"])).toBe("Weiden · Aufdach");
  });

  it("lässt Leerstellen weg statt Gedankenstriche zu zeigen", () => {
    expect(kopfzeile([null, "Aufdach", "", undefined, "   "])).toBe("Aufdach");
  });

  it("ergibt bei nichts einen leeren Text", () => {
    expect(kopfzeile([null, undefined])).toBe("");
  });
});

describe("projektname", () => {
  it("nimmt die Bezeichnung, wenn es eine gibt", () => {
    expect(projektname("PV-Park Letzau", "EnergiePark Letzau GmbH")).toBe(
      "PV-Park Letzau",
    );
  });

  it("fällt bei den migrierten Projekten auf den Kunden zurück", () => {
    expect(projektname(null, "Pöllath")).toBe("Pöllath");
    expect(projektname("   ", "Pöllath")).toBe("Pöllath");
  });
});
