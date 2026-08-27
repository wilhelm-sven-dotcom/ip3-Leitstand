"""Festschreib- und Zahlungsplansperren (PLAN §5, §6.4).

Diese Tests prüfen die Sperren dort, wo sie sitzen: in der Datenbank. Sie umgehen die Anwendung
bewusst und schreiben mit reinem SQL – genau so würde ein Importskript, eine künftige Phase mit
einem Fehler oder jemand mit einem SQLite-Werkzeug zugreifen. Was hier durchkommt, kommt auch
in der Betriebsprüfung durch.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.datenbank import engine_erzeugen, schreib_transaktion
from app.datenbank_sperren import SPERRMELDUNGEN, als_fachfehler, sperren_uebersetzen
from app.fehler import Konflikt
from app.modelle import Firma, Kunde, Projekt, Rechnung, Rechnungsposition, Zahlungsplanposition
from app.zeit import jetzt_utc


@pytest.fixture
def db(db_pfad: Path):
    engine = engine_erzeugen(db_pfad)
    yield engine
    engine.dispose()


@pytest.fixture
def beleg(db) -> dict[str, int]:
    """Ein Projekt mit Zahlungsplanposition und einem Rechnungsentwurf."""
    with Session(db) as sitzung, schreib_transaktion(sitzung):
        firma = Firma(kuerzel="ip3", firmierung="ip³ Energietechnik GmbH")
        kunde = Kunde(kunden_nr=10001, name="Maschinenbau Köstler GmbH", typ="b2b")
        sitzung.add_all([firma, kunde])
        sitzung.flush()

        projekt = Projekt(
            projekt_nr=26014,
            firma_id=firma.id,
            kunde_id=kunde.id,
            typ="projekt",
            ust_kz="19",
            ab_wert_netto=36750000,
        )
        sitzung.add(projekt)
        sitzung.flush()

        position = Zahlungsplanposition(
            projekt_id=projekt.id,
            pos_nr=1,
            bezeichnung="1. Abschlag PV",
            gewerk="pv",
            art="abschlag",
            betrag_netto=9187500,
            plan_monat="2026-09",
        )
        rechnung = Rechnung(
            firma_id=firma.id,
            art="abschlag",
            projekt_id=projekt.id,
            datum=date(2026, 9, 1),
            netto=9187500,
            ust=1745625,
            brutto=10933125,
            status="entwurf",
        )
        sitzung.add_all([position, rechnung])
        sitzung.flush()

        sitzung.add(
            Rechnungsposition(
                rechnung_id=rechnung.id,
                pos=1,
                bezeichnung="1. Abschlag Photovoltaikanlage",
                menge=1,
                ep_netto=9187500,
                ust_satz=190,
                zahlungsplan_id=position.id,
            )
        )
        sitzung.flush()
        return {
            "firma": firma.id,
            "kunde": kunde.id,
            "projekt": projekt.id,
            "position": position.id,
            "rechnung": rechnung.id,
        }


def _migration_laden():
    """Migration 0002 als Modul laden.

    Über den Dateipfad statt per Import: ``alembic/versions`` ist kein Paket, und nur wegen eines
    Tests dort eine ``__init__.py`` anzulegen würde Alembic beim Suchen der Migrationen irritieren.
    """
    import importlib.util

    pfad = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0002_festschreibsperren.py"
    )
    spezifikation = importlib.util.spec_from_file_location("migration_0002", pfad)
    assert spezifikation is not None and spezifikation.loader is not None
    modul = importlib.util.module_from_spec(spezifikation)
    spezifikation.loader.exec_module(modul)
    return modul


def _festschreiben(db, rechnung_id: int, nummer: str = "RE-2026-0087") -> None:
    """Beleg festschreiben, wie es Phase 3 tun wird: Nummer, Zeitstempel, Hash, Status."""
    with Session(db) as sitzung, schreib_transaktion(sitzung):
        sitzung.execute(
            text(
                "UPDATE rechnungen SET status='festgeschrieben', rechnung_nr=:nr, "
                "festgeschrieben_am=:ts, hash=:hash WHERE id=:id"
            ),
            {
                "nr": nummer,
                "ts": jetzt_utc().replace(tzinfo=None),
                "hash": "a" * 64,
                "id": rechnung_id,
            },
        )


class TestEntwuerfeBleibenAenderbar:
    def test_entwurf_kann_geaendert_werden(self, db, beleg):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE rechnungen SET netto=5000 WHERE id=:id"), {"id": beleg["rechnung"]}
            )
        with Session(db) as sitzung:
            assert sitzung.get(Rechnung, beleg["rechnung"]).netto == 5000

    def test_entwurf_kann_geloescht_werden(self, db, beleg):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("DELETE FROM rechnungspos WHERE rechnung_id=:id"), {"id": beleg["rechnung"]}
            )
            sitzung.execute(text("DELETE FROM rechnungen WHERE id=:id"), {"id": beleg["rechnung"]})
        with Session(db) as sitzung:
            assert sitzung.get(Rechnung, beleg["rechnung"]) is None

    def test_position_am_entwurf_kann_angefuegt_werden(self, db, beleg):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.add(
                Rechnungsposition(
                    rechnung_id=beleg["rechnung"],
                    pos=2,
                    bezeichnung="Zusatzleistung",
                    menge=1,
                    ep_netto=50000,
                    ust_satz=190,
                )
            )


class TestFestgeschriebenerBelegIstUnveraenderbar:
    def test_update_wird_abgewiesen(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)) as fehler,
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungen SET netto=1 WHERE id=:id"), {"id": beleg["rechnung"]}
            )
        assert "nicht aenderbar" in str(fehler.value)

    def test_delete_wird_abgewiesen(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)) as fehler,
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(text("DELETE FROM rechnungen WHERE id=:id"), {"id": beleg["rechnung"]})
        assert "nicht loeschbar" in str(fehler.value)

    def test_nummer_kann_nicht_geaendert_werden(self, db, beleg):
        """Eine geänderte Rechnungsnummer würde die Lückenlosigkeit des Kreises zerstören."""
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungen SET rechnung_nr='RE-2026-0001' WHERE id=:id"),
                {"id": beleg["rechnung"]},
            )

    def test_hash_kann_nicht_geaendert_werden(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungen SET hash=:h WHERE id=:id"),
                {"h": "b" * 64, "id": beleg["rechnung"]},
            )

    def test_positionen_sind_gesperrt(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)) as fehler,
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungspos SET ep_netto=1 WHERE rechnung_id=:id"),
                {"id": beleg["rechnung"]},
            )
        assert "Position" in str(fehler.value)

    def test_positionen_koennen_nicht_geloescht_werden(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("DELETE FROM rechnungspos WHERE rechnung_id=:id"),
                {"id": beleg["rechnung"]},
            )

    def test_keine_neue_position_am_festgeschriebenen_beleg(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.add(
                Rechnungsposition(
                    rechnung_id=beleg["rechnung"],
                    pos=99,
                    bezeichnung="Nachträglich eingeschmuggelt",
                    menge=1,
                    ep_netto=100000,
                    ust_satz=190,
                )
            )
            sitzung.flush()


class TestStornoIstDerEineErlaubteWeg:
    def test_statuswechsel_auf_storniert_mit_verweis_ist_erlaubt(self, db, beleg):
        """PLAN §6.4: Korrektur nur per Stornobeleg mit Verweis."""
        _festschreiben(db, beleg["rechnung"])
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            # Der Gegenbeleg entsteht als eigener Datensatz.
            gegenbeleg = Rechnung(
                firma_id=beleg["firma"],
                art="storno",
                projekt_id=beleg["projekt"],
                datum=date(2026, 9, 15),
                netto=-9187500,
                ust=-1745625,
                brutto=-10933125,
                status="entwurf",
                storno_ref=beleg["rechnung"],
            )
            sitzung.add(gegenbeleg)
            sitzung.flush()
            # Der Ursprungsbeleg wird auf storniert gesetzt, mit Verweis auf den Gegenbeleg.
            sitzung.execute(
                text("UPDATE rechnungen SET status='storniert', storno_ref=:ref WHERE id=:id"),
                {"ref": gegenbeleg.id, "id": beleg["rechnung"]},
            )
        with Session(db) as sitzung:
            original = sitzung.get(Rechnung, beleg["rechnung"])
            assert original.status == "storniert"
            assert original.rechnung_nr == "RE-2026-0087", "Die Nummer bleibt erhalten"
            assert original.netto == 9187500, "Die Beträge bleiben erhalten"

    def test_statuswechsel_ohne_verweis_wird_abgewiesen(self, db, beleg):
        """Ein Storno ohne Verweis wäre ein stilles Verschwinden des Belegs."""
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungen SET status='storniert' WHERE id=:id"),
                {"id": beleg["rechnung"]},
            )

    def test_storno_darf_die_betraege_nicht_veraendern(self, db, beleg):
        """Sonst wäre der Storno ein Schlupfloch, um den Beleg umzuschreiben."""
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text(
                    "UPDATE rechnungen SET status='storniert', storno_ref=1, netto=0 WHERE id=:id"
                ),
                {"id": beleg["rechnung"]},
            )

    def test_zurueck_auf_entwurf_ist_ausgeschlossen(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE rechnungen SET status='entwurf' WHERE id=:id"),
                {"id": beleg["rechnung"]},
            )

    def test_stornierter_beleg_bleibt_unloeschbar(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE rechnungen SET status='storniert', storno_ref=:r WHERE id=:id"),
                {"r": beleg["rechnung"], "id": beleg["rechnung"]},
            )
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(text("DELETE FROM rechnungen WHERE id=:id"), {"id": beleg["rechnung"]})


class TestZahlungsplanSperre:
    def test_offene_position_bleibt_aenderbar(self, db, beleg):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE zahlungsplan SET betrag_netto=5000000 WHERE id=:id"),
                {"id": beleg["position"]},
            )
        with Session(db) as sitzung:
            assert sitzung.get(Zahlungsplanposition, beleg["position"]).betrag_netto == 5000000

    def test_berechnete_position_ist_gesperrt(self, db, beleg):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE zahlungsplan SET rechnung_id=:r WHERE id=:id"),
                {"r": beleg["rechnung"], "id": beleg["position"]},
            )
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)) as fehler,
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("UPDATE zahlungsplan SET betrag_netto=1 WHERE id=:id"),
                {"id": beleg["position"]},
            )
        assert "Zahlungsplanposition" in str(fehler.value)

    def test_berechnete_position_ist_unloeschbar(self, db, beleg):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE zahlungsplan SET rechnung_id=:r WHERE id=:id"),
                {"r": beleg["rechnung"], "id": beleg["position"]},
            )
        with (
            Session(db) as sitzung,
            pytest.raises((IntegrityError, OperationalError)),
            schreib_transaktion(sitzung),
        ):
            sitzung.execute(
                text("DELETE FROM zahlungsplan WHERE id=:id"), {"id": beleg["position"]}
            )

    def test_storno_gibt_die_position_wieder_frei(self, db, beleg):
        """PLAN §7, Phase 3: Storno gibt die Zahlungsplanposition wieder frei."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE zahlungsplan SET rechnung_id=:r WHERE id=:id"),
                {"r": beleg["rechnung"], "id": beleg["position"]},
            )
        # Freigabe: rechnung_id auf NULL – das lässt der Trigger zu.
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE zahlungsplan SET rechnung_id=NULL WHERE id=:id"),
                {"id": beleg["position"]},
            )
        # Danach ist die Position wieder bearbeitbar.
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            sitzung.execute(
                text("UPDATE zahlungsplan SET betrag_netto=8000000 WHERE id=:id"),
                {"id": beleg["position"]},
            )
        with Session(db) as sitzung:
            assert sitzung.get(Zahlungsplanposition, beleg["position"]).betrag_netto == 8000000


