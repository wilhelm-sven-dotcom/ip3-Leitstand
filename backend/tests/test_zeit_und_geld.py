"""Zeit- und Geldrechnung – die Grundlagen, auf denen Umsatz und Belege stehen."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app import geld, zeit


class TestZeit:
    def test_jetzt_hat_zeitzone(self):
        assert zeit.jetzt_utc().tzinfo is not None

    def test_zeitpunkt_ohne_zeitzone_wird_abgewiesen(self):
        with pytest.raises(ValueError, match="ohne Zeitzone"):
            zeit.nach_utc(datetime(2026, 3, 15, 14, 0))

    def test_umrechnung_nach_utc(self):
        ortszeit = datetime(2026, 7, 1, 14, 0, tzinfo=zeit.ORTSZEIT)
        assert zeit.nach_utc(ortszeit) == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def test_monat_aus_ortszeit_nicht_aus_utc(self):
        """Der kritische Fall: kurz nach Monatswechsel in Ortszeit, in UTC noch Vormonat."""
        # 1. April 2026, 00:30 Ortszeit (Sommerzeit) = 31. März 2026, 22:30 UTC
        zeitpunkt = datetime(2026, 3, 31, 22, 30, tzinfo=UTC)
        assert zeit.monat(zeitpunkt) == "2026-04"

    def test_monat_am_jahreswechsel(self):
        # 1. Januar 2026, 00:30 Ortszeit (Winterzeit) = 31. Dezember 2025, 23:30 UTC
        assert zeit.monat(datetime(2025, 12, 31, 23, 30, tzinfo=UTC)) == "2026-01"

    def test_monat_in_der_doppelten_stunde_der_zeitumstellung(self):
        """Ende der Sommerzeit: 25.10.2026 gibt es 02:00 bis 03:00 zweimal in Ortszeit."""
        assert zeit.monat(datetime(2026, 10, 25, 0, 30, tzinfo=UTC)) == "2026-10"

    def test_monat_aus_datum(self):
        assert zeit.monat(date(2026, 8, 27)) == "2026-08"

    @pytest.mark.parametrize("wert", ["2026-01", "2026-12", "1999-06"])
    def test_gueltige_monate(self, wert: str):
        assert zeit.monat_gueltig(wert)

    @pytest.mark.parametrize(
        "wert", ["2026-13", "2026-00", "2026-1", "26-01", "2026/01", "", "JJJJ-MM", "2026-ab"]
    )
    def test_ungueltige_monate(self, wert: str):
        assert not zeit.monat_gueltig(wert)

    def test_monat_pruefen_nennt_beispiel(self):
        with pytest.raises(ValueError, match="2026-03"):
            zeit.monat_pruefen("Maerz 2026")

    def test_alter_in_stunden(self):
        bezug = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
        vorher = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
        assert zeit.alter_in_stunden(vorher, bezug) == pytest.approx(24.0)


class TestGeld:
    @pytest.mark.parametrize(
        ("eingabe", "erwartet"),
        [
            (0.5, 1),
            (1.5, 2),  # Pythons round() würde hier 2 liefern, bei 2.5 aber 2 statt 3
            (2.5, 3),
            (-0.5, -1),
            (-2.5, -3),
            (10.4, 10),
            (10.6, 11),
        ],
    )
    def test_kaufmaennische_rundung(self, eingabe: float, erwartet: int):
        assert geld.kaufmaennisch_runden(eingabe) == erwartet

    def test_euro_nach_cent(self):
        assert geld.euro_nach_cent("1250.00") == 125000
        assert geld.euro_nach_cent(Decimal("0.005")) == 1  # halbe Cent aufwärts
        assert geld.euro_nach_cent(91875) == 9187500

    def test_cent_nach_euro(self):
        assert geld.cent_nach_euro(125000) == Decimal("1250.00")

    def test_formatierung_deutsch(self):
        # Geschütztes Leerzeichen vor dem Währungszeichen (PLAN §6.10)
        assert geld.formatiere_euro(125000) == "1.250,00 €"
        assert geld.formatiere_euro(9187500) == "91.875,00 €"
        assert geld.formatiere_euro(-1432000) == "-14.320,00 €"
        assert geld.formatiere_euro(5) == "0,05 €"

    def test_umsatzsteuer_einzeln(self):
        assert geld.ust_betrag(100000, 190) == 19000
        assert geld.ust_betrag(100000, 0) == 0
        # 0,5 Cent wird aufgerundet
        assert geld.ust_betrag(1005, 190) == 191

    def test_steuer_wird_je_satz_auf_die_belegsumme_gerechnet(self):
        """PLAN §6.11: nicht je Position runden, sonst weicht die Summe ab.

        Drei Positionen à 3,33 € netto: 3,33 × 19 % = 0,6327 → je Position 0,63 = 1,89.
        Richtig: 9,99 × 19 % = 1,8981 → 1,90.
        """
        positionen = [(333, 190), (333, 190), (333, 190)]
        je_satz = geld.steuer_je_satz(positionen)
        assert je_satz[190] == (999, 190)
        einzeln_gerundet = sum(geld.ust_betrag(netto, 190) for netto, _ in positionen)
        assert einzeln_gerundet == 189
        assert je_satz[190][1] != einzeln_gerundet

    def test_gemischte_steuersaetze(self):
        """Schlussrechnung mit 0 % (Wohngebäude) und 19 % (Gewerbeanteil)."""
        positionen = [(1000000, 0), (500000, 190)]
        netto, steuer, brutto = geld.belegsumme(positionen)
        assert netto == 1500000
        assert steuer == 95000
        assert brutto == 1595000

    def test_belegsumme_nur_nullprozent(self):
        netto, steuer, brutto = geld.belegsumme([(2500000, 0)])
        assert (netto, steuer, brutto) == (2500000, 0, 2500000)

    def test_position_netto(self):
        assert geld.position_netto("2.5", 1000) == 2500
        assert geld.position_netto(3, 33333) == 99999
        # 1,005 × 100 Cent = 100,5 → 101 (kaufmännisch)
        assert geld.position_netto("1.005", 100) == 101

    def test_negative_betraege_fuer_gutschriften(self):
        """Gutschriften und Stornos arbeiten mit negativen Beträgen (PLAN §6.14)."""
        netto, steuer, brutto = geld.belegsumme([(-100000, 190)])
        assert netto == -100000
        assert steuer == -19000
        assert brutto == -119000
