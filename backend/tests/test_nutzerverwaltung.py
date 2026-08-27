"""Nutzerverwaltung über die Kommandozeile.

Bis es eine Oberfläche dafür gibt (spätere Phase), ist die Kommandozeile der einzige Weg,
Konten für die Geschäftsführung, die Buchhaltung und das Team einzurichten. Ohne sie wären
die drei Rollen aus PLAN §4 nicht vergebbar – der Leitstand hätte genau einen Nutzer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from app.cli import anwendung
from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import ERWARTETE_TABELLEN, Sitzung, User
from app.sicherheit import passwort as pw
from app.zeit import jetzt_utc

runner = CliRunner()


def kopf_der_migrationskette() -> str:
    """Neueste Alembic-Revision, aus den Migrationsskripten gelesen.

    Absichtlich nicht als Zahl im Test festgeschrieben: sonst müsste jede neue Migration hier
    nachgezogen werden, und der Test würde bei Vergessen fehlschlagen, ohne dass am Programm
    etwas falsch ist. Geprüft wird die Aussage, die zählt – der ``pruefen``-Befehl nennt den
    Stand, auf den die Migrationen die Datenbank gebracht haben.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    wurzel = Path(__file__).resolve().parents[1]
    konfiguration = Config(str(wurzel / "alembic.ini"))
    konfiguration.set_main_option("script_location", str(wurzel / "alembic"))
    return ScriptDirectory.from_config(konfiguration).get_current_head() or ""


@pytest.fixture
def cli(gesäte_db, test_einstellungen, monkeypatch):
    """CLI gegen die Testdatenbank.

    Die Befehle holen die Konfiguration über ``app.cli.einstellungen``; dieser Name wird
    ersetzt, damit sie dieselbe Datenbank verwenden wie der Test.
    """
    monkeypatch.setattr("app.cli.einstellungen", lambda: test_einstellungen)
    return runner


class TestNutzerAnlegen:
    def test_konto_mit_rolle_wird_angelegt(self, cli):
        ergebnis = cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "michael@ip3-energie.de",
                "Michael Bäumler",
                "--rolle",
                "admin",
                "--passwort",
                "Speicher-Theisseil-2026",
            ],
        )
        assert ergebnis.exit_code == 0, ergebnis.output
        assert "Nutzer angelegt" in ergebnis.output

        with lese_sitzung() as sitzung:
            nutzer = sitzung.scalar(select(User).where(User.email == "michael@ip3-energie.de"))
            assert nutzer is not None
            assert nutzer.name == "Michael Bäumler"
            assert [r.name for r in nutzer.rollen] == ["admin"]
            assert nutzer.aktiv is True
            assert pw.passt("Speicher-Theisseil-2026", nutzer.pw_hash)

    def test_passwortwechsel_wird_verlangt(self, cli):
        """Das Startpasswort stand auf dem Bildschirm und in der Terminalhistorie."""
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "neu@ip3-energie.de",
                "Neu",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        with lese_sitzung() as sitzung:
            nutzer = sitzung.scalar(select(User).where(User.email == "neu@ip3-energie.de"))
            assert nutzer.muss_passwort_wechseln is True

    def test_kennung_wird_kleingeschrieben(self, cli):
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "Michael@IP3-Energie.de",
                "Michael",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(User).where(User.email == "michael@ip3-energie.de"))

    def test_ohne_passwort_wird_eines_erzeugt(self, cli):
        ergebnis = cli.invoke(
            anwendung, ["nutzer-anlegen", "erzeugt@ip3-energie.de", "Erzeugt", "--rolle", "team"]
        )
        assert ergebnis.exit_code == 0
        assert "Startpasswort:" in ergebnis.output
        # Das erzeugte Passwort steht in der Ausgabe und muss verwendbar sein.
        zeile = next(z for z in ergebnis.output.splitlines() if z.startswith("Startpasswort:"))
        klartext = zeile.split(":", 1)[1].strip()
        with lese_sitzung() as sitzung:
            nutzer = sitzung.scalar(select(User).where(User.email == "erzeugt@ip3-energie.de"))
            assert pw.passt(klartext, nutzer.pw_hash)

    def test_doppelte_kennung_wird_abgewiesen(self, cli):
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "doppelt@ip3-energie.de",
                "Erster",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        ergebnis = cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "doppelt@ip3-energie.de",
                "Zweiter",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        assert ergebnis.exit_code == 1
        assert "bereits einen Nutzer" in ergebnis.output
        assert "passwort-setzen" in ergebnis.output, "Der nächste Schritt fehlt"

    def test_unbekannte_rolle_nennt_die_vorhandenen(self, cli):
        ergebnis = cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "x@ip3-energie.de",
                "X",
                "--rolle",
                "chefetage",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        assert ergebnis.exit_code == 1
        assert "chefetage" in ergebnis.output
        assert "admin" in ergebnis.output
        assert "buchhaltung" in ergebnis.output

    def test_zu_kurzes_passwort_wird_abgewiesen(self, cli):
        ergebnis = cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "kurz@ip3-energie.de",
                "Kurz",
                "--rolle",
                "team",
                "--passwort",
                "kurz",
            ],
        )
        assert ergebnis.exit_code == 1
        assert "zu kurz" in ergebnis.output
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(User).where(User.email == "kurz@ip3-energie.de")) is None

    def test_alle_drei_rollen_sind_vergebbar(self, cli):
        """Der eigentliche Zweck des Befehls: PLAN §4 verlangt drei Rollen."""
        for nummer, rolle in enumerate(("admin", "buchhaltung", "team")):
            ergebnis = cli.invoke(
                anwendung,
                [
                    "nutzer-anlegen",
                    f"person{nummer}@ip3-energie.de",
                    f"Person {nummer}",
                    "--rolle",
                    rolle,
                    "--passwort",
                    "Startpasswort-2026",
                ],
            )
            assert ergebnis.exit_code == 0, ergebnis.output
        with lese_sitzung() as sitzung:
            rollen = {
                nutzer.email: [r.name for r in nutzer.rollen]
                for nutzer in sitzung.scalars(select(User)).all()
            }
        assert rollen["person0@ip3-energie.de"] == ["admin"]
        assert rollen["person1@ip3-energie.de"] == ["buchhaltung"]
        assert rollen["person2@ip3-energie.de"] == ["team"]


