"""Angebotspipeline und der Import aus dem Angebots-Tool (PLAN §7 Phase 7).

Die Pipeline steht neben dem Forecast, nie darin: ein gewichtetes Angebot ist kein Auftrag.
Diese Tests halten das fest – und die Regeln des Imports, der mit einer Datei umgehen muss,
die es noch nicht gibt.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import pipeline as dienst
from app.importe import angebote as leser
from app.importe.csv_leser import SpaltenFehlen
from app.konfiguration import AngebotEinstellungen
from app.modelle import Angebot, Firma, Kunde, Projekt

SPALTEN = AngebotEinstellungen().spalten
STATUS_ZUORDNUNG = AngebotEinstellungen().status_zuordnung


# ---------------------------------------------------------------------------
# Rechnen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("summe", "promille", "erwartet"),
    [
        (10_000_00, 600, 6_000_00),
        (10_000_00, 0, 0),
        (10_000_00, 1000, 10_000_00),
        # Kaufmännisch gerundet: 1.000,01 € mal 33,3 % sind 333,00 €, nicht 332,99 €.
        (100_001, 333, 33_300),
    ],
)
def test_gewichten(summe, promille, erwartet) -> None:
    assert dienst.gewichten(summe, promille) == erwartet


def _angebot(**felder) -> None:
    vorgabe = {
        "kunde_name": "Interessent GmbH",
        "summe_netto": 100_000_00,
        "wahrscheinlichkeit_promille": 500,
        "erwarteter_monat": "2027-03",
        "status": "offen",
    }
    with schreib_sitzung() as sitzung:
        sitzung.add(Angebot(**{**vorgabe, **felder}))


def test_jahresverlauf_trennt_roh_und_gewichtet(gesäte_db) -> None:
    """Nur gewichtet zu zeigen verschweigt das Risiko, nur roh die Wahrscheinlichkeit."""
    _angebot(angebot_nr="A-1", summe_netto=100_000_00, wahrscheinlichkeit_promille=600)
    _angebot(angebot_nr="A-2", summe_netto=50_000_00, wahrscheinlichkeit_promille=200)

    with lese_sitzung() as sitzung:
        bild = dienst.jahresverlauf(sitzung, 2027)

    maerz = next(m for m in bild.monate if m.monat == "2027-03")
    assert maerz.roh_cent == 150_000_00
    assert maerz.gewichtet_cent == 70_000_00
    assert maerz.anzahl == 2
    assert bild.roh_cent == 150_000_00
    assert bild.gewichtet_cent == 70_000_00


def test_gewonnene_und_verlorene_zaehlen_nicht(gesäte_db) -> None:
    """Ein gewonnenes Angebot ist ein Projekt – es hier zu zeigen zählte den Euro zweimal."""
    _angebot(angebot_nr="A-1", status="gewonnen")
    _angebot(angebot_nr="A-2", status="verloren")
    _angebot(angebot_nr="A-3", status="offen")

    with lese_sitzung() as sitzung:
        bild = dienst.jahresverlauf(sitzung, 2027)
    assert bild.anzahl == 1


def test_ohne_monat_wird_nicht_geraten(gesäte_db) -> None:
    _angebot(angebot_nr="A-1", erwarteter_monat=None, summe_netto=80_000_00)

    with lese_sitzung() as sitzung:
        bild = dienst.jahresverlauf(sitzung, 2027)

    assert all(m.anzahl == 0 for m in bild.monate)
    assert bild.unterminiert.anzahl == 1
    assert bild.unterminiert.roh_cent == 80_000_00
    # In der Gesamtsumme zählt es trotzdem – es ist ja im Rennen.
    assert bild.roh_cent == 80_000_00
    assert any("keinen erwarteten" in h for h in bild.hinweise)


def test_anderes_jahr_bleibt_draussen(gesäte_db) -> None:
    _angebot(angebot_nr="A-1", erwarteter_monat="2028-01")

    with lese_sitzung() as sitzung:
        assert dienst.jahresverlauf(sitzung, 2027).anzahl == 0
        assert dienst.jahre_mit_angeboten(sitzung) == [2028]


def test_gewonnenes_angebot_ohne_projekt_faellt_auf(gesäte_db) -> None:
    """Sein Wert steht weder in der Pipeline noch im Auftragsbestand."""
    _angebot(angebot_nr="A-77", status="gewonnen", projekt_id=None)

    with lese_sitzung() as sitzung:
        hinweise = dienst.jahresverlauf(sitzung, 2027).hinweise
    assert any("A-77" in h and "keinem Projekt" in h for h in hinweise)


def test_gewonnenes_angebot_mit_projekt_ist_still(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=70001, name="Interessent GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        projekt = Projekt(projekt_nr=26400, firma_id=firma_id, kunde_id=kunde.id, status="in_bau")
        sitzung.add(projekt)
        sitzung.flush()
        projekt_id = projekt.id
    _angebot(angebot_nr="A-77", status="gewonnen", projekt_id=projekt_id)

    with lese_sitzung() as sitzung:
        hinweise = dienst.jahresverlauf(sitzung, 2027).hinweise
    assert not any("keinem Projekt" in h for h in hinweise)


def test_geringe_chancen_werden_benannt(gesäte_db) -> None:
    """Sie blähen die rohe Summe auf und tragen zur gewichteten fast nichts bei."""
    _angebot(angebot_nr="A-1", summe_netto=500_000_00, wahrscheinlichkeit_promille=50)

    with lese_sitzung() as sitzung:
        bild = dienst.jahresverlauf(sitzung, 2027)

    # 500.000 € roh, aber nur 25.000 € gewichtet: die rohe Summe sagt hier fast nichts.
    assert bild.roh_cent == 500_000_00
    assert bild.gewichtet_cent == 25_000_00
    # Deutsche Zahlen mit geschütztem Leerzeichen vor der Einheit (CLAUDE.md Regel 11).
    hinweis = next(h for h in bild.hinweise if "20\u00a0%" in h)
    assert "500.000,00\u00a0€" in hinweis
    # Numerus stimmt auch bei genau einem Angebot.
    assert "1 Angebot mit" in hinweis


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------


def _mappe(pfad: Path, kopf: list[str], zeilen: list[list[object]], *, vorspann: bool = False):
    mappe = Workbook()
    blatt = mappe.active
    blatt.title = "Angebote"
    if vorspann:
        # Angebotslisten tragen oft eine Überschrift und eine Leerzeile über der Tabelle.
        blatt.append(["Angebotsübersicht 2027"])
        blatt.append([])
    blatt.append(kopf)
    for zeile in zeilen:
        blatt.append(zeile)
    mappe.save(pfad)
    return pfad


def _lesen(pfad: Path):
    return leser.lesen(pfad, SPALTEN, STATUS_ZUORDNUNG, standard_wahrscheinlichkeit=500)


KOPF = [
    "Angebotsnummer",
    "Kunde",
    "Bezeichnung",
    "Angebotssumme",
    "Wahrscheinlichkeit",
    "Erwarteter Auftrag",
    "Status",
    "Angebotsdatum",
]


def test_excel_wird_gelesen(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [
            [
                "A-2027-001",
                "Solarpark Nord GmbH",
                "Freifläche",
                "1.250.000,00",
                "60 %",
                "03/2027",
                "offen",
                "12.01.2027",
            ],
        ],
    )
    datei = _lesen(pfad)

    assert datei.befunde == []
    zeile = datei.zeilen[0]
    assert zeile.angebot_nr == "A-2027-001"
    assert zeile.kunde_name == "Solarpark Nord GmbH"
    assert zeile.summe_cent == 125_000_000
    assert zeile.wahrscheinlichkeit_promille == 600
    assert zeile.erwarteter_monat == "2027-03"
    assert zeile.status == "offen"
    assert zeile.datum == date(2027, 1, 12)


def test_ueberschrift_ueber_der_tabelle_stoert_nicht(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "1000", "50", "03/2027", "offen", ""]],
        vorspann=True,
    )
    assert len(_lesen(pfad).zeilen) == 1


def test_csv_geht_genauso(tmp_path: Path) -> None:
    """Welches Format das Angebots-Tool ausgibt, entscheidet sich erst, wenn es da ist."""
    pfad = tmp_path / "angebote.csv"
    pfad.write_text(
        "Angebotsnummer;Kunde;Angebotssumme;Wahrscheinlichkeit;Erwarteter Auftrag;Status\n"
        "A-1;Kunde GmbH;1.000,00;50 %;03/2027;offen\n",
        encoding="utf-8",
    )
    zeile = _lesen(pfad).zeilen[0]
    assert zeile.summe_cent == 100_000
    assert zeile.wahrscheinlichkeit_promille == 500


def test_fehlende_pflichtspalte_nennt_die_datei(tmp_path: Path) -> None:
    pfad = _mappe(tmp_path / "angebote.xlsx", ["Nummer", "Bemerkung"], [["A-1", "irgendwas"]])
    with pytest.raises(SpaltenFehlen) as fehler:
        _lesen(pfad)
    assert "Kunde" in str(fehler.value.meldung) or "kunde" in str(fehler.value.meldung).lower()


def test_zeile_ohne_kunde_wird_gemeldet(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "", "", "1000", "50", "03/2027", "offen", ""]],
    )
    datei = _lesen(pfad)
    assert datei.zeilen == []
    assert any("ohne Kunde" in b.meldung for b in datei.befunde)


def test_unlesbare_summe_wird_gemeldet(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "auf Anfrage", "50", "03/2027", "offen", ""]],
    )
    datei = _lesen(pfad)
    assert datei.zeilen == []
    assert any("nicht lesbar" in b.meldung for b in datei.befunde)


def test_fehlende_wahrscheinlichkeit_nimmt_die_vorbelegung(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "1000", "", "03/2027", "offen", ""]],
    )
    datei = _lesen(pfad)
    assert datei.zeilen[0].wahrscheinlichkeit_promille == 500
    # Eine leere Zelle ist keine Auffälligkeit, eine unlesbare schon.
    assert datei.befunde == []


def test_unlesbare_wahrscheinlichkeit_wird_gemeldet(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "1000", "gut", "03/2027", "offen", ""]],
    )
    datei = _lesen(pfad)
    assert datei.zeilen[0].wahrscheinlichkeit_promille == 500
    assert any("Wahrscheinlichkeit nicht lesbar" in b.meldung for b in datei.befunde)


def test_wahrscheinlichkeit_ueber_hundert_prozent_wird_gemeldet(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "1000", "150 %", "03/2027", "offen", ""]],
    )
    datei = _lesen(pfad)
    assert datei.zeilen[0].wahrscheinlichkeit_promille == 1000
    assert any("außerhalb" in b.meldung for b in datei.befunde)


def test_unbekannter_status_gilt_als_offen_und_wird_genannt(tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "1000", "50", "03/2027", "nachgefasst", ""]],
    )
    datei = _lesen(pfad)
    assert datei.zeilen[0].status == "offen"
    befund = next(b for b in datei.befunde if b.spalte == "status")
    assert "config.toml" in befund.meldung
    assert befund.schwere == "hinweis"


def test_datei_ohne_angebotsnummer_warnt_vor_dubletten(tmp_path: Path) -> None:
    pfad = tmp_path / "angebote.csv"
    pfad.write_text("Kunde;Angebotssumme\nKunde GmbH;1.000,00\n", encoding="utf-8")
    datei = _lesen(pfad)
    assert any("erneut an" in b.meldung for b in datei.befunde)


def test_fehlende_datei_nennt_den_pfad(tmp_path: Path) -> None:
    with pytest.raises(leser.AngebotsdateiFehlt) as fehler:
        _lesen(tmp_path / "gibtsnicht.xlsx")
    assert "gibtsnicht.xlsx" in fehler.value.meldung


# ---------------------------------------------------------------------------
# Übernehmen
# ---------------------------------------------------------------------------


def _uebernehmen(pfad: Path):
    datei = _lesen(pfad)
    with schreib_sitzung() as sitzung:
        return leser.uebernehmen(sitzung, datei)


def test_uebernahme_legt_an_und_aktualisiert(gesäte_db, tmp_path: Path) -> None:
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "Dach", "1000", "50", "03/2027", "offen", ""]],
    )
    erst = _uebernehmen(pfad)
    assert (erst.neu, erst.aktualisiert) == (1, 0)

    # Zweiter Lauf mit geänderter Summe: dieselbe Zeile, kein Duplikat.
    _mappe(
        pfad,
        KOPF,
        [["A-1", "Kunde GmbH", "Dach", "2000", "70", "04/2027", "offen", ""]],
    )
    zweit = _uebernehmen(pfad)
    assert (zweit.neu, zweit.aktualisiert) == (0, 1)

    with lese_sitzung() as sitzung:
        angebote = list(sitzung.scalars(select(Angebot)))
        assert len(angebote) == 1
        assert angebote[0].summe_netto == 200_000
        assert angebote[0].wahrscheinlichkeit_promille == 700
        assert angebote[0].erwarteter_monat == "2027-04"
        assert angebote[0].quelle_datei == "angebote.xlsx"


def test_gewonnenes_angebot_wird_nicht_ueberschrieben(gesäte_db, tmp_path: Path) -> None:
    """Daran hängt ein Projekt – ein Import darf den Auftragsbestand nicht verändern."""
    _angebot(angebot_nr="A-1", status="gewonnen", summe_netto=999_00)
    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [["A-1", "Kunde GmbH", "", "1000", "50", "03/2027", "verloren", ""]],
    )
    ergebnis = _uebernehmen(pfad)

    assert ergebnis.uebersprungen == 1
    with lese_sitzung() as sitzung:
        angebot = sitzung.scalar(select(Angebot))
        assert angebot.status == "gewonnen"
        assert angebot.summe_netto == 999_00
    assert any("bereits gewonnen" in b.meldung for b in ergebnis.befunde)


def test_kunde_wird_ueber_den_namen_zugeordnet(gesäte_db, tmp_path: Path) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(Kunde(kunden_nr=70002, name="Bekannt GmbH", ort="Weiden", typ="b2b"))

    pfad = _mappe(
        tmp_path / "angebote.xlsx",
        KOPF,
        [
            ["A-1", "Bekannt GmbH", "", "1000", "50", "03/2027", "offen", ""],
            ["A-2", "Noch Kein Kunde e.K.", "", "1000", "50", "03/2027", "offen", ""],
        ],
    )
    _uebernehmen(pfad)

    with lese_sitzung() as sitzung:
        zuordnung = {
            a.angebot_nr: a.kunde_id for a in sitzung.scalars(select(Angebot).order_by(Angebot.id))
        }
    assert zuordnung["A-1"] is not None
    # Ein Interessent ist noch kein Kunde – die Zuordnung bleibt leer, der Name steht daneben.
    assert zuordnung["A-2"] is None


def test_ansicht_oeffnet_auf_dem_jahr_mit_angeboten(gesäte_db) -> None:
    """Nicht stur das laufende Jahr – sonst zeigt die Seite leer, während die Liste voll ist.

    Derselbe Fehler wie im Cockpit der Phase 5: eine Ansicht, die beim Aufrufen auf Nullen
    zeigt, sieht kaputt aus statt leer.
    """
    _angebot(angebot_nr="A-1", erwarteter_monat="2028-04")

    with lese_sitzung() as sitzung:
        # Nächstes Jahr mit Angeboten ab dem laufenden.
        assert dienst.jahr_mit_angeboten(sitzung, 2026) == 2028
        assert dienst.jahr_mit_angeboten(sitzung, 2028) == 2028
        # Liegt alles in der Vergangenheit, das jüngste davon.
        assert dienst.jahr_mit_angeboten(sitzung, 2030) == 2028


def test_ohne_angebote_bleibt_das_laufende_jahr(gesäte_db) -> None:
    with lese_sitzung() as sitzung:
        assert dienst.jahr_mit_angeboten(sitzung, 2026) == 2026


def test_gewonnene_angebote_bestimmen_das_jahr_nicht(gesäte_db) -> None:
    """Sie stehen im Auftragsbestand; die Pipeline soll auf offene Angebote aufgehen."""
    _angebot(angebot_nr="A-1", erwarteter_monat="2028-04", status="gewonnen", projekt_id=None)
    _angebot(angebot_nr="A-2", erwarteter_monat="2029-01", status="offen")

    with lese_sitzung() as sitzung:
        assert dienst.jahre_mit_angeboten(sitzung) == [2029]
        assert dienst.jahr_mit_angeboten(sitzung, 2026) == 2029
