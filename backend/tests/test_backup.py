"""Datensicherung (PLAN §2).

Eine Sicherung, die niemand geprüft hat, ist eine Vermutung. Diese Tests prüfen, was im Ernstfall
zählt: dass die Kopie vollständig und lesbar ist, dass die Rotation nur die eigenen Dateien
anfasst und dass ein gescheiterter Lauf sichtbar wird statt still zu verschwinden.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.datenbank import engine_erzeugen, schreib_sitzung, schreib_transaktion
from app.jobs.backup import (
    NAMENSMUSTER,
    backup_job,
    generationen_aufraeumen,
    sicherung_durchfuehren,
    sicherung_erstellen,
    sicherung_pruefen,
)
from app.modelle import Firma, JobLauf, Kunde
from app.werkzeuge.seed import grunddaten


@pytest.fixture
def db_mit_daten(gesäte_db: Path, test_einstellungen) -> Path:
    """Datenbank mit einigen Datensätzen, damit die Kopie prüfbar ist."""
    with schreib_sitzung() as sitzung:
        for nummer in range(1, 21):
            sitzung.add(Kunde(kunden_nr=20000 + nummer, name=f"Kunde {nummer}", typ="b2b"))
    return gesäte_db


class TestKopieErstellen:
    def test_kopie_entsteht_und_ist_lesbar(self, db_mit_daten: Path, tmp_path: Path):
        ziel_ordner = tmp_path / "backup"
        datei, groesse = sicherung_erstellen(db_mit_daten, ziel_ordner)
        assert datei.exists()
        assert groesse > 0
        assert NAMENSMUSTER.match(datei.name), f"Name passt nicht zum Muster: {datei.name}"

    def test_kopie_enthaelt_alle_zeilen(self, db_mit_daten: Path, tmp_path: Path):
        """Der eigentliche Zweck: die Daten müssen vollständig drin sein."""
        with schreib_sitzung() as sitzung:
            erwartet = sitzung.scalar(select(func.count()).select_from(Kunde))

        datei, _ = sicherung_erstellen(db_mit_daten, tmp_path / "backup")

        kopie = engine_erzeugen(datei, ohne_pool=True)
        try:
            with Session(kopie) as sitzung:
                assert sitzung.scalar(select(func.count()).select_from(Kunde)) == erwartet
                assert sitzung.scalar(select(func.count()).select_from(Firma)) == 1
        finally:
            kopie.dispose()

    def test_kopie_ist_in_sich_geschlossen(self, db_mit_daten: Path, tmp_path: Path):
        """VACUUM INTO liefert eine Datei ohne -wal und -shm.

        Deshalb genügt beim Restore das Zurückkopieren dieser einen Datei (RUNBOOK).
        """
        datei, _ = sicherung_erstellen(db_mit_daten, tmp_path / "backup")
        assert not Path(f"{datei}-wal").exists()
        assert not Path(f"{datei}-shm").exists()

    def test_zielverzeichnis_wird_angelegt(self, db_mit_daten: Path, tmp_path: Path):
        ziel = tmp_path / "noch" / "nicht" / "da"
        datei, _ = sicherung_erstellen(db_mit_daten, ziel)
        assert datei.parent == ziel

    def test_vorhandene_datei_wird_nicht_ueberschrieben(self, db_mit_daten: Path, tmp_path: Path):
        """VACUUM INTO bricht bei vorhandener Zieldatei ab – und eine bestehende Sicherung
        zu überschreiben wäre ohnehin falsch."""
        ordner = tmp_path / "backup"
        erste, _ = sicherung_erstellen(db_mit_daten, ordner)
        zweite, _ = sicherung_erstellen(db_mit_daten, ordner)
        assert erste != zweite
        assert erste.exists() and zweite.exists()

    def test_fehlende_quelldatenbank_meldet_sich(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            sicherung_erstellen(tmp_path / "gibt-es-nicht.sqlite3", tmp_path / "backup")

    def test_kopie_bei_gleichzeitigem_schreiber(self, db_mit_daten: Path, tmp_path: Path):
        """Der Grund für VACUUM INTO statt Dateikopie: es darf jemand gleichzeitig arbeiten.

        Eine zweite Verbindung hält eine offene Schreibtransaktion, während die Sicherung läuft.
        Die Kopie muss den Stand vor dieser Transaktion enthalten, in sich schlüssig.
        """
        zweite_verbindung = sqlite3.connect(str(db_mit_daten))
        try:
            zweite_verbindung.execute("BEGIN IMMEDIATE")
            zweite_verbindung.execute(
                "INSERT INTO kunden (kunden_nr, name, typ, status, created_at, updated_at) "
                "VALUES (99999, 'Noch nicht bestätigt', 'b2b', 'aktiv', "
                "'2026-08-27 00:00:00', '2026-08-27 00:00:00')"
            )
            datei, _ = sicherung_erstellen(db_mit_daten, tmp_path / "backup")
            assert sicherung_pruefen(datei), "Die Kopie ist nicht in sich schlüssig"

            kopie = engine_erzeugen(datei, ohne_pool=True)
            try:
                with kopie.connect() as verbindung:
                    offen = verbindung.execute(
                        text("SELECT COUNT(*) FROM kunden WHERE kunden_nr = 99999")
                    ).scalar()
                assert offen == 0, "Eine nicht abgeschlossene Änderung darf nicht in der Kopie sein"
            finally:
                kopie.dispose()
        finally:
            zweite_verbindung.rollback()
            zweite_verbindung.close()


class TestIntegritaetspruefung:
    def test_gute_kopie_besteht_die_pruefung(self, db_mit_daten: Path, tmp_path: Path):
        datei, _ = sicherung_erstellen(db_mit_daten, tmp_path / "backup")
        assert sicherung_pruefen(datei) is True

    def test_beschaedigte_datei_faellt_auf(self, db_mit_daten: Path, tmp_path: Path):
        datei, _ = sicherung_erstellen(db_mit_daten, tmp_path / "backup")
        # Mitten in der Datei etwas überschreiben – so sieht ein Übertragungsfehler aus.
        rohdaten = bytearray(datei.read_bytes())
        for stelle in range(2000, min(6000, len(rohdaten))):
            rohdaten[stelle] = 0
        datei.write_bytes(bytes(rohdaten))
        assert sicherung_pruefen(datei) is False


class TestRotation:
    def _sicherungen_anlegen(self, ordner: Path, anzahl: int) -> list[Path]:
        ordner.mkdir(parents=True, exist_ok=True)
        dateien = []
        for nummer in range(anzahl):
            # Eindeutige Namen: bei Wiederholungen entstünden weniger Dateien als gedacht und
            # der Test würde nichts prüfen.
            stunde, minute = divmod(nummer, 60)
            datei = ordner / f"leitstand_20260801-{stunde:02d}{minute:02d}00.sqlite3"
            datei.write_bytes(b"x" * 100)
            # Änderungszeitpunkte auseinanderziehen, damit die Reihenfolge feststeht.
            zeitpunkt = time.time() - (anzahl - nummer) * 3600
            import os

            os.utime(datei, (zeitpunkt, zeitpunkt))
            dateien.append(datei)
        return dateien

    def test_genau_dreissig_generationen_bleiben(self, tmp_path: Path):
        """PLAN §2: 30 Generationen vorhalten."""
        ordner = tmp_path / "backup"
        self._sicherungen_anlegen(ordner, 35)
        geloescht = generationen_aufraeumen(ordner, 30)
        assert geloescht == 5
        verbleibend = [p for p in ordner.iterdir() if NAMENSMUSTER.match(p.name)]
        assert len(verbleibend) == 30

    def test_die_aeltesten_werden_geloescht(self, tmp_path: Path):
        ordner = tmp_path / "backup"
        dateien = self._sicherungen_anlegen(ordner, 12)
        generationen_aufraeumen(ordner, 10)
        # Die zwei ältesten sind weg, die jüngsten sind da.
        assert not dateien[0].exists()
        assert not dateien[1].exists()
        assert dateien[-1].exists()

    def test_fremde_dateien_bleiben_unberuehrt(self, tmp_path: Path):
        """Im OneDrive-Ordner liegen möglicherweise andere Dateien – die gehören nicht uns."""
        ordner = tmp_path / "backup"
        self._sicherungen_anlegen(ordner, 35)
        fremde = ordner / "Wichtige_Notizen.txt"
        fremde.write_text("Nicht löschen", encoding="utf-8")
        restore = ordner / "leitstand_restore_2026-08-01.sqlite3"
        restore.write_bytes(b"x")

        generationen_aufraeumen(ordner, 30)

        assert fremde.exists(), "Eine fremde Datei wurde gelöscht"
        assert restore.exists(), "Eine Datei außerhalb des Namensmusters wurde gelöscht"

    def test_weniger_als_das_limit_bleibt_unangetastet(self, tmp_path: Path):
        ordner = tmp_path / "backup"
        self._sicherungen_anlegen(ordner, 5)
        assert generationen_aufraeumen(ordner, 30) == 0
        assert len(list(ordner.iterdir())) == 5

    def test_fehlender_ordner_ist_kein_fehler(self, tmp_path: Path):
        assert generationen_aufraeumen(tmp_path / "gibt-es-nicht", 30) == 0

    def test_rotation_oeffnet_keine_datei(self, tmp_path: Path, monkeypatch):
        """Im OneDrive-Ordner würde ein Lesezugriff alte Sicherungen aus der Cloud zurückholen.

        Nach einigen Nächten wäre die Festplatte mit 30 Datenbankkopien belegt.
        """
        ordner = tmp_path / "backup"
        self._sicherungen_anlegen(ordner, 35)

        geoeffnet: list[str] = []
        originales_open = Path.open

        def ueberwacht(self, *args, **kwargs):
            if NAMENSMUSTER.match(self.name):
                geoeffnet.append(self.name)
            return originales_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", ueberwacht)
        generationen_aufraeumen(ordner, 30)
        assert geoeffnet == [], f"Sicherungen wurden geöffnet: {geoeffnet}"


class TestVollstaendigerAblauf:
    def test_sicherung_mit_pruefung_und_rotation(self, db_mit_daten: Path, test_einstellungen):
        test_einstellungen.jobs.backup_generationen = 3
        for _ in range(5):
            sicherung_durchfuehren(test_einstellungen)
        bericht = sicherung_durchfuehren(test_einstellungen)

        assert bericht.integritaet_ok
        verbleibend = [
            p for p in test_einstellungen.pfade.backup.iterdir() if NAMENSMUSTER.match(p.name)
        ]
        assert len(verbleibend) == 3

    def test_ohne_backupziel_verstaendlicher_fehler(self, db_mit_daten: Path, test_einstellungen):
        test_einstellungen.pfade.backup = None
        with pytest.raises(FileNotFoundError, match="Backup-Ziel"):
            sicherung_durchfuehren(test_einstellungen)


class TestJobProtokoll:
    def test_erfolgreicher_lauf_wird_protokolliert(self, db_mit_daten: Path, test_einstellungen):
        backup_job("manuell", test_einstellungen)
        with schreib_sitzung() as sitzung:
            lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "backup"))
            assert lauf.status == "erfolg"
            assert lauf.ausgeloest_von == "manuell"
            assert lauf.beendet is not None
            assert lauf.dauer_ms is not None and lauf.dauer_ms >= 0
            assert "Sicherung" in lauf.meldung
            assert lauf.kennzahlen["groesse_mb"] > 0
            assert lauf.kennzahlen["integritaet"] == "ok"

    def test_fehlgeschlagener_lauf_wird_protokolliert_ohne_ausnahme(
        self, db_mit_daten: Path, test_einstellungen
    ):
        """Ein Job darf nicht mit einer Ausnahme enden – der Scheduler würde sie schlucken."""
        test_einstellungen.pfade.backup = None

        backup_job("zeitplan", test_einstellungen)  # wirft nicht

        with schreib_sitzung() as sitzung:
            lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "backup"))
            assert lauf.status == "fehler"
            assert "Verzeichnis oder eine Datei fehlt" in lauf.meldung
            assert "config.toml" in lauf.meldung

    def test_unbrauchbares_ziel_ergibt_deutsche_meldung(
        self, db_mit_daten: Path, test_einstellungen, tmp_path: Path
    ):
        """Häufigster Fall im Betrieb: ein Tippfehler im Backup-Pfad.

        Hier zeigt der Pfad auf eine Datei statt auf ein Verzeichnis. Bewusst nicht über
        Dateirechte geprüft: der Testlauf hat unter Umständen Administratorrechte, und dann
        greifen sie nicht – der Test wäre wirkungslos, ohne fehlzuschlagen.
        """
        keine_datei = tmp_path / "das-ist-eine-datei.txt"
        keine_datei.write_text("kein Verzeichnis", encoding="utf-8")
        test_einstellungen.pfade.backup = keine_datei / "unterordner"

        backup_job("zeitplan", test_einstellungen)  # wirft nicht

        with schreib_sitzung() as sitzung:
            lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "backup"))
            assert lauf.status == "fehler"
            assert "Datensicherung fehlgeschlagen" in lauf.meldung
            # Kein Stacktrace, keine Python-Klassennamen in der Meldung.
            assert "Traceback" not in lauf.meldung
            assert "NotADirectoryError" not in lauf.meldung

    def test_beschaedigte_kopie_ergibt_warnung_statt_erfolg(
        self, db_mit_daten: Path, test_einstellungen, monkeypatch
    ):
        monkeypatch.setattr("app.jobs.backup.sicherung_pruefen", lambda _: False)
        backup_job("manuell", test_einstellungen)
        with schreib_sitzung() as sitzung:
            lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "backup"))
            assert lauf.status == "warnung"
            assert "Integritätsprüfung" in lauf.meldung
            assert "ip3-leitstand pruefen" in lauf.meldung

    def test_unbekannter_job_wird_abgewiesen(self, gesäte_db):
        from app.jobs.lauf import protokollierter_lauf

        with (
            pytest.raises(KeyError, match="Unbekannter Job"),
            protokollierter_lauf("gibt-es-nicht"),
        ):
            pass


class TestRestore:
    def test_zurueckgespieltes_backup_ist_verwendbar(
        self, db_mit_daten: Path, test_einstellungen, tmp_path: Path
    ):
        """Der Ablauf aus dem RUNBOOK: sichern, Datenbank beiseitelegen, Kopie zurückspielen.

        Das Akzeptanzkriterium der Phase 0 verlangt eine geprobte Rückspielung.
        """
        with schreib_sitzung() as sitzung:
            vorher = sitzung.scalar(select(func.count()).select_from(Kunde))

        bericht = sicherung_durchfuehren(test_einstellungen)

        # Nach der Sicherung passiert noch etwas – das soll nach dem Restore fehlen.
        with schreib_sitzung() as sitzung:
            sitzung.add(Kunde(kunden_nr=88888, name="Nach der Sicherung", typ="b2b"))

        # Datenbank beiseitelegen (nicht löschen!) und Sicherung an ihre Stelle kopieren.
        import shutil

        beiseite = db_mit_daten.with_suffix(".sqlite3.vor-restore")
        shutil.move(str(db_mit_daten), str(beiseite))
        for begleitdatei in (f"{db_mit_daten}-wal", f"{db_mit_daten}-shm"):
            if Path(begleitdatei).exists():
                Path(begleitdatei).unlink()
        shutil.copy2(bericht.datei, db_mit_daten)

        from app.datenbank import zuruecksetzen
        from app.werkzeuge.schema import kopf_revision, schema_revision

        zuruecksetzen()

        assert schema_revision(db_mit_daten) == kopf_revision()
        with schreib_sitzung() as sitzung:
            assert sitzung.scalar(select(func.count()).select_from(Kunde)) == vorher
            assert sitzung.scalar(select(Kunde).where(Kunde.kunden_nr == 88888)) is None, (
                "Der Stand nach der Sicherung darf nach dem Restore nicht da sein"
            )

        # Die zurückgelegte Datei ist noch vorhanden – wichtig, falls das Backup unbrauchbar wäre.
        assert beiseite.exists()

    def test_seed_laeuft_auf_zurueckgespielter_datenbank(
        self, db_mit_daten: Path, test_einstellungen, tmp_path: Path
    ):
        """Nach einem Restore muss der Leitstand normal weiterarbeiten."""
        bericht = sicherung_durchfuehren(test_einstellungen)
        ziel = tmp_path / "wiederhergestellt.sqlite3"
        import shutil

        shutil.copy2(bericht.datei, ziel)

        engine = engine_erzeugen(ziel)
        try:
            with Session(engine) as sitzung, schreib_transaktion(sitzung):
                ergebnis = grunddaten(sitzung, test_einstellungen)
            assert not ergebnis.firma_angelegt, "Die Grunddaten waren in der Sicherung enthalten"
        finally:
            engine.dispose()
