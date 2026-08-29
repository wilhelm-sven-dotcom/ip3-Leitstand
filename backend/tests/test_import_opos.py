"""Offene Posten und der Zahlungsstatus (PLAN §6.7, §6.13, §8).

Die Regel, die hier abgesichert wird, ist eine der strengsten des Plans: **gestellt ist nicht
bezahlt.** Der Leitstand kennt keine Kontoauszüge; ob eine Rechnung bezahlt ist, sagt
ausschließlich der OPOS-Import – und zwar durch Abwesenheit.

Drei Fälle, in denen eine naive Auswertung falsch läge:

* Eine Rechnung, die **jünger als der Stichtag** ist, fehlt in der Liste, weil es sie damals
  noch nicht gab. Sie als bezahlt zu zeigen wäre frei erfunden.
* Ein Kunde, der **Skonto gezogen** hat, bliebe mit seinem Restbetrag dauerhaft überfällig.
* Eine OPOS-Liste ist ein **Stichtag**, kein Monat. Zwei Stände desselben Monats stehen
  nebeneinander; nur derselbe Tag ersetzt.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import zahlungsstatus as zs
from app.importe.opos import StichtagUnbekannt, opos_lesen, stichtag_aus_dateiname, uebernehmen
from app.konfiguration import OposEinstellungen
from app.modelle import Firma, Importlauf, Kunde, Opos, Rechnung

KOPF = "Rechnungsnummer;Kunde;Rechnungsbetrag;Offener Betrag;Fälligkeit;Belegdatum"

ZEILEN = [
    "RE-2026-0001;Mustermann GmbH;119.000,00;119.000,00;15.07.2026;01.07.2026",
    "RE-2026-0002;Schmidt KG;23.800,00;23.800,00;20.08.2026;06.08.2026",
    "RE-2026-0003;Huber e.K.;11.900,00;238,00;25.07.2026;11.07.2026",
    ";Summe Debitor 10001;154.700,00;143.038,00;;",
]

SKONTO = 3.0


def datei_schreiben(pfad: Path, zeilen: list[str], *, kopf: str = KOPF) -> Path:
    pfad.write_text("\n".join([kopf, *zeilen]) + "\n", encoding="cp1252")
    return pfad


def standarddatei(ordner: Path, name: str = "opos_2026-08-31.csv") -> Path:
    return datei_schreiben(ordner / name, ZEILEN)


def einlesen(pfad: Path, **kwargs):
    return opos_lesen(pfad, OposEinstellungen(), **kwargs)


@pytest.fixture
def rechnungen(gesäte_db) -> None:
    """Drei festgeschriebene Rechnungen, passend zu den OPOS-Zeilen."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=17001, name="Mustermann GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        for nummer, datum, faellig, betrag, name in (
            ("RE-2026-0001", date(2026, 7, 1), date(2026, 7, 15), 11_900_000, "Mustermann GmbH"),
            ("RE-2026-0002", date(2026, 8, 6), date(2026, 8, 20), 2_380_000, "Schmidt KG"),
            ("RE-2026-0003", date(2026, 7, 11), date(2026, 7, 25), 1_190_000, "Huber e.K."),
            ("RE-2026-0004", date(2026, 6, 2), date(2026, 6, 16), 500_000, "Bezahlt AG"),
        ):
            sitzung.add(
                Rechnung(
                    rechnung_nr=nummer,
                    firma_id=firma_id,
                    art="abschlag",
                    kunde_id=kunde.id,
                    kunde_snapshot={"name": name},
                    datum=datum,
                    faellig_am=faellig,
                    netto=betrag,
                    brutto=betrag,
                    zahlbetrag=betrag,
                    status="festgeschrieben",
                )
            )


# ---------------------------------------------------------------------------
# Dateiname und Lesen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "erwartet"),
    [
        ("opos_2026-08-31.csv", date(2026, 8, 31)),
        ("opos_2026_08_31.csv", date(2026, 8, 31)),
        ("OPOS Debitoren 2026-12-31.csv", date(2026, 12, 31)),
        ("opos_2026-08.csv", None),  # nur Monat genügt nicht
        ("opos_2026-02-30.csv", None),  # den gibt es nicht
    ],
)
def test_stichtag_aus_dateiname(name: str, erwartet: date | None) -> None:
    assert stichtag_aus_dateiname(Path(name)) == erwartet


def test_ohne_stichtag_kommt_eine_verstaendliche_meldung(tmp_path) -> None:
    pfad = datei_schreiben(tmp_path / "opos.csv", ZEILEN)
    with pytest.raises(StichtagUnbekannt) as fehler:
        einlesen(pfad)
    assert "opos_JJJJ-MM-TT.csv" in fehler.value.naechster_schritt
    assert "Tag" in fehler.value.naechster_schritt