class TestDeaktivieren:
    def test_deaktivieren_beendet_offene_sitzungen(self, cli, test_einstellungen):
        """Ein ausgeschiedener Mitarbeiter soll nicht bis zum Ablauf angemeldet bleiben."""
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "geht@ip3-energie.de",
                "Geht",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        from app.sicherheit import sitzungen as sitzungsdienst

        with schreib_sitzung() as sitzung:
            nutzer = sitzung.scalar(select(User).where(User.email == "geht@ip3-energie.de"))
            sitzungsdienst.anlegen(sitzung, nutzer, test_einstellungen.sitzung)
            nutzer_id = nutzer.id

        ergebnis = cli.invoke(anwendung, ["nutzer-deaktivieren", "geht@ip3-energie.de"])
        assert ergebnis.exit_code == 0
        assert "1 offene Sitzung" in ergebnis.output

        with lese_sitzung() as sitzung:
            assert sitzung.get(User, nutzer_id).aktiv is False
            offen = sitzung.scalars(
                select(Sitzung).where(Sitzung.user_id == nutzer_id, Sitzung.beendet_am.is_(None))
            ).all()
            assert offen == []

    def test_wieder_freigeben(self, cli):
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "pause@ip3-energie.de",
                "Pause",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        cli.invoke(anwendung, ["nutzer-deaktivieren", "pause@ip3-energie.de"])
        ergebnis = cli.invoke(
            anwendung, ["nutzer-deaktivieren", "pause@ip3-energie.de", "--aktivieren"]
        )
        assert ergebnis.exit_code == 0
        assert "wieder freigegeben" in ergebnis.output
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(User).where(User.email == "pause@ip3-energie.de")).aktiv

    def test_nutzer_wird_nie_geloescht(self, cli):
        """PLAN §5: das Änderungsprotokoll verweist auf Nutzer."""
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "bleibt@ip3-energie.de",
                "Bleibt",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        cli.invoke(anwendung, ["nutzer-deaktivieren", "bleibt@ip3-energie.de"])
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(User).where(User.email == "bleibt@ip3-energie.de"))

    def test_unbekannter_nutzer_nennt_den_naechsten_schritt(self, cli):
        ergebnis = cli.invoke(anwendung, ["nutzer-deaktivieren", "niemand@ip3-energie.de"])
        assert ergebnis.exit_code == 1
        assert "nutzer-liste" in ergebnis.output


