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
  abweichungText,
  verguetungsart,
  zahlungslage,
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

describe("verguetungsart", () => {
  it("nennt den Satz, weil er die Erwartung erklärt", () => {
    expect(verguetungsart("einspeisung", 8.11)).toContain("Einspeisung");
    expect(verguetungsart("einspeisung", 8.11)).toContain("8,11");
    expect(verguetungsart("einspeisung", 8.11)).toContain("ct/kWh");
  });

  it("sagt es, wenn der Satz fehlt", () => {
    // Ohne Satz gibt es keine Erwartung – das muss dastehen, sonst sucht niemand danach.
    expect(verguetungsart("direktvermarktung", null)).toBe(
      "Direktvermarktung · Satz fehlt",
    );
  });

  it("setzt ein geschütztes Leerzeichen vor die Einheit", () => {
    expect(verguetungsart("einspeisung", 6.5)).toContain(" ct/kWh");
  });
});

describe("abweichungText", () => {
  it("ohne Erwartung gibt es keine Abweichung", () => {
    // Ein Strich, nicht „0,00 €": der Unterschied zwischen „stimmt" und „lässt sich nicht sagen".
    expect(abweichungText(null, null).text).toBe("–");
    expect(abweichungText(null, null).auffaellig).toBe(false);
  });

  it("null Abweichung heißt stimmt", () => {
    expect(abweichungText(0, 0).text).toBe("stimmt");
  });

  it("zeigt Vorzeichen und Anteil", () => {
    const zuwenig = abweichungText(-10000, -125);
    expect(zuwenig.text).toContain("−");
    expect(zuwenig.text).toContain("12,5");
    expect(zuwenig.auffaellig).toBe(true);
  });

  it("kleine Abweichungen fallen nicht auf", () => {
    // Sonst bedeutet die Akzentfarbe irgendwann nichts mehr.
    expect(abweichungText(-500, -10).auffaellig).toBe(false);
  });
});

describe("zahlungslage", () => {
  it("bezahlt nennt das Datum", () => {
    const lage = zahlungslage({
      bezahlt_am: "2026-08-20",
      offen: false,
      abgerechnet_cent: 80000,
    });
    expect(lage.art).toBe("erfolg");
    expect(lage.text).toContain("20.08.2026");
  });

  it("offen ist die Warnung", () => {
    const lage = zahlungslage({
      bezahlt_am: null,
      offen: true,
      abgerechnet_cent: 80000,
    });
    expect(lage.art).toBe("warnung");
    expect(lage.text).toBe("offen");
  });

  it("ein Nullbetrag ist nicht offen", () => {
    const lage = zahlungslage({
      bezahlt_am: null,
      offen: false,
      abgerechnet_cent: 0,
    });
    expect(lage.art).toBe("neutral");
  });
});
