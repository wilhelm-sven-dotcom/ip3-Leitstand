"""Systemstatus (PLAN §2: „stille Job-Ausfälle darf es nicht geben", §7)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.datenbank import schreib_sitzung
from app.jobs import katalog
from app.modelle import JobLauf
from app.zeit import jetzt_utc
from tests.conftest_auth import anmelden


@pytest.fixture
def admin(nutzer_erzeugen) -> int:
    return nutzer_erzeugen("chef@ip3-energie.de", "admin", name="Sven Wilhelm")


@pytest.fixture
def teammitglied(nutzer_erzeugen) -> int:
    return nutzer_erzeugen("monteur@ip3-energie.de", "team", name="Monteur")


def _lauf_anlegen(job: str, status: str, vor_stunden: float = 1, meldung: str = "Testlauf") -> None:
    zeitpunkt = jetzt_utc() - timedelta(hours=vor_stunden)
    with schreib_sitzung() as sitzung:
        sitzung.add(
            JobLauf(
                job=job,
                gestartet=zeitpunkt,
                beendet=zeitpunkt + timedelta(seconds=3),
                status=status,
                ausgeloest_von="zeitplan",
                meldung=meldung,
                dauer_ms=3000,
            )
        )


class TestKatalog:
    def test_jeder_eintrag_ist_vollstaendig(self):
        for eintrag in katalog.KATALOG:
            assert eintrag.schluessel
            assert eintrag.bezeichnung
            assert eintrag.beschreibung
            assert eintrag.max_alter_stunden > 0
            assert eintrag.ab_phase >= 0

    def test_backup_gibt_es_in_phase_null(self):
        assert katalog.ist_eingerichtet(katalog.definition("backup"))

    def test_jobs_dieser_phase_sind_eingerichtet(self):
        for schluessel in ("backup", "datev_import", "timetac_sync", "kalkulation_scan"):
            assert katalog.ist_eingerichtet(katalog.definition(schluessel))

    def test_spaetere_jobs_sind_noch_nicht_eingerichtet(self):
        # Die Fristenprüfung kommt mit Phase 6.
        assert not katalog.ist_eingerichtet(katalog.definition("fristen"))

    def test_unbekannter_job_nennt_die_bekannten(self):
        with pytest.raises(KeyError) as fehler:
            katalog.definition("gibt-es-nicht")
        assert "backup" in str(fehler.value)
        assert "app/jobs/katalog.py" in str(fehler.value)


class TestStatusZustaende:
    def test_nie_gelaufen(self, client: TestClient, admin):
        anmelden(client, "chef@ip3-energie.de")
        antwort = client.get("/api/systemstatus")
        assert antwort.status_code == 200
        backup = next(j for j in antwort.json()["jobs"] if j["schluessel"] == "backup")
        assert backup["status"] == "unbekannt"
        assert backup["text"] == "noch nie gelaufen"
        assert backup["letzter_lauf"] is None

    def test_frischer_erfolg_ist_ok(self, client: TestClient, admin):
        _lauf_anlegen("backup", "erfolg", vor_stunden=2)
        anmelden(client, "chef@ip3-energie.de")
        backup = next(
            j for j in client.get("/api/systemstatus").json()["jobs"] if j["schluessel"] == "backup"
        )
        assert backup["status"] == "ok"
        assert backup["text"] == "vor 2 Stunden"
        assert backup["alter_stunden"] == pytest.approx(2.0, abs=0.1)

    def test_zu_alter_erfolg_warnt(self, client: TestClient, admin):
        """Grenze für die Sicherung: 26 Stunden (config). 40 Stunden sind zu viel."""
        _lauf_anlegen("backup", "erfolg", vor_stunden=40)
        anmelden(client, "chef@ip3-energie.de")
        backup = next(
            j for j in client.get("/api/systemstatus").json()["jobs"] if j["schluessel"] == "backup"
        )
        assert backup["status"] == "warnung"
        assert "länger her" in backup["text"]
        assert "vor 1 Tag" in backup["text"]

    def test_fehlgeschlagener_lauf_ergibt_fehler(self, client: TestClient, admin):
        _lauf_anlegen("backup", "fehler", vor_stunden=1, meldung="Zielordner nicht erreichbar")
        anmelden(client, "chef@ip3-energie.de")
        koerper = client.get("/api/systemstatus").json()
        backup = next(j for j in koerper["jobs"] if j["schluessel"] == "backup")
        assert backup["status"] == "fehler"
        assert backup["meldung"] == "Zielordner nicht erreichbar"
        assert koerper["gesamtstatus"] == "fehler"

    def test_lauf_mit_warnung(self, client: TestClient, admin):
        _lauf_anlegen("backup", "warnung", vor_stunden=1, meldung="Integritätsprüfung fehlerhaft")
        anmelden(client, "chef@ip3-energie.de")
        backup = next(
            j for j in client.get("/api/systemstatus").json()["jobs"] if j["schluessel"] == "backup"
        )
        assert backup["status"] == "warnung"

    def test_fehler_nach_altem_erfolg_bleibt_fehler(self, client: TestClient, admin):
        """Ein alter Erfolg darf einen aktuellen Fehler nicht verdecken."""
        _lauf_anlegen("backup", "erfolg", vor_stunden=30)
        _lauf_anlegen("backup", "fehler", vor_stunden=2)
        anmelden(client, "chef@ip3-energie.de")
        backup = next(
            j for j in client.get("/api/systemstatus").json()["jobs"] if j["schluessel"] == "backup"
        )
        assert backup["status"] == "fehler"

    def test_alter_wird_in_worten_ausgegeben(self, client: TestClient, admin):
        _lauf_anlegen("backup", "erfolg", vor_stunden=0.25)
        anmelden(client, "chef@ip3-energie.de")
        backup = next(
            j for j in client.get("/api/systemstatus").json()["jobs"] if j["schluessel"] == "backup"
        )
        assert "Minuten" in backup["text"]


class TestAlleJobsSindSichtbar:
    def test_auch_die_spaeteren_jobs_erscheinen(self, client: TestClient, admin):
        """PLAN §2: Es soll von Anfang an sichtbar sein, welche Datenquellen es gibt."""
        anmelden(client, "chef@ip3-energie.de")
        jobs = client.get("/api/systemstatus").json()["jobs"]
        schluessel = {j["schluessel"] for j in jobs}
        assert schluessel == set(katalog.SCHLUESSEL)

    def test_spaetere_jobs_nennen_ihre_phase(self, client: TestClient, admin):
        anmelden(client, "chef@ip3-energie.de")
        jobs = client.get("/api/systemstatus").json()["jobs"]
        fristen = next(j for j in jobs if j["schluessel"] == "fristen")
        assert fristen["eingerichtet"] is False
        assert fristen["ab_phase"] == 6
        assert "ab Phase 6" in fristen["text"]

    def test_jobs_dieser_phase_gelten_als_eingerichtet(self, client: TestClient, admin):
        anmelden(client, "chef@ip3-energie.de")
        jobs = client.get("/api/systemstatus").json()["jobs"]
        datev = next(j for j in jobs if j["schluessel"] == "datev_import")
        assert datev["eingerichtet"] is True

    def test_spaetere_jobs_faerben_den_gesamtstatus_nicht_rot(
        self, client: TestClient, admin, test_einstellungen, tmp_path
    ):
        """Sonst stünde die Startseite dauerhaft auf Alarm, bis Phase 6 fertig ist."""
        test_einstellungen.firma.strasse = "Industriestraße 1"
        test_einstellungen.firma.plz = "92637"
        test_einstellungen.firma.ust_id = "DE123456789"
        test_einstellungen.firma.st_nr = "255/123/45678"
        test_einstellungen.firma.hrb = "HRB 12345"
        test_einstellungen.firma.geschaeftsfuehrer = "Sven Wilhelm"
        test_einstellungen.firma.bank.iban = "DE02120300000000202051"
        test_einstellungen.pfade.rechnungen = tmp_path / "01_Rechnungen"
        test_einstellungen.pfade.datev = tmp_path / "02_DATEV"
        test_einstellungen.pfade.kalkulation = tmp_path / "03_Kalkulation"
        test_einstellungen.timetac.aktiv = False
        for job in ("backup", "datev_import", "timetac_sync", "kalkulation_scan"):
            _lauf_anlegen(job, "erfolg", vor_stunden=2)

        anmelden(client, "chef@ip3-energie.de")
        koerper = client.get("/api/systemstatus").json()
        assert koerper["gesamtstatus"] == "ok"
        assert koerper["hinweise"] == []


class TestKonfigurationshinweise:
    def test_unvollstaendige_firmenstammdaten_erscheinen_als_hinweis(
        self, client: TestClient, admin
    ):
        _lauf_anlegen("backup", "erfolg", vor_stunden=1)
        anmelden(client, "chef@ip3-energie.de")
        koerper = client.get("/api/systemstatus").json()
        assert any("Firmenstammdaten" in h for h in koerper["hinweise"])
        assert koerper["gesamtstatus"] == "warnung"

    def test_fehlendes_backupziel_erscheint_als_hinweis(
        self, client: TestClient, admin, test_einstellungen
    ):
        """Der häufigste Grund dafür, dass gar nichts läuft."""
        test_einstellungen.pfade.backup = None
        anmelden(client, "chef@ip3-energie.de")
        koerper = client.get("/api/systemstatus").json()
        assert any("Backup-Ziel" in h for h in koerper["hinweise"])


class TestBerechtigungen:
    def test_ohne_anmeldung_401(self, client: TestClient, admin):
        assert client.get("/api/systemstatus").status_code == 401

    def test_team_darf_den_datenstand_sehen(self, client: TestClient, teammitglied):
        """Die Startseite zeigt den Datenstand allen – ein ausgefallener Job betrifft alle."""
        anmelden(client, "monteur@ip3-energie.de")
        assert client.get("/api/systemstatus").status_code == 200

    def test_ohne_die_berechtigung_403(self, client: TestClient, nutzer_erzeugen, gesäte_db):
        from sqlalchemy import select

        from app.modelle import Rolle, User

        nutzer_erzeugen("ohne@ip3-energie.de", "team")
        with schreib_sitzung() as sitzung:
            nutzer = sitzung.scalar(select(User).where(User.email == "ohne@ip3-energie.de"))
            rolle = sitzung.scalar(select(Rolle).where(Rolle.name == "team"))
            nutzer.rollen.remove(rolle)

        anmelden(client, "ohne@ip3-energie.de")
        antwort = client.get("/api/systemstatus")
        assert antwort.status_code == 403
        assert antwort.json()["code"] == "keine_berechtigung"


class TestJobVonHandStarten:
    def test_admin_kann_die_sicherung_ausloesen(self, client: TestClient, admin):
        angemeldet = anmelden(client, "chef@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/systemstatus/jobs/backup/starten")
        assert antwort.status_code == 200
        assert antwort.json()["gestartet"] is True

        # Der Lauf steht danach im Systemstatus.
        backup = next(
            j for j in client.get("/api/systemstatus").json()["jobs"] if j["schluessel"] == "backup"
        )
        assert backup["status"] == "ok"
        assert "Sicherung" in backup["meldung"]

    def test_manueller_start_wird_als_solcher_vermerkt(self, client: TestClient, admin):
        from sqlalchemy import select

        angemeldet = anmelden(client, "chef@ip3-energie.de")
        angemeldet.schreiben("POST", "/api/systemstatus/jobs/backup/starten")
        with schreib_sitzung() as sitzung:
            lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "backup"))
            assert lauf.ausgeloest_von == "manuell"

    def test_manueller_start_wird_protokolliert(self, client: TestClient, admin):
        from sqlalchemy import select

        from app.modelle import AuditEintrag

        angemeldet = anmelden(client, "chef@ip3-energie.de")
        angemeldet.schreiben("POST", "/api/systemstatus/jobs/backup/starten")
        with schreib_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "job.manuell_gestartet")
            )
            assert eintrag is not None
            assert eintrag.neu["job"] == "backup"

    def test_team_darf_keinen_job_starten(self, client: TestClient, teammitglied):
        angemeldet = anmelden(client, "monteur@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/systemstatus/jobs/backup/starten")
        assert antwort.status_code == 403

    def test_unbekannter_job_404_mit_hinweis(self, client: TestClient, admin):
        angemeldet = anmelden(client, "chef@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/systemstatus/jobs/erfunden/starten")
        assert antwort.status_code == 404
        assert "erfunden" in antwort.json()["meldung"]

    def test_noch_nicht_eingerichteter_job_409(self, client: TestClient, admin):
        angemeldet = anmelden(client, "chef@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/systemstatus/jobs/fristen/starten")
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "job_nicht_eingerichtet"
        assert "Phase 6" in koerper["meldung"]

    def test_importlauf_ohne_eingerichteten_ordner_warnt_statt_zu_scheitern(
        self, client: TestClient, admin, test_einstellungen
    ):
        """Ein fehlender Ordner ist ein Einrichtungsmangel, kein Absturz."""
        test_einstellungen.pfade.datev = None
        angemeldet = anmelden(client, "chef@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/systemstatus/jobs/datev_import/starten")
        assert antwort.status_code == 200
        assert antwort.json()["gestartet"] is True

        jobs = client.get("/api/systemstatus").json()["jobs"]
        datev = next(j for j in jobs if j["schluessel"] == "datev_import")
        assert datev["status"] == "warnung"
        assert "02_DATEV" in datev["meldung"], "die Meldung sagt, was einzurichten ist"


class TestZeitplan:
    def test_im_test_laeuft_kein_zeitplan(self, client: TestClient, admin):
        """Sonst würde jeder Testlauf einen Zeitplan starten und möglicherweise sichern."""
        anmelden(client, "chef@ip3-energie.de")
        assert client.get("/api/systemstatus").json()["zeitplan_laeuft"] is False

    def test_zeitplan_startet_mit_backupziel(self, test_einstellungen, gesäte_db):
        from app.jobs import scheduler

        try:
            ergebnis = scheduler.starten(test_einstellungen)
            assert ergebnis is not None
            zustand = scheduler.zustand()
            assert zustand["laeuft"] is True
            assert zustand["naechster_lauf"] is not None
        finally:
            scheduler.beenden()

    def test_ohne_jede_voraussetzung_kein_zeitplan(self, test_einstellungen, gesäte_db, caplog):
        from app.jobs import scheduler

        test_einstellungen.pfade.backup = None
        test_einstellungen.pfade.datev = None
        test_einstellungen.pfade.kalkulation = None
        test_einstellungen.timetac.aktiv = False
        try:
            with caplog.at_level("WARNING"):
                assert scheduler.starten(test_einstellungen) is None
            assert "Kein Hintergrundlauf ist eingerichtet" in caplog.text
        finally:
            scheduler.beenden()

    def test_ohne_backupziel_laufen_die_uebrigen_trotzdem(
        self, test_einstellungen, gesäte_db, tmp_path, caplog
    ):
        """Ein Haus ohne Backup-Ordner soll trotzdem nachts seine Stunden holen."""
        from app.jobs import scheduler

        test_einstellungen.pfade.backup = None
        test_einstellungen.pfade.datev = tmp_path / "02_DATEV"
        try:
            with caplog.at_level("WARNING"):
                assert scheduler.starten(test_einstellungen) is not None
            assert "backup ist nicht gesetzt" in caplog.text
        finally:
            scheduler.beenden()

    def test_warnung_bei_mehreren_arbeitsprozessen(
        self, test_einstellungen, gesäte_db, monkeypatch, caplog
    ):
        """Mit mehreren Prozessen laufen die nächtlichen Jobs mehrfach."""
        from app.jobs import scheduler

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        try:
            with caplog.at_level("WARNING"):
                scheduler.starten(test_einstellungen)
            assert "Arbeitsprozesse" in caplog.text
            assert "doppelte Sicherungen" in caplog.text
        finally:
            scheduler.beenden()