class TestMeldungenSindVerstaendlich:
    def test_meldungen_in_migration_und_uebersetzung_sind_deckungsgleich(self):
        """Ohne Übersetzung landet der Triggertext im Rohzustand auf dem Bildschirm.

        Die Texte stehen an zwei Stellen: in der Migration (als Triggertext) und in
        ``app.datenbank_sperren`` (als Übersetzung). Läuft das auseinander, zeigt der Leitstand
        „festgeschriebene Rechnung nicht aenderbar" statt eines verständlichen Satzes.
        """
        migration = _migration_laden()
        in_migration = {
            wert
            for name, wert in vars(migration).items()
            if name.startswith("MELDUNG_") and isinstance(wert, str)
        }
        assert in_migration == set(SPERRMELDUNGEN), (
            "Ohne Übersetzung: "
            + ", ".join(sorted(in_migration - set(SPERRMELDUNGEN)))
            + " | Übersetzung ohne Trigger: "
            + ", ".join(sorted(set(SPERRMELDUNGEN) - in_migration))
        )

    def test_jeder_triggertext_kommt_auch_im_sql_vor(self):
        """Eine Konstante, die in keinem Trigger verwendet wird, ist eine tote Übersetzung."""
        migration = _migration_laden()
        alle_trigger = "\n".join(migration.TRIGGER.values())
        for meldung in SPERRMELDUNGEN:
            assert meldung in alle_trigger, f"Meldung in keinem Trigger verwendet: {meldung}"

    def test_triggermeldung_wird_zu_einem_konflikt(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with Session(db) as sitzung:
            try:
                with schreib_transaktion(sitzung):
                    sitzung.execute(
                        text("UPDATE rechnungen SET netto=1 WHERE id=:id"),
                        {"id": beleg["rechnung"]},
                    )
            except Exception as fehler:
                uebersetzt = als_fachfehler(fehler)
                assert isinstance(uebersetzt, Konflikt)
                assert uebersetzt.status_code == 409
                assert uebersetzt.code == "beleg_festgeschrieben"
                assert "festgeschrieben" in uebersetzt.meldung
                assert "Storno" in uebersetzt.naechster_schritt
                assert "aenderbar" not in uebersetzt.meldung, "Der Rohtext darf nicht durchsickern"
            else:
                pytest.fail("Die Sperre hat nicht gegriffen")

    def test_anderer_datenbankfehler_wird_nicht_uebersetzt(self, db, beleg):
        """Ein doppelter Schlüssel ist kein Sperrfall und gehört in die allgemeine Behandlung."""
        with Session(db) as sitzung:
            try:
                with schreib_transaktion(sitzung):
                    sitzung.add(Kunde(kunden_nr=10001, name="Doppelt", typ="b2b"))
                    sitzung.flush()
            except Exception as fehler:
                assert als_fachfehler(fehler) is None
            else:
                pytest.fail("Der doppelte Schlüssel wurde nicht abgewiesen")

    def test_sperren_uebersetzen_wirft_nur_bei_sperren(self, db, beleg):
        _festschreiben(db, beleg["rechnung"])
        with Session(db) as sitzung, pytest.raises(Konflikt):
            try:
                with schreib_transaktion(sitzung):
                    sitzung.execute(
                        text("DELETE FROM rechnungen WHERE id=:id"), {"id": beleg["rechnung"]}
                    )
            except Exception as fehler:
                sperren_uebersetzen(fehler)
                raise


class TestTriggerSindVorhanden:
    def test_alle_trigger_stehen_in_der_datenbank(self, db):
        with db.connect() as verbindung:
            vorhandene = {
                zeile[0]
                for zeile in verbindung.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }
        erwartet = {
            "trg_rechnungen_festgeschrieben_update",
            "trg_rechnungen_festgeschrieben_delete",
            "trg_rechnungen_storno_nur_status",
            "trg_rechnungspos_update",
            "trg_rechnungspos_delete",
            "trg_rechnungspos_insert",
            "trg_zahlungsplan_berechnet_update",
            "trg_zahlungsplan_berechnet_delete",
        }
        assert erwartet <= vorhandene, "Fehlende Trigger: " + ", ".join(erwartet - vorhandene)
