"""Belege erzeugen: AB, Abschlag, Schlussrechnung, Service, Storno, Gutschrift (PLAN §7 Phase 3).

Der Schwerpunkt liegt auf den beiden Regeln, die man nicht sehen kann, wenn man nur die
Oberfläche bedient: dass die Schlussrechnung keinen Weg am Absetzungsblock vorbei hat
(§ 14 Abs. 5 UStG), und dass Projekte mit Altabschlägen davon ausgenommen sind, weil zu ihnen
die Pflichtangaben fehlen (Entscheidung 16).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.datenbank import schreib_sitzung
from app.dienste.belegarten import (
    BelegFehler,
    ab_aus_projekt,
    abschlag_aus_position,
    gutschrift,
    kreis_fuer,
    offene_vorschlaege,
    schlussrechnung,
    servicerechnung,
    steuersatz,
    storno,
)
from app.dienste.festschreibung import festschreiben
from app.fehler import NichtGefunden
from app.modelle import (
    Firma,
    Kunde,
    Meilenstein,
    Nachtrag,
    Projekt,
    Rechnung,
    Zahlungsplanposition,
)


@pytest.fixture
def bestand(gesäte_db, vollstaendige_firma) -> dict:
    """Ein laufendes Projekt mit Zahlungsplan, dazu ein Altprojekt mit gestellten Positionen."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(
            kunden_nr=12001,
            name="Maschinenbau Köstler GmbH",
            strasse="Bahnhofstraße 12",
            plz="92660",
            ort="Neustadt a. d. Waldnaab",
            ust_id="DE123456789",
            typ="b2b",
        )
        privat = Kunde(
            kunden_nr=12002,
            name="Thomas und Marina Gruber",
            strasse="Hauptstraße 28",
            plz="92699",
            ort="Bechtsrieth",
            typ="b2c",
        )
        sitzung.add_all([kunde, privat])
        sitzung.flush()

        projekt = Projekt(
            projekt_nr=26014,
            firma_id=firma_id,
            kunde_id=kunde.id,
            standort="Neustadt a. d. Waldnaab",
            ab_wert_netto=36750000,
            auftrag_vom=date(2026, 3, 2),
            ust_kz="19",
            status="in_bau",
        )
        alt = Projekt(
            projekt_nr=25088,
            firma_id=firma_id,
            kunde_id=privat.id,
            ab_wert_netto=5500000,
            ust_kz="0",
            status="in_bau",
        )
        sitzung.add_all([projekt, alt])
        sitzung.flush()

        positionen = [
            Zahlungsplanposition(
                projekt_id=projekt.id,
                pos_nr=nummer,
                bezeichnung=bezeichnung,
                gewerk="pv",
                art="abschlag",
                betrag_netto=betrag,
                plan_monat="2026-09",
                trigger_status=ausloeser,
            )
            for nummer, (bezeichnung, betrag, ausloeser) in enumerate(
                [
                    ("1. Abschlag Auftragserteilung", 11025000, None),
                    ("2. Abschlag Lieferung", 11025000, "lieferung"),
                    ("3. Abschlag Inbetriebnahme", 9187500, "abnahme"),
                ],
                start=1,
            )
        ]
        rest = Zahlungsplanposition(
            projekt_id=projekt.id,
            pos_nr=4,
            bezeichnung="Schlussrechnung",
            gewerk="pv",
            art="schluss",
            betrag_netto=5512500,
            plan_monat="2026-12",
        )
        alt_position = Zahlungsplanposition(
            projekt_id=alt.id,
            pos_nr=1,
            bezeichnung="1. Abschlag",
            gewerk="pv",
            art="abschlag",
            betrag_netto=2750000,
            migriert_gestellt=True,
            quelle_migration="Offene_Auftraege_2025.xlsx:17",
        )
        sitzung.add_all([*positionen, rest, alt_position])
        sitzung.flush()
        return {
            "firma": firma_id,
            "kunde": kunde.id,
            "privat": privat.id,
            "projekt": projekt.id,
            "alt_projekt": alt.id,
            "positionen": [p.id for p in positionen],
            "rest": rest.id,
            "alt_position": alt_position.id,
        }


