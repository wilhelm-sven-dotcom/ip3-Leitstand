"""Konfliktprüfung beim Speichern (PLAN §5).

Der Fall, um den es geht: Sven und Michael öffnen dasselbe Projekt, beide ändern etwas, beide
speichern. Ohne Prüfung gewinnt der Zweite und die Änderung des Ersten ist weg – ohne Meldung.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.datenbank import engine_erzeugen, schreib_transaktion
from app.dienste.konflikt import (
    geaenderte_felder,
    konflikt_meldung,
    konflikt_uebersetzen,
    stand_pruefen,
)
from app.fehler import Konflikt
from app.modelle import Kunde


@pytest.fixture
def db(db_pfad: Path):
    engine = engine_erzeugen(db_pfad)
    yield engine
    engine.dispose()


@pytest.fixture
def kunde_id(db) -> int:
    with Session(db) as sitzung, schreib_transaktion(sitzung):
        kunde = Kunde(kunden_nr=10001, name="Maschinenbau Köstler GmbH", typ="b2b", ort="Weiden")
        sitzung.add(kunde)
        sitzung.flush()
        return kunde.id


class TestStandPruefen:
    def test_aktueller_stand_geht_durch(self, db, kunde_id):
        with Session(db) as sitzung:
            kunde = sitzung.get(Kunde, kunde_id)
            stand_pruefen(kunde, kunde.updated_at, "Der Kunde")

    def test_veralteter_stand_ergibt_konflikt(self, db, kunde_id):
        with Session(db) as sitzung:
            kunde = sitzung.get(Kunde, kunde_id)
            veraltet = kunde.updated_at - timedelta(minutes=5)
            with pytest.raises(Konflikt) as fehler:
                stand_pruefen(kunde, veraltet, "Der Kunde")
        assert fehler.value.status_code == 409
        assert fehler.value.code == "stand_veraltet"
        assert "Der Kunde" in fehler.value.meldung

    def test_meldung_nennt_zeitpunkt_in_ortszeit(self, db, kunde_id):
        """Ein Zeitpunkt in UTC auf dem Bildschirm wäre für den Nutzer irritierend."""
        from datetime import UTC, datetime

        with Session(db) as sitzung, schreib_transaktion(sitzung):
            kunde = sitzung.get(Kunde, kunde_id)
            # 14:00 UTC ist 16:00 Ortszeit im Sommer.
            kunde.updated_at = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
        with Session(db) as sitzung:
            kunde = sitzung.get(Kunde, kunde_id)
            meldung = konflikt_meldung(kunde, "Das Projekt")
        assert "16:00" in meldung.meldung
        assert "01.07.2026" in meldung.meldung

    def test_ohne_gelesenen_stand_wird_nicht_geprueft(self, db, kunde_id):
        """Importe und interne Vorgänge arbeiten ohne Konfliktschutz."""
        with Session(db) as sitzung:
            kunde = sitzung.get(Kunde, kunde_id)
            stand_pruefen(kunde, None, "Der Kunde")

    def test_bruchteile_von_sekunden_zaehlen(self, db, kunde_id):
        """Auf ganze Sekunden gekürzt wäre der Schutz wirkungslos.

        Zwei Speicherungen innerhalb derselben Sekunde sind keine Seltenheit: wer in einer Maske
        zweimal kurz hintereinander speichert, erzeugt genau das. Würde die Prüfung dort nichts
        finden, überschriebe der zweite Stand den ersten stillschweigend – der Fehler, den sie
        verhindern soll.
        """
        with Session(db) as sitzung:
            kunde = sitzung.get(Kunde, kunde_id)
            gerundet = kunde.updated_at.replace(microsecond=0)
            if kunde.updated_at.microsecond == 0:  # pragma: no cover – kommt praktisch nie vor
                pytest.skip("Zeitstempel hat zufällig keine Mikrosekunden")
            with pytest.raises(Konflikt):
                stand_pruefen(kunde, gerundet, "Der Kunde")

    def test_mikrosekunden_ueberleben_die_schnittstelle(self):
        """Grundlage für den genauen Vergleich: der Zeitstempel verliert unterwegs nichts."""
        from datetime import datetime

        from pydantic import BaseModel

        class Modell(BaseModel):
            stand: datetime

        original = datetime(2026, 8, 27, 14, 40, 52, 620868, tzinfo=UTC)
        zurueck = Modell.model_validate_json(Modell(stand=original).model_dump_json())
        assert zurueck.stand == original


class TestKonfliktBeimSpeichern:
    def test_zwei_gleichzeitige_bearbeitungen(self, db, kunde_id):
        sitzung_a = Session(db)
        sitzung_b = Session(db)
        kunde_a = sitzung_a.get(Kunde, kunde_id)
        kunde_b = sitzung_b.get(Kunde, kunde_id)

        kunde_a.ort = "Weiden i.d.OPf."
        with schreib_transaktion(sitzung_a):
            pass
        sitzung_a.close()

        kunde_b.ort = "Theisseil"
        with pytest.raises(StaleDataError), schreib_transaktion(sitzung_b):
            pass
        sitzung_b.close()

        # Die erste Änderung ist erhalten, die zweite wurde abgewiesen.
        with Session(db) as pruefung:
            assert pruefung.get(Kunde, kunde_id).ort == "Weiden i.d.OPf."

    def test_uebersetzung_in_eine_verstaendliche_meldung(self, db, kunde_id):
        sitzung_a = Session(db)
        sitzung_b = Session(db)
        kunde_a = sitzung_a.get(Kunde, kunde_id)
        kunde_b = sitzung_b.get(Kunde, kunde_id)

        kunde_a.bemerkung = "Erste Änderung"
        with schreib_transaktion(sitzung_a):
            pass
        sitzung_a.close()

        kunde_b.bemerkung = "Zweite Änderung"
        with pytest.raises(Konflikt) as fehler:
            try:
                with schreib_transaktion(sitzung_b):
                    pass
            except Exception as roh:
                konflikt_uebersetzen(roh, "Der Kunde")
                raise
        sitzung_b.close()
        assert fehler.value.code == "stand_veraltet"
        assert "neu laden" in fehler.value.naechster_schritt

    def test_anderer_fehler_wird_nicht_uebersetzt(self):
        konflikt_uebersetzen(ValueError("etwas anderes"), "Der Kunde")


class TestGeaenderteFelder:
    def test_nur_unterschiede(self):
        alt = {"name": "Köstler GmbH", "ort": "Weiden", "typ": "b2b"}
        neu = {"name": "Maschinenbau Köstler GmbH", "ort": "Weiden", "typ": "b2b"}
        assert geaenderte_felder(alt, neu) == {
            "name": {"alt": "Köstler GmbH", "neu": "Maschinenbau Köstler GmbH"}
        }

    def test_neues_feld(self):
        assert geaenderte_felder({}, {"ort": "Weiden"}) == {"ort": {"alt": None, "neu": "Weiden"}}

    def test_entferntes_feld(self):
        assert geaenderte_felder({"ort": "Weiden"}, {}) == {"ort": {"alt": "Weiden", "neu": None}}

    def test_ohne_aenderung_leer(self):
        assert geaenderte_felder({"a": 1}, {"a": 1}) == {}

    def test_decimal_und_float_sind_dieselbe_zahl(self):
        """Sonst steht nach jedem Speichern „514.08 → 514.08" im Protokoll.

        Die Datenbank liefert für ``pv_kwp`` ein ``Decimal``, die Maske schickt eine
        Gleitkommazahl zurück. In Python sind die beiden nie gleich.
        """
        from decimal import Decimal

        assert geaenderte_felder({"pv_kwp": Decimal("514.080")}, {"pv_kwp": 514.08}) == {}
        assert geaenderte_felder({"kwh": Decimal("13.5")}, {"kwh": 13.5}) == {}
        assert geaenderte_felder({"pv_kwp": Decimal("29.580")}, {"pv_kwp": 4}) == {
            "pv_kwp": {"alt": Decimal("29.580"), "neu": 4}
        }

    def test_echte_zahlaenderung_bleibt_eine_aenderung(self):
        from decimal import Decimal

        assert geaenderte_felder({"pv_kwp": Decimal("514.080")}, {"pv_kwp": 600.5}) == {
            "pv_kwp": {"alt": Decimal("514.080"), "neu": 600.5}
        }

    def test_none_gegen_zahl_ist_eine_aenderung(self):
        assert geaenderte_felder({"pv_kwp": None}, {"pv_kwp": 0.0}) == {
            "pv_kwp": {"alt": None, "neu": 0.0}
        }

    def test_wahrheitswerte_stuerzen_nicht_ab(self):
        """``bool`` ist in Python eine Ganzzahl, ``Decimal("False")`` aber ein Fehler.

        Aufgefallen am Wartungsvertrag im Anlagenregister: die erste Maske mit einem
        Ja/Nein-Feld brachte das Speichern zum Absturz, weil der Zahlenvergleich für den
        Umweg über ``Decimal`` griff.
        """
        assert geaenderte_felder({"wartungsvertrag": False}, {"wartungsvertrag": True}) == {
            "wartungsvertrag": {"alt": False, "neu": True}
        }
        assert geaenderte_felder({"wartungsvertrag": True}, {"wartungsvertrag": True}) == {}
        assert geaenderte_felder({"aktiv": True}, {"aktiv": None}) == {
            "aktiv": {"alt": True, "neu": None}
        }
