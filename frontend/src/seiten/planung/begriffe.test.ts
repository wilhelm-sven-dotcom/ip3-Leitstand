import { describe, expect, it } from "vitest";
import {
  angebotStatus,
  auslastung,
  auslastungZusatz,
  chance,
  kalenderwoche,
  kalenderwocheLang,
  mehrzahl,
  pipelineZusatz,
  satzgruppe,
  satzgruppen,
  stunden,
  wochenlage,
  wochenlageText,
} from "./begriffe";

describe("kalenderwoche", () => {
  it("kürzt den Schlüssel auf das Lesbare", () => {
    expect(kalenderwoche("2026-W36")).toBe("KW 36");
    // Führende Null weg: „KW 6" liest sich wie im Kalender.
    expect(kalenderwoche("2026-W06")).toBe("KW 6");
  });

  it("nennt im Langtext das Jahr", () => {
    expect(kalenderwocheLang("2026-W36")).toBe("KW 36/2026");
  });

  it("gibt Unbekanntes unverändert zurück", () => {
    expect(kalenderwoche("kaputt")).toBe("kaputt");
  });
});

describe("stunden", () => {
  it("schreibt ganze Stunden ohne Nachkommastellen", () => {
    expect(stunden(160)).toBe("160 h");
  });

  it("schreibt Teilstunden mit Dezimalkomma", () => {
    expect(stunden(38.5)).toBe("38,5 h");
  });

  it("zeigt Fehlendes als Gedankenstrich", () => {
    expect(stunden(null)).toBe("–");
  });

  it("nutzt das Minuszeichen, nicht den Bindestrich", () => {
    expect(stunden(-121.5)).toBe("−121,5 h");
  });
});

describe("wochenlage", () => {
  const schwelle = 900;

  it("nennt über 100 % überbucht", () => {
    expect(wochenlage(1200, schwelle)).toBe("eng");
    expect(wochenlageText(wochenlage(1200, schwelle))).toBe("überbucht");
  });

  it("nennt ab der Schwelle voll", () => {
    expect(wochenlage(900, schwelle)).toBe("voll");
    expect(wochenlage(1000, schwelle)).toBe("voll");
  });

  it("nennt darunter Luft", () => {
    expect(wochenlage(500, schwelle)).toBe("frei");
    expect(wochenlageText(wochenlage(500, schwelle))).toBe("Luft");
  });

  it("sagt ohne Mannschaft, dass die Zahl fehlt", () => {
    // Bedarf durch null ist keine Auslastung, sondern eine fehlende Angabe.
    expect(wochenlage(null, schwelle)).toBeNull();
    expect(wochenlageText(null)).toBe("keine Mannschaft erfasst");
  });
});

describe("auslastung", () => {
  it("rechnet Promille in Prozent ohne Pluszeichen", () => {
    expect(auslastung(750)).toBe("75 %");
    expect(auslastung(4156)).toBe("416 %");
  });

  it("zeigt Fehlendes als Gedankenstrich", () => {
    expect(auslastung(null)).toBe("–");
  });
});

describe("auslastungZusatz", () => {
  it("nennt die Zahl der überbuchten Wochen", () => {
    const wochen = [
      { auslastung_promille: 1200 },
      { auslastung_promille: 400 },
      { auslastung_promille: 1100 },
    ];
    expect(auslastungZusatz(wochen, 900)).toBe("2 von 3 Wochen überbucht");
  });

  it("sagt auch, wenn nichts überbucht ist", () => {
    expect(auslastungZusatz([{ auslastung_promille: 400 }], 900)).toBe(
      "keine der 1 Wochen überbucht",
    );
  });

  it("bleibt bei leerer Liste still", () => {
    expect(auslastungZusatz([], 900)).toBe("");
  });
});

describe("satzgruppe", () => {
  it("übersetzt die Schlüssel", () => {
    expect(satzgruppe("obermonteur")).toBe("Obermonteur");
    expect(satzgruppen().map((s) => s.wert)).toContain("elektriker");
  });

  it("benennt fehlende Zuordnung, statt leer zu bleiben", () => {
    expect(satzgruppe(null)).toBe("ohne Zuordnung");
  });
});

describe("Pipeline", () => {
  it("nennt beide Summen nebeneinander", () => {
    // Nur die gewichtete verschweigt das Risiko, nur die rohe die Wahrscheinlichkeit.
    expect(pipelineZusatz(125_000_000, 75_000_000)).toBe(
      "1.250.000,00 € angeboten, davon 750.000,00 € gewichtet",
    );
  });

  it("schreibt die Wahrscheinlichkeit als Prozent", () => {
    expect(chance(600)).toBe("60 %");
  });

  it("übersetzt den Status", () => {
    expect(angebotStatus("gewonnen")).toBe("gewonnen");
    expect(angebotStatus("neuer_status")).toBe("neuer_status");
  });
});

describe("mehrzahl", () => {
  it("hält Zahl und Wort im gleichen Numerus", () => {
    // „1 offene Angebote" liest sich wie eine Maschinenausgabe und wird überlesen.
    expect(mehrzahl(1, "offenes Angebot", "offene Angebote")).toBe(
      "1 offenes Angebot",
    );
    expect(mehrzahl(3, "offenes Angebot", "offene Angebote")).toBe(
      "3 offene Angebote",
    );
    expect(mehrzahl(0, "offenes Angebot", "offene Angebote")).toBe(
      "0 offene Angebote",
    );
  });

  it("setzt den Tausenderpunkt", () => {
    expect(mehrzahl(1234, "Angebot", "Angebote")).toBe("1.234 Angebote");
  });
});
