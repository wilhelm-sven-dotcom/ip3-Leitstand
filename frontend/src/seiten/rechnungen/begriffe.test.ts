/**
 * Die reinen Rechen- und Textteile der Fakturierung.
 *
 * Der Schwerpunkt liegt auf den Summenzeilen: sie geben auf dem Bildschirm wieder, was auf dem
 * PDF steht. Weichen beide voneinander ab, glaubt der Nutzer der falschen Zahl.
 */

import { describe, expect, it } from "vitest";
import { NBSP } from "@/format/formate";
import {
  ART_KURZ,
  ART_TEXT,
  badgeZustand,
  belegnummer,
  belegtitel,
  mengeText,
  satzText,
  sperrgrund,
  summenbezeichnung,
  summenzeilen,
} from "./begriffe";

const ABSCHLAG = {
  netto: 9187500,
  ust: 1745625,
  brutto: 10933125,
  absetzung_netto: 0,
  absetzung_ust: 0,
  zahlbetrag: 10933125,
  ust_details: [{ satz: 190, netto: 9187500, ust: 1745625 }],
  art: "abschlag",
};

describe("Beschriftungen", () => {
  it("kennt jede Belegart in Lang- und Kurzform", () => {
    for (const art of Object.keys(ART_TEXT)) {
      expect(ART_TEXT[art as keyof typeof ART_TEXT]).toBeTruthy();
      expect(ART_KURZ[art as keyof typeof ART_KURZ]).toBeTruthy();
    }
  });

  it("nummeriert den Abschlag wie die Word-Vorlage", () => {
    expect(belegtitel("abschlag", 3)).toBe("3. Abschlagsrechnung");
    expect(belegtitel("abschlag", null)).toBe("Abschlagsrechnung");
    expect(belegtitel("schluss")).toBe("Schlussrechnung");
  });

  it("nennt einen Entwurf einen Entwurf", () => {
    expect(belegnummer(null)).toBe("Entwurf");
    expect(belegnummer("RE-2026-0143")).toBe("RE-2026-0143");
  });

  it("bildet die drei Belegstatus auf Badge-Zustände ab", () => {
    expect(badgeZustand("entwurf")).toBe("entwurf");
    expect(badgeZustand("festgeschrieben")).toBe("festgeschrieben");
    expect(badgeZustand("storniert")).toBe("storniert");
  });

  it("setzt ein geschütztes Leerzeichen vor das Prozentzeichen", () => {
    expect(satzText(190)).toBe(`19${NBSP}%`);
    expect(satzText(0)).toBe(`0${NBSP}%`);
    expect(satzText(75)).toBe(`7,5${NBSP}%`);
  });

  it("benennt die Endsumme je Belegart", () => {
    expect(summenbezeichnung("abschlag")).toBe("Rechnungsbetrag brutto");
    expect(summenbezeichnung("schluss")).toBe("Restbetrag zur Zahlung");
    expect(summenbezeichnung("ab")).toBe("Auftragssumme brutto");
    expect(summenbezeichnung("storno")).toBe("Stornobetrag");
  });
});

describe("Menge", () => {
  it("zeigt eine Menge von 1 nicht als tausend", () => {
    // Die Schnittstelle liefert "1.000" (drei Nachkommastellen). Ungefiltert gelesen wäre das
    // auf deutsch tausend – genau das stand im Rundgang in der Positionstabelle.
    expect(mengeText("1.000")).toBe("1");
    expect(mengeText("2.500")).toBe("2,5");
    expect(mengeText("0.750")).toBe("0,75");
  });

  it("behält echte Tausender", () => {
    expect(mengeText("1500.000")).toBe("1.500");
  });

  it("lässt unlesbare Werte stehen, statt sie zu erfinden", () => {
    expect(mengeText("keine Zahl")).toBe("keine Zahl");
  });
});

describe("Summenzeilen", () => {
  it("Abschlag: netto, eine Steuerzeile, brutto", () => {
    const zeilen = summenzeilen(ABSCHLAG);
    expect(zeilen.map((z) => z.beschriftung)).toEqual([
      "Summe netto",
      `Umsatzsteuer 19${NBSP}%`,
      "Rechnungsbetrag brutto",
    ]);
    expect(zeilen.map((z) => z.betrag)).toEqual([9187500, 1745625, 10933125]);
    expect(zeilen.at(-1)?.hervorgehoben).toBe(true);
  });

  it("nennt bei mehreren Sätzen die Bemessungsgrundlage", () => {
    const zeilen = summenzeilen({
      ...ABSCHLAG,
      netto: 10637500,
      ust: 1745625,
      brutto: 12383125,
      zahlbetrag: 12383125,
      ust_details: [
        { satz: 0, netto: 1450000, ust: 0 },
        { satz: 190, netto: 9187500, ust: 1745625 },
      ],
    });
    expect(zeilen[1]!.beschriftung).toBe(
      `Umsatzsteuer 0${NBSP}% auf 14.500,00${NBSP}€`,
    );
    expect(zeilen[2]!.beschriftung).toBe(
      `Umsatzsteuer 19${NBSP}% auf 91.875,00${NBSP}€`,
    );
  });

  it("Schlussrechnung: Absetzung und Restbetrag als eigene Zeilen", () => {
    const zeilen = summenzeilen({
      netto: 36750000,
      ust: 6982500,
      brutto: 43732500,
      absetzung_netto: 31237500,
      absetzung_ust: 5935125,
      zahlbetrag: 6559875,
      ust_details: [{ satz: 190, netto: 36750000, ust: 6982500 }],
      art: "schluss",
    });
    expect(zeilen.map((z) => z.beschriftung)).toEqual([
      "Summe netto",
      `Umsatzsteuer 19${NBSP}%`,
      "Gesamtbetrag brutto",
      "abzüglich Abschlagszahlungen netto",
      "abzüglich darauf entfallende Umsatzsteuer",
      "Restbetrag zur Zahlung",
    ]);
    expect(zeilen[3]!.betrag).toBe(-31237500);
    expect(zeilen[4]!.betrag).toBe(-5935125);
    expect(zeilen.at(-1)?.betrag).toBe(6559875);
    expect(zeilen.at(-1)?.hervorgehoben).toBe(true);
  });

  it("rechnet nichts nach, sondern zeigt die Werte des Servers", () => {
    // Absichtlich unstimmige Zahlen: die Oberfläche darf sie nicht „korrigieren", sonst
    // zeigte sie etwas anderes als das PDF und als die Datenbank.
    const zeilen = summenzeilen({ ...ABSCHLAG, brutto: 999 });
    expect(zeilen.at(-1)?.betrag).toBe(999);
  });

  it("Nullbelege haben trotzdem eine Endsumme", () => {
    const zeilen = summenzeilen({
      netto: 0,
      ust: 0,
      brutto: 0,
      absetzung_netto: 0,
      absetzung_ust: 0,
      zahlbetrag: 0,
      ust_details: [],
      art: "service",
    });
    expect(zeilen).toHaveLength(2);
    expect(zeilen.at(-1)?.beschriftung).toBe("Rechnungsbetrag brutto");
  });
});

describe("Sperrgrund", () => {
  it("Entwurf ist offen", () => {
    expect(sperrgrund("entwurf")).toBeNull();
  });

  it("nennt bei einem festgeschriebenen Beleg den Weg zur Korrektur", () => {
    expect(sperrgrund("festgeschrieben")).toContain("Storno");
  });

  it("nennt bei einem stornierten Beleg den nächsten Schritt", () => {
    expect(sperrgrund("storniert")).toContain("neuen Beleg");
  });
});
