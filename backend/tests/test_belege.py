"""Belegrechnung: Umsatzsteuer, Pflichtangaben, Fälligkeit, Hash (PLAN §6.2, §6.11, §6.4).

Diese Tests prüfen die eine Stelle, die aus Positionen einen Beleg macht. Ein Cent Abweichung
zwischen Positionssumme und Belegsumme ist hier kein Schönheitsfehler, sondern genau das, worauf
eine Betriebsprüfung schaut.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.dienste.belege import (
    HINWEIS_13B,
    HINWEIS_ABSETZUNG,
    HINWEIS_NULL_PROZENT,
    beleg_hash,
    faelligkeit,
    fehlende_pflichtangaben,
    kunde_snapshot,
    steuer_hinweise,
    summen_berechnen,
    zahlungsziel,
)
from app.konfiguration import Einstellungen, FirmaEinstellungen
from app.modelle import Kunde, Rechnung, Rechnungsposition


def pos(
    nummer: int,
    ep_netto: int,
    ust_satz: int = 190,
    menge: Decimal | int | str = 1,
    bezeichnung: str = "Leistung",
) -> Rechnungsposition:
    return Rechnungsposition(
        pos=nummer,
        bezeichnung=bezeichnung,
        menge=Decimal(str(menge)),
        ep_netto=ep_netto,
        ust_satz=ust_satz,
    )


VOLLSTAENDIGE_FIRMA = FirmaEinstellungen(
    strasse="Brandweg 1",
    plz="92637",
    ort="Theisseil",
    ust_id="DE346672260",
    hrb="HRB 5725 Amtsgericht Weiden",
    geschaeftsfuehrer="Sven Wilhelm, Michael Bäumler",
    bank={
        "institut": "VR Bank Nordoberpfalz",
        "iban": "DE76753900000000556424",
        "bic": "GENODEF1WEV",
    },
)


class TestUmsatzsteuer:
    def test_steuer_wird_einmal_auf_die_nettosumme_gerechnet(self):
        """PLAN §6.11: je Steuersatz auf die Belegsumme, nicht je Position.

        Der klassische Fall: 3 × 33,33 € netto. Positionsweise gerundet ergibt 3 × 6,33 € =
        18,99 €; richtig sind 19 % von 99,99 € = 19,00 €. Ein Cent Unterschied – und die
        Belegsumme passt nicht zur Positionssumme.
        """
        summen = summen_berechnen([pos(1, 3333), pos(2, 3333), pos(3, 3333)])
        assert summen.netto == 9999
        assert summen.ust == 1900
        assert summen.brutto == 11899

    def test_gemischte_saetze_werden_getrennt_ausgewiesen(self):
        summen = summen_berechnen([pos(1, 100000, 190), pos(2, 50000, 0)])
        assert [(a.satz, a.netto, a.ust) for a in summen.je_satz] == [
            (0, 50000, 0),
            (190, 100000, 19000),
        ]
        assert summen.netto == 150000
        assert summen.ust == 19000
        assert summen.brutto == 169000

    def test_menge_und_einzelpreis_werden_kaufmaennisch_gerundet(self):
        # 2,5 × 1.234,57 € = 3.086,425 € → 3.086,43 € (0,5 Cent wird aufgerundet).
        summen = summen_berechnen([pos(1, 123457, 190, menge="2.5")])
        assert summen.netto == 308643

    def test_nur_null_prozent_ergibt_keine_steuer(self):
        summen = summen_berechnen([pos(1, 2500000, 0)])
        assert summen.ust == 0
        assert summen.brutto == summen.netto == 2500000

    def test_ust_details_sind_speicherbar(self):
        summen = summen_berechnen([pos(1, 100000, 190), pos(2, 50000, 0)])
        assert summen.ust_details() == [
            {"satz": 0, "netto": 50000, "ust": 0},
            {"satz": 190, "netto": 100000, "ust": 19000},
        ]

    def test_prozenttext_deutsch(self):
        """Mit geschütztem Leerzeichen vor dem Prozentzeichen (PLAN §6.10)."""
        summen = summen_berechnen([pos(1, 10000, 190), pos(2, 10000, 75), pos(3, 10000, 0)])
        assert [a.prozent_text for a in summen.je_satz] == ["0\u00a0%", "7,5\u00a0%", "19\u00a0%"]


class TestZahlbetrag:
    def test_ohne_absetzung_ist_der_zahlbetrag_der_bruttobetrag(self):
        summen = summen_berechnen([pos(1, 100000)])
        assert summen.zahlbetrag == summen.brutto == 119000

    def test_absetzung_mindert_den_zahlbetrag(self):
        """Die Schlussrechnung weist die Gesamtleistung aus und setzt die Abschläge ab."""
        summen = summen_berechnen([pos(1, 1000000)], absetzung_netto=600000, absetzung_ust=114000)
        assert summen.netto == 1000000
        assert summen.ust == 190000
        assert summen.brutto == 1190000
        assert summen.absetzung_brutto == 714000
        assert summen.zahlbetrag == 476000

    def test_negativer_zahlbetrag_wird_nicht_geklammert(self):
        """Mehr abgesetzt als berechnet heißt: der Kunde bekommt Geld zurück.

        Auf null zu klammern wäre eine Aussage über Zahlen, die niemand geprüft hat – und der
        Beleg wäre falsch.
        """
        summen = summen_berechnen([pos(1, 100000)], absetzung_netto=200000, absetzung_ust=38000)
        assert summen.zahlbetrag == -119000


class TestSteuerhinweise:
    def test_dreizehn_b_weist_auf_die_steuerschuldnerschaft_hin(self):
        hinweise = steuer_hinweise("13b", [pos(1, 100000, 0)])
        assert hinweise == [HINWEIS_13B]

    def test_null_prozent_nennt_paragraf_zwoelf_absatz_drei(self):
        """Derselbe Steuersatz 0, ein anderer Grund – und ein anderer Pflichthinweis."""
        hinweise = steuer_hinweise("0", [pos(1, 100000, 0)])
        assert hinweise == [HINWEIS_NULL_PROZENT]

    def test_neunzehn_prozent_braucht_keinen_hinweis(self):
        assert steuer_hinweise("19", [pos(1, 100000, 190)]) == []

    def test_gemischt_mit_einer_null_position_nennt_den_grund(self):
        hinweise = steuer_hinweise("gemischt", [pos(1, 100000, 190), pos(2, 50000, 0)])
        assert hinweise == [HINWEIS_NULL_PROZENT]

    def test_absetzungsblock_wird_erwaehnt(self):
        hinweise = steuer_hinweise("19", [pos(1, 100000, 190)], mit_absetzung=True)
        assert hinweise == [HINWEIS_ABSETZUNG]


class TestFaelligkeit:
    def test_zahlungsziel_des_kunden_geht_vor(self, test_einstellungen: Einstellungen):
        kunde = Kunde(kunden_nr=10001, name="Köstler GmbH", typ="b2b", zahlungsziel_tage=30)
        assert zahlungsziel(kunde) == 30
        assert faelligkeit(date(2026, 8, 27), kunde) == date(2026, 9, 26)

    def test_ohne_angabe_gilt_die_konfiguration(self, test_einstellungen: Einstellungen):
        kunde = Kunde(kunden_nr=10002, name="Gruber", typ="b2c")
        assert zahlungsziel(kunde) == test_einstellungen.fakturierung.zahlungsziel_tage == 14
        assert faelligkeit(date(2026, 8, 27), kunde) == date(2026, 9, 10)

    def test_null_tage_des_kunden_wird_nicht_als_fehlend_gelesen(
        self, test_einstellungen: Einstellungen
    ):
        """0 Tage heißt „sofort fällig" und ist eine Angabe, kein leeres Feld."""
        kunde = Kunde(kunden_nr=10003, name="Barzahler", typ="b2c", zahlungsziel_tage=0)
        assert zahlungsziel(kunde) == 0
        assert faelligkeit(date(2026, 8, 27), kunde) == date(2026, 8, 27)


