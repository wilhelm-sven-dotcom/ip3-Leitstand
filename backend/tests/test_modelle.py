"""Datenmodell: Vollständigkeit, Übereinstimmung mit der Migration, Indizes, Typen.

Diese Tests sind billig und fangen die Fehler, die später teuer werden: eine Tabelle, die nur im
Modell steht, ein Index, der auf dem Bürorechner fehlt, ein Zeitpunkt ohne Zone in der Datenbank.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.datenbank import engine_erzeugen, fremdschluessel_aktiv, schreib_transaktion
from app.modelle import ERWARTETE_TABELLEN, Base, Firma, JobLauf, Kunde, User
from app.werkzeuge.schema import kopf_revision, schema_revision, tabellen
from app.zeit import jetzt_utc


@pytest.fixture
def db(db_pfad: Path):
    engine = engine_erzeugen(db_pfad)
    yield engine
    engine.dispose()


class TestVollstaendigkeit:
    def test_alle_erwarteten_tabellen_im_modell(self):
        """Fehlt eine Tabelle im Import von app/modelle/__init__.py, fällt sie aus den Migrationen."""
        im_modell = set(Base.metadata.tables)
        assert ERWARTETE_TABELLEN - im_modell == set(), "Tabellen fehlen im Modell"
        assert im_modell - ERWARTETE_TABELLEN == set(), "Unerwartete Tabellen im Modell"

    def test_migration_erzeugt_alle_tabellen(self, db):
        assert tabellen(db) == ERWARTETE_TABELLEN

    def test_datenbank_ist_auf_der_erwarteten_revision(self, db_pfad: Path):
        assert schema_revision(db_pfad) == kopf_revision()


class TestSchemaDrift:
    def test_modelle_und_migration_stimmen_ueberein(self, db, db_pfad: Path):
        """Ohne diesen Test läuft das Modell irgendwann auseinander mit dem, was migriert wird.

        Verglichen werden Tabellen, Spalten, Nullbarkeit und Indizes. Ein Unterschied bedeutet:
        eine Migration fehlt.
        """
        pruefer = inspect(db)
        abweichungen: list[str] = []

        for name, tabelle in Base.metadata.tables.items():
            spalten_db = {s["name"]: s for s in pruefer.get_columns(name)}
            spalten_modell = {s.name: s for s in tabelle.columns}

            for fehlend in spalten_modell.keys() - spalten_db.keys():
                abweichungen.append(f"{name}.{fehlend} fehlt in der Datenbank")
            for ueberzaehlig in spalten_db.keys() - spalten_modell.keys():
                abweichungen.append(f"{name}.{ueberzaehlig} steht nur in der Datenbank")

            for spaltenname in spalten_modell.keys() & spalten_db.keys():
                modell = spalten_modell[spaltenname]
                datenbank = spalten_db[spaltenname]
                if modell.nullable != datenbank["nullable"]:
                    abweichungen.append(
                        f"{name}.{spaltenname}: nullable {modell.nullable} im Modell, "
                        f"{datenbank['nullable']} in der Datenbank"
                    )

        assert abweichungen == [], "Schema und Modell weichen ab:\n" + "\n".join(abweichungen)

    def test_indizes_der_migration_entsprechen_dem_modell(self, db):
        pruefer = inspect(db)
        fehlend: list[str] = []
        for name, tabelle in Base.metadata.tables.items():
            in_db = {i["name"] for i in pruefer.get_indexes(name)}
            for index in tabelle.indexes:
                if index.name not in in_db:
                    fehlend.append(f"{name}: {index.name}")
        assert fehlend == [], "Indizes fehlen in der Datenbank: " + ", ".join(fehlend)


class TestIndizes:
    def test_jeder_fremdschluessel_hat_einen_index(self, db):
        """SQLite legt für Fremdschlüssel keinen Index an. Ohne Index werden Verbundabfragen
        über Projekte und Rechnungen mit wachsender Datenmenge langsam (PLAN §2)."""
        pruefer = inspect(db)
        ohne_index: list[str] = []
        for tabellenname in tabellen(db):
            indizierte_spalten = {
                next(iter(i["column_names"]))
                for i in pruefer.get_indexes(tabellenname)
                if i["column_names"]
            }
            # Ein zusammengesetzter Primärschlüssel deckt seine erste Spalte mit ab.
            pk = pruefer.get_pk_constraint(tabellenname).get("constrained_columns") or []
            if pk:
                indizierte_spalten.add(pk[0])
            for fk in pruefer.get_foreign_keys(tabellenname):
                spalte = fk["constrained_columns"][0]
                if spalte not in indizierte_spalten:
                    ohne_index.append(f"{tabellenname}.{spalte}")
        assert ohne_index == [], "Fremdschlüssel ohne Index: " + ", ".join(ohne_index)

    @pytest.mark.parametrize(
        ("tabelle", "spalte"),
        [
            ("projekte", "projekt_nr"),
            ("kunden", "kunden_nr"),
            ("zahlungsplan", "plan_monat"),
            ("ist_kosten", "monat"),
            ("stunden", "monat"),
            ("datev_salden", "monat"),
            ("fixkosten_plan", "monat"),
            ("rechnungen", "rechnung_nr"),
            ("rechnungen", "datum"),
        ],
    )
    def test_schluessel_und_monatsspalten_sind_indiziert(self, db, tabelle: str, spalte: str):
        """PLAN §2 verlangt Indizes auf projekt_nr, kunden_nr und den Monatsspalten."""
        indizes = inspect(db).get_indexes(tabelle)
        indizierte = {s for i in indizes for s in i["column_names"] if s}
        assert spalte in indizierte, f"{tabelle}.{spalte} ist nicht indiziert"


class TestDatenbankeinstellungen:
    def test_fremdschluesselpruefung_auf_jeder_verbindung(self, db):
        """Die Prüfung gilt je Verbindung; ein einmaliges PRAGMA beim Start würde nicht reichen."""
        assert fremdschluessel_aktiv(db)
        # Zweite, frische Verbindung – hier zeigte sich der Fehler, wenn das PRAGMA nur einmal
        # gesetzt würde.
        assert fremdschluessel_aktiv(db)

    def test_wal_modus_ist_aktiv(self, db):
        with db.connect() as verbindung:
            assert verbindung.execute(text("PRAGMA journal_mode")).scalar() == "wal"

    def test_verletzter_fremdschluessel_wird_abgewiesen(self, db):
        from sqlalchemy.exc import IntegrityError

        with (
            Session(db) as sitzung,
            pytest.raises(IntegrityError),
            schreib_transaktion(sitzung),
        ):
            sitzung.add(Kunde(kunden_nr=10001, name="Testkunde", typ="b2c", status="aktiv"))
            sitzung.flush()
            from app.modelle import Ansprechpartner

            sitzung.add(Ansprechpartner(kunde_id=999999, name="Niemand"))
            sitzung.flush()


class TestZeitstempel:
    def test_utc_zeitpunkt_kommt_mit_zone_zurueck(self, db):
        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                lauf = JobLauf(job="backup", gestartet=jetzt_utc(), status="erfolg")
                sitzung.add(lauf)
            geladen = sitzung.query(JobLauf).one()
            assert geladen.gestartet.tzinfo is not None
            assert geladen.gestartet.utcoffset().total_seconds() == 0

    def test_zeitpunkt_ohne_zone_wird_abgewiesen(self, db):
        """Ein Zeitpunkt ohne Zone in der Datenbank ist eine Zahl ohne Bedeutung."""
        from sqlalchemy.exc import StatementError

        # SQLAlchemy verpackt den ValueError des Spaltentyps in einen StatementError; die Meldung
        # bleibt erhalten und nennt den nächsten Schritt.
        with (
            Session(db) as sitzung,
            pytest.raises(StatementError, match="Zeitzone"),
            schreib_transaktion(sitzung),
        ):
            sitzung.add(JobLauf(job="backup", gestartet=datetime(2026, 8, 27, 1, 30)))
            sitzung.flush()

    def test_ortszeit_wird_als_utc_gespeichert(self, db):
        from zoneinfo import ZoneInfo

        ortszeit = datetime(2026, 7, 1, 14, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                sitzung.add(JobLauf(job="backup", gestartet=ortszeit, status="erfolg"))
            # Direkt in der Datenbank stehen 12:00 (UTC), nicht 14:00.
            roh = sitzung.execute(text("SELECT gestartet FROM job_laeufe")).scalar()
            assert "12:00" in str(roh)
            geladen = sitzung.query(JobLauf).one()
            assert geladen.gestartet == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def test_zeitstempel_werden_automatisch_gesetzt(self, db):
        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                firma = Firma(kuerzel="test", firmierung="Test GmbH")
                sitzung.add(firma)
            assert firma.created_at is not None
            assert firma.updated_at is not None


class TestOptimisticLocking:
    def test_speichern_mit_veraltetem_stand_ergibt_konflikt(self, db):
        """PLAN §5: kein stilles Überschreiben, wenn zwei Personen dasselbe Projekt bearbeiten."""
        from sqlalchemy.orm.exc import StaleDataError

        with Session(db) as vorbereitung:
            with schreib_transaktion(vorbereitung):
                vorbereitung.add(
                    Kunde(kunden_nr=10001, name="Maschinenbau Köstler GmbH", typ="b2b")
                )
            kunden_id = vorbereitung.query(Kunde).one().id

        # Zwei Sitzungen lesen denselben Stand.
        sitzung_a = Session(db)
        sitzung_b = Session(db)
        kunde_a = sitzung_a.get(Kunde, kunden_id)
        kunde_b = sitzung_b.get(Kunde, kunden_id)

        kunde_a.ort = "Weiden"
        with schreib_transaktion(sitzung_a):
            pass
        sitzung_a.close()

        kunde_b.ort = "Theisseil"
        with pytest.raises(StaleDataError), schreib_transaktion(sitzung_b):
            pass
        sitzung_b.close()

    def test_importtabellen_ohne_optimistic_locking(self):
        """Importierte Zeilen (Salden, OPOS, Stunden) werden nicht von Hand bearbeitet."""
        from app.modelle import DatevSaldo, IstKosten, Opos, Stunden

        for klasse in (DatevSaldo, Opos, IstKosten, Stunden):
            assert klasse.__mapper__.version_id_col is None, klasse.__name__

    def test_stammdaten_mit_optimistic_locking(self):
        from app.modelle import Projekt, Rechnung, Zahlungsplanposition

        for klasse in (Kunde, Projekt, Rechnung, Zahlungsplanposition, User):
            assert klasse.__mapper__.version_id_col is not None, klasse.__name__


class TestPruefbedingungen:
    def test_unzulaessiger_status_wird_abgewiesen(self, db):
        from sqlalchemy.exc import IntegrityError

        with (
            Session(db) as sitzung,
            pytest.raises(IntegrityError),
            schreib_transaktion(sitzung),
        ):
            sitzung.add(Kunde(kunden_nr=10002, name="Test", typ="b2b", status="halbaktiv"))
            sitzung.flush()

    def test_unzulaessiger_monat_wird_abgewiesen(self, db):
        from sqlalchemy.exc import IntegrityError

        from app.modelle import FixkostenPlan

        with (
            Session(db) as sitzung,
            pytest.raises(IntegrityError),
            schreib_transaktion(sitzung),
        ):
            sitzung.add(FixkostenPlan(monat="2026-13", block="personal", betrag=100000))
            sitzung.flush()

    def test_gueltiger_monat_wird_angenommen(self, db):
        from app.modelle import FixkostenPlan

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                sitzung.add(FixkostenPlan(monat="2026-12", block="personal", betrag=100000))
            assert sitzung.query(FixkostenPlan).count() == 1

    def test_geldbetraege_duerfen_negativ_sein(self, db):
        """Gutschriften und Stornos tragen Negativbeträge (PLAN §6.14)."""
        from app.modelle import FixkostenPlan

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                sitzung.add(FixkostenPlan(monat="2026-01", block="sonstiges", betrag=-50000))
            assert sitzung.query(FixkostenPlan).one().betrag == -50000

    def test_meilenstein_je_projekt_nur_einmal(self, db):
        from sqlalchemy.exc import IntegrityError

        from app.modelle import Meilenstein, Projekt

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                firma = Firma(kuerzel="ip3", firmierung="ip³ Energietechnik GmbH")
                kunde = Kunde(kunden_nr=10003, name="Testkunde", typ="b2b")
                sitzung.add_all([firma, kunde])
                sitzung.flush()
                projekt = Projekt(
                    projekt_nr=26001, firma_id=firma.id, kunde_id=kunde.id, typ="projekt"
                )
                sitzung.add(projekt)
                sitzung.flush()
                sitzung.add(Meilenstein(projekt_id=projekt.id, typ="abnahme"))
            with pytest.raises(IntegrityError), schreib_transaktion(sitzung):
                sitzung.add(Meilenstein(projekt_id=projekt.id, typ="abnahme"))
                sitzung.flush()

    def test_zahlungsplan_positionsnummer_je_projekt_eindeutig(self, db):
        from sqlalchemy.exc import IntegrityError

        from app.modelle import Projekt, Zahlungsplanposition

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                firma = Firma(kuerzel="ip3", firmierung="ip³ Energietechnik GmbH")
                kunde = Kunde(kunden_nr=10004, name="Testkunde", typ="b2b")
                sitzung.add_all([firma, kunde])
                sitzung.flush()
                projekt = Projekt(projekt_nr=26002, firma_id=firma.id, kunde_id=kunde.id)
                sitzung.add(projekt)
                sitzung.flush()
                sitzung.add(
                    Zahlungsplanposition(
                        projekt_id=projekt.id,
                        pos_nr=1,
                        bezeichnung="1. Abschlag PV",
                        gewerk="pv",
                        art="abschlag",
                        betrag_netto=9187500,
                    )
                )
            with pytest.raises(IntegrityError), schreib_transaktion(sitzung):
                sitzung.add(
                    Zahlungsplanposition(
                        projekt_id=projekt.id,
                        pos_nr=1,
                        bezeichnung="Doppelte Position",
                        gewerk="pv",
                        art="abschlag",
                        betrag_netto=1000,
                    )
                )
                sitzung.flush()


class TestBerechtigungsmodell:
    def test_scope_alle_gewinnt_gegen_eigene(self, db):
        """Mehrere Rollen: der weitere Scope setzt sich durch (PLAN §4)."""
        from app.modelle import Berechtigung, Rolle

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                eng = Berechtigung(schluessel="projekte.lesen", scope="eigene")
                weit = Berechtigung(schluessel="projekte.lesen", scope="alle")
                rolle_pl = Rolle(name="projektleiter", berechtigungen=[eng])
                rolle_bh = Rolle(name="buchhaltung", berechtigungen=[weit])
                nutzer = User(
                    name="Test",
                    email="test@ip3-energie.de",
                    pw_hash="x",
                    rollen=[rolle_pl, rolle_bh],
                )
                sitzung.add(nutzer)
            assert nutzer.berechtigungsschluessel()["projekte.lesen"] == "alle"

    def test_scope_eigene_bleibt_ohne_weitere_rolle(self, db):
        from app.modelle import Berechtigung, Rolle

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                eng = Berechtigung(schluessel="projekte.lesen", scope="eigene")
                nutzer = User(
                    name="Test",
                    email="pl@ip3-energie.de",
                    pw_hash="x",
                    rollen=[Rolle(name="projektleiter", berechtigungen=[eng])],
                )
                sitzung.add(nutzer)
            assert nutzer.berechtigungsschluessel() == {"projekte.lesen": "eigene"}

    def test_berechtigung_ohne_scope_gilt_als_alle(self, db):
        from app.modelle import Berechtigung, Rolle

        with Session(db) as sitzung:
            with schreib_transaktion(sitzung):
                ohne = Berechtigung(schluessel="cockpit.lesen", scope=None)
                nutzer = User(
                    name="Sven",
                    email="s.wilhelm@ip3-energie.de",
                    pw_hash="x",
                    rollen=[Rolle(name="admin", berechtigungen=[ohne])],
                )
                sitzung.add(nutzer)
            assert nutzer.berechtigungsschluessel()["cockpit.lesen"] == "alle"
