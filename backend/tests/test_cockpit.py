"""Firmen-Cockpit: vom Umsatz zur Über-/Unterdeckung (PLAN §7 Phase 5).

Zugleich das Akzeptanzkriterium der Phase: ein Monat mit Umsatz, variablen Kosten und
Fixkosten rechnet auf den Cent nachvollziehbar durch.

Die vier Stellen, an denen die Zahlen kippen würden:

* **Eigenleistung darf auf Firmenebene nicht zählen** (PLAN §6.6). Die TimeTac-Stunden stehen
  im Projekt-Ist; die echten Personalkosten stehen in der SuSa. Beides zu addieren zählte
  Personal doppelt und drückte den Deckungsbeitrag um einen erfundenen Betrag.
* **Fixkosten kommen aus der SuSa oder aus dem Plan, nie aus beidem.** Ein Monat mit
  Buchhaltung *und* Planwerten dürfte die Fixkosten nicht verdoppeln.
* **Der Block 'neutral' zählt nicht mit**, ein Konto ohne Zuordnung ebenfalls nicht – aber aus
  verschiedenen Gründen, und nur das zweite ist ein Pflegehinweis.
* **Break-even und Reichweite brauchen eine Marge.** Ohne Umsatz gibt es keine, und dann darf
  auch keine Zahl dastehen.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import cockpit
from app.modelle import (
    DatevSaldo,
    Firma,
    FixkostenPlan,
    IstKosten,
    Kunde,
    Projekt,
    Rechnung,
    Zahlungsplanposition,
)

MONAT = "2026-07"
SKONTO = 3.0


def sichtbare():
    return select(Projekt)


@pytest.fixture
def projekt(gesäte_db) -> int:
    """Ein Projekt mit Auftragswert, an dem die Ist-Kosten hängen."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=18001, name="Mustermann GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        eintrag = Projekt(
            projekt_nr=26001,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            standort="Weiden",
            ab_wert_netto=50_000_000,
        )
        sitzung.add(eintrag)
        sitzung.flush()
        return eintrag.id


def umsatz_buchen(projekt_id: int, *, monat: str, betrag_cent: int, nummer: str) -> None:
    """Eine festgeschriebene Rechnung samt der Zahlungsplanposition, die sie abrechnet.

    Der Ist-Umsatz aus Phase 2 hängt an der Position über ``rechnung_id`` (siehe
    ``auswertung.ist_bedingung``), nicht am Beleg allein – deshalb beides und verknüpft, sonst
    rechnet das Cockpit mit null.
    """
    jahr, mon = (int(teil) for teil in monat.split("-"))
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
        rechnung = Rechnung(
            rechnung_nr=nummer,
            firma_id=firma_id,
            art="abschlag",
            projekt_id=projekt_id,
            kunde_id=kunde_id,
            kunde_snapshot={"name": "Mustermann GmbH"},
            datum=date(jahr, mon, 15),
            faellig_am=date(jahr, mon, 28),
            netto=betrag_cent,
            brutto=betrag_cent,
            zahlbetrag=betrag_cent,
            status="festgeschrieben",
        )
        sitzung.add(rechnung)
        sitzung.flush()

        vorhandene = sitzung.scalar(
            select(func.count())
            .select_from(Zahlungsplanposition)
            .where(Zahlungsplanposition.projekt_id == projekt_id)
        )
        sitzung.add(
            Zahlungsplanposition(
                projekt_id=projekt_id,
                pos_nr=(vorhandene or 0) + 1,
                bezeichnung=f"Abschlag {nummer}",
                gewerk="pv",
                art="abschlag",
                betrag_netto=betrag_cent,
                plan_monat=monat,
                rechnung_id=rechnung.id,
                created_by="test",
            )
        )


def kosten_buchen(projekt_id: int, *, quelle: str, betrag_cent: int, monat: str = MONAT) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(
            IstKosten(
                projekt_id=projekt_id,
                quelle=quelle,
                monat=monat,
                betrag=betrag_cent,
                referenz=f"Test {quelle}",
            )
        )