def test_posten_werden_gelesen(tmp_path) -> None:
    datei = einlesen(standarddatei(tmp_path))

    assert [p.rechnung_nr for p in datei.posten] == [
        "RE-2026-0001",
        "RE-2026-0002",
        "RE-2026-0003",
    ]
    assert datei.offen_cent == 11_900_000 + 2_380_000 + 23_800
    # Stichtag ist der 31.08.; alle drei waren bis dahin fällig (15.07., 20.08., 25.07.).
    assert [p.rechnung_nr for p in datei.ueberfaellig()] == [
        "RE-2026-0001",
        "RE-2026-0002",
        "RE-2026-0003",
    ]


def test_ohne_rechnungsbetrag_zaehlt_der_rest(tmp_path) -> None:
    """Führt die Liste nur den Restbetrag, ist das kein Fehler."""
    pfad = datei_schreiben(
        tmp_path / "opos_2026-08-31.csv",
        ["RE-2026-0001;Mustermann;;500,00;15.07.2026;01.07.2026"],
    )
    datei = einlesen(pfad)

    assert datei.posten[0].offen_cent == 50_000
    assert datei.posten[0].betrag_cent == 50_000
    assert datei.befunde == []


def test_zweiter_stichtag_steht_neben_dem_ersten(rechnungen, tmp_path) -> None:
    """Eine OPOS-Liste ist ein Stichtag, kein Monat – der Verlauf muss erhalten bleiben."""
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))
    zweiter = datei_schreiben(
        tmp_path / "opos_2026-09-30.csv",
        ["RE-2026-0002;Schmidt KG;23.800,00;23.800,00;20.08.2026;06.08.2026"],
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, einlesen(zweiter))

    assert ergebnis.geloescht == 0
    with lese_sitzung() as sitzung:
        staende = sitzung.scalars(select(Opos.stand_datum).distinct()).all()
    assert sorted(staende) == [date(2026, 8, 31), date(2026, 9, 30)]


def test_derselbe_stichtag_ersetzt(rechnungen, tmp_path) -> None:
    pfad = standarddatei(tmp_path)
    with schreib_sitzung() as sitzung:
        erst = uebernehmen(sitzung, einlesen(pfad))
    with schreib_sitzung() as sitzung:
        zweit = uebernehmen(sitzung, einlesen(pfad))

    assert zweit.geloescht == erst.posten
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(func.count()).select_from(Opos)) == erst.posten


def test_teilzahlungen_derselben_rechnung_werden_verdichtet(rechnungen, tmp_path) -> None:
    pfad = datei_schreiben(
        tmp_path / "opos_2026-08-31.csv",
        [
            "RE-2026-0001;Mustermann;119.000,00;60.000,00;15.07.2026;01.07.2026",
            "RE-2026-0001;Mustermann;119.000,00;59.000,00;15.07.2026;01.07.2026",
        ],
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, einlesen(pfad))

    assert ergebnis.posten == 1
    with lese_sitzung() as sitzung:
        posten = sitzung.scalar(select(Opos))
        assert posten is not None
        assert posten.offen_betrag == 11_900_000


def test_unbekannte_belegnummer_wird_protokolliert_aber_nicht_gewarnt(rechnungen, tmp_path) -> None:
    """Altbestandsbelege sind der Regelfall, solange PLAN §8 'AR-Altbestand' nicht gelaufen ist."""
    pfad = datei_schreiben(
        tmp_path / "opos_2026-08-31.csv",
        ["RE-2025-0999;Alter Kunde;5.000,00;5.000,00;01.02.2025;15.01.2025"],
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, einlesen(pfad))

    assert ergebnis.unbekannte_rechnungen == ["RE-2025-0999"]
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(Importlauf).where(Importlauf.quelle == "opos"))
        assert lauf is not None
        assert lauf.status == "erfolg"


# ---------------------------------------------------------------------------
# Zahlungsstatus
# ---------------------------------------------------------------------------


def test_ohne_opos_import_ist_nichts_bezahlt(rechnungen) -> None:
    """Der teuerste Denkfehler wäre, aus 'nicht in der Liste' auf 'bezahlt' zu schließen."""
    with lese_sitzung() as sitzung:
        lage = zs.uebersicht(sitzung, skonto_prozent=SKONTO)

    assert lage.stichtag is None
    assert {p.status for p in lage.posten} == {zs.OHNE_STAND}
    assert lage.bezahlt_cent == 0
    assert any("kein OPOS-Import" in h for h in lage.hinweise)


