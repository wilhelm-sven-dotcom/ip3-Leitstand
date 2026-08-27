import { describe, expect, it } from "vitest";
import {
  alleEntschieden,
  betragOffen,
  fortschritt,
  fuerSchnittstelle,
  leereEntscheidungen,
  offene,
  type Zuordnung,
} from "./entscheidungen";

const zugeordnet: Zuordnung = {
  kundenteil: "Aigner, Mitterteich",
  zeilen: [8, 9, 10, 11],
  betrag_netto: 1100075,
  art: "exakt",
  offen: false,
  projekt_zeile: 8,
  vorschlaege: [],
};

const mitVorschlag: Zuordnung = {
  kundenteil: "Huber, Pressath",
  zeilen: [18],
  betrag_netto: 250000,
  art: "vorschlag",
  offen: true,
  projekt_zeile: null,
  vorschlaege: [
    { projekt_zeile: 17, kunde: "Huber, Pressath", guete: 100 },
    { projekt_zeile: 18, kunde: "Huber, Pressath", guete: 100 },
  ],
};

const ohneKandidat: Zuordnung = {
  kundenteil: "Nachbauer, Weiden",
  zeilen: [24],
  betrag_netto: 55000000,
  art: "ohne",
  offen: true,
  projekt_zeile: null,
  vorschlaege: [],
};

const alle = [zugeordnet, mitVorschlag, ohneKandidat];

describe("offene Zuordnungen", () => {
  it("zählt nur, was eine Entscheidung braucht und keine hat", () => {
    expect(
      offene(alle, leereEntscheidungen()).map((z) => z.kundenteil),
    ).toEqual(["Huber, Pressath", "Nachbauer, Weiden"]);
  });

  it("nimmt eine getroffene Entscheidung heraus", () => {
    const nach = offene(alle, { "Huber, Pressath": 17 });
    expect(nach.map((z) => z.kundenteil)).toEqual(["Nachbauer, Weiden"]);
  });

  it('erkennt „eigenes Projekt anlegen" als Entscheidung', () => {
    // null ist eine Entscheidung, undefined nicht – die Unterscheidung ist der Kern.
    expect(
      offene(alle, { "Nachbauer, Weiden": null, "Huber, Pressath": 17 }),
    ).toEqual([]);
  });

  it("summiert die offenen Beträge", () => {
    expect(betragOffen(alle, leereEntscheidungen())).toBe(250000 + 55000000);
    expect(betragOffen(alle, { "Nachbauer, Weiden": null })).toBe(250000);
  });
});

describe("alleEntschieden", () => {
  it("gibt die Übernahme erst frei, wenn nichts offen ist", () => {
    expect(alleEntschieden(alle, leereEntscheidungen())).toBe(false);
    expect(alleEntschieden(alle, { "Huber, Pressath": 17 })).toBe(false);
    expect(
      alleEntschieden(alle, {
        "Huber, Pressath": 17,
        "Nachbauer, Weiden": null,
      }),
    ).toBe(true);
  });

  it("ist bei ausschließlich exakten Treffern sofort frei", () => {
    expect(alleEntschieden([zugeordnet], leereEntscheidungen())).toBe(true);
  });
});

describe("fuerSchnittstelle", () => {
  it("schickt nur die Kunden, die eine Entscheidung brauchten", () => {
    const koerper = fuerSchnittstelle(alle, {
      "Huber, Pressath": 17,
      "Nachbauer, Weiden": null,
      // Ein exakt zugeordneter Kunde gehört nicht in die Anfrage.
      "Aigner, Mitterteich": 8,
    });
    expect(koerper).toEqual({
      "Huber, Pressath": 17,
      "Nachbauer, Weiden": null,
    });
  });

  it("lässt Unentschiedenes weg statt es als null zu senden", () => {
    // null heißt „eigenes Projekt anlegen" – ein vergessener Eintrag darf das nicht auslösen.
    expect(fuerSchnittstelle(alle, { "Huber, Pressath": 17 })).toEqual({
      "Huber, Pressath": 17,
    });
  });
});

describe("fortschritt", () => {
  it("trennt automatisch zugeordnet von selbst entschieden", () => {
    expect(fortschritt(alle, leereEntscheidungen())).toEqual({
      entschieden: 0,
      gesamt: 2,
      automatisch: 1,
    });
    expect(fortschritt(alle, { "Huber, Pressath": 17 })).toEqual({
      entschieden: 1,
      gesamt: 2,
      automatisch: 1,
    });
  });
});

describe("leereEntscheidungen", () => {
  it("belegt nichts vor", () => {
    // Eine vorausgefüllte Maske wird durchgeklickt – dann ist die Bestätigung wertlos.
    expect(leereEntscheidungen()).toEqual({});
  });
});
