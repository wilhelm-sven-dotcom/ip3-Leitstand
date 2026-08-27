"""Nummernvergabe (PLAN §3, §6.4).

Der wichtigste Test hier lässt mehrere Threads gleichzeitig Nummern ziehen. Rechnungsnummern
müssen lückenlos und einmalig sein; eine doppelt vergebene Nummer wäre ein Mangel, der bei einer
Prüfung auffällt, und ein nachträglicher Ausgleich ist nicht möglich.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datenbank import engine_erzeugen, schreib_transaktion
from app.dienste import nummernkreise
from app.dienste.nummernkreise import NummernkreisFehler
from app.modelle import Firma, Nummernkreis


@pytest.fixture
def db(db_pfad: Path):
    engine = engine_erzeugen(db_pfad)
    yield engine
    engine.dispose()


@pytest.fixture
def firma_id(db) -> int:
    with Session(db) as sitzung, schreib_transaktion(sitzung):
        firma = Firma(kuerzel="ip3", firmierung="ip³ Energietechnik GmbH")
        sitzung.add(firma)
        sitzung.flush()
        return firma.id


class TestVergabe:
    def test_erste_nummer_beginnt_bei_eins(self, db, firma_id):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            assert nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026) == "RE-2026-0001"

    def test_nummern_laufen_fort(self, db, firma_id):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummern = [
                nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026) for _ in range(5)
            ]
        assert nummern == [
            "RE-2026-0001",
            "RE-2026-0002",
            "RE-2026-0003",
            "RE-2026-0004",
            "RE-2026-0005",
        ]

    def test_kreise_zaehlen_getrennt(self, db, firma_id):
        """Projekt- und Servicerechnungen laufen in getrennten Kreisen (PLAN §3)."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            assert nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026) == "RE-2026-0001"
            assert nummernkreise.naechste_nummer(sitzung, firma_id, "SR", 2026) == "SR-2026-0001"
            assert nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026) == "RE-2026-0002"

    def test_jahre_zaehlen_getrennt(self, db, firma_id):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026)
            nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026)
            assert nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2027) == "RE-2027-0001"

    def test_firmen_zaehlen_getrennt(self, db, firma_id):
        """Vorbereitung für eine zweite Firma (PLAN §12): eigene Kreise je Firma."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            zweite = Firma(kuerzel="mt2s", firmierung="MT2S GmbH")
            sitzung.add(zweite)
            sitzung.flush()
            assert nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026) == "RE-2026-0001"
            assert nummernkreise.naechste_nummer(sitzung, zweite.id, "RE", 2026) == "RE-2026-0001"

    def test_kundennummern_beginnen_bei_10001(self, db, firma_id):
        """PLAN §3: fortlaufend ab 10001, ohne Jahresbezug."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            assert nummernkreise.naechster_wert(sitzung, firma_id, "KD") == 10001
            assert nummernkreise.naechster_wert(sitzung, firma_id, "KD") == 10002

    def test_stand_schreibt_nicht_fort(self, db, firma_id):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026)
            assert nummernkreise.stand(sitzung, firma_id, "RE", 2026) == 1
            assert nummernkreise.stand(sitzung, firma_id, "RE", 2026) == 1