def salden_buchen(*eintraege: tuple[str, str | None, int], monat: str = MONAT) -> None:
    with schreib_sitzung() as sitzung:
        for konto, block, betrag in eintraege:
            sitzung.add(
                DatevSaldo(monat=monat, konto=konto, bezeichnung=konto, saldo=betrag, block=block)
            )


def ansicht(monat: str = MONAT, **kwargs):
    with lese_sitzung() as sitzung:
        return cockpit.monatsansicht(
            sitzung, sichtbare(), monat=monat, skonto_prozent=SKONTO, **kwargs
        )


# ---------------------------------------------------------------------------
# Der Rechenweg
# ---------------------------------------------------------------------------


def test_vom_umsatz_zur_ueberdeckung(projekt: int) -> None:
    """Das Akzeptanzkriterium: jede Zahl ist auf ihre Quelle zurückzuführen."""
    umsatz_buchen(projekt, monat=MONAT, betrag_cent=20_000_000, nummer="RE-2026-0001")
    kosten_buchen(projekt, quelle="datev", betrag_cent=11_000_000)
    kosten_buchen(projekt, quelle="stueckliste", betrag_cent=1_500_000)
    salden_buchen(("4120", "personal", 4_000_000), ("4210", "raum", 500_000))

    monat = ansicht().aktueller

    assert monat.umsatz_cent == 20_000_000
    assert monat.variable_kosten_cent == 12_500_000
    assert monat.deckungsbeitrag_cent == 7_500_000
    assert monat.fixkosten_cent == 4_500_000
    assert monat.deckung_cent == 3_000_000
    assert monat.db_promille == 375
    # 7.500.000 / 4.500.000 = 166,67 % – kaufmännisch gerundet 1667 Promille.
    assert monat.fixkostendeckung_promille == 1667


def test_eigenleistung_zaehlt_auf_firmenebene_nicht(projekt: int) -> None:
    """PLAN §6.6: sonst stünde das Personal doppelt drin – einmal kalkulatorisch, einmal echt."""
    umsatz_buchen(projekt, monat=MONAT, betrag_cent=20_000_000, nummer="RE-2026-0001")
    kosten_buchen(projekt, quelle="datev", betrag_cent=11_000_000)
    kosten_buchen(projekt, quelle="timetac", betrag_cent=3_000_000)
    salden_buchen(("4120", "personal", 4_000_000))

    monat = ansicht().aktueller

    assert monat.variable_kosten_cent == 11_000_000, "die TimeTac-Stunden gehören nicht hierher"
    assert monat.deckungsbeitrag_cent == 9_000_000
    # Das Personal steht genau einmal drin: als echte Kosten im Fixkostenblock.
    assert monat.fixkosten_cent == 4_000_000


def test_kumulierte_deckung_bis_zum_gewaehlten_monat(projekt: int) -> None:
    for nummer, monat, umsatz in (
        ("RE-2026-0001", "2026-05", 10_000_000),
        ("RE-2026-0002", "2026-06", 10_000_000),
        ("RE-2026-0003", "2026-07", 10_000_000),
    ):
        umsatz_buchen(projekt, monat=monat, betrag_cent=umsatz, nummer=nummer)
        kosten_buchen(projekt, quelle="datev", betrag_cent=6_000_000, monat=monat)
        salden_buchen(("4120", "personal", 3_000_000), monat=monat)

    # August hat schon Fixkosten, aber noch keinen Umsatz – er darf nicht mitzählen.
    salden_buchen(("4120", "personal", 3_000_000), monat="2026-08")

    assert ansicht("2026-06").kumuliert_cent == 2_000_000
    assert ansicht("2026-07").kumuliert_cent == 3_000_000


# ---------------------------------------------------------------------------
# Fixkosten: Ist schlägt Plan
# ---------------------------------------------------------------------------