class TestKundensnapshot:
    def test_snapshot_haelt_die_angaben_nach_paragraf_vierzehn(self):
        kunde = Kunde(
            kunden_nr=10001,
            name="Maschinenbau Köstler GmbH",
            strasse="Bahnhofstraße 12",
            plz="92660",
            ort="Neustadt a. d. Waldnaab",
            ust_id="DE123456789",
            typ="b2b",
        )
        snapshot = kunde_snapshot(kunde)
        assert snapshot["name"] == "Maschinenbau Köstler GmbH"
        assert snapshot["plz"] == "92660"
        assert snapshot["ust_id"] == "DE123456789"


class TestPflichtangaben:
    def _beleg(self, **felder) -> Rechnung:
        vorgabe = {
            "art": "abschlag",
            "datum": date(2026, 8, 27),
            "ust_kz": "19",
            "leistungszeitraum": "01.07.–27.08.2026",
            "kunde_snapshot": {
                "name": "Maschinenbau Köstler GmbH",
                "strasse": "Bahnhofstraße 12",
                "plz": "92660",
                "ort": "Neustadt a. d. Waldnaab",
                "ust_id": "DE123456789",
            },
        }
        vorgabe.update(felder)
        return Rechnung(**vorgabe)

    def test_vollstaendiger_beleg_hat_nichts_offen(self):
        fehlt = fehlende_pflichtangaben(self._beleg(), [pos(1, 100000)], VOLLSTAENDIGE_FIRMA)
        assert fehlt == []

    def test_fehlender_leistungszeitraum_wird_genannt(self):
        fehlt = fehlende_pflichtangaben(
            self._beleg(leistungszeitraum="  "), [pos(1, 100000)], VOLLSTAENDIGE_FIRMA
        )
        assert "Leistungszeitraum" in fehlt

    def test_beleg_ohne_positionen_ist_unvollstaendig(self):
        fehlt = fehlende_pflichtangaben(self._beleg(), [], VOLLSTAENDIGE_FIRMA)
        assert "mindestens eine Position" in fehlt

    def test_dreizehn_b_ohne_ust_id_des_kunden_wird_abgewiesen(self):
        """PLAN §6.2: 13b nur bei hinterlegter USt-ID – sonst ist der Empfänger kein Unternehmer."""
        beleg = self._beleg(
            ust_kz="13b",
            kunde_snapshot={
                "name": "Gruber",
                "strasse": "Hauptstraße 28",
                "plz": "92699",
                "ort": "Bechtsrieth",
                "ust_id": "",
            },
        )
        fehlt = fehlende_pflichtangaben(beleg, [pos(1, 100000, 0)], VOLLSTAENDIGE_FIRMA)
        assert any("13b" in eintrag for eintrag in fehlt)

    def test_satz_muss_zum_kennzeichen_passen(self):
        fehlt = fehlende_pflichtangaben(
            self._beleg(ust_kz="0"), [pos(1, 100000, 190)], VOLLSTAENDIGE_FIRMA
        )
        assert any("gemischt" in eintrag for eintrag in fehlt)

    def test_gemischt_laesst_verschiedene_saetze_zu(self):
        fehlt = fehlende_pflichtangaben(
            self._beleg(ust_kz="gemischt"),
            [pos(1, 100000, 190), pos(2, 50000, 0)],
            VOLLSTAENDIGE_FIRMA,
        )
        assert fehlt == []

    def test_unvollstaendige_firmenangaben_blockieren(self):
        fehlt = fehlende_pflichtangaben(
            self._beleg(), [pos(1, 100000)], FirmaEinstellungen(strasse="", plz="")
        )
        assert "Straße und Hausnummer" in fehlt
        assert "Steuernummer oder Umsatzsteuer-Identifikationsnummer" in fehlt

    def test_alles_fehlende_kommt_auf_einmal(self):
        """Der Reihe nach gemeldet müsste der Nutzer fünfmal speichern, um alles zu erfahren."""
        beleg = self._beleg(leistungszeitraum=None, kunde_snapshot={})
        fehlt = fehlende_pflichtangaben(beleg, [], VOLLSTAENDIGE_FIRMA)
        assert len(fehlt) >= 4