class TestProjektnummern:
    def test_schema_jjnnn(self, db, firma_id):
        """PLAN §3: Jahr zweistellig plus laufende Nummer, z. B. 26014."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            assert nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026) == 26001
            assert nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026) == 26002

    def test_serviceauftraege_mit_fuehrender_neun(self, db, firma_id):
        """PLAN §3: eigener Kreis 9JJNN, damit im KOST-Feld unterscheidbar."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummer = nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026, service=True)
            assert nummer == 902601
            assert str(nummer).startswith("9")

    def test_projekt_und_serviceauftrag_zaehlen_getrennt(self, db, firma_id):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            assert nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026) == 26001
            assert (
                nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026, service=True)
                == 902601
            )
            assert nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026) == 26002

    def test_nummern_bleiben_achtstellig(self, db, firma_id):
        """DATEV-KOST-tauglich heißt: rein numerisch, höchstens 8 Stellen (PLAN §3)."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            projekt = nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026)
            service = nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026, service=True)
        assert len(str(projekt)) <= 8
        assert len(str(service)) <= 8

    def test_erschoepfter_kreis_meldet_sich_verstaendlich(self, db, firma_id):
        """999 Projekte im Jahr sind weit jenseits der Wirklichkeit – aber kein stiller Fehler."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummernkreise.zaehler_mindestens(sitzung, firma_id, "PR", 999, 2026)
        with (
            Session(db) as sitzung,
            pytest.raises(NummernkreisFehler) as fehler,
            schreib_transaktion(sitzung),
        ):
            nummernkreise.naechste_projektnummer(sitzung, firma_id, 2026)
        assert "vergeben" in fehler.value.meldung
        assert fehler.value.naechster_schritt


class TestMigrationsunterstuetzung:
    def test_zaehler_kann_hochgesetzt_werden(self, db, firma_id):
        """Nach der Migration muss der Zähler über den vergebenen Bestandsnummern liegen."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummernkreise.zaehler_mindestens(sitzung, firma_id, "PR", 87, 2025)
            assert nummernkreise.naechste_projektnummer(sitzung, firma_id, 2025) == 25088

    def test_zaehler_wird_nie_verringert(self, db, firma_id):
        """Ein versehentliches Zurücksetzen würde bereits benutzte Nummern erneut vergeben."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            nummernkreise.zaehler_mindestens(sitzung, firma_id, "RE", 100, 2026)
            nummernkreise.zaehler_mindestens(sitzung, firma_id, "RE", 5, 2026)
            assert nummernkreise.stand(sitzung, firma_id, "RE", 2026) == 100


class TestParallelzugriff:
    def test_gleichzeitige_vergabe_bleibt_luekenlos_und_einmalig(self, db, firma_id):
        """PLAN §7, Phase 3: Nummernvergabe lückenlos unter Parallelzugriff.

        Zehn Threads ziehen gleichzeitig je fünf Nummern. Ohne BEGIN IMMEDIATE würden zwei
        Schreiber denselben Zählerstand lesen und dieselbe Nummer vergeben.
        """
        anzahl_threads = 10
        je_thread = 5

        def ziehen() -> list[str]:
            eigene_engine = engine_erzeugen(db.url.database and Path(db.url.database))
            try:
                gezogen: list[str] = []
                with Session(eigene_engine) as sitzung:
                    for _ in range(je_thread):
                        with schreib_transaktion(sitzung):
                            gezogen.append(
                                nummernkreise.naechste_nummer(sitzung, firma_id, "RE", 2026)
                            )
                return gezogen
            finally:
                eigene_engine.dispose()

        with ThreadPoolExecutor(max_workers=anzahl_threads) as pool:
            ergebnisse = list(pool.map(lambda _: ziehen(), range(anzahl_threads)))

        alle = [nummer for teil in ergebnisse for nummer in teil]
        erwartet = anzahl_threads * je_thread

        assert len(alle) == erwartet
        assert len(set(alle)) == erwartet, "Eine Nummer wurde doppelt vergeben"

        # Lückenlos: die gezogenen Nummern sind genau 1 bis erwartet.
        laufende = sorted(int(nummer.split("-")[-1]) for nummer in alle)
        assert laufende == list(range(1, erwartet + 1)), "Es fehlt eine Nummer im Kreis"

    def test_zaehler_entspricht_der_anzahl_der_vergaben(self, db, firma_id):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            for _ in range(7):
                nummernkreise.naechste_nummer(sitzung, firma_id, "AB", 2026)
        with Session(db) as sitzung:
            eintrag = sitzung.scalar(
                select(Nummernkreis).where(
                    Nummernkreis.firma_id == firma_id,
                    Nummernkreis.kreis == "AB",
                    Nummernkreis.jahr == 2026,
                )
            )
            assert eintrag is not None
            assert eintrag.letzter_wert == 7
