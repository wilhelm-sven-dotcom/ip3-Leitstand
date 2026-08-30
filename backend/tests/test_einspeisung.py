"""Vergütungs-Controlling der eigenen Bestandsanlagen (PLAN §7 Phase 7).

Die Zahl, auf die es ankommt, ist die Abweichung zwischen Erwartung und Abrechnung. Sie ist nur
so viel wert wie das, was ihr fehlt: eine Anlage ohne Satz, ein Monat ohne Abrechnung, eine
Zeile ohne zugeordnete Anlage. Diese Tests prüfen vor allem die Ränder.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import einspeisung as dienst
from app.importe import einspeisung as leser
from app.modelle import EigeneAnlage, EinspeiseAbrechnung

SPALTEN = {
    "zaehler": ["Zählernummer"],
    "mastr": ["MaStR-Nr."],
    "anlage": ["Anlage"],
    "monat": ["Abrechnungsmonat"],
    "kwh": ["Menge kWh"],
    "betrag": ["Betrag netto"],
}


def _anlage(bezeichnung: str, **felder) -> int:
    with schreib_sitzung() as sitzung:
        anlage = EigeneAnlage(bezeichnung=bezeichnung, **felder)
        sitzung.add(anlage)
        sitzung.flush()
        return anlage.id


def _abrechnung(anlage_id: int, monat: str, kwh: str, betrag_cent: int, **felder) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(
            EinspeiseAbrechnung(
                anlage_id=anlage_id,
                monat=monat,
                kwh=Decimal(kwh),
                betrag_cent=betrag_cent,
                **felder,
            )
        )


def _bild(**felder):
    with lese_sitzung() as sitzung:
        return dienst.bild(sitzung, **felder)


# ------------------------------------------------------------------------------------------
# Die Erwartung
# ------------------------------------------------------------------------------------------


class TestErwartung:
    def test_einspeisung_ist_menge_mal_satz(self):
        anlage = EigeneAnlage(
            bezeichnung="Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.11")
        )
        # 12.500 kWh mal 8,11 ct = 101.375 ct = 1.013,75 €
        assert dienst.erwartung_cent(anlage, Decimal("12500")) == 101375

    def test_direktvermarktung_zieht_das_vermarkterentgelt_ab(self):
        """Sonst läge die Erwartung systematisch zu hoch."""
        anlage = EigeneAnlage(
            bezeichnung="Freifläche",
            verguetungsart="direktvermarktung",
            verguetung_ct_kwh=Decimal("6.50"),
            vermarkter_entgelt_ct_kwh=Decimal("0.25"),
        )
        # 100.000 kWh mal (6,50 − 0,25) ct = 625.000 ct
        assert dienst.erwartung_cent(anlage, Decimal("100000")) == 625000

    def test_entgelt_zaehlt_nur_bei_direktvermarktung(self):
        anlage = EigeneAnlage(
            bezeichnung="Dach",
            verguetungsart="einspeisung",
            verguetung_ct_kwh=Decimal("8.00"),
            vermarkter_entgelt_ct_kwh=Decimal("0.25"),
        )
        assert dienst.erwartung_cent(anlage, Decimal("1000")) == 8000

    def test_rundet_kaufmaennisch_nicht_zur_geraden_zahl(self):
        """``quantize`` ohne Angabe rundet zur geraden Zahl – ein halber Cent fiele mal hoch,
        mal runter, und die Kontrollrechnung meldete eine Abweichung, die keine ist."""
        anlage = EigeneAnlage(
            bezeichnung="Freifläche",
            verguetungsart="direktvermarktung",
            verguetung_ct_kwh=Decimal("6.50"),
            vermarkter_entgelt_ct_kwh=Decimal("0.25"),
        )
        # 104.250 kWh mal 6,25 ct = 651.562,5 ct – genau ein halber Cent.
        assert dienst.erwartung_cent(anlage, Decimal("104250")) == 651563

    def test_ohne_satz_gibt_es_keine_erwartung(self):
        """``None`` ist etwas anderes als 0,00 €: eine Null läse sich als „nichts zu erwarten"."""
        anlage = EigeneAnlage(bezeichnung="Neu", verguetungsart="einspeisung")
        assert dienst.erwartung_cent(anlage, Decimal("1000")) is None


