"""Nachkalkulation je Projekt (PLAN §7 Phase 4, §6.5, §6.6).

Das Akzeptanzkriterium der Phase steht in
:func:`test_testprojekt_mit_allen_drei_ist_quellen_rechnet_nachvollziehbar`: ein Projekt mit
DATEV-Kosten, bewerteter Stückliste und TimeTac-Stunden muss auf den Cent aufgehen, und die
Doppelbelastungsprüfung muss greifen.

Geprüft wird der Dienst, nicht die Route: die Rechenregeln sind der Teil, der stimmen muss, und
sie gelten ab Phase 5 auch für das Firmen-Cockpit.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import nachkalkulation as dienst
from app.modelle import (
    Firma,
    IstKosten,
    Kunde,
    Nachtrag,
    Projekt,
    SollKalkulation,
    Stuecklistenposition,
    Zahlungsplanposition,
)


def alle_projekte():
    return select(Projekt)


def kunde_und_firma(sitzung, nummer: int = 18001) -> tuple[int, int]:
    firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
    kunde = Kunde(kunden_nr=nummer, name="Nachkalkulation GmbH", ort="Weiden", typ="b2b")
    sitzung.add(kunde)
    sitzung.flush()
    return firma_id, kunde.id


def projekt_anlegen(sitzung, nummer: int, *, ab_wert: int | None, status: str = "abgeschlossen"):
    firma_id, kunde_id = kunde_und_firma(sitzung, 18000 + nummer % 1000)
    projekt = Projekt(
        projekt_nr=nummer,
        firma_id=firma_id,
        kunde_id=kunde_id,
        status=status,
        ab_wert_netto=ab_wert,
        pl_name="Stefan",
    )
    sitzung.add(projekt)
    sitzung.flush()
    return projekt


def ist_kosten_anlegen(sitzung, projekt_id: int, quelle: str, betrag: int, monat="2026-07"):
    sitzung.add(
        IstKosten(
            projekt_id=projekt_id,
            quelle=quelle,
            monat=monat,
            betrag=betrag,
            referenz=f"Test {quelle}",
        )
    )
    sitzung.flush()


# ---------------------------------------------------------------------------
# Akzeptanzkriterium PLAN §7
# ---------------------------------------------------------------------------


@pytest.fixture
def testprojekt(tmp_path, gesäte_db) -> int:
    """Ein Projekt mit allen drei Ist-Quellen – **über die echten Importe**, nicht von Hand.

    Das ist der Punkt: die Ist-Zeilen entstehen durch dieselben Funktionen, die im Betrieb
    laufen. Ein Fixture, das die Beträge selbst hinschreibt, prüft am Ende nur sich selbst und
    läuft irgendwann auseinander.

    | Größe | Wert | Herkunft |
    |---|---|---|
    | Auftragswert | 100.000,00 € | Projektmaske |
    | Nachtrag (beauftragt) | 8.000,00 € | Nachträge |
    | **Erlös** | **108.000,00 €** | |
    | DATEV | 41.500,50 € | Kostenträgerimport, Konto 3400 |
    | Stückliste | 788,40 € | 36 × 21,90 € Lagerentnahme |
    | TimeTac | 10.242,50 € | 120,5 h × 85,00 € |
    | **Ist** | **52.531,40 €** | |
    | **Marge** | **55.468,60 €** = 51,4 % | Sollmarge 18 % |
    """
    from app.dienste import stueckliste as stuecklistendienst
    from app.importe.datev import kostentraeger_lesen
    from app.importe.datev import uebernehmen as datev_uebernehmen
    from app.importe.timetac import Stundenlieferung, Zeitbuchung
    from app.importe.timetac import uebernehmen as timetac_uebernehmen
    from app.konfiguration import KostentraegerEinstellungen, StundensaetzeEinstellungen

    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26001, ab_wert=10000000)
        projekt_id = projekt.id
        sitzung.add(
            Nachtrag(
                projekt_id=projekt_id,
                bezeichnung="Wallbox",
                betrag_netto=800000,
                status="beauftragt",
            )
        )
        sitzung.add(
            SollKalkulation(
                projekt_id=projekt_id,
                material_soll=4500000,
                dl_soll=800000,
                stunden_soll=Decimal("130.00"),
                marge_soll=180,
            )
        )
        # Stückliste mit beiden Quellen (PLAN §6.5): das Modul kommt über DATEV, die Schiene
        # aus dem Lager. Nur die Schiene wird bewertet.
        sitzung.add(
            Stuecklistenposition(
                projekt_id=projekt_id,
                artikel_nr="MOD-450",
                bezeichnung="Modul 450 Wp",
                menge_soll=Decimal("88.000"),
                menge_ist=Decimal("88.000"),
                ek_preis=9240,
                quelle="projektbestellt",
            )
        )
        sitzung.add(
            Stuecklistenposition(
                projekt_id=projekt_id,
                artikel_nr="SCH-44",
                bezeichnung="Montageschiene",
                menge_soll=Decimal("36.000"),
                menge_ist=Decimal("36.000"),
                ek_preis=2190,
                quelle="lager",
            )
        )

    # 1. DATEV-Kostenträger
    pfad = tmp_path / "kostentraeger_2026-07.csv"
    pfad.write_text(
        "Belegdatum;Konto;Kontobezeichnung;Buchungstext;Belegfeld 1;Umsatz;"
        "Soll/Haben-Kennzeichen;KOST2\n"
        "05.07.2026;3400;Wareneingang 19 % VSt;Module;RE-4711;41.500,50;S;26001\n",
        encoding="utf-8",
    )
    with schreib_sitzung() as sitzung:
        datev_uebernehmen(sitzung, kostentraeger_lesen(pfad, KostentraegerEinstellungen()))

    # 2. Lagerbewertung
    with schreib_sitzung() as sitzung:
        stuecklistendienst.bewerten(sitzung, sitzung.get(Projekt, projekt_id), monat="2026-07")

    # 3. TimeTac-Stunden
    with schreib_sitzung() as sitzung:
        timetac_uebernehmen(
            sitzung,
            Stundenlieferung(
                herkunft="test",
                monate=["2026-07"],
                buchungen=[
                    Zeitbuchung(
                        herkunft="test",
                        zeile=2,
                        projekt_text="26001 Nachkalkulation GmbH",
                        mitarbeiter="Wilhelm, Sven",
                        datum=date(2026, 7, 6),
                        stunden=Decimal("120.50"),
                    )
                ],
            ),
            StundensaetzeEinstellungen(mitarbeiter={"Wilhelm, Sven": "planung"}),
        )
    return projekt_id


def test_testprojekt_mit_allen_drei_ist_quellen_rechnet_nachvollziehbar(
    testprojekt: int,
) -> None:
    """Akzeptanzkriterium PLAN §7 Phase 4."""
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]

    assert zeile.ab_wert_cent == 10000000
    assert zeile.nachtraege_cent == 800000
    assert zeile.erloes_cent == 10800000

    assert zeile.ist_datev_cent == 4150050
    assert zeile.ist_stueckliste_cent == 78840, "36 × 21,90 € – nur die Lagerposition"
    assert zeile.ist_timetac_cent == 1024250, "120,5 h × 85,00 €"
    assert zeile.ist_cent == 5253140, "die drei Quellen ergeben zusammen den Ist"
    assert zeile.ist_material_cent == 4150050 + 78840

    assert zeile.marge_cent == 10800000 - 5253140 == 5546860
    assert zeile.marge_promille == 514, "51,4 % Marge auf den Erlös"
    assert zeile.ampel == "im_soll"
    assert zeile.abweichung_promille == 514 - 180

    assert zeile.soll_cent == 5300000
    assert zeile.soll_ist_abweichung_cent == 5253140 - 5300000, "468,60 € unter dem Soll"
    assert zeile.stunden_ist == Decimal("120.50")
    assert zeile.stunden_abweichung == Decimal("-9.50")
    assert zeile.hinweise == []


def test_stunden_werden_nicht_doppelt_gezaehlt(testprojekt: int) -> None:
    """``stunden`` ist Detail, ``ist_kosten`` die Summe – wer beides addiert, zählt doppelt."""
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    # 120,5 h * 85,00 € = 10.242,50 € – genau einmal im Ist.
    assert zeile.ist_cent == 4150050 + 78840 + 1024250
    assert zeile.stunden_ist == Decimal("120.50")


# ---------------------------------------------------------------------------
# Marge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("erloes", "ist", "erwartet"),
    [
        (10000000, 8200000, 180),  # 18,0 %
        (10000000, 10000000, 0),
        (10000000, 12000000, -200),  # Verlust
        (10000000, 0, 1000),  # 100 %
    ],
)
def test_marge_auf_den_erloes(gesäte_db, erloes: int, ist: int, erwartet: int) -> None:
    """Entscheidung Svens: Marge € geteilt durch Erlös, nicht durch die Kosten."""
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26002, ab_wert=erloes)
        if ist:
            ist_kosten_anlegen(sitzung, projekt.id, "datev", ist)
    with lese_sitzung() as sitzung:
        assert dienst.uebersicht(sitzung, alle_projekte()).projekte[0].marge_promille == erwartet


def test_ohne_auftragswert_keine_marge(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26003, ab_wert=None)
        ist_kosten_anlegen(sitzung, projekt.id, "datev", 500000)
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]

    assert zeile.erloes_cent is None
    assert zeile.marge_cent is None and zeile.marge_promille is None
    assert zeile.ampel == "ohne_soll"
    assert zeile.ist_cent == 500000, "der Ist steht trotzdem"
    assert [h.code for h in zeile.hinweise] == ["ohne_auftragswert", "ohne_kalkulation"]


def test_nachtraege_zaehlen_nach_derselben_regel_wie_im_umsatz(gesäte_db) -> None:
    """PLAN §6.12: 'angeboten' ist kein Auftrag, 'beauftragt' und 'berechnet' zählen."""
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26004, ab_wert=10000000)
        for bezeichnung, betrag, status in (
            ("Angebot", 500000, "angeboten"),
            ("Beauftragt", 300000, "beauftragt"),
            ("Berechnet", 200000, "berechnet"),
        ):
            sitzung.add(
                Nachtrag(
                    projekt_id=projekt.id,
                    bezeichnung=bezeichnung,
                    betrag_netto=betrag,
                    status=status,
                )
            )
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    assert zeile.nachtraege_cent == 500000
    assert zeile.erloes_cent == 10500000


def test_fakturierter_betrag_steht_neben_dem_erloes(gesäte_db) -> None:
    """Weichen beide ab, sagt es die Ansicht – geschätzt wird nichts."""
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26005, ab_wert=10000000)
        sitzung.add(
            Zahlungsplanposition(
                projekt_id=projekt.id,
                pos_nr=1,
                bezeichnung="Abschlag 1",
                gewerk="pv",
                art="abschlag",
                betrag_netto=3000000,
                migriert_gestellt=True,
            )
        )
        sitzung.add(
            Zahlungsplanposition(
                projekt_id=projekt.id,
                pos_nr=2,
                bezeichnung="Abschlag 2",
                gewerk="pv",
                art="abschlag",
                betrag_netto=4000000,
            )
        )
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    assert zeile.erloes_cent == 10000000
    assert zeile.fakturiert_cent == 3000000, "nur die gestellte Position zählt"


# ---------------------------------------------------------------------------
# Ampel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ist", "erwartet"),
    [
        (8200000, "im_soll"),  # 18,0 % – genau auf dem Soll
        (8000000, "im_soll"),  # 20,0 %
        (8600000, "knapp"),  # 14,0 % – 4 Prozentpunkte darunter
        (8700000, "knapp"),  # 13,0 % – genau 5 Prozentpunkte darunter
        (8800000, "unter_soll"),  # 12,0 %
    ],
)
def test_ampel_gegen_die_sollmarge(gesäte_db, ist: int, erwartet: str) -> None:
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26006, ab_wert=10000000)
        sitzung.add(SollKalkulation(projekt_id=projekt.id, marge_soll=180))
        ist_kosten_anlegen(sitzung, projekt.id, "datev", ist)
    with lese_sitzung() as sitzung:
        assert dienst.uebersicht(sitzung, alle_projekte()).projekte[0].ampel == erwartet


def test_ohne_kalkulationsblatt_keine_ampel(gesäte_db) -> None:
    """Für die 539 migrierten Projekte der Regelfall – eine Null als Soll wäre eine Behauptung."""
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26007, ab_wert=10000000)
        ist_kosten_anlegen(sitzung, projekt.id, "datev", 5000000)
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]

    assert zeile.marge_promille == 500, "die Marge steht, sie hat nur kein Soll zum Vergleich"
    assert zeile.ampel == "ohne_soll"
    assert zeile.soll_cent is None and zeile.soll_ist_abweichung_cent is None
    assert "ohne_kalkulation" in [h.code for h in zeile.hinweise]


def test_eigene_gelbschwelle(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26008, ab_wert=10000000)
        sitzung.add(SollKalkulation(projekt_id=projekt.id, marge_soll=180))
        ist_kosten_anlegen(sitzung, projekt.id, "datev", 8600000)  # 14 %
    with lese_sitzung() as sitzung:
        streng = dienst.uebersicht(sitzung, alle_projekte(), ampel_gelb_promille=20)
        großzuegig = dienst.uebersicht(sitzung, alle_projekte(), ampel_gelb_promille=100)
    assert streng.projekte[0].ampel == "unter_soll"
    assert großzuegig.projekte[0].ampel == "knapp"


# ---------------------------------------------------------------------------
# Doppelbelastungsprüfung (PLAN §6.5)
# ---------------------------------------------------------------------------


def test_datev_kosten_ohne_projektbestellte_position_ist_verdaechtig(gesäte_db) -> None:
    """Richtung 1: Material könnte doppelt im Ist stehen."""
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26010, ab_wert=10000000)
        sitzung.add(
            Stuecklistenposition(
                projekt_id=projekt.id,
                bezeichnung="Schiene",
                menge_soll=Decimal("10.000"),
                menge_ist=Decimal("10.000"),
                ek_preis=1000,
                quelle="lager",
            )
        )
        ist_kosten_anlegen(sitzung, projekt.id, "datev", 500000)
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    assert "doppelbelastung_verdacht" in [h.code for h in zeile.hinweise]


def test_projektbestellte_position_ohne_datev_kosten_ist_eine_luecke(gesäte_db) -> None:
    """Richtung 2: das Ist ist zu niedrig, solange die Kostenträgerbuchungen fehlen."""
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26011, ab_wert=10000000)
        sitzung.add(
            Stuecklistenposition(
                projekt_id=projekt.id,
                bezeichnung="Modul",
                menge_soll=Decimal("88.000"),
                ek_preis=9240,
                quelle="projektbestellt",
            )
        )
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    assert "material_fehlt" in [h.code for h in zeile.hinweise]


def test_gemischte_stueckliste_mit_datev_kosten_ist_in_ordnung(testprojekt: int) -> None:
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    codes = [h.code for h in zeile.hinweise]
    assert "doppelbelastung_verdacht" not in codes
    assert "material_fehlt" not in codes


def test_offene_mengen_werden_gemeldet(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        projekt = projekt_anlegen(sitzung, 26012, ab_wert=10000000)
        sitzung.add(
            Stuecklistenposition(
                projekt_id=projekt.id,
                bezeichnung="Schiene",
                menge_soll=Decimal("36.000"),
                ek_preis=2190,
                quelle="lager",
            )
        )
        sitzung.add(
            Stuecklistenposition(
                projekt_id=projekt.id,
                bezeichnung="Modul",
                menge_soll=Decimal("88.000"),
                ek_preis=9240,
                quelle="projektbestellt",
            )
        )
        ist_kosten_anlegen(sitzung, projekt.id, "datev", 812000)
    with lese_sitzung() as sitzung:
        zeile = dienst.uebersicht(sitzung, alle_projekte()).projekte[0]
    hinweis = next(h for h in zeile.hinweise if h.code == "mengen_ist_offen")
    assert "1 Lagerpositionen" in hinweis.text


# ---------------------------------------------------------------------------
# Übersicht
# ---------------------------------------------------------------------------


@pytest.fixture
def drei_projekte(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        gut = projekt_anlegen(sitzung, 26021, ab_wert=10000000)
        sitzung.add(SollKalkulation(projekt_id=gut.id, marge_soll=180))
        ist_kosten_anlegen(sitzung, gut.id, "datev", 7000000)  # 30 %

        schlecht = projekt_anlegen(sitzung, 26022, ab_wert=10000000)
        sitzung.add(SollKalkulation(projekt_id=schlecht.id, marge_soll=180))
        ist_kosten_anlegen(sitzung, schlecht.id, "datev", 9500000)  # 5 %

        projekt_anlegen(sitzung, 26023, ab_wert=None, status="in_bau")

        # Ein Angebot und ein storniertes Projekt gehören nicht in die Übersicht.
        projekt_anlegen(sitzung, 26024, ab_wert=5000000, status="angebot")
        projekt_anlegen(sitzung, 26025, ab_wert=5000000, status="storniert")


def test_uebersicht_sortiert_die_schwaechste_marge_nach_oben(drei_projekte) -> None:
    with lese_sitzung() as sitzung:
        gefunden = dienst.uebersicht(sitzung, alle_projekte())
    assert [p.projekt_nr for p in gefunden.projekte] == [26022, 26021, 26023]


def test_angebot_und_storniertes_projekt_bleiben_draussen(drei_projekte) -> None:
    with lese_sitzung() as sitzung:
        nummern = [p.projekt_nr for p in dienst.uebersicht(sitzung, alle_projekte()).projekte]
    assert 26024 not in nummern and 26025 not in nummern


def test_summen_der_uebersicht(drei_projekte) -> None:
    with lese_sitzung() as sitzung:
        gefunden = dienst.uebersicht(sitzung, alle_projekte())

    assert gefunden.erloes_cent == 20000000
    assert gefunden.ist_cent == 16500000
    assert gefunden.marge_cent == 3500000
    assert gefunden.marge_promille == 175
    assert [p.projekt_nr for p in gefunden.ohne_kalkulation] == [26023]


def test_ein_projekt_ohne_erloes_verfaelscht_die_gesamtmarge_nicht(drei_projekte) -> None:
    """Sonst stünde Ist ohne Erlös in der Summe und die Gesamtmarge wäre zu schlecht."""
    with schreib_sitzung() as sitzung:
        ohne = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26023))
        ist_kosten_anlegen(sitzung, ohne.id, "datev", 900000)
    with lese_sitzung() as sitzung:
        gefunden = dienst.uebersicht(sitzung, alle_projekte())
    assert gefunden.marge_cent == 3500000
    assert gefunden.marge_promille == 175


def test_fuer_projekt_zeigt_auch_ein_angebot(drei_projekte) -> None:
    with lese_sitzung() as sitzung:
        angebot = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26024))
        zeile = dienst.fuer_projekt(sitzung, angebot)
    assert zeile.projekt_nr == 26024 and zeile.status == "angebot"


def test_leere_auswahl_ergibt_eine_leere_uebersicht(gesäte_db) -> None:
    with lese_sitzung() as sitzung:
        gefunden = dienst.uebersicht(sitzung, alle_projekte())
    assert gefunden.projekte == []
    assert gefunden.marge_promille is None
