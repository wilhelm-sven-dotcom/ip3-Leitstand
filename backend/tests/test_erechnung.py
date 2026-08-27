"""E-Rechnung nach EN 16931 (PLAN §6.3).

Ab dem 1.1.2027 ist ip³ verpflichtet, für inländische B2B-Umsätze E-Rechnungen auszustellen. Diese
Tests halten fest, dass das XML gegen das Schema gültig ist, die Pflichtfelder trägt und **dieselben
Zahlen** wie das PDF – zwei verschiedene Rechnungen in einer Datei wären der schlimmste Ausgang.

**Grenze dieser Prüfung:** das XSD prüft die Struktur, nicht die Geschäftsregeln (BR-*, BR-DE-*)
der EN 16931. Eine vollständige Schematron-Prüfung braucht die KoSIT-Werkzeuge und damit Java; sie
läuft nicht in dieser Suite. Der RUNBOOK-Abnahmeschritt sieht deshalb eine Prüfung von Hand vor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from app.belege import Rechnungsablage
from app.belege.pdf import eingebettete_dateien, ist_pdf_a3
from app.belege.zugferd import (
    ANHANGSNAME,
    ERechnungFehler,
    braucht_erechnung,
    pruefen_gegen_schema,
    xml_erzeugen,
)
from app.dienste.belegarten import summen_setzen
from app.modelle import Absetzung, Rechnungsposition
from tests.test_beleg_pdf import FIRMA, _beleg

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}


@pytest.fixture
def firma(test_einstellungen):
    test_einstellungen.firma = FIRMA
    return test_einstellungen


def _baum(beleg) -> etree._Element:
    return etree.fromstring(xml_erzeugen(beleg, FIRMA))


def _text(baum: etree._Element, pfad: str) -> str | None:
    treffer = baum.xpath(pfad, namespaces=NS)
    return treffer[0].text if treffer else None


class TestWerBekommtEineERechnung:
    def test_b2b_ueber_der_kleinbetragsgrenze_ja(self, firma):
        assert braucht_erechnung(_beleg()) is True

    def test_b2c_nein(self, firma):
        """Für Privatkunden gibt es keine Pflicht – ein normales PDF genügt (PLAN §6.3)."""
        beleg = _beleg()
        beleg.kunde_snapshot["typ"] = "b2c"
        assert braucht_erechnung(beleg) is False

    def test_kleinbetrag_nein(self, firma):
        """Unter 250 € brutto dürfen Angaben fehlen, die EN 16931 verlangt (§ 33 UStDV)."""
        beleg = _beleg()
        beleg.positionen[0].ep_netto = 10000
        summen_setzen(beleg)
        assert beleg.brutto < firma.fakturierung.kleinbetrag_grenze_cent
        assert braucht_erechnung(beleg) is False

    def test_auftragsbestaetigung_nein(self, firma):
        """Eine AB ist keine Rechnung (PLAN §10)."""
        beleg = _beleg("ab", abschlag_nr=None, rechnung_nr="AB-2026-0007")
        assert braucht_erechnung(beleg) is False

    def test_storno_ja(self, firma):
        """Eine Korrektur muss denselben Weg gehen wie der Beleg, den sie korrigiert."""
        beleg = _beleg("storno", abschlag_nr=None)
        beleg.positionen[0].ep_netto = -9187500
        summen_setzen(beleg)
        assert braucht_erechnung(beleg) is True


class TestSchemagueltigkeit:
    def test_xml_ist_gegen_das_en16931_schema_gueltig(self, firma):
        """Ein ungültiges XML im PDF ist schlimmer als keins: der Empfänger scheitert daran."""
        xml = xml_erzeugen(_beleg(), FIRMA)
        assert pruefen_gegen_schema(xml).startswith(b"<?xml")

    def test_schlussrechnung_mit_absetzungsblock_ist_gueltig(self, firma):
        beleg = _beleg("schluss", abschlag_nr=None)
        beleg.absetzungen = [
            Absetzung(
                pos=1,
                rechnung_nr="RE-2026-0031",
                datum=date(2026, 4, 2),
                netto=5000000,
                ust_satz=190,
                ust=950000,
            )
        ]
        summen_setzen(beleg)
        assert pruefen_gegen_schema(xml_erzeugen(beleg, FIRMA))

    def test_null_prozent_beleg_ist_gueltig(self, firma):
        beleg = _beleg(ust_kz="0")
        beleg.positionen[0].ust_satz = 0
        summen_setzen(beleg)
        assert pruefen_gegen_schema(xml_erzeugen(beleg, FIRMA))

    def test_gemischte_saetze_sind_gueltig(self, firma):
        beleg = _beleg(ust_kz="gemischt")
        beleg.positionen.append(
            Rechnungsposition(
                pos=2, bezeichnung="Speicher", menge=Decimal(1), ep_netto=1450000, ust_satz=0
            )
        )
        summen_setzen(beleg)
        assert pruefen_gegen_schema(xml_erzeugen(beleg, FIRMA))

    def test_entwurf_ohne_nummer_wird_abgewiesen(self, firma):
        beleg = _beleg(rechnung_nr=None, status="entwurf")
        with pytest.raises(ERechnungFehler) as fehler:
            xml_erzeugen(beleg, FIRMA)
        assert "Rechnungsnummer" in str(fehler.value)


class TestPflichtfelder:
    def test_profil_ist_en16931(self, firma):
        baum = _baum(_beleg())
        assert (
            _text(baum, "//ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
            == "urn:cen.eu:en16931:2017"
        )

    def test_nummer_datum_und_typ(self, firma):
        baum = _baum(_beleg())
        assert _text(baum, "//rsm:ExchangedDocument/ram:ID") == "RE-2026-0143"
        assert _text(baum, "//rsm:ExchangedDocument/ram:TypeCode") == "380"
        # Das Belegdatum steht als udt:DateTimeString im Format 102 (JJJJMMTT).
        assert "20260827" in etree.tostring(baum).decode()

    def test_gutschrift_traegt_den_code_381(self, firma):
        baum = _baum(_beleg("gutschrift", abschlag_nr=None))
        assert _text(baum, "//rsm:ExchangedDocument/ram:TypeCode") == "381"

    def test_verkaeufer_mit_anschrift_und_ust_id(self, firma):
        baum = _baum(_beleg())
        assert _text(baum, "//ram:SellerTradeParty/ram:Name") == "ip³ Energietechnik GmbH"
        assert _text(baum, "//ram:SellerTradeParty//ram:LineOne") == "Brandweg 1"
        assert _text(baum, "//ram:SellerTradeParty//ram:PostcodeCode") == "92637"
        assert _text(baum, "//ram:SellerTradeParty//ram:CityName") == "Theisseil"
        assert _text(baum, "//ram:SellerTradeParty//ram:CountryID") == "DE"
        kennungen = baum.xpath(
            "//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID", namespaces=NS
        )
        assert [k.text for k in kennungen] == ["DE346672260"]
        assert [k.get("schemeID") for k in kennungen] == ["VA"]

    def test_kaeufer_mit_anschrift(self, firma):
        baum = _baum(_beleg())
        assert _text(baum, "//ram:BuyerTradeParty/ram:Name") == "Maschinenbau Köstler GmbH"
        assert _text(baum, "//ram:BuyerTradeParty//ram:LineOne") == "Bahnhofstraße 12"
        assert _text(baum, "//ram:BuyerTradeParty//ram:PostcodeCode") == "92660"
        assert _text(baum, "//ram:BuyerTradeParty/ram:ID") == "10042"

    def test_waehrung_und_zahlungsangaben(self, firma):
        baum = _baum(_beleg())
        assert _text(baum, "//ram:InvoiceCurrencyCode") == "EUR"
        assert _text(baum, "//ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == (
            "DE76753900000000556424"
        )
        assert _text(baum, "//ram:TypeCode[text()='58']") == "58"

    def test_leistungszeitraum_steht_als_hinweis_darin(self, firma):
        inhalt = etree.tostring(_baum(_beleg()), encoding="unicode")
        assert "Leistungszeitraum: 02.03.–27.08.2026" in inhalt

    def test_positionen_mit_menge_und_einzelpreis(self, firma):
        baum = _baum(_beleg())
        zeilen = baum.xpath("//ram:IncludedSupplyChainTradeLineItem", namespaces=NS)
        assert len(zeilen) == 1
        assert _text(baum, "//ram:SpecifiedTradeProduct/ram:Name").startswith("Errichtung")
        assert _text(baum, "//ram:NetPriceProductTradePrice/ram:ChargeAmount") == "91875.00"


class TestZahlenStimmenMitDemPapierUeberein:
    def test_summen_der_abschlagsrechnung(self, firma):
        beleg = _beleg()
        baum = _baum(beleg)
        assert _text(baum, "//ram:LineTotalAmount") == "91875.00"
        assert _text(baum, "//ram:TaxBasisTotalAmount") == "91875.00"
        assert _text(baum, "//ram:TaxTotalAmount") == "17456.25"
        assert _text(baum, "//ram:GrandTotalAmount") == "109331.25"
        assert _text(baum, "//ram:DuePayableAmount") == "109331.25"
        assert beleg.brutto == 10933125

    def test_absetzungsblock_wird_zur_anzahlung(self, firma):
        """BT-113: der abgesetzte Betrag; BT-115 ist dann der Restbetrag wie auf dem Papier."""
        beleg = _beleg("schluss", abschlag_nr=None)
        beleg.positionen[0].ep_netto = 36750000
        beleg.absetzungen = [
            Absetzung(
                pos=nummer,
                rechnung_nr=nummer_text,
                datum=date(2026, 4, 2),
                netto=netto,
                ust_satz=190,
                ust=ust,
            )
            for nummer, (nummer_text, netto, ust) in enumerate(
                [
                    ("RE-2026-0031", 11025000, 2094750),
                    ("RE-2026-0078", 11025000, 2094750),
                    ("RE-2026-0112", 9187500, 1745625),
                ],
                start=1,
            )
        ]
        summen_setzen(beleg)
        baum = _baum(beleg)
        assert _text(baum, "//ram:GrandTotalAmount") == "437325.00"
        assert _text(baum, "//ram:TotalPrepaidAmount") == "371726.25"
        assert _text(baum, "//ram:DuePayableAmount") == "65598.75"
        assert beleg.zahlbetrag == 6559875, "Dieselbe Zahl wie auf dem PDF"

    def test_jeder_abgesetzte_abschlag_wird_genannt(self, firma):
        beleg = _beleg("schluss", abschlag_nr=None)
        beleg.absetzungen = [
            Absetzung(
                pos=1,
                rechnung_nr="RE-2026-0031",
                datum=date(2026, 4, 2),
                netto=11025000,
                ust_satz=190,
                ust=2094750,
            )
        ]
        summen_setzen(beleg)
        inhalt = etree.tostring(_baum(beleg), encoding="unicode")
        assert "RE-2026-0031" in inhalt
        assert "02.04.2026" in inhalt

    def test_steuer_je_satz_getrennt(self, firma):
        beleg = _beleg(ust_kz="gemischt")
        beleg.positionen.append(
            Rechnungsposition(
                pos=2, bezeichnung="Speicher", menge=Decimal(1), ep_netto=1450000, ust_satz=0
            )
        )
        summen_setzen(beleg)
        baum = _baum(beleg)
        saetze = baum.xpath(
            "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax", namespaces=NS
        )
        werte = {
            s.find("ram:RateApplicablePercent", NS).text: s.find("ram:CalculatedAmount", NS).text
            for s in saetze
        }
        assert werte == {"0": "0.00", "19": "17456.25"}


class TestSteuerbefreiung:
    def test_null_prozent_nennt_den_grund(self, firma):
        """EN 16931 weist einen Umsatz mit 0 % ohne Begründung zurück."""
        beleg = _beleg(ust_kz="0")
        beleg.positionen[0].ust_satz = 0
        summen_setzen(beleg)
        baum = _baum(beleg)
        assert _text(baum, "//ram:ExemptionReason") == "Steuersatz 0 % nach § 12 Abs. 3 UStG"
        assert _text(baum, "//ram:ApplicableTradeTax/ram:CategoryCode") == "Z"

    def test_dreizehn_b_wird_als_reverse_charge_ausgewiesen(self, firma):
        beleg = _beleg(ust_kz="13b")
        beleg.positionen[0].ust_satz = 0
        summen_setzen(beleg)
        baum = _baum(beleg)
        assert _text(baum, "//ram:ApplicableTradeTax/ram:CategoryCode") == "AE"
        assert "§ 13b UStG" in _text(baum, "//ram:ExemptionReason")


class TestEinbettung:
    def test_b2b_beleg_wird_als_pdf_a3_mit_anhang_abgelegt(self, firma, tmp_path):
        ablage = Rechnungsablage(tmp_path / "01_Rechnungen")
        dateien = ablage.rendern(_beleg())
        assert dateien.xml_name == "RE-2026-0143_26014_Maschinenbau-Koestler-GmbH.xml"
        assert dateien.xml_bytes is not None
        assert dateien.pdf_bytes.startswith(b"%PDF")
        # Der Anhang muss unter dem vorgeschriebenen Namen im PDF stehen – ein Prüfprogramm
        # sucht genau diese Datei. Die Verweise liegen in komprimierten Objektströmen, eine
        # Suche in den Rohbytes fände sie nicht.
        assert ANHANGSNAME in eingebettete_dateien(dateien.pdf_bytes)
        assert ist_pdf_a3(dateien.pdf_bytes), "PDF/A-3 mit AFRelationship (Factur-X)"

    def test_beide_dateien_landen_im_ordner(self, firma, tmp_path):
        ablage = Rechnungsablage(tmp_path / "01_Rechnungen")
        pfade = ablage.schreiben(ablage.rendern(_beleg()))
        assert pfade.pdf_pfad.endswith(".pdf")
        assert pfade.xml_pfad.endswith(".xml")
        ordner = tmp_path / "01_Rechnungen"
        assert {p.suffix for p in ordner.iterdir()} == {".pdf", ".xml"}

    def test_b2c_beleg_bekommt_kein_xml(self, firma, tmp_path):
        beleg = _beleg()
        beleg.kunde_snapshot["typ"] = "b2c"
        ablage = Rechnungsablage(tmp_path / "01_Rechnungen")
        dateien = ablage.rendern(beleg)
        assert dateien.xml_name is None
        assert dateien.xml_bytes is None
        pfade = ablage.schreiben(dateien)
        assert pfade.xml_pfad is None
        assert {p.suffix for p in (tmp_path / "01_Rechnungen").iterdir()} == {".pdf"}

    def test_das_eingebettete_xml_ist_dasselbe_wie_die_datei(self, firma, tmp_path):
        ablage = Rechnungsablage(tmp_path / "01_Rechnungen")
        dateien = ablage.rendern(_beleg())
        pfade = ablage.schreiben(dateien)
        from pathlib import Path

        assert Path(pfade.xml_pfad).read_bytes() == dateien.xml_bytes