class TestMonatszeile:
    def test_abweichung_in_promille(self):
        zeile = dienst.Monatszeile(
            monat="2026-07",
            kwh=Decimal("1000"),
            erwartet_cent=100000,
            abgerechnet_cent=98000,
            bezahlt_am=None,
        )
        assert zeile.abweichung_cent == -2000
        assert zeile.abweichung_promille == -20

    def test_ohne_erwartung_keine_abweichung(self):
        zeile = dienst.Monatszeile(
            monat="2026-07",
            kwh=Decimal("1000"),
            erwartet_cent=None,
            abgerechnet_cent=98000,
            bezahlt_am=None,
        )
        assert zeile.abweichung_cent is None
        assert zeile.abweichung_promille is None

    def test_null_erwartung_teilt_nicht_durch_null(self):
        zeile = dienst.Monatszeile(
            monat="2026-07",
            kwh=Decimal("0"),
            erwartet_cent=0,
            abgerechnet_cent=0,
            bezahlt_am=None,
        )
        assert zeile.abweichung_promille is None


# ------------------------------------------------------------------------------------------
# Das Bild
# ------------------------------------------------------------------------------------------


class TestBild:
    def test_ohne_anlagen_sagt_es_das(self, gesäte_db):
        bild = _bild(heute=date(2026, 8, 30))
        assert bild.anlagen == []
        assert "keine eigene Anlage" in bild.hinweise[0]

    def test_summen_ueber_die_monate(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00")
        )
        _abrechnung(anlage_id, "2026-06", "10000", 80000, bezahlt_am=date(2026, 7, 15))
        _abrechnung(anlage_id, "2026-07", "12000", 96000, bezahlt_am=date(2026, 8, 15))

        bild = _bild(heute=date(2026, 8, 30))

        assert len(bild.anlagen) == 1
        teil = bild.anlagen[0]
        assert teil.kwh_gesamt == Decimal("22000")
        assert teil.erwartet_cent == 176000
        assert teil.abgerechnet_cent == 176000
        assert bild.offen_cent == 0

    def test_abweichung_ueber_der_toleranz_wird_genannt(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00")
        )
        # Erwartet 80.000 ct, abgerechnet 70.000 ct – 12,5 % zu wenig.
        _abrechnung(anlage_id, "2026-07", "10000", 70000, bezahlt_am=date(2026, 8, 10))

        bild = _bild(heute=date(2026, 8, 30), toleranz_promille=20)

        hinweise = bild.anlagen[0].hinweise
        # Einzahl: „1 Monat weicht", nicht „weichen" – siehe TestNumerus.
        assert any("um mehr als" in h for h in hinweise)
        assert any("07/2026" in h for h in hinweise)

    def test_kleine_abweichung_bleibt_stumm(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00")
        )
        # 1 % Abweichung, Toleranz 2 %.
        _abrechnung(anlage_id, "2026-07", "10000", 79200, bezahlt_am=date(2026, 8, 10))

        bild = _bild(heute=date(2026, 8, 30), toleranz_promille=20)

        assert not any("um mehr als" in h for h in bild.anlagen[0].hinweise)

    def test_fehlender_monat_wird_gemeldet(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd",
            verguetungsart="einspeisung",
            verguetung_ct_kwh=Decimal("8.00"),
            inbetriebnahme=date(2026, 5, 1),
        )
        _abrechnung(anlage_id, "2026-07", "10000", 80000)

        bild = _bild(heute=date(2026, 8, 30), monate=6)

        hinweise = bild.anlagen[0].hinweise
        assert any("keine Abrechnung vor" in h for h in hinweise)
        # Mai und Juni fehlen, der August läuft noch.
        assert any("05/2026" in h and "06/2026" in h for h in hinweise)

    def test_der_laufende_monat_gilt_nicht_als_fehlend(self, gesäte_db):
        """Ein laufender Monat ist nicht abgerechnet, sondern noch nicht dran."""
        anlage_id = _anlage(
            "Halle Süd",
            verguetungsart="einspeisung",
            verguetung_ct_kwh=Decimal("8.00"),
            inbetriebnahme=date(2026, 7, 1),
        )
        _abrechnung(anlage_id, "2026-07", "10000", 80000)

        bild = _bild(heute=date(2026, 8, 30), monate=3)

        assert not any("keine Abrechnung vor" in h for h in bild.anlagen[0].hinweise)

    def test_vor_der_inbetriebnahme_fehlt_nichts(self, gesäte_db):
        anlage_id = _anlage(
            "Neubau",
            verguetungsart="einspeisung",
            verguetung_ct_kwh=Decimal("8.00"),
            inbetriebnahme=date(2026, 7, 1),
        )
        _abrechnung(anlage_id, "2026-07", "10000", 80000)

        bild = _bild(heute=date(2026, 8, 30), monate=12)

        assert not any("keine Abrechnung vor" in h for h in bild.anlagen[0].hinweise)

    def test_ueberfaellige_zahlung_wird_gemeldet(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00")
        )
        _abrechnung(anlage_id, "2026-05", "10000", 80000)  # nicht bezahlt

        bild = _bild(heute=date(2026, 8, 30), zahlungsziel_tage=45)

        assert any("nicht als bezahlt vermerkt" in h for h in bild.anlagen[0].hinweise)
        assert bild.offen_cent == 80000

    def test_frische_abrechnung_ist_noch_nicht_ueberfaellig(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00")
        )
        _abrechnung(anlage_id, "2026-07", "10000", 80000)

        bild = _bild(heute=date(2026, 8, 30), zahlungsziel_tage=45)

        assert not any("nicht als bezahlt" in h for h in bild.anlagen[0].hinweise)

    def test_anlage_ohne_satz_steht_im_gesamthinweis(self, gesäte_db):
        anlage_id = _anlage("Ohne Satz", verguetungsart="einspeisung")
        _abrechnung(anlage_id, "2026-07", "10000", 80000)

        bild = _bild(heute=date(2026, 8, 30))

        assert any("Ohne Satz" in h for h in bild.hinweise)
        assert bild.anlagen[0].monate[0].erwartet_cent is None

    def test_stillgelegte_anlagen_bleiben_draussen(self, gesäte_db):
        """Nichts löschen, was Bezüge hat (CLAUDE.md Regel 5) – nur nicht mehr mitzählen."""
        _anlage("Alt", verguetungsart="einspeisung", aktiv=False)
        _anlage("Neu", verguetungsart="einspeisung")

        bild = _bild(heute=date(2026, 8, 30))

        assert [a.bezeichnung for a in bild.anlagen] == ["Neu"]

    def test_monatswort_im_richtigen_numerus(self):
        assert dienst._monatswort(1) == "1 Monat"
        assert dienst._monatswort(3) == "3 Monate"


