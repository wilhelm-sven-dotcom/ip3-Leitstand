"""Rechnungs-PDF: Pflichtangaben, Corporate Design, Dateiname, Ablage (PLAN §10, §11).

Zwei Dinge werden hier getrennt geprüft, weil sie unabhängig kaputtgehen:

* **Der Inhalt** – die Pflichtangaben nach § 14 UStG. Der Text im fertigen PDF ist nicht
  durchsuchbar (Teilmengen der Schriften, Zeichen als Glyphennummern), deshalb läuft die Prüfung
  über den gesetzten Kastenbaum. Das erfasst auch die Fußzeile, die als ``running element`` in den
  Seitenrand läuft.
* **Das Corporate Design** – die eingebetteten Schriften. Beim Bau setzte WeasyPrint den Beleg
  stillschweigend in DejaVu Serif, weil Jinja die ``@font-face``-Regeln escapte. Nichts schlug
  fehl, der Beleg war nur falsch. Deshalb liest dieser Test die Schriftnamen aus dem PDF.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.belege import Rechnungsablage, ablage_aus_konfiguration
from app.belege.pdf import (
    dateiname,
    eingebettete_schriften,
    pdf_erzeugen,
    seitentexte,
)
from app.dienste.belegarten import summen_setzen
from app.dienste.festschreibung import Belegdateien
from app.konfiguration import FirmaEinstellungen
from app.modelle import Absetzung, Kunde, Projekt, Rechnung, Rechnungsposition

FIRMA = FirmaEinstellungen(
    strasse="Brandweg 1",
    plz="92637",
    ort="Theisseil",
    ust_id="DE346672260",
    hrb="HRB 5725 Amtsgericht Weiden",
    geschaeftsfuehrer="Sven Wilhelm, Michael Bäumler",
    telefon="+49 961 40191 360",
    bank={
        "institut": "VR Bank Nordoberpfalz eG",
        "iban": "DE76753900000000556424",
        "bic": "GENODEF1WEV",
    },
)


def _kunde() -> Kunde:
    return Kunde(
        kunden_nr=10042,
        name="Maschinenbau Köstler GmbH",
        strasse="Bahnhofstraße 12",
        plz="92660",
        ort="Neustadt a. d. Waldnaab",
        ust_id="DE123456789",
        typ="b2b",
    )


def _beleg(art: str = "abschlag", **felder) -> Rechnung:
    kunde = _kunde()
    projekt = Projekt(
        projekt_nr=26014,
        firma_id=1,
        kunde_id=1,
        bezeichnung="Aufdachanlage Halle 2",
        standort="Neustadt a. d. Waldnaab",
        ust_kz="19",
        ab_wert_netto=36750000,
        auftrag_vom=date(2026, 3, 2),
    )
    vorgabe = {
        "id": 1,
        "firma_id": 1,
        "art": art,
        "projekt_id": 1,
        "kunde_id": 1,
        "kunde_snapshot": {
            "kunden_nr": kunde.kunden_nr,
            "name": kunde.name,
            "strasse": kunde.strasse,
            "plz": kunde.plz,
            "ort": kunde.ort,
            "ust_id": kunde.ust_id,
            "typ": kunde.typ,
        },
        "ust_kz": "19",
        "datum": date(2026, 8, 27),
        "leistungszeitraum": "02.03.–27.08.2026",
        "faellig_am": date(2026, 9, 10),
        "rechnung_nr": "RE-2026-0143",
        "status": "festgeschrieben",
        "abschlag_nr": 3,
    }
    vorgabe.update(felder)
    beleg = Rechnung(**vorgabe)
    beleg.kunde = kunde
    beleg.projekt = projekt
    beleg.positionen = [
        Rechnungsposition(
            pos=1,
            bezeichnung="Errichtung der Anlage laut Auftrag vom 02.03.2026",
            menge=Decimal(1),
            ep_netto=9187500,
            ust_satz=190,
        )
    ]
    summen_setzen(beleg)
    return beleg


@pytest.fixture
def firma(test_einstellungen):
    """Vollständige Firmenstammdaten in der geladenen Konfiguration."""
    test_einstellungen.firma = FIRMA
    return test_einstellungen


class TestPflichtangaben:
    """§ 14 UStG. Jede fehlende Angabe macht den Beleg für den Vorsteuerabzug unbrauchbar."""

    def _text(self, beleg: Rechnung) -> str:
        return " ".join(seitentexte(beleg, FIRMA))

    @pytest.mark.parametrize(
        "erwartet",
        [
            "ip³ Energietechnik GmbH",
            "Brandweg 1",
            "92637",
            "Theisseil",
            "DE346672260",
            "HRB 5725 Amtsgericht Weiden",
            "Maschinenbau Köstler GmbH",
            "Bahnhofstraße 12",
            "92660 Neustadt a. d. Waldnaab",
            "RE-2026-0143",
            "27.08.2026",
            "02.03.–27.08.2026",
            "Errichtung der Anlage laut Auftrag vom 02.03.2026",
            "91.875,00",
            "17.456,25",
            "109.331,25",
            "19\u00a0%",
            "DE76753900000000556424",
        ],
    )
    def test_angabe_steht_auf_dem_beleg(self, firma, erwartet):
        assert erwartet in self._text(_beleg())

    def test_faelligkeit_steht_darauf(self, firma):
        assert "10.09.2026" in self._text(_beleg())

    def test_abschlagsnummer_steht_im_titel(self, firma):
        assert "3. Abschlagsrechnung" in self._text(_beleg())

    def test_objektzeile_wie_in_der_wordvorlage(self, firma):
        assert "Objekt: Aufdachanlage Halle 2, Neustadt a. d. Waldnaab" in self._text(_beleg())

    def test_fusszeile_steht_auf_jeder_seite(self, firma):
        """Die Fußzeile ist ein running element – im HTML steht sie einmal, im PDF auf jeder Seite."""
        beleg = _beleg()
        beleg.positionen = [
            Rechnungsposition(
                pos=nummer,
                bezeichnung=f"Position {nummer} mit einer etwas längeren Bezeichnung, "
                "damit der Beleg über eine Seite hinausläuft",
                menge=Decimal(1),
                ep_netto=100000,
                ust_satz=190,
            )
            for nummer in range(1, 45)
        ]
        summen_setzen(beleg)
        seiten = seitentexte(beleg, FIRMA)
        assert len(seiten) >= 2, "Der Beleg sollte für diesen Test mehrseitig sein"
        for nummer, text in enumerate(seiten, start=1):
            assert "Geschäftsführer: Sven Wilhelm, Michael Bäumler" in text, f"Seite {nummer}"
            assert "DE346672260" in text, f"Seite {nummer}"

    def test_seitenzahl_nennt_die_gesamtzahl(self, firma):
        beleg = _beleg()
        assert "1 / 1" in " ".join(seitentexte(beleg, FIRMA))


class TestSteuerausweis:
    def test_null_prozent_nennt_den_paragrafen(self, firma):
        beleg = _beleg(ust_kz="0")
        beleg.positionen[0].ust_satz = 0
        summen_setzen(beleg)
        text = " ".join(seitentexte(beleg, FIRMA))
        assert "§ 12 Abs. 3 UStG" in text
        assert "0\u00a0%" in text

    def test_dreizehn_b_nennt_die_steuerschuldnerschaft(self, firma):
        beleg = _beleg(ust_kz="13b")
        beleg.positionen[0].ust_satz = 0
        summen_setzen(beleg)
        text = " ".join(seitentexte(beleg, FIRMA))
        assert "Steuerschuldnerschaft des Leistungsempfängers" in text
        assert "§ 13b" in text

    def test_bei_mehreren_saetzen_steht_die_bemessungsgrundlage_dabei(self, firma):
        """§ 14 Abs. 4 Nr. 8 UStG: sonst ist nicht erkennbar, worauf der Steuerbetrag entfällt."""
        beleg = _beleg(ust_kz="gemischt")
        beleg.positionen.append(
            Rechnungsposition(
                pos=2,
                bezeichnung="Speicher für das Wohnhaus",
                menge=Decimal(1),
                ep_netto=1450000,
                ust_satz=0,
            )
        )
        summen_setzen(beleg)
        text = " ".join(seitentexte(beleg, FIRMA))
        assert "Umsatzsteuer 19\u00a0% auf 91.875,00\u00a0€" in text
        assert "Umsatzsteuer 0\u00a0% auf 14.500,00\u00a0€" in text

    def test_bei_einem_satz_bleibt_die_zeile_knapp(self, firma):
        text = " ".join(seitentexte(_beleg(), FIRMA))
        assert "Umsatzsteuer 19\u00a0%" in text
        assert "Umsatzsteuer 19\u00a0% auf" not in text


class TestAbsetzungsblock:
    def _schlussrechnung(self) -> Rechnung:
        beleg = _beleg("schluss", abschlag_nr=None)
        beleg.positionen = [
            Rechnungsposition(
                pos=1,
                bezeichnung="Errichtung der Anlage laut Auftrag vom 02.03.2026",
                menge=Decimal(1),
                ep_netto=36750000,
                ust_satz=190,
            )
        ]
        beleg.absetzungen = [
            Absetzung(
                pos=nummer,
                rechnung_nr=nummer_text,
                datum=datum,
                netto=netto,
                ust_satz=190,
                ust=ust,
            )
            for nummer, (nummer_text, datum, netto, ust) in enumerate(
                [
                    ("RE-2026-0031", date(2026, 4, 2), 11025000, 2094750),
                    ("RE-2026-0078", date(2026, 6, 15), 11025000, 2094750),
                    ("RE-2026-0112", date(2026, 7, 30), 9187500, 1745625),
                ],
                start=1,
            )
        ]
        summen_setzen(beleg)
        return beleg

    def test_jeder_abschlag_steht_mit_nummer_datum_netto_und_steuer(self, firma):
        text = " ".join(seitentexte(self._schlussrechnung(), FIRMA))
        for nummer, datum, netto, ust in [
            ("RE-2026-0031", "02.04.2026", "110.250,00", "20.947,50"),
            ("RE-2026-0078", "15.06.2026", "110.250,00", "20.947,50"),
            ("RE-2026-0112", "30.07.2026", "91.875,00", "17.456,25"),
        ]:
            assert nummer in text
            assert datum in text
            assert netto in text
            assert ust in text

    def test_restbetrag_wird_ausgewiesen(self, firma):
        beleg = self._schlussrechnung()
        text = " ".join(seitentexte(beleg, FIRMA))
        assert "Restbetrag zur Zahlung" in text
        assert "65.598,75" in text
        assert beleg.zahlbetrag == 6559875

    def test_paragraf_vierzehn_absatz_fuenf_wird_genannt(self, firma):
        text = " ".join(seitentexte(self._schlussrechnung(), FIRMA))
        assert "§ 14 Abs. 5 UStG" in text


class TestBelegarten:
    @pytest.mark.parametrize(
        "art,titel",
        [
            ("ab", "Auftragsbestätigung"),
            ("schluss", "Schlussrechnung"),
            ("service", "Servicerechnung"),
            ("gutschrift", "Gutschrift"),
            ("storno", "Stornorechnung"),
        ],
    )
    def test_titel_je_belegart(self, firma, art, titel):
        beleg = _beleg(art, abschlag_nr=None)
        assert titel in " ".join(seitentexte(beleg, FIRMA))

    def test_ab_nennt_keine_rechnungsnummer(self, firma):
        """Eine Auftragsbestätigung ist keine Rechnung (PLAN §10)."""
        beleg = _beleg("ab", abschlag_nr=None, rechnung_nr="AB-2026-0007")
        text = " ".join(seitentexte(beleg, FIRMA))
        assert "Auftragsbestätigung Nr." in text
        assert "Rechnung Nr." not in text

    def test_ab_zeigt_keine_bankverbindung(self, firma):
        beleg = _beleg("ab", abschlag_nr=None, rechnung_nr="AB-2026-0007")
        assert "Bankverbindung" not in " ".join(seitentexte(beleg, FIRMA))

    def test_entwurf_sagt_dass_die_nummer_noch_fehlt(self, firma):
        beleg = _beleg(rechnung_nr=None, status="entwurf")
        assert "wird bei der Festschreibung vergeben" in " ".join(seitentexte(beleg, FIRMA))

    def test_storno_bringt_sein_anschreiben_mit(self, firma):
        beleg = _beleg(
            "storno",
            abschlag_nr=None,
            anschreiben="Hiermit stornieren wir unsere Rechnung RE-2026-0100 vollständig.",
        )
        assert "stornieren wir unsere Rechnung RE-2026-0100" in " ".join(seitentexte(beleg, FIRMA))


class TestCorporateDesign:
    def test_die_cd_schriften_sind_eingebettet(self, firma):
        """PLAN §11: Libre Franklin für Text, Space Grotesk für Zahlen.

        Ohne diese Prüfung wäre der Fehler unsichtbar gewesen: WeasyPrint fällt bei einer
        ungültigen ``@font-face``-Regel auf die Systemschrift zurück, ohne etwas zu melden.
        """
        schriften = eingebettete_schriften(pdf_erzeugen(_beleg(), FIRMA))
        assert any("Libre-Franklin" in name for name in schriften), schriften
        assert any("Space-Grotesk" in name for name in schriften), schriften
        assert not any("DejaVu" in name or "Serif" in name for name in schriften), schriften

    def test_kein_gruen_und_keine_verlaeufe_im_stil(self):
        """Corporate Design: nur die Markenfarben, keine Verläufe."""
        stil = (Path(__file__).resolve().parents[1] / "app/belege/vorlagen/beleg.css").read_text()
        assert "gradient" not in stil.lower()
        for farbe in ("#2F2482", "#C83C30", "#666666", "#E0E0E0", "#F5F6F9"):
            assert farbe in stil
        # ENMAG-Grün und Ampelgrün gehören nicht in ein ip³-Dokument.
        assert "4C9B3B" not in stil.upper()
        assert "green" not in stil.lower()

    def test_zahlen_stehen_in_tabellenziffern(self):
        stil = (Path(__file__).resolve().parents[1] / "app/belege/vorlagen/beleg.css").read_text()
        assert "font-variant-numeric: tabular-nums" in stil
        assert "Space Grotesk" in stil

    def test_kein_zeichen_drei_auf_der_rechnung(self):
        """Die CD-Regel schließt das Wasserzeichen auf zahlenlastigen Flächen aus."""
        vorlage = (
            Path(__file__).resolve().parents[1] / "app/belege/vorlagen/beleg.html"
        ).read_text()
        assert "zeichen-3" not in vorlage

    def test_geschuetztes_leerzeichen_vor_der_einheit(self, firma):
        """PLAN §6.10: ``2,5 Stk`` mit geschütztem Leerzeichen."""
        beleg = _beleg()
        beleg.positionen[0].menge = Decimal("2.5")
        beleg.positionen[0].einheit = "Stk"
        summen_setzen(beleg)
        # Auf dem gesetzten Beleg geprüft, nicht im HTML: dort steht die Entität `&nbsp;`.
        assert "2,5\u00a0Stk" in " ".join(seitentexte(beleg, FIRMA))


class TestDateiname:
    def test_schema_aus_plan_paragraf_sieben(self, firma):
        assert dateiname(_beleg()) == "RE-2026-0143_26014_Maschinenbau-Koestler-GmbH.pdf"

    def test_umlaute_werden_umgeschrieben(self, firma):
        beleg = _beleg()
        beleg.kunde_snapshot["name"] = "Müller & Söhne GbR"
        assert dateiname(beleg) == "RE-2026-0143_26014_Mueller-Soehne-GbR.pdf"

    def test_verbotene_zeichen_verschwinden(self, firma):
        """Der Rechnungsordner liegt im OneDrive und wird von Windows aus benutzt."""
        beleg = _beleg()
        beleg.kunde_snapshot["name"] = 'Bau: Nord/Süd "GmbH" <Test>'
        name = dateiname(beleg)
        assert not any(zeichen in name for zeichen in '\\/:*?"<>|')

    def test_entwurf_ohne_nummer_bekommt_einen_namen(self, firma):
        beleg = _beleg(rechnung_nr=None, status="entwurf")
        assert dateiname(beleg).startswith("entwurf-1_26014_")


class TestAblage:
    def test_pdf_landet_im_rechnungsordner(self, firma, tmp_path):
        ablage = Rechnungsablage(tmp_path / "01_Rechnungen")
        dateien = ablage.rendern(_beleg())
        pfade = ablage.schreiben(dateien)
        ziel = Path(pfade.pdf_pfad)
        assert ziel.exists()
        assert ziel.read_bytes().startswith(b"%PDF")
        assert ziel.name == "RE-2026-0143_26014_Maschinenbau-Koestler-GmbH.pdf"

    def test_pfade_stehen_vor_dem_schreiben_fest(self, firma, tmp_path):
        """Sie müssen im selben UPDATE stehen wie der Status – danach sperrt der Trigger."""
        ablage = Rechnungsablage(tmp_path / "01_Rechnungen")
        pfade = ablage.pfade(Belegdateien(pdf_name="RE-2026-0143.pdf", pdf_bytes=b""))
        assert pfade.pdf_pfad.endswith("01_Rechnungen/RE-2026-0143.pdf")
        assert not (tmp_path / "01_Rechnungen").exists()

    def test_unerreichbarer_uebergeordneter_ordner_wird_gemeldet(self, firma, tmp_path):
        """Kein Ersatzordner im Nichts: ein nicht verbundenes OneDrive soll auffallen."""
        ablage = Rechnungsablage(tmp_path / "nicht-verbunden" / "01_Rechnungen")
        with pytest.raises(OSError) as fehler:
            ablage.schreiben(Belegdateien(pdf_name="x.pdf", pdf_bytes=b"x"))
        assert "nicht erreichbar" in str(fehler.value)

    def test_ohne_konfigurierten_ordner_gibt_es_keine_ablage(self, firma):
        firma.pfade.rechnungen = None
        assert ablage_aus_konfiguration() is None

    def test_mit_konfiguriertem_ordner_entsteht_eine_ablage(self, firma, tmp_path):
        firma.pfade.rechnungen = tmp_path / "01_Rechnungen"
        ablage = ablage_aus_konfiguration()
        assert isinstance(ablage, Rechnungsablage)
        assert ablage.ordner == tmp_path / "01_Rechnungen"


class TestFehlendeSchriften:
    def test_ohne_schriftdateien_entsteht_trotzdem_ein_beleg(self, firma, tmp_path, caplog):
        """Ein Abbruch beim Festschreiben wegen einer fehlenden Schrift wäre der falsche Preis."""
        firma.pfade.cd_assets = tmp_path / "leer"
        (tmp_path / "leer").mkdir()
        daten = pdf_erzeugen(_beleg(), FIRMA)
        assert daten.startswith(b"%PDF")
        assert any("Schriftdateien" in eintrag.message for eintrag in caplog.records)