def _festschreiben(beleg_id: int) -> Rechnung:
    from app.datenbank import schreib_transaktion

    with schreib_sitzung() as sitzung, schreib_transaktion(sitzung):
        beleg = sitzung.get(Rechnung, beleg_id)
        festschreiben(sitzung, beleg)
        return beleg


class TestSteuersatz:
    @pytest.mark.parametrize("kennzeichen,satz", [("19", 190), ("0", 0), ("13b", 0)])
    def test_satz_je_kennzeichen(self, kennzeichen, satz):
        assert steuersatz(kennzeichen) == satz

    def test_gemischt_belegt_mit_dem_regelsatz_vor(self):
        """Ein richtiger Default existiert nicht; die Pflichtprüfung verlangt später den Satz."""
        assert steuersatz("gemischt") == 190


class TestAuftragsbestaetigung:
    def test_ab_uebernimmt_den_zahlungsplan(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = ab_aus_projekt(sitzung, bestand["projekt"])
            sitzung.add(beleg)
            sitzung.flush()
            assert beleg.art == "ab"
            assert len(beleg.positionen) == 4
            assert beleg.netto == 11025000 + 11025000 + 9187500 + 5512500
            assert beleg.ust == 6982500
            assert beleg.zahlbetrag == beleg.brutto

    def test_ab_laeuft_im_eigenen_kreis(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = ab_aus_projekt(sitzung, bestand["projekt"])
            assert kreis_fuer(beleg) == "AB"

    def test_ab_sperrt_den_zahlungsplan_nicht(self, bestand):
        """Eine Bestätigung ist keine Rechnung (PLAN §10)."""
        with schreib_sitzung() as sitzung:
            beleg = ab_aus_projekt(sitzung, bestand["projekt"])
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            offen = sitzung.scalars(
                select(Zahlungsplanposition).where(
                    Zahlungsplanposition.projekt_id == bestand["projekt"]
                )
            ).all()
            assert all(position.rechnung_id is None for position in offen)

    def test_ohne_zahlungsplan_steht_der_auftragswert_darauf(self, gesäte_db, vollstaendige_firma):
        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            kunde = Kunde(
                kunden_nr=13001,
                name="Ohne Plan GmbH",
                strasse="Weg 1",
                plz="92637",
                ort="Theisseil",
                typ="b2b",
            )
            sitzung.add(kunde)
            sitzung.flush()
            projekt = Projekt(
                projekt_nr=26099, firma_id=firma_id, kunde_id=kunde.id, ab_wert_netto=1000000
            )
            sitzung.add(projekt)
            sitzung.flush()
            beleg = ab_aus_projekt(sitzung, projekt.id)
            assert len(beleg.positionen) == 1
            assert beleg.positionen[0].ep_netto == 1000000


class TestAbschlagsrechnung:
    def test_abschlag_uebernimmt_betrag_und_bezeichnung(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][0])
            assert beleg.art == "abschlag"
            assert beleg.abschlag_nr == 1
            assert beleg.betreff == "1. Abschlagsrechnung"
            assert beleg.positionen[0].bezeichnung == "1. Abschlag Auftragserteilung"
            assert beleg.netto == 11025000
            assert beleg.ust == 2094750

    def test_zaehler_steigt_mit_jedem_festgeschriebenen_abschlag(self, bestand):
        with schreib_sitzung() as sitzung:
            erster = abschlag_aus_position(sitzung, bestand["positionen"][0])
            sitzung.add(erster)
            erster.leistungszeitraum = "März 2026"
            sitzung.flush()
            erster_id = erster.id
        _festschreiben(erster_id)
        with schreib_sitzung() as sitzung:
            zweiter = abschlag_aus_position(sitzung, bestand["positionen"][1])
            assert zweiter.abschlag_nr == 2
            assert zweiter.betreff == "2. Abschlagsrechnung"

    def test_berechnete_position_wird_abgewiesen(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][0])
            beleg.leistungszeitraum = "März 2026"
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung, pytest.raises(BelegFehler) as fehler:
            abschlag_aus_position(sitzung, bestand["positionen"][0])
        assert "bereits berechnet" in fehler.value.meldung
        assert "stornieren" in fehler.value.naechster_schritt

    def test_altposition_wird_abgewiesen(self, bestand):
        with schreib_sitzung() as sitzung, pytest.raises(BelegFehler) as fehler:
            abschlag_aus_position(sitzung, bestand["alt_position"])
        assert "vor der Einführung" in fehler.value.meldung
        assert "Kennzeichen" in fehler.value.naechster_schritt

    def test_unbekannte_position_meldet_sich_verstaendlich(self, gesäte_db):
        with schreib_sitzung() as sitzung, pytest.raises(NichtGefunden):
            abschlag_aus_position(sitzung, 987654)

    def test_abschlag_auf_einem_altprojekt_bleibt_moeglich(self, bestand):
        """Entscheidung 16 sperrt nur die Schlussrechnung, nicht das Abrechnen überhaupt."""
        with schreib_sitzung() as sitzung:
            offen = Zahlungsplanposition(
                projekt_id=bestand["alt_projekt"],
                pos_nr=2,
                bezeichnung="2. Abschlag",
                gewerk="pv",
                art="abschlag",
                betrag_netto=1650000,
            )
            sitzung.add(offen)
            sitzung.flush()
            beleg = abschlag_aus_position(sitzung, offen.id)
            assert beleg.netto == 1650000
            assert beleg.ust == 0, "Das Altprojekt trägt 0 % nach § 12 Abs. 3 UStG"