# ------------------------------------------------------------------------------------------
# Der Leser
# ------------------------------------------------------------------------------------------


def _csv(pfad: Path, zeilen: list[str]) -> Path:
    datei = pfad / "abrechnung.csv"
    datei.write_text("\n".join(zeilen), encoding="utf-8")
    return datei


class TestLeser:
    def test_zuordnung_ueber_die_zaehlernummer(self, gesäte_db, tmp_path: Path):
        anlage_id = _anlage("Halle Süd", verguetungsart="einspeisung", zaehler_nr="1ESY0012345")
        datei = _csv(
            tmp_path,
            [
                "Zählernummer;Abrechnungsmonat;Menge kWh;Betrag netto",
                "1ESY0012345;07/2026;12.500,50;1.013,75",
            ],
        )

        with schreib_sitzung() as sitzung:
            gelesen = leser.lesen(sitzung, datei, SPALTEN)
            uebernahme = leser.uebernehmen(sitzung, gelesen)

        assert uebernahme.neu == 1
        assert not [b for b in uebernahme.befunde if b.schwere != "hinweis"]
        with lese_sitzung() as sitzung:
            eintrag = sitzung.execute(select(EinspeiseAbrechnung)).scalar_one()
        assert eintrag.anlage_id == anlage_id
        assert eintrag.monat == "2026-07"
        assert eintrag.kwh == Decimal("12500.500")
        assert eintrag.betrag_cent == 101375

    def test_zuordnung_ueber_die_mastr_nummer(self, gesäte_db, tmp_path: Path):
        anlage_id = _anlage("Freifläche", verguetungsart="einspeisung", mastr_nr="SEE900000123456")
        datei = _csv(
            tmp_path,
            [
                "MaStR-Nr.;Abrechnungsmonat;Menge kWh;Betrag netto",
                "SEE900000123456;2026-07;1000;80,00",
            ],
        )

        with schreib_sitzung() as sitzung:
            leser.uebernehmen(sitzung, leser.lesen(sitzung, datei, SPALTEN))

        with lese_sitzung() as sitzung:
            assert sitzung.execute(select(EinspeiseAbrechnung)).scalar_one().anlage_id == anlage_id

    def test_zeile_ohne_anlage_wird_genannt_statt_verworfen(self, gesäte_db, tmp_path: Path):
        _anlage("Halle Süd", verguetungsart="einspeisung", zaehler_nr="1ESY0012345")
        datei = _csv(
            tmp_path,
            [
                "Zählernummer;Abrechnungsmonat;Menge kWh;Betrag netto",
                "1ESY9999999;07/2026;1000;80,00",
            ],
        )

        with schreib_sitzung() as sitzung:
            gelesen = leser.lesen(sitzung, datei, SPALTEN)

        assert gelesen.zeilen == []
        befund = gelesen.befunde[0]
        assert befund.wert == "1ESY9999999"
        assert "keine eigene Anlage" in befund.meldung
        assert "Nächster Schritt" in befund.meldung

    def test_zweiter_lauf_aktualisiert_und_laesst_die_zahlung_stehen(
        self, gesäte_db, tmp_path: Path
    ):
        """Ein erneuter Import darf einen von Hand vermerkten Zahlungseingang nicht löschen."""
        anlage_id = _anlage("Halle Süd", verguetungsart="einspeisung", zaehler_nr="1ESY0012345")
        _abrechnung(anlage_id, "2026-07", "1000", 80000, bezahlt_am=date(2026, 8, 20))
        datei = _csv(
            tmp_path,
            [
                "Zählernummer;Abrechnungsmonat;Menge kWh;Betrag netto",
                "1ESY0012345;07/2026;1100;880,00",
            ],
        )

        with schreib_sitzung() as sitzung:
            uebernahme = leser.uebernehmen(sitzung, leser.lesen(sitzung, datei, SPALTEN))

        assert uebernahme.neu == 0
        assert uebernahme.aktualisiert == 1
        with lese_sitzung() as sitzung:
            eintrag = sitzung.execute(select(EinspeiseAbrechnung)).scalar_one()
        assert eintrag.kwh == Decimal("1100")
        assert eintrag.betrag_cent == 88000
        assert eintrag.bezahlt_am == date(2026, 8, 20)

    def test_negative_menge_wird_gemeldet_und_gedreht(self, gesäte_db, tmp_path: Path):
        _anlage("Halle Süd", verguetungsart="einspeisung", zaehler_nr="1ESY0012345")
        datei = _csv(
            tmp_path,
            [
                "Zählernummer;Abrechnungsmonat;Menge kWh;Betrag netto",
                "1ESY0012345;07/2026;-1000;80,00",
            ],
        )

        with schreib_sitzung() as sitzung:
            gelesen = leser.lesen(sitzung, datei, SPALTEN)

        assert gelesen.zeilen[0].kwh == Decimal("1000")
        assert any("Negative Einspeisemenge" in b.meldung for b in gelesen.befunde)

    def test_negativer_betrag_bleibt_negativ(self, gesäte_db, tmp_path: Path):
        """Eine Korrekturabrechnung für einen Vormonat darf negativ sein."""
        _anlage("Halle Süd", verguetungsart="einspeisung", zaehler_nr="1ESY0012345")
        datei = _csv(
            tmp_path,
            [
                "Zählernummer;Abrechnungsmonat;Menge kWh;Betrag netto",
                "1ESY0012345;07/2026;0;-120,50",
            ],
        )

        with schreib_sitzung() as sitzung:
            gelesen = leser.lesen(sitzung, datei, SPALTEN)

        assert gelesen.zeilen[0].betrag_cent == -12050

    def test_unlesbarer_monat_uebergeht_die_zeile_mit_befund(self, gesäte_db, tmp_path: Path):
        _anlage("Halle Süd", verguetungsart="einspeisung", zaehler_nr="1ESY0012345")
        datei = _csv(
            tmp_path,
            [
                "Zählernummer;Abrechnungsmonat;Menge kWh;Betrag netto",
                "1ESY0012345;Sommer;1000;80,00",
            ],
        )

        with schreib_sitzung() as sitzung:
            gelesen = leser.lesen(sitzung, datei, SPALTEN)

        assert gelesen.zeilen == []
        assert any("Abrechnungsmonat nicht lesbar" in b.meldung for b in gelesen.befunde)

    def test_fehlende_datei_nennt_den_naechsten_schritt(self, gesäte_db, tmp_path: Path):
        with schreib_sitzung() as sitzung, pytest.raises(leser.AbrechnungsdateiFehlt) as fehler:
            leser.lesen(sitzung, tmp_path / "gibt-es-nicht.csv", SPALTEN)
        assert "gibt-es-nicht.csv" in fehler.value.meldung
        assert fehler.value.naechster_schritt

    @pytest.mark.parametrize(
        ("roh", "erwartet"),
        [
            ("2026-07", "2026-07"),
            ("07/2026", "2026-07"),
            ("07.2026", "2026-07"),
            ("7/26", "2026-07"),
            ("15.07.2026", "2026-07"),
            ("Sommer", None),
            ("", None),
        ],
    )
    def test_monatsschreibweisen(self, roh: str, erwartet: str | None):
        assert leser.monat_lesen(roh) == erwartet


