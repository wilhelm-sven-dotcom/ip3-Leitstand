import { describe, expect, it } from "vitest";
import {
  abweichungText,
  ampelTitel,
  hinweisKurz,
  istAnteile,
  margeText,
  projektname,
  rechenweg,
  stundenText,
} from "./begriffe";

describe("margeText", () => {
  it("zeigt die Marge mit Vorzeichen", () => {
    expect(margeText(514)).toBe("+51,4\u00A0%");
  });

  it("nutzt das echte Minuszeichen bei Verlust", () => {
    // U+2212, nicht der Bindestrich: es steht auf der Höhe der Ziffern (PLAN §11).
    expect(margeText(-200)).toBe("−20,0\u00A0%");
  });

  it("zeigt null ohne Vorzeichen", () => {
    expect(margeText(0)).toBe("0,0\u00A0%");
  });

  it("zeigt einen Strich, wenn es keine Marge gibt", () => {
    expect(margeText(null)).toBe("–");
    expect(margeText(undefined)).toBe("–");
  });
});

describe("abweichungText", () => {
  it("rechnet Promille in Prozentpunkte", () => {
    expect(abweichungText(-40)).toBe("−4,0\u00A0%-Pkt.");
    expect(abweichungText(330)).toBe("+33,0\u00A0%-Pkt.");
  });
});

describe("stundenText", () => {
  it("hängt die Einheit mit geschütztem Leerzeichen an", () => {
    expect(stundenText(120.5)).toBe("120,50\u00A0h");
    expect(stundenText("95.00")).toBe("95,00\u00A0h");
  });

  it("verträgt fehlende Werte", () => {
    expect(stundenText(null)).toBe("–");
    expect(stundenText("")).toBe("–");
  });
});

describe("ampelTitel", () => {
  it("nennt den Abstand zur Sollmarge", () => {
    expect(ampelTitel("knapp", 180, -40)).toBe(
      "4,0\u00A0% unter der Sollmarge von 18,0\u00A0%",
    );
    expect(ampelTitel("im_soll", 180, 330)).toBe(
      "33,0\u00A0% über der Sollmarge von 18,0\u00A0%",
    );
  });

  it("sagt es, wenn es keine Sollmarge gibt", () => {
    expect(ampelTitel("ohne_soll", null, null)).toContain("keine Sollmarge");
  });
});

describe("istAnteile", () => {
  const zeile = {
    ist_datev: 4150050,
    ist_stueckliste: 78840,
    ist_timetac: 1024250,
    ist_gesamt: 5253140,
  };

  it("rechnet die Anteile am Ist", () => {
    const anteile = istAnteile(zeile);
    expect(anteile.map((a) => a.text)).toEqual(["DATEV", "Lager", "Stunden"]);
    expect(anteile[0]?.anteil).toBeCloseTo(79.0, 1);
    const summe = anteile.reduce((s, a) => s + a.anteil, 0);
    expect(summe).toBeCloseTo(100, 5);
  });

  it("teilt nicht durch null", () => {
    const leer = istAnteile({
      ist_datev: 0,
      ist_stueckliste: 0,
      ist_timetac: 0,
      ist_gesamt: 0,
    });
    expect(leer.every((a) => a.anteil === 0)).toBe(true);
  });

  it("behält Quellen ohne Betrag – dass nichts kam, ist eine Auskunft", () => {
    const ohneLager = istAnteile({ ...zeile, ist_stueckliste: 0 });
    expect(ohneLager).toHaveLength(3);
    expect(ohneLager[1]?.betrag).toBe(0);
  });
});

describe("rechenweg", () => {
  const zeile = {
    ab_wert_netto: 10000000,
    nachtraege_netto: 800000,
    erloes_netto: 10800000,
    ist_gesamt: 5253140,
    marge_netto: 5546860,
    marge_promille: 514,
  };

  it("zeigt den Weg vom Auftragswert zur Marge", () => {
    const zeilen = rechenweg(zeile);
    expect(zeilen.map((z) => z.text)).toEqual([
      "Auftragswert",
      "Beauftragte Nachträge",
      "Erlös",
      "Ist-Kosten",
      "Marge",
    ]);
    expect(zeilen[4]?.wert).toBe("55.468,60\u00A0€ (+51,4\u00A0%)");
  });

  it("lässt die Nachtragszeile weg, wenn es keine gibt", () => {
    const zeilen = rechenweg({ ...zeile, nachtraege_netto: 0 });
    expect(zeilen.map((z) => z.text)).not.toContain("Beauftragte Nachträge");
  });

  it("zeigt die Ist-Kosten als Abzug", () => {
    expect(rechenweg(zeile)[3]?.wert).toBe("−52.531,40\u00A0€");
  });

  it("erklärt eine fehlende Marge, statt eine Null zu zeigen", () => {
    const ohne = rechenweg({
      ...zeile,
      ab_wert_netto: null,
      erloes_netto: null,
      marge_netto: null,
      marge_promille: null,
    });
    const marge = ohne.at(-1)!;
    expect(marge.wert).toBe("–");
    expect(marge.hinweis).toContain("Ohne Auftragswert");
  });
});

describe("hinweisKurz", () => {
  it("kürzt die bekannten Hinweise für die Tabelle", () => {
    expect(hinweisKurz("doppelbelastung_verdacht")).toBe("Material doppelt?");
  });

  it("gibt unbekannte Codes unverändert zurück, statt sie zu verschlucken", () => {
    expect(hinweisKurz("etwas_neues")).toBe("etwas_neues");
  });
});

describe("projektname", () => {
  it("nimmt die Bezeichnung, sonst den Kunden", () => {
    expect(projektname({ bezeichnung: "PV Halle", kunde: "Meier" })).toBe(
      "PV Halle",
    );
    expect(projektname({ bezeichnung: "  ", kunde: "Meier" })).toBe("Meier");
    expect(projektname({ bezeichnung: null, kunde: "Meier" })).toBe("Meier");
  });
});
