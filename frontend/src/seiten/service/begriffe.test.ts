import { describe, expect, it } from "vitest";
import {
  anlagenZusatz,
  frist,
  fristBadge,
  fristStatus,
  fristTyp,
  fristTypen,
  fristenZusatz,
  gewaehrleistung,
} from "./begriffe";

describe("fristTyp", () => {
  it("übersetzt die Schlüssel der API", () => {
    expect(fristTyp("gewaehrleistung")).toBe("Gewährleistung");
    expect(fristTyp("mastr")).toBe("MaStR-Registrierung");
  });

  it("gibt Unbekanntes unverändert zurück statt zu verschlucken", () => {
    expect(fristTyp("neuer_typ")).toBe("neuer_typ");
  });

  it("liefert alle Typen für die Auswahl", () => {
    expect(fristTypen().map((t) => t.wert)).toContain("reservierung");
  });
});

describe("fristStatus", () => {
  it("benennt die drei Zustände", () => {
    expect(fristStatus("ueberfaellig")).toBe("überfällig");
    expect(fristStatus("faellig")).toBe("läuft ab");
    expect(fristStatus("offen")).toBe("offen");
  });
});

describe("frist", () => {
  it("sagt, wie lange noch – nicht nur wann", () => {
    expect(frist(0)).toBe("heute fällig");
    expect(frist(1)).toBe("morgen fällig");
    expect(frist(12)).toBe("in 12 Tagen");
  });

  it("zählt Überfälligkeit nach oben", () => {
    expect(frist(-1)).toBe("seit gestern überfällig");
    expect(frist(-3)).toBe("seit 3 Tagen überfällig");
  });

  it("rechnet lange Fristen in Monate und Jahre um", () => {
    // „in 1.284 Tagen" ordnet niemand ein.
    expect(frist(90)).toBe("in rund 3 Monaten");
    expect(frist(365)).toBe("in rund 12 Monaten");
    expect(frist(1284)).toBe("in rund 4 Jahren");
  });
});

describe("fristenZusatz", () => {
  it("nennt beide Zahlen", () => {
    expect(fristenZusatz({ ueberfaellig: 2, faellig: 3, offen: 9 })).toBe(
      "2 überfällig, 3 laufen ab",
    );
  });

  it("bleibt im Singular richtig", () => {
    expect(fristenZusatz({ ueberfaellig: 0, faellig: 1, offen: 0 })).toBe(
      "1 läuft ab",
    );
  });

  it("ist leer, wenn nichts ansteht", () => {
    expect(fristenZusatz({ ueberfaellig: 0, faellig: 0, offen: 4 })).toBe("");
  });
});

describe("gewaehrleistung", () => {
  it("nennt das Ende", () => {
    expect(gewaehrleistung("2030-05-20")).toBe("bis 20.05.2030");
  });

  it("sagt beim fehlenden Ende, woran es liegt", () => {
    // Ein „–" ließe offen, ob die Frist abgelaufen oder nie berechnet worden ist.
    expect(gewaehrleistung(null)).toBe("offen – Abnahmedatum fehlt");
  });
});

describe("anlagenZusatz", () => {
  it("fasst Inbetriebnahme und Wartungsvertrag zusammen", () => {
    expect(anlagenZusatz("2026-05-12", false)).toBe(
      "in Betrieb seit 12.05.2026 · ohne Wartungsvertrag",
    );
    expect(anlagenZusatz(null, true)).toBe("mit Wartungsvertrag");
  });
});

describe("fristBadge", () => {
  it("färbt nur Überfälliges voll", () => {
    expect(fristBadge("ueberfaellig")).toBe("ueberfaellig");
    expect(fristBadge("faellig")).toBe("frist");
  });

  it("zeigt Fernes neutral", () => {
    // Eine Gewährleistung, die in vier Jahren endet, in derselben Farbe wie eine versäumte
    // MaStR-Registrierung zu zeigen, macht das Signal wertlos.
    expect(fristBadge("offen")).toBe("geplant");
    expect(fristBadge("neuer_zustand")).toBe("geplant");
  });
});
