"""Lagerbewertung und Mengen-Ist-Bestätigung (PLAN §6.5, §7 Phase 4).

Der Kern ist die **Doppelbelastungssperre**: Material kommt entweder über die DATEV-Kostenträger
(projektbestellt) oder über die bewertete Stückliste (Lagerentnahme) ins Projekt-Ist, nie über
beide Wege. Stünde es zweimal drin, wäre die Marge um den vollen Materialwert zu schlecht – und
niemand würde es der Zahl ansehen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import stueckliste as dienst
from app.modelle import Firma, IstKosten, Kunde, Projekt, Stuecklistenposition
from tests.conftest_auth import anmelden


def alle_projekte():
    return select(Projekt)


@pytest.fixture
def projekt_mit_stueckliste(gesäte_db) -> dict[str, int]:
    """Projekt 26001 mit zwei Lager- und einer projektbestellten Position.

    | Position | Quelle | Menge Soll | EK |
    |---|---|---|---|
    | SCH-44 Montageschiene | lager | 36 | 21,90 € |
    | KAB-6 Solarkabel | lager | 250 | 1,45 € |
    | MOD-450 Modul | projektbestellt | 88 | 92,40 € |
    """
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=17001, name="Lager GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        projekt = Projekt(
            projekt_nr=26001,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            ab_wert_netto=6000000,
        )
        sitzung.add(projekt)
        sitzung.flush()

        kennungen = {"projekt": projekt.id}
        for artikel, bezeichnung, menge, ek, quelle in (
            ("SCH-44", "Montageschiene 4,4 m", 36, 2190, "lager"),
            ("KAB-6", "Solarkabel 6 mm²", 250, 145, "lager"),
            ("MOD-450", "Modul 450 Wp", 88, 9240, "projektbestellt"),
        ):
            position = Stuecklistenposition(
                projekt_id=projekt.id,
                artikel_nr=artikel,
                bezeichnung=bezeichnung,
                menge_soll=Decimal(menge),
                ek_preis=ek,
                quelle=quelle,
                gewerk="pv",
            )
            sitzung.add(position)
            sitzung.flush()
            kennungen[artikel] = position.id
        return kennungen


def positionen(sitzung) -> dict[str, Stuecklistenposition]:
    return {
        p.artikel_nr: p
        for p in sitzung.scalars(select(Stuecklistenposition).order_by(Stuecklistenposition.id))
    }


def ist_kosten(sitzung) -> list[IstKosten]:
    return list(
        sitzung.scalars(
            select(IstKosten).where(IstKosten.quelle == "stueckliste").order_by(IstKosten.id)
        )
    )


# ---------------------------------------------------------------------------
# Doppelbelastungssperre
# ---------------------------------------------------------------------------


def test_nur_lagerpositionen_werden_bewertet(projekt_mit_stueckliste: dict[str, int]) -> None:
    """PLAN §6.5: projektbestelltes Material kommt über DATEV, nie zusätzlich über den EK."""
    with schreib_sitzung() as sitzung:
        projekt = sitzung.get(Projekt, projekt_mit_stueckliste["projekt"])
        ergebnis = dienst.bewerten(sitzung, projekt)

    # 36 * 21,90 € = 788,40 € ; 250 * 1,45 € = 362,50 € ; Modul bleibt draußen.
    assert ergebnis.betrag_cent == 78840 + 36250
    assert ergebnis.lagerpositionen == 2 and ergebnis.bewertet == 2
    with lese_sitzung() as sitzung:
        gefunden = positionen(sitzung)
        assert gefunden["SCH-44"].bewertet_betrag == 78840
        assert gefunden["KAB-6"].bewertet_betrag == 36250
        assert gefunden["MOD-450"].bewertet_betrag is None


def test_wechsel_auf_projektbestellt_nimmt_den_betrag_zurueck(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    """Sonst bliebe ein Betrag stehen, den DATEV inzwischen ein zweites Mal liefert."""
    with schreib_sitzung() as sitzung:
        dienst.bewerten(sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]))
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["SCH-44"].quelle = "projektbestellt"
    with schreib_sitzung() as sitzung:
        ergebnis = dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"])
        )

    assert ergebnis.betrag_cent == 36250
    with lese_sitzung() as sitzung:
        assert positionen(sitzung)["SCH-44"].bewertet_betrag is None


def test_lagerposition_ohne_preis_wird_gezaehlt_aber_nicht_bewertet(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["KAB-6"].ek_preis = None
    with schreib_sitzung() as sitzung:
        ergebnis = dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"])
        )

    assert ergebnis.ohne_preis == 1 and ergebnis.bewertet == 1
    assert not ergebnis.vollstaendig
    assert ergebnis.betrag_cent == 78840


# ---------------------------------------------------------------------------
# Menge
# ---------------------------------------------------------------------------


def test_ohne_bestaetigung_gilt_die_kalkulierte_menge(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    """Eine Null wäre die Behauptung, es sei nichts verbaut worden."""
    with schreib_sitzung() as sitzung:
        ergebnis = dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"])
        )
    assert ergebnis.betrag_cent == 78840 + 36250


def test_bestaetigte_menge_hat_vorrang(projekt_mit_stueckliste: dict[str, int]) -> None:
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["SCH-44"].menge_ist = Decimal("34.000")
    with schreib_sitzung() as sitzung:
        ergebnis = dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"])
        )

    # 34 * 21,90 € = 744,60 €
    assert ergebnis.betrag_cent == 74460 + 36250


def test_bruchmenge_wird_kaufmaennisch_gerundet(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["KAB-6"].menge_ist = Decimal("133.500")
    with schreib_sitzung() as sitzung:
        dienst.bewerten(sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]))

    # 133,5 * 1,45 € = 193,575 € -> 193,58 €
    with lese_sitzung() as sitzung:
        assert positionen(sitzung)["KAB-6"].bewertet_betrag == 19358


# ---------------------------------------------------------------------------
# Ist-Kosten
# ---------------------------------------------------------------------------


def test_bewertung_erzeugt_eine_ist_kosten_zeile(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    with schreib_sitzung() as sitzung:
        dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]), monat="2026-07"
        )
    with lese_sitzung() as sitzung:
        zeilen = ist_kosten(sitzung)
        assert len(zeilen) == 1
        assert zeilen[0].betrag == 78840 + 36250
        assert zeilen[0].monat == "2026-07"
        assert zeilen[0].referenz == dienst.REFERENZ


def test_zweite_bestaetigung_ersetzt_statt_zu_verdoppeln(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    with schreib_sitzung() as sitzung:
        dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]), monat="2026-07"
        )
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["SCH-44"].menge_ist = Decimal("30.000")
    with schreib_sitzung() as sitzung:
        dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]), monat="2026-07"
        )

    with lese_sitzung() as sitzung:
        zeilen = ist_kosten(sitzung)
        assert len(zeilen) == 1
        assert zeilen[0].betrag == 65700 + 36250


def test_bewertung_in_einem_anderen_monat_ersetzt_die_erste(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    """Die Lagerbewertung ist der aktuelle Wertansatz, keine Reihe je Bestätigung.

    Der Fehler, den dieser Test verhindert, ist in der Abnahme aufgefallen: bestätigt jemand im
    August erneut, stünde die Lagerentnahme sonst zweimal im Ist – und eine verdoppelte Zahl
    sieht in der Nachkalkulation aus wie ein teures Projekt, nicht wie ein Fehler.
    """
    with schreib_sitzung() as sitzung:
        dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]), monat="2026-07"
        )
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["SCH-44"].menge_ist = Decimal("30.000")
    with schreib_sitzung() as sitzung:
        dienst.bewerten(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]), monat="2026-08"
        )

    with lese_sitzung() as sitzung:
        zeilen = ist_kosten(sitzung)
        assert len(zeilen) == 1, "es gibt genau einen Wertansatz je Projekt"
        assert zeilen[0].monat == "2026-08", "der Monat der letzten Bestätigung"
        assert zeilen[0].betrag == 65700 + 36250


def test_projekt_ohne_lagerpositionen_erzeugt_keine_zeile(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=17002, name="Ohne Lager", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        projekt = Projekt(projekt_nr=26009, firma_id=firma_id, kunde_id=kunde.id, status="in_bau")
        sitzung.add(projekt)
        sitzung.flush()
        ergebnis = dienst.bewerten(sitzung, projekt)

    assert ergebnis.betrag_cent == 0
    with lese_sitzung() as sitzung:
        assert ist_kosten(sitzung) == []


# ---------------------------------------------------------------------------
# Offene Mengen
# ---------------------------------------------------------------------------


def test_offene_mengen_zaehlt_nur_lagerpositionen(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    with lese_sitzung() as sitzung:
        offen = dienst.offene_mengen(sitzung, alle_projekte())
        assert len(offen) == 1
        assert offen[0].projekt_nr == 26001
        assert offen[0].positionen == 2, "das projektbestellte Modul zählt nicht mit"
        assert offen[0].offen == 2


def test_projekt_verschwindet_aus_der_liste_wenn_alles_gezaehlt_ist(
    projekt_mit_stueckliste: dict[str, int],
) -> None:
    with schreib_sitzung() as sitzung:
        for position in positionen(sitzung).values():
            if position.quelle == "lager":
                position.menge_ist = position.menge_soll
    with lese_sitzung() as sitzung:
        assert dienst.offene_mengen(sitzung, alle_projekte()) == []
        assert not dienst.hat_offene_mengen(
            sitzung, sitzung.get(Projekt, projekt_mit_stueckliste["projekt"])
        )


def test_angebot_steht_nicht_in_der_liste(projekt_mit_stueckliste: dict[str, int]) -> None:
    """Vor dem Bau ist die Mengenbestätigung noch nicht fällig."""
    with schreib_sitzung() as sitzung:
        sitzung.get(Projekt, projekt_mit_stueckliste["projekt"]).status = "angebot"
    with lese_sitzung() as sitzung:
        assert dienst.offene_mengen(sitzung, alle_projekte()) == []


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen):
    nutzer_erzeugen("bau@ip3-energie.de", "buchhaltung")
    return anmelden(client, "bau@ip3-energie.de")


def liste_lesen(sitzung) -> list[dict]:
    antwort = sitzung.client.get("/api/projekte/26001/stueckliste")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_route_bestaetigt_und_bewertet_in_einem_schritt(
    buchhaltung, projekt_mit_stueckliste: dict[str, int]
) -> None:
    """Eine bestätigte Menge ohne Bewertung wäre eine Nachkalkulation, die zu gut aussieht."""
    schiene = next(p for p in liste_lesen(buchhaltung) if p["artikel_nr"] == "SCH-44")

    antwort = buchhaltung.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={"positionen": [{"id": schiene["id"], "menge_ist": "34", "stand": schiene["stand"]}]},
    )
    assert antwort.status_code == 200, antwort.text
    inhalt = antwort.json()
    assert inhalt["bewertet"] == 2
    assert inhalt["betrag_cent"] == 74460 + 36250
    assert inhalt["offene_mengen"] is True, "das Kabel ist noch nicht gezählt"
    assert "Mengen aus" in inhalt["meldung"]


def test_route_meldet_wenn_alles_gezaehlt_ist(
    buchhaltung, projekt_mit_stueckliste: dict[str, int]
) -> None:
    lager = [p for p in liste_lesen(buchhaltung) if p["quelle"] == "lager"]
    antwort = buchhaltung.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={
            "positionen": [
                {"id": p["id"], "menge_ist": p["menge_soll"], "stand": p["stand"]} for p in lager
            ]
        },
    )
    inhalt = antwort.json()
    assert inhalt["offene_mengen"] is False
    assert "alle Mengen sind bestätigt" in inhalt["meldung"]


def test_route_meldet_eine_position_ohne_einkaufspreis(
    buchhaltung, projekt_mit_stueckliste: dict[str, int]
) -> None:
    with schreib_sitzung() as sitzung:
        positionen(sitzung)["KAB-6"].ek_preis = None

    schiene = next(p for p in liste_lesen(buchhaltung) if p["artikel_nr"] == "SCH-44")
    antwort = buchhaltung.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={"positionen": [{"id": schiene["id"], "menge_ist": "36", "stand": schiene["stand"]}]},
    )
    inhalt = antwort.json()
    assert inhalt["ohne_preis"] == 1
    assert "Kalkulationsblatt" in inhalt["meldung"]


def test_route_meldet_einen_veralteten_stand(
    buchhaltung, projekt_mit_stueckliste: dict[str, int]
) -> None:
    schiene = next(p for p in liste_lesen(buchhaltung) if p["artikel_nr"] == "SCH-44")
    buchhaltung.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={"positionen": [{"id": schiene["id"], "menge_ist": "34", "stand": schiene["stand"]}]},
    )
    zweite = buchhaltung.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={"positionen": [{"id": schiene["id"], "menge_ist": "30", "stand": schiene["stand"]}]},
    )
    assert zweite.status_code == 409
    assert "Stücklistenposition" in zweite.json()["meldung"]


def test_route_weist_eine_fremde_position_ab(
    buchhaltung, projekt_mit_stueckliste: dict[str, int]
) -> None:
    vorhanden = liste_lesen(buchhaltung)[0]
    antwort = buchhaltung.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={"positionen": [{"id": 99999, "menge_ist": "1", "stand": vorhanden["stand"]}]},
    )
    assert antwort.status_code == 404
    assert "Stückliste neu laden" in antwort.json()["naechster_schritt"]


def test_team_sieht_die_liste_darf_aber_nicht_bestaetigen(
    client, nutzer_erzeugen, projekt_mit_stueckliste: dict[str, int]
) -> None:
    """Mengen zählen ist Projektpflege; sie zu sehen reicht dafür nicht (PLAN §4)."""
    nutzer_erzeugen("team@ip3-energie.de", "team")
    team = anmelden(client, "team@ip3-energie.de")

    assert team.client.get("/api/projekte/26001/stueckliste").status_code == 200
    antwort = team.schreiben(
        "POST",
        "/api/projekte/26001/mengen-ist",
        json={"positionen": [{"id": 1, "menge_ist": "1", "stand": "2026-08-28T00:00:00Z"}]},
    )
    assert antwort.status_code == 403