def test_susa_schlaegt_den_plan(projekt: int) -> None:
    """Ein Monat hat entweder Buchhaltung oder Planung, nie beides addiert."""
    salden_buchen(("4120", "personal", 4_000_000))
    with schreib_sitzung() as sitzung:
        sitzung.add(FixkostenPlan(monat=MONAT, block="personal", betrag=9_900_000))

    block = ansicht().fixkosten
    assert block.herkunft == "susa"
    assert block.summe_cent == 4_000_000


def test_zukunftsmonat_nimmt_den_plan(projekt: int) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(FixkostenPlan(monat="2026-12", block="personal", betrag=4_000_000))
        sitzung.add(FixkostenPlan(monat="2026-12", block="raum", betrag=500_000))

    block = ansicht("2026-12").fixkosten
    assert block.herkunft == "plan"
    assert block.summe_cent == 4_500_000


def test_neutraler_block_zaehlt_nicht(projekt: int) -> None:
    """Durchlaufende Posten sind zugeordnet und gehören trotzdem nicht in die Fixkosten."""
    salden_buchen(
        ("4120", "personal", 4_000_000),
        ("1600", "neutral", 9_000_000),
    )

    assert ansicht().fixkosten.summe_cent == 4_000_000


def test_konto_ohne_zuordnung_zaehlt_nicht_und_wird_gemeldet(projekt: int) -> None:
    """Der Unterschied zu 'neutral': hier hat es noch niemand angesehen."""
    salden_buchen(("4120", "personal", 4_000_000), ("4700", None, 1_200_000))

    ergebnis = ansicht()
    assert ergebnis.fixkosten.summe_cent == 4_000_000
    assert any("keinem Kostenblock zugeordnet" in h for h in ergebnis.hinweise)
    # Geschütztes Leerzeichen vor der Einheit (CD-Regel, PLAN §11).
    assert any("12.000,00\u00a0€" in h for h in ergebnis.hinweise)


def test_ohne_fixkosten_kommt_ein_hinweis(projekt: int) -> None:
    umsatz_buchen(projekt, monat=MONAT, betrag_cent=20_000_000, nummer="RE-2026-0001")

    ergebnis = ansicht()
    assert ergebnis.fixkosten.herkunft == "keine"
    assert any("weder eine Summen- und Saldenliste noch Planwerte" in h for h in ergebnis.hinweise)


def test_planwerte_werden_als_solche_ausgewiesen(projekt: int) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(FixkostenPlan(monat=MONAT, block="personal", betrag=4_000_000))

    assert any("Planwerte" in h for h in ansicht().hinweise)


# ---------------------------------------------------------------------------
# Kennzahlen
# ---------------------------------------------------------------------------


def test_break_even_ueber_die_jahresmarge(projekt: int) -> None:
    """Entscheidung 27: Basis ist das laufende Jahr bis zum gewählten Monat."""
    for nummer, monat in (
        ("RE-2026-0001", "2026-05"),
        ("RE-2026-0002", "2026-06"),
        ("RE-2026-0003", "2026-07"),
    ):
        umsatz_buchen(projekt, monat=monat, betrag_cent=10_000_000, nummer=nummer)
        kosten_buchen(projekt, quelle="datev", betrag_cent=7_500_000, monat=monat)
    salden_buchen(("4120", "personal", 1_500_000))

    kennzahlen = ansicht().kennzahlen
    assert kennzahlen.marge_promille == 250  # 25 % über drei Monate
    assert kennzahlen.marge_monate == 3
    # 15.000 € Fixkosten bei 25 % Marge -> 60.000 € Monatsumsatz.
    assert kennzahlen.break_even_cent == 6_000_000