class TestHash:
    def _beleg(self) -> Rechnung:
        return Rechnung(
            rechnung_nr="RE-2026-0001",
            art="abschlag",
            datum=date(2026, 8, 27),
            leistungszeitraum="01.07.–27.08.2026",
            faellig_am=date(2026, 9, 10),
            ust_kz="19",
            kunde_snapshot={"name": "Köstler GmbH", "kunden_nr": 10001},
            projekt_id=7,
        )

    def test_gleiche_daten_ergeben_denselben_hash(self):
        positionen = [pos(1, 100000), pos(2, 50000)]
        summen = summen_berechnen(positionen)
        erster = beleg_hash(self._beleg(), positionen, summen)
        zweiter = beleg_hash(self._beleg(), positionen, summen)
        assert erster == zweiter
        assert len(erster) == 64

    def test_reihenfolge_der_positionen_ist_unerheblich(self):
        """Sonst hinge der Hash daran, in welcher Reihenfolge die Datenbank die Zeilen liefert."""
        vorwaerts = [pos(1, 100000), pos(2, 50000)]
        rueckwaerts = [pos(2, 50000), pos(1, 100000)]
        assert beleg_hash(self._beleg(), vorwaerts, summen_berechnen(vorwaerts)) == beleg_hash(
            self._beleg(), rueckwaerts, summen_berechnen(rueckwaerts)
        )

    @pytest.mark.parametrize(
        "aenderung",
        [
            {"rechnung_nr": "RE-2026-0002"},
            {"datum": date(2026, 8, 28)},
            {"leistungszeitraum": "01.08.–27.08.2026"},
            {"ust_kz": "0"},
            {"kunde_snapshot": {"name": "Anders GmbH", "kunden_nr": 10002}},
        ],
    )
    def test_jede_aenderung_am_kopf_aendert_den_hash(self, aenderung):
        positionen = [pos(1, 100000)]
        summen = summen_berechnen(positionen)
        original = beleg_hash(self._beleg(), positionen, summen)
        beleg = self._beleg()
        for feld, wert in aenderung.items():
            setattr(beleg, feld, wert)
        assert beleg_hash(beleg, positionen, summen) != original

    def test_geaenderter_betrag_aendert_den_hash(self):
        original = beleg_hash(self._beleg(), [pos(1, 100000)], summen_berechnen([pos(1, 100000)]))
        geaendert = beleg_hash(self._beleg(), [pos(1, 100001)], summen_berechnen([pos(1, 100001)]))
        assert geaendert != original

    def test_absetzungsblock_geht_in_den_hash_ein(self):
        positionen = [pos(1, 1000000)]
        summen = summen_berechnen(positionen, absetzung_netto=600000, absetzung_ust=114000)
        ohne = beleg_hash(self._beleg(), positionen, summen)
        mit = beleg_hash(
            self._beleg(),
            positionen,
            summen,
            absetzungen=[{"rechnung_nr": "RE-2026-0001", "netto": 600000, "ust": 114000}],
        )
        assert mit != ohne