class TestSchlussrechnung:
    def _drei_abschlaege(self, bestand) -> list[int]:
        nummern = []
        for index, position_id in enumerate(bestand["positionen"], start=1):
            with schreib_sitzung() as sitzung:
                beleg = abschlag_aus_position(sitzung, position_id, datum=date(2026, index + 4, 1))
                beleg.leistungszeitraum = f"Monat {index}"
                sitzung.add(beleg)
                sitzung.flush()
                beleg_id = beleg.id
            _festschreiben(beleg_id)
            nummern.append(beleg_id)
        return nummern

    def test_absetzungsblock_fuehrt_jeden_abschlag_einzeln(self, bestand):
        """PLAN §6.1 / § 14 Abs. 5 UStG: drei Abschläge, drei Absetzungszeilen."""
        self._drei_abschlaege(bestand)
        with schreib_sitzung() as sitzung:
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            assert len(beleg.absetzungen) == 3
            assert [e.netto for e in beleg.absetzungen] == [11025000, 11025000, 9187500]
            assert [e.ust for e in beleg.absetzungen] == [2094750, 2094750, 1745625]
            assert all(e.rechnung_nr.startswith("RE-2026-") for e in beleg.absetzungen)

    def test_restbetrag_stimmt_auf_den_cent(self, bestand):
        self._drei_abschlaege(bestand)
        with schreib_sitzung() as sitzung:
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            assert beleg.netto == 36750000, "Gesamtleistung aus dem Auftragswert"
            assert beleg.ust == 6982500
            assert beleg.brutto == 43732500
            assert beleg.absetzung_netto == 31237500
            assert beleg.absetzung_ust == 5935125
            assert beleg.zahlbetrag == 6559875

    def test_beauftragte_nachtraege_zaehlen_zur_gesamtleistung(self, bestand):
        with schreib_sitzung() as sitzung:
            sitzung.add_all(
                [
                    Nachtrag(
                        projekt_id=bestand["projekt"],
                        bezeichnung="Zusätzliche Unterkonstruktion",
                        betrag_netto=450000,
                        status="beauftragt",
                    ),
                    Nachtrag(
                        projekt_id=bestand["projekt"],
                        bezeichnung="Noch nicht beauftragt",
                        betrag_netto=999999,
                        status="angeboten",
                    ),
                ]
            )
            sitzung.flush()
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            assert len(beleg.positionen) == 2
            assert beleg.netto == 36750000 + 450000
            assert "Zusätzliche Unterkonstruktion" in beleg.positionen[1].bezeichnung

    def test_gemischte_steuersaetze_werden_je_satz_abgesetzt(self, bestand):
        """Ein Abschlag mit 19 %, einer mit 0 % – der Block trennt die Sätze."""
        with schreib_sitzung() as sitzung:
            erster = abschlag_aus_position(sitzung, bestand["positionen"][0])
            erster.leistungszeitraum = "Mai 2026"
            sitzung.add(erster)
            sitzung.flush()
            erster_id = erster.id
        _festschreiben(erster_id)
        with schreib_sitzung() as sitzung:
            zweiter = abschlag_aus_position(sitzung, bestand["positionen"][1])
            zweiter.leistungszeitraum = "Juni 2026"
            zweiter.ust_kz = "gemischt"
            zweiter.positionen[0].ust_satz = 0
            sitzung.add(zweiter)
            sitzung.flush()
            from app.dienste.belegarten import summen_setzen

            summen_setzen(zweiter)
            sitzung.flush()
            zweiter_id = zweiter.id
        _festschreiben(zweiter_id)
        with schreib_sitzung() as sitzung:
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            saetze = sorted((e.ust_satz, e.netto, e.ust) for e in beleg.absetzungen)
            assert saetze == [(0, 11025000, 0), (190, 11025000, 2094750)]
            assert beleg.absetzung_netto == 22050000
            assert beleg.absetzung_ust == 2094750

    def test_null_prozent_projekt_ergibt_null_prozent_schlussrechnung(self, bestand):
        """§ 12 Abs. 3 UStG: die begünstigte Anlage auf dem Wohngebäude."""
        with schreib_sitzung() as sitzung:
            position = sitzung.get(Zahlungsplanposition, bestand["alt_position"])
            position.migriert_gestellt = None
            sitzung.flush()
            beleg = schlussrechnung(sitzung, bestand["alt_projekt"])
            assert beleg.ust_kz == "0"
            assert beleg.netto == 5500000
            assert beleg.ust == 0
            assert beleg.brutto == beleg.netto

    def test_ohne_abschlaege_bleibt_der_block_leer(self, bestand):
        """Ein leerer Block ist richtig – es gibt nichts abzusetzen."""
        with schreib_sitzung() as sitzung:
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            assert beleg.absetzungen == []
            assert beleg.zahlbetrag == beleg.brutto

    def test_stornierter_abschlag_wird_nicht_abgesetzt(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][0])
            beleg.leistungszeitraum = "Mai 2026"
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            gegenbeleg = storno(sitzung, beleg_id)
            sitzung.add(gegenbeleg)
            sitzung.flush()
            gegen_id = gegenbeleg.id
        _festschreiben(gegen_id)
        with schreib_sitzung() as sitzung:
            schluss = schlussrechnung(sitzung, bestand["projekt"])
            assert schluss.absetzungen == [], "Ein stornierter Abschlag wurde nie berechnet"