class TestNumerus:
    """„1 Monat weichen ab" liest sich wie eine Maschinenausgabe – und wird dann überlesen.

    Das Zählwort allein reicht nicht, das Verb muss mit. Beim Zählen ist das in diesem
    Projekt schon dreimal danebengegangen; deshalb steht es hier als eigener Test.
    """

    def test_zaehlwort(self):
        assert dienst._monatswort(1) == "1 Monat"
        assert dienst._monatswort(3) == "3 Monate"

    def test_verb_stimmt_mit(self):
        assert dienst._monatssatz(1, "weicht", "weichen") == "1 Monat weicht"
        assert dienst._monatssatz(4, "weicht", "weichen") == "4 Monate weichen"
        assert dienst._monatssatz(1, "ist", "sind") == "1 Monat ist"
        assert dienst._monatssatz(2, "ist", "sind") == "2 Monate sind"

    def test_im_hinweis_selbst(self, gesäte_db):
        anlage_id = _anlage(
            "Halle Süd", verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00")
        )
        _abrechnung(anlage_id, "2026-05", "10000", 70000)  # abweichend und unbezahlt

        hinweise = _bild(heute=date(2026, 8, 30)).anlagen[0].hinweise

        assert any("1 Monat weicht um mehr als" in h for h in hinweise)
        assert any("1 Monat ist abgerechnet" in h for h in hinweise)
        assert not any("1 Monat weichen" in h or "1 Monat sind" in h for h in hinweise)