def test_status_je_rechnung(rechnungen, tmp_path) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))

    with lese_sitzung() as sitzung:
        lage = zs.uebersicht(sitzung, skonto_prozent=SKONTO)

    status = {p.rechnung_nr: p.status for p in lage.posten}
    # Offen und über die Fälligkeit hinaus.
    assert status["RE-2026-0001"] == zs.UEBERFAELLIG
    # Offen, aber erst am 20.08. fällig gewesen – am Stichtag 31.08. also überfällig.
    assert status["RE-2026-0002"] == zs.UEBERFAELLIG
    # 238 € Rest auf 11.900 € sind 2 % – innerhalb der Skonto-Toleranz.
    assert status["RE-2026-0003"] == zs.BEZAHLT_MIT_ABZUG
    # Steht nicht mehr in der Liste und ist älter als der Stichtag.
    assert status["RE-2026-0004"] == zs.BEZAHLT


def test_rechnung_juenger_als_der_stichtag_gilt_nicht_als_bezahlt(rechnungen, tmp_path) -> None:
    """Eine Liste von gestern kann eine Rechnung von heute nicht kennen."""
    frueher = datei_schreiben(
        tmp_path / "opos_2026-07-31.csv",
        ["RE-2026-0001;Mustermann GmbH;119.000,00;119.000,00;15.07.2026;01.07.2026"],
    )
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(frueher))

    with lese_sitzung() as sitzung:
        lage = zs.uebersicht(sitzung, skonto_prozent=SKONTO)

    status = {p.rechnung_nr: p.status for p in lage.posten}
    # Vom 06.08., der Stichtag ist der 31.07. – dazu ist schlicht nichts bekannt.
    assert status["RE-2026-0002"] == zs.OHNE_STAND
    assert status["RE-2026-0001"] == zs.UEBERFAELLIG


@pytest.mark.parametrize(
    ("zahlbetrag", "rest", "erwartet"),
    [
        (1_190_000, 0, zs.BEZAHLT),
        (1_190_000, 23_800, zs.BEZAHLT_MIT_ABZUG),  # genau 2 %
        (1_190_000, 35_700, zs.BEZAHLT_MIT_ABZUG),  # genau 3 %, die Grenze
        (1_190_000, 35_701, zs.UEBERFAELLIG),  # ein Cent darüber
        (1_190_000, 1_190_000, zs.UEBERFAELLIG),
    ],
)
def test_skonto_toleranz_an_der_grenze(zahlbetrag: int, rest: int, erwartet: str) -> None:
    """PLAN §6.13: der volle Skontosatz muss noch durchgehen, ein Cent darüber nicht mehr."""
    ergebnis = zs.status_bestimmen(
        rechnungsdatum=date(2026, 7, 1),
        faellig_am=date(2026, 7, 15),
        zahlbetrag_cent=zahlbetrag,
        offen_cent=rest,
        stichtag=date(2026, 8, 31),
        skonto_prozent=SKONTO,
    )
    assert ergebnis == erwartet


def test_offen_aber_noch_nicht_faellig_ist_nicht_ueberfaellig() -> None:
    assert (
        zs.status_bestimmen(
            rechnungsdatum=date(2026, 8, 20),
            faellig_am=date(2026, 9, 15),
            zahlbetrag_cent=100_000,
            offen_cent=100_000,
            stichtag=date(2026, 8, 31),
            skonto_prozent=SKONTO,
        )
        == zs.OFFEN
    )


def test_summen_der_uebersicht(rechnungen, tmp_path) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))

    with lese_sitzung() as sitzung:
        lage = zs.uebersicht(sitzung, skonto_prozent=SKONTO)

    assert lage.offen_cent == 11_900_000 + 2_380_000
    assert lage.ueberfaellig_cent == 11_900_000 + 2_380_000
    # Voll bezahlt (RE-0004) plus mit Abzug bezahlt (RE-0003), jeweils der Rechnungsbetrag.
    assert lage.bezahlt_cent == 500_000 + 1_190_000
    assert lage.je_status()[zs.BEZAHLT_MIT_ABZUG] == 1


def test_eingang_je_monat_ordnet_dem_rechnungsmonat_zu(rechnungen, tmp_path) -> None:
    """Der Zahltag steht in keiner OPOS-Liste – zugeordnet wird deshalb der Rechnungsmonat."""
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))

    with lese_sitzung() as sitzung:
        je_monat = zs.eingang_je_monat(sitzung, jahr=2026, skonto_prozent=SKONTO)

    assert je_monat == {"2026-06": 500_000, "2026-07": 1_190_000}