class TestAltprojekteSindGesperrt:
    def test_schlussrechnung_wird_mit_begruendung_abgelehnt(self, bestand):
        """Entscheidung 16: ohne Nummer, Datum und Satz wäre der Absetzungsblock falsch."""
        with schreib_sitzung() as sitzung, pytest.raises(BelegFehler) as fehler:
            schlussrechnung(sitzung, bestand["alt_projekt"])
        assert fehler.value.code == "altabschlaege_ohne_beleg"
        assert "25088" in fehler.value.meldung
        assert "§ 14 Abs. 5 UStG" in fehler.value.naechster_schritt
        assert "Abschlagsrechnungen sind für dieses Projekt weiter möglich" in (
            fehler.value.naechster_schritt
        )

    def test_die_betroffenen_positionen_werden_genannt(self, bestand):
        with schreib_sitzung() as sitzung, pytest.raises(BelegFehler) as fehler:
            schlussrechnung(sitzung, bestand["alt_projekt"])
        assert "Pos. 1" in fehler.value.meldung
        assert "27.500,00" in fehler.value.meldung

    def test_nach_ruecknahme_des_kennzeichens_geht_es(self, bestand):
        with schreib_sitzung() as sitzung:
            position = sitzung.get(Zahlungsplanposition, bestand["alt_position"])
            position.migriert_gestellt = None
            sitzung.flush()
            beleg = schlussrechnung(sitzung, bestand["alt_projekt"])
            assert beleg.art == "schluss"