def test_duenne_margenbasis_wird_gemeldet(projekt: int) -> None:
    """Im Januar steht die Jahresmarge auf einem einzigen Monat."""
    umsatz_buchen(projekt, monat="2026-01", betrag_cent=10_000_000, nummer="RE-2026-0001")
    kosten_buchen(projekt, quelle="datev", betrag_cent=7_000_000, monat="2026-01")

    ergebnis = ansicht("2026-01")
    assert ergebnis.kennzahlen.marge_monate == 1
    assert any("steht auf 1 Monat" in h for h in ergebnis.hinweise)


def test_ohne_umsatz_keine_marge_und_kein_break_even(projekt: int) -> None:
    salden_buchen(("4120", "personal", 4_000_000))

    kennzahlen = ansicht().kennzahlen
    assert kennzahlen.marge_promille is None
    assert kennzahlen.break_even_cent is None
    assert kennzahlen.reichweite.fixkostenmonate is None


def test_reichweite_zeigt_beide_zahlen(projekt: int) -> None:
    """Entscheidung 26: Umsatzmonate groß, Fixkostenmonate als Unterzeile."""
    for nummer, monat in (("RE-2026-0001", "2026-06"), ("RE-2026-0002", "2026-07")):
        umsatz_buchen(projekt, monat=monat, betrag_cent=10_000_000, nummer=nummer)
        kosten_buchen(projekt, quelle="datev", betrag_cent=8_000_000, monat=monat)
    salden_buchen(("4120", "personal", 1_000_000))

    reichweite = ansicht().kennzahlen.reichweite
    # Auftragswert 500.000 € minus 200.000 € fakturiert = 300.000 € Bestand.
    assert reichweite.bestand_cent == 30_000_000
    # 300.000 € bei 100.000 € Durchschnittsumsatz.
    assert reichweite.umsatzmonate == 3.0
    # 20 % Marge auf 300.000 € = 60.000 € Deckungsbeitrag, bei 10.000 € Fixkosten je Monat.
    assert reichweite.deckungsbeitrag_cent == 6_000_000
    assert reichweite.fixkostenmonate == 6.0


# ---------------------------------------------------------------------------
# Umschalter gestellt / bezahlt
# ---------------------------------------------------------------------------


def test_umsatzbasis_bezahlt_ohne_opos_ist_leer(projekt: int) -> None:
    """Ohne OPOS-Import gilt keine Rechnung als bezahlt (PLAN §6.7)."""
    umsatz_buchen(projekt, monat=MONAT, betrag_cent=20_000_000, nummer="RE-2026-0001")

    ergebnis = ansicht(basis="bezahlt")
    assert ergebnis.aktueller.umsatz_cent == 0
    assert ergebnis.umsatzbasis == "bezahlt"
    assert any("Zahlungseingang laut OPOS" in h for h in ergebnis.hinweise)


def test_umsatzbasis_gestellt_und_bezahlt_unterscheiden_sich(projekt: int) -> None:
    from app.modelle import Opos

    umsatz_buchen(projekt, monat=MONAT, betrag_cent=20_000_000, nummer="RE-2026-0001")
    umsatz_buchen(projekt, monat=MONAT, betrag_cent=5_000_000, nummer="RE-2026-0002")
    with schreib_sitzung() as sitzung:
        # RE-0001 steht noch offen, RE-0002 fehlt in der Liste und gilt damit als bezahlt.
        sitzung.add(
            Opos(
                rechnung_nr="RE-2026-0001",
                betrag=20_000_000,
                offen_betrag=20_000_000,
                stand_datum=date(2026, 8, 31),
            )
        )

    assert ansicht().aktueller.umsatz_cent == 25_000_000
    assert ansicht(basis="bezahlt").aktueller.umsatz_cent == 5_000_000


def test_monate_mit_daten_sind_nie_leer(gesäte_db) -> None:
    """Die Monatswahl braucht immer mindestens einen Eintrag, sonst hängt die Ansicht."""
    with lese_sitzung() as sitzung:
        monate = cockpit.monate_mit_daten(sitzung, sichtbare())
    assert monate
