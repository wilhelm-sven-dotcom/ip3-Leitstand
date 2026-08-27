"""Festschreibung: Nummer, Hash, Sperre, Ablage (PLAN §6.4, §7 Phase 3).

Hier stehen die Akzeptanzkriterien der Phase, die sich nicht am Bildschirm nachstellen lassen:
lückenlose Nummern bei gleichzeitigem Zugriff, ein Beleg, der auch per SQL unveränderbar bleibt,
und ein Storno, der die Zahlungsplanposition wieder freigibt.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.datenbank import lese_sitzung, schreib_sitzung, schreib_transaktion
from app.dienste.belegarten import (
    abschlag_aus_position,
    gutschrift,
    schlussrechnung,
    servicerechnung,
    storno,
)
from app.dienste.festschreibung import (
    AblageFehler,
    Ablagepfade,
    Belegdateien,
    UnvollstaendigerBeleg,
    ablage_wiederholen,
    dateien_ablegen,
    festschreiben,
)
from app.dienste.nummernkreise import stand
from app.modelle import Firma, Kunde, Nummernkreis, Projekt, Rechnung, Zahlungsplanposition


class AblageAttrappe:
    """Belegablage für den Test: rendert einen Platzhalter und schreibt ihn in ein Verzeichnis."""

    def __init__(self, ziel: Path, scheitern: bool = False) -> None:
        self.ziel = ziel
        self.scheitern = scheitern
        self.gerendert: list[str] = []

    def rendern(self, beleg: Rechnung) -> Belegdateien:
        self.gerendert.append(beleg.rechnung_nr or "ohne Nummer")
        return Belegdateien(
            pdf_name=f"{beleg.rechnung_nr}.pdf",
            pdf_bytes=f"PDF {beleg.rechnung_nr} {beleg.zahlbetrag}".encode(),
        )

    def pfade(self, dateien: Belegdateien) -> Ablagepfade:
        return Ablagepfade(pdf_pfad=str(self.ziel / dateien.pdf_name))

    def schreiben(self, dateien: Belegdateien) -> Ablagepfade:
        if self.scheitern:
            raise OSError(13, "Zugriff verweigert")
        self.ziel.mkdir(parents=True, exist_ok=True)
        pfad = self.ziel / dateien.pdf_name
        pfad.write_bytes(dateien.pdf_bytes)
        return Ablagepfade(pdf_pfad=str(pfad))


@pytest.fixture
def bestand(gesäte_db, vollstaendige_firma) -> dict:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(
            kunden_nr=14001,
            name="Maschinenbau Köstler GmbH",
            strasse="Bahnhofstraße 12",
            plz="92660",
            ort="Neustadt a. d. Waldnaab",
            ust_id="DE123456789",
            typ="b2b",
        )
        sitzung.add(kunde)
        sitzung.flush()
        projekt = Projekt(
            projekt_nr=26014,
            firma_id=firma_id,
            kunde_id=kunde.id,
            ab_wert_netto=36750000,
            ust_kz="19",
            status="in_bau",
        )
        sitzung.add(projekt)
        sitzung.flush()
        positionen = [
            Zahlungsplanposition(
                projekt_id=projekt.id,
                pos_nr=nummer,
                bezeichnung=f"{nummer}. Abschlag",
                gewerk="pv",
                art="abschlag",
                betrag_netto=9187500,
                plan_monat="2026-09",
            )
            for nummer in range(1, 5)
        ]
        sitzung.add_all(positionen)
        sitzung.flush()
        return {
            "firma": firma_id,
            "kunde": kunde.id,
            "projekt": projekt.id,
            "positionen": [p.id for p in positionen],
        }


def _entwurf(bestand, index: int = 0, datum: date | None = None) -> int:
    with schreib_sitzung() as sitzung:
        beleg = abschlag_aus_position(sitzung, bestand["positionen"][index], datum=datum)
        beleg.leistungszeitraum = "Juli 2026"
        sitzung.add(beleg)
        sitzung.flush()
        return beleg.id


def _festschreiben(beleg_id: int, ablage=None) -> dict:
    with schreib_sitzung() as sitzung, schreib_transaktion(sitzung):
        beleg = sitzung.get(Rechnung, beleg_id)
        ergebnis = festschreiben(sitzung, beleg, ablage=ablage)
        return {
            "nummer": beleg.rechnung_nr,
            "hash": beleg.hash,
            "status": beleg.status,
            "pdf_pfad": beleg.pdf_pfad,
            "berechnet": list(ergebnis.berechnete_positionen),
            "freigegeben": list(ergebnis.freigegebene_positionen),
            "ergebnis": ergebnis,
        }


class TestNummernvergabe:
    def test_erste_nummer_des_jahres(self, bestand):
        ergebnis = _festschreiben(_entwurf(bestand, 0, date(2026, 7, 15)))
        assert ergebnis["nummer"] == "RE-2026-0001"

    def test_jahr_kommt_aus_dem_belegdatum(self, bestand):
        """Ein Beleg vom 31.12. gehört in den Kreis des alten Jahres, auch wenn er später entsteht."""
        ergebnis = _festschreiben(_entwurf(bestand, 0, date(2025, 12, 31)))
        assert ergebnis["nummer"] == "RE-2025-0001"

    def test_verworfener_entwurf_hinterlaesst_keine_luecke(self, bestand):
        """Die Nummer wird erst beim Festschreiben gezogen (PLAN §6.4)."""
        entwurf = _entwurf(bestand, 0)
        with schreib_sitzung() as sitzung:
            beleg = sitzung.get(Rechnung, entwurf)
            assert beleg.rechnung_nr is None
            sitzung.delete(beleg)
        ergebnis = _festschreiben(_entwurf(bestand, 1))
        assert ergebnis["nummer"] == "RE-2026-0001"

    def test_gescheiterte_festschreibung_rollt_die_nummer_zurueck(self, bestand, tmp_path):
        """Sonst müsste eine fehlende Nummer gegenüber dem Prüfer erklärt werden."""

        class Kaputt(AblageAttrappe):
            def rendern(self, beleg):
                raise RuntimeError("Vorlage nicht lesbar")

        entwurf = _entwurf(bestand, 0)
        with pytest.raises(RuntimeError):
            _festschreiben(entwurf, Kaputt(tmp_path / "rechnungen"))
        with lese_sitzung() as sitzung:
            assert stand(sitzung, bestand["firma"], "RE", 2026) == 0
            assert sitzung.get(Rechnung, entwurf).status == "entwurf"
        assert _festschreiben(_entwurf(bestand, 1))["nummer"] == "RE-2026-0001"

    def test_service_und_projektbelege_haben_eigene_kreise(self, bestand):
        from app.modelle import Rechnungsposition

        _festschreiben(_entwurf(bestand, 0))
        with schreib_sitzung() as sitzung:
            beleg = servicerechnung(sitzung, bestand["kunde"], bestand["firma"])
            beleg.leistungszeitraum = "August 2026"
            beleg.positionen.append(
                Rechnungsposition(
                    pos=1, bezeichnung="Wartung", menge=1, ep_netto=50000, ust_satz=190
                )
            )
            sitzung.add(beleg)
            sitzung.flush()
            service_id = beleg.id
        assert _festschreiben(service_id)["nummer"] == "SR-2026-0001"

    def test_zehn_gleichzeitige_festschreibungen_ergeben_zehn_nummern(self, bestand):
        """Die Vergabe läuft mit BEGIN IMMEDIATE; der zweite Schreiber wartet, statt zu überholen."""
        with schreib_sitzung() as sitzung:
            projekt = sitzung.get(Projekt, bestand["projekt"])
            weitere = [
                Zahlungsplanposition(
                    projekt_id=projekt.id,
                    pos_nr=nummer,
                    bezeichnung=f"{nummer}. Abschlag",
                    gewerk="pv",
                    art="abschlag",
                    betrag_netto=100000,
                )
                for nummer in range(5, 11)
            ]
            sitzung.add_all(weitere)
            sitzung.flush()
            alle = [p.id for p in weitere]
        entwuerfe = []
        for position_id in bestand["positionen"] + alle:
            with schreib_sitzung() as sitzung:
                beleg = abschlag_aus_position(sitzung, position_id)
                beleg.leistungszeitraum = "Juli 2026"
                sitzung.add(beleg)
                sitzung.flush()
                entwuerfe.append(beleg.id)

        nummern: list[str] = []
        sperre = threading.Lock()

        def schreiben(beleg_id: int) -> None:
            ergebnis = _festschreiben(beleg_id)
            with sperre:
                nummern.append(ergebnis["nummer"])

        faeden = [threading.Thread(target=schreiben, args=(b,)) for b in entwuerfe]
        for faden in faeden:
            faden.start()
        for faden in faeden:
            faden.join()

        assert sorted(nummern) == [f"RE-2026-{i:04d}" for i in range(1, 11)]
        with lese_sitzung() as sitzung:
            assert stand(sitzung, bestand["firma"], "RE", 2026) == 10


class TestFestgeschriebenIstEndgueltig:
    def test_status_hash_und_zeitstempel_werden_gesetzt(self, bestand):
        ergebnis = _festschreiben(_entwurf(bestand, 0))
        assert ergebnis["status"] == "festgeschrieben"
        assert len(ergebnis["hash"]) == 64
        with lese_sitzung() as sitzung:
            beleg = sitzung.get(Rechnung, sitzung.scalar(select(Rechnung.id)))
            assert beleg.festgeschrieben_am is not None

    def test_zweimal_festschreiben_geht_nicht(self, bestand):
        from app.dienste.belegarten import BelegFehler

        beleg_id = _entwurf(bestand, 0)
        _festschreiben(beleg_id)
        with pytest.raises(BelegFehler) as fehler:
            _festschreiben(beleg_id)
        assert "bereits festgeschrieben" in fehler.value.meldung

    def test_beleg_ist_auch_per_sql_unveraenderbar(self, bestand):
        beleg_id = _entwurf(bestand, 0)
        _festschreiben(beleg_id)
        with (
            schreib_sitzung() as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungen SET netto = 1 WHERE id = :id"), {"id": beleg_id}
            )

    def test_zahlungsplanposition_ist_danach_gesperrt(self, bestand):
        ergebnis = _festschreiben(_entwurf(bestand, 0))
        assert ergebnis["berechnet"] == [bestand["positionen"][0]]
        with lese_sitzung() as sitzung:
            position = sitzung.get(Zahlungsplanposition, bestand["positionen"][0])
            assert position.rechnung_id is not None

    def test_unvollstaendiger_beleg_wird_mit_allem_fehlenden_abgewiesen(self, bestand):
        with schreib_sitzung() as sitzung:
            beleg = abschlag_aus_position(sitzung, bestand["positionen"][0])
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        with pytest.raises(UnvollstaendigerBeleg) as fehler:
            _festschreiben(beleg_id)
        assert "Leistungszeitraum" in fehler.value.meldung
        assert "Stornobeleg" in fehler.value.naechster_schritt
        with lese_sitzung() as sitzung:
            assert sitzung.get(Rechnung, beleg_id).rechnung_nr is None


class TestSchlussrechnungSchliesstDasProjekt:
    def test_offene_positionen_werden_mit_der_schlussrechnung_berechnet(self, bestand):
        """Sonst stünde nach der Schlussrechnung noch etwas im Forecast, das niemand mehr stellt."""
        _festschreiben(_entwurf(bestand, 0))
        with schreib_sitzung() as sitzung:
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            beleg.leistungszeitraum = "März bis Dezember 2026"
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        ergebnis = _festschreiben(beleg_id)
        assert sorted(ergebnis["berechnet"]) == sorted(bestand["positionen"][1:])
        with lese_sitzung() as sitzung:
            offen = sitzung.scalars(
                select(Zahlungsplanposition).where(
                    Zahlungsplanposition.projekt_id == bestand["projekt"],
                    Zahlungsplanposition.rechnung_id.is_(None),
                )
            ).all()
            assert offen == []

    def test_absetzungsblock_bleibt_nach_dem_festschreiben_stehen(self, bestand):
        _festschreiben(_entwurf(bestand, 0))
        with schreib_sitzung() as sitzung:
            beleg = schlussrechnung(sitzung, bestand["projekt"])
            beleg.leistungszeitraum = "2026"
            sitzung.add(beleg)
            sitzung.flush()
            beleg_id = beleg.id
        _festschreiben(beleg_id)
        with lese_sitzung() as sitzung:
            beleg = sitzung.get(Rechnung, beleg_id)
            assert len(beleg.absetzungen) == 1
            assert beleg.absetzungen[0].netto == 9187500
            assert beleg.zahlbetrag == beleg.brutto - beleg.absetzungen[0].brutto


class TestStornoGibtFrei:
    def test_storno_setzt_das_original_auf_storniert_und_gibt_die_position_frei(self, bestand):
        beleg_id = _entwurf(bestand, 0)
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            gegenbeleg = storno(sitzung, beleg_id)
            sitzung.add(gegenbeleg)
            sitzung.flush()
            gegen_id = gegenbeleg.id
        ergebnis = _festschreiben(gegen_id)

        assert ergebnis["nummer"] == "RE-2026-0002", "Der Storno bekommt eine eigene Nummer"
        assert ergebnis["freigegeben"] == [bestand["positionen"][0]]
        with lese_sitzung() as sitzung:
            original = sitzung.get(Rechnung, beleg_id)
            assert original.status == "storniert"
            assert original.storno_ref == gegen_id
            assert original.rechnung_nr == "RE-2026-0001", "Nummer und Beträge bleiben stehen"
            assert original.netto == 9187500
            position = sitzung.get(Zahlungsplanposition, bestand["positionen"][0])
            assert position.rechnung_id is None

    def test_freigegebene_position_laesst_sich_neu_berechnen(self, bestand):
        beleg_id = _entwurf(bestand, 0)
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            gegenbeleg = storno(sitzung, beleg_id)
            sitzung.add(gegenbeleg)
            sitzung.flush()
            gegen_id = gegenbeleg.id
        _festschreiben(gegen_id)
        ergebnis = _festschreiben(_entwurf(bestand, 0))
        assert ergebnis["nummer"] == "RE-2026-0003"

    def test_gutschrift_laesst_das_original_stehen(self, bestand):
        from app.modelle import Rechnungsposition

        beleg_id = _entwurf(bestand, 0)
        _festschreiben(beleg_id)
        with schreib_sitzung() as sitzung:
            beleg = gutschrift(sitzung, beleg_id, grund="Nachlass")
            beleg.leistungszeitraum = "Juli 2026"
            beleg.positionen.append(
                Rechnungsposition(
                    pos=1, bezeichnung="Nachlass", menge=1, ep_netto=-100000, ust_satz=190
                )
            )
            sitzung.add(beleg)
            sitzung.flush()
            gut_id = beleg.id
        _festschreiben(gut_id)
        with lese_sitzung() as sitzung:
            assert sitzung.get(Rechnung, beleg_id).status == "festgeschrieben"
            position = sitzung.get(Zahlungsplanposition, bestand["positionen"][0])
            assert position.rechnung_id == beleg_id, "Die Gutschrift gibt nichts frei"


class TestAblage:
    def test_pdf_landet_im_rechnungsordner(self, bestand, tmp_path):
        ablage = AblageAttrappe(tmp_path / "01_Rechnungen")
        ergebnis = _festschreiben(_entwurf(bestand, 0), ablage)
        dateien_ablegen(ablage, ergebnis["ergebnis"])
        assert (tmp_path / "01_Rechnungen" / "RE-2026-0001.pdf").exists()
        assert ergebnis["pdf_pfad"].endswith("RE-2026-0001.pdf")

    def test_gescheiterte_ablage_laesst_den_beleg_gueltig(self, bestand, tmp_path):
        """Der Hash deckt die Belegdaten ab, nicht die PDF-Bytes – nachholen ist zulässig."""
        ablage = AblageAttrappe(tmp_path / "01_Rechnungen", scheitern=True)
        ergebnis = _festschreiben(_entwurf(bestand, 0), ablage)
        gemeldet = dateien_ablegen(ablage, ergebnis["ergebnis"])
        assert ergebnis["status"] == "festgeschrieben"
        assert "festgeschrieben" in gemeldet.ablage_offen
        assert "Rechnungsordner" in gemeldet.ablage_offen
        assert not (tmp_path / "01_Rechnungen").exists()

    def test_ablage_laesst_sich_wiederholen(self, bestand, tmp_path):
        ablage = AblageAttrappe(tmp_path / "01_Rechnungen", scheitern=True)
        ergebnis = _festschreiben(_entwurf(bestand, 0), ablage)
        dateien_ablegen(ablage, ergebnis["ergebnis"])

        ablage.scheitern = False
        with schreib_sitzung() as sitzung:
            beleg = sitzung.scalar(select(Rechnung).where(Rechnung.rechnung_nr == "RE-2026-0001"))
            vorher = beleg.hash
            pfade = ablage_wiederholen(sitzung, beleg, ablage)
            assert beleg.hash == vorher, "Der Beleg selbst bleibt unangetastet"
        assert Path(pfade.pdf_pfad).exists()

    def test_wiederholte_ablage_meldet_einen_ordnerfehler_verstaendlich(self, bestand, tmp_path):
        ablage = AblageAttrappe(tmp_path / "01_Rechnungen")
        ergebnis = _festschreiben(_entwurf(bestand, 0), ablage)
        dateien_ablegen(ablage, ergebnis["ergebnis"])
        ablage.scheitern = True
        with schreib_sitzung() as sitzung, pytest.raises(AblageFehler) as fehler:
            beleg = sitzung.scalar(select(Rechnung).where(Rechnung.rechnung_nr == "RE-2026-0001"))
            ablage_wiederholen(sitzung, beleg, ablage)
        assert "Rechnungsordner" in fehler.value.naechster_schritt
        assert "bleibt gültig" in fehler.value.naechster_schritt

    def test_ohne_ablage_bleiben_die_pfade_leer(self, bestand):
        ergebnis = _festschreiben(_entwurf(bestand, 0))
        assert ergebnis["pdf_pfad"] is None


class TestNummernkreiseSindGetrennt:
    def test_je_firma_und_jahr_ein_zaehler(self, bestand):
        _festschreiben(_entwurf(bestand, 0, date(2025, 12, 31)))
        _festschreiben(_entwurf(bestand, 1, date(2026, 1, 2)))
        with lese_sitzung() as sitzung:
            kreise = {
                (k.kreis, k.jahr): k.letzter_wert for k in sitzung.scalars(select(Nummernkreis))
            }
        assert kreise[("RE", 2025)] == 1
        assert kreise[("RE", 2026)] == 1