class TestServicerechnung:
    def test_service_laeuft_im_eigenen_kreis_und_ohne_projekt(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = servicerechnung(sitzung, bestand["kunde"], bestand["firma"])
            assert beleg.art == "service"
            assert beleg.projekt_id is None
            assert beleg.kunde_id == bestand["kunde"]
            assert kreis_fuer(beleg) == "SR"

    def test_service_mit_projektbezug(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = servicerechnung(
                sitzung, bestand["kunde"], bestand["firma"], projekt_id=bestand["projekt"]
            )
            assert beleg.projekt_id == bestand["projekt"]
            assert beleg.ust_kz == "19"


class TestStornoUndGutschrift:
    def _abschlag(self, bestand) -> int:
        with schreib_sitzung() as sitzung:
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][0])
            beleg.leistungszeitraum = "Mai 2026"
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        return beleg_id

    def test_storno_spiegelt_die_positionen_negativ(self, bestand):
        beleg_id = self._abschlag(bestand)
        with schreib_sitzung() as sitzung:
            gegenbeleg = storno(sitzung, beleg_id, grund="Falscher Empfänger")
            assert gegenbeleg.art == "storno"
            assert gegenbeleg.storno_ref == beleg_id
            assert gegenbeleg.netto == -11025000
            assert gegenbeleg.ust == -2094750
            assert "Falscher Empfänger" in gegenbeleg.anschreiben

    def test_storno_bleibt_im_kreis_des_originals(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = servicerechnung(sitzung, bestand["kunde"], bestand["firma"])
            beleg.leistungszeitraum = "August 2026"
            from app.modelle import Rechnungsposition

            beleg.positionen.append(
                Rechnungsposition(
                    pos=1, bezeichnung="Wartung", menge=1, ep_netto=50000, ust_satz=190
                )
            )
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            original = sitzung.get(Rechnung, beleg_id)
            assert original.rechnung_nr.startswith("SR-")
            gegenbeleg = storno(sitzung, beleg_id)
            assert kreis_fuer(gegenbeleg, original) == "SR"

    def test_entwurf_laesst_sich_nicht_stornieren(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][0])
            sitzung.add(beleg)
            sitzung.flush()
            with pytest.raises(BelegFehler) as fehler:
                storno(sitzung, beleg.id)
        assert "verworfen" in fehler.value.naechster_schritt

    def test_gutschrift_laesst_das_original_gueltig(self, bestand):
        beleg_id = self._abschlag(bestand)
        with schreib_sitzung() as sitzung:
            beleg = gutschrift(sitzung, beleg_id, grund="Nachlass 2 %")
            assert beleg.art == "gutschrift"
            assert beleg.positionen == [], "Welcher Teil zu korrigieren ist, weiß nur der Mensch"
            assert "Nachlass 2 %" in beleg.anschreiben
            original = sitzung.get(Rechnung, beleg_id)
            assert original.status == "festgeschrieben"


class TestAbschlagsvorschlaege:
    def test_erreichter_meilenstein_ergibt_einen_vorschlag(self, bestand):
        """PLAN §6.8: Vorschlag, kein Automatikversand."""
        with schreib_sitzung() as sitzung:
            sitzung.add(
                Meilenstein(
                    projekt_id=bestand["projekt"],
                    typ="lieferung",
                    erledigt=True,
                    erledigt_am=date(2026, 8, 20),
                )
            )
            sitzung.flush()
            vorschlaege = offene_vorschlaege(sitzung)
        assert len(vorschlaege) == 1
        assert vorschlaege[0]["bezeichnung"] == "2. Abschlag Lieferung"
        assert vorschlaege[0]["ausloeser"] == "lieferung"
        assert vorschlaege[0]["betrag_netto"] == 11025000

    def test_offener_meilenstein_ergibt_keinen_vorschlag(self, bestand):
        with schreib_sitzung() as sitzung:
            sitzung.add(Meilenstein(projekt_id=bestand["projekt"], typ="lieferung", erledigt=False))
            sitzung.flush()
            assert offene_vorschlaege(sitzung) == []

    def test_berechnete_position_verschwindet_aus_den_vorschlaegen(self, bestand):
        with schreib_sitzung() as sitzung:
            sitzung.add(Meilenstein(projekt_id=bestand["projekt"], typ="lieferung", erledigt=True))
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][1])
            beleg.leistungszeitraum = "August 2026"
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            assert offene_vorschlaege(sitzung) == []