class TestPasswortSetzen:
    def test_passwort_wird_ersetzt_und_wechsel_verlangt(self, cli):
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "reset@ip3-energie.de",
                "Reset",
                "--rolle",
                "team",
                "--passwort",
                "Altes-Passwort-2026",
            ],
        )
        ergebnis = cli.invoke(
            anwendung,
            ["passwort-setzen", "reset@ip3-energie.de", "--passwort", "Neues-Passwort-2026"],
        )
        assert ergebnis.exit_code == 0
        with lese_sitzung() as sitzung:
            nutzer = sitzung.scalar(select(User).where(User.email == "reset@ip3-energie.de"))
            assert pw.passt("Neues-Passwort-2026", nutzer.pw_hash)
            assert not pw.passt("Altes-Passwort-2026", nutzer.pw_hash)
            assert nutzer.muss_passwort_wechseln is True

    def test_unbekannter_nutzer(self, cli):
        ergebnis = cli.invoke(anwendung, ["passwort-setzen", "niemand@ip3-energie.de"])
        assert ergebnis.exit_code == 1
        assert "keinen Nutzer" in ergebnis.output


class TestNutzerListe:
    def test_liste_zeigt_rollen_und_zustand(self, cli):
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "liste@ip3-energie.de",
                "Liste",
                "--rolle",
                "buchhaltung",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        ergebnis = cli.invoke(anwendung, ["nutzer-liste"])
        assert ergebnis.exit_code == 0
        assert "liste@ip3-energie.de" in ergebnis.output
        assert "buchhaltung" in ergebnis.output
        assert "Passwortwechsel offen" in ergebnis.output

    def test_deaktivierte_werden_gekennzeichnet(self, cli):
        cli.invoke(
            anwendung,
            [
                "nutzer-anlegen",
                "weg@ip3-energie.de",
                "Weg",
                "--rolle",
                "team",
                "--passwort",
                "Startpasswort-2026",
            ],
        )
        cli.invoke(anwendung, ["nutzer-deaktivieren", "weg@ip3-energie.de"])
        ergebnis = cli.invoke(anwendung, ["nutzer-liste"])
        assert "deaktiviert" in ergebnis.output


class TestPruefen:
    def test_pruefbefehl_meldet_integritaet_und_schemastand(self, cli, db_pfad):
        """Nach einem Restore der erste Schritt (RUNBOOK, Abschnitt 7)."""
        ergebnis = cli.invoke(anwendung, ["pruefen"])
        assert ergebnis.exit_code == 0
        assert "Integrität: in Ordnung" in ergebnis.output
        assert f"Schemastand: {kopf_der_migrationskette()}" in ergebnis.output
        assert f"Tabellen:  {len(ERWARTETE_TABELLEN)}" in ergebnis.output

    def test_pruefbefehl_bei_fehlender_datei(self, cli, test_einstellungen, tmp_path):
        test_einstellungen.pfade.datenbank = tmp_path / "gibt-es-nicht.sqlite3"
        ergebnis = cli.invoke(anwendung, ["pruefen"])
        assert ergebnis.exit_code == 2
        assert "gibt es nicht" in ergebnis.output
        assert "ip3-leitstand schema" in ergebnis.output


class TestBackupBefehl:
    def test_backup_von_hand(self, cli, test_einstellungen):
        ergebnis = cli.invoke(anwendung, ["backup"])
        assert ergebnis.exit_code == 0
        assert "Integrität:  in Ordnung" in ergebnis.output
        dateien = list(test_einstellungen.pfade.backup.glob("leitstand_*.sqlite3"))
        assert len(dateien) == 1

    def test_backup_ohne_ziel_nennt_den_naechsten_schritt(self, cli, test_einstellungen):
        test_einstellungen.pfade.backup = None
        ergebnis = cli.invoke(anwendung, ["backup"])
        assert ergebnis.exit_code == 2
        assert "kein Backup-Ziel" in ergebnis.output
        assert "config.toml" in ergebnis.output


class TestVersion:
    def test_version_nennt_die_konfigurationsdatei(self, cli):
        ergebnis = cli.invoke(anwendung, ["version"])
        assert ergebnis.exit_code == 0
        assert "ip³ Leitstand" in ergebnis.output
        assert "Konfiguration:" in ergebnis.output


def test_jetzt_utc_ist_verwendbar():
    """Sanity: die Zeitfunktion, auf der die CLI-Ausgaben beruhen."""
    assert jetzt_utc().tzinfo is not None
