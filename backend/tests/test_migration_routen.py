"""API-Routen der Migration (PLAN §7, Phase 1).

Der Schwerpunkt liegt auf zwei Dingen, die die Oberfläche nicht abfangen kann: dass die
Berechtigung serverseitig geprüft wird (CLAUDE.md Regel 2) und dass eine veraltete Vorschau die
Übernahme nicht durchlässt. Letzteres ist keine Förmlichkeit – die Entscheidungen der Maske
verweisen auf Zeilennummern, und eine verschobene Zeile würde 550.000 € dem falschen Projekt
zuschreiben.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung
from app.modelle import Importlauf, Projekt
from tests.bestandsdateien import auftragsliste_bauen, teamliste_bauen
from tests.conftest_auth import anmelden


@pytest.fixture
def quellordner(tmp_path: Path, test_einstellungen) -> Path:
    ordner = tmp_path / "migration-quellen"
    ordner.mkdir()
    auftragsliste_bauen(ordner / "Offene_Auftraege_2025.xlsx")
    teamliste_bauen(ordner / "Teambesprechung_NEU.xlsx")
    test_einstellungen.pfade.migration = ordner
    return ordner


@pytest.fixture
def admin(client, nutzer_erzeugen):
    nutzer_erzeugen("admin-mig@ip3-energie.de", "admin")
    return anmelden(client, "admin-mig@ip3-energie.de")


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen):
    nutzer_erzeugen("buha-mig@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha-mig@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen):
    nutzer_erzeugen("team-mig@ip3-energie.de", "team")
    return anmelden(client, "team-mig@ip3-energie.de")


def _uebernehmen(anmeldung, vorschau: dict, **kw):
    entscheidungen = {
        z["kundenteil"]: (z["vorschlaege"][0]["projekt_zeile"] if z["vorschlaege"] else None)
        for z in vorschau["zuordnungen"]
        if z["offen"]
    }
    koerper = {
        "kennung": vorschau["kennung"],
        "entscheidungen": entscheidungen,
        **kw,
    }
    return anmeldung.schreiben("POST", "/api/migration/uebernehmen", json=koerper)


class TestBerechtigung:
    def test_ohne_anmeldung_401(self, client, quellordner):
        for pfad in ("/api/migration/stand", "/api/migration/vorschau"):
            antwort = client.get(pfad)
            assert antwort.status_code == 401, pfad
            assert antwort.json()["code"]
            assert antwort.json()["meldung"]

    def test_team_darf_nicht_migrieren(self, team, quellordner):
        """PLAN §4: Importe sind Sache von Buchhaltung und Geschäftsführung."""
        antwort = team.client.get("/api/migration/vorschau")
        assert antwort.status_code == 403
        koerper = antwort.json()
        assert koerper["code"]
        assert "Berechtigung" in koerper["meldung"] or "berechtigt" in koerper["meldung"]

    def test_team_darf_nicht_uebernehmen(self, team, quellordner):
        antwort = team.schreiben("POST", "/api/migration/uebernehmen", json={"kennung": "x"})
        assert antwort.status_code == 403
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Projekt).limit(1)) is None

    def test_buchhaltung_darf(self, buchhaltung, quellordner):
        assert buchhaltung.client.get("/api/migration/vorschau").status_code == 200

    def test_ohne_csrf_token_kein_schreiben(self, admin, quellordner):
        antwort = admin.client.post("/api/migration/uebernehmen", json={"kennung": "x"})
        assert antwort.status_code == 403


class TestStand:
    def test_vor_der_migration(self, admin, quellordner):
        antwort = admin.client.get("/api/migration/stand")
        assert antwort.status_code == 200
        assert antwort.json() == {
            "migriert": False,
            "importlauf_id": None,
            "status": None,
            "gestartet": None,
            "beendet": None,
            "dateien": None,
            "ergebnis": None,
        }

    def test_nach_der_migration(self, admin, quellordner):
        vorschau = admin.client.get("/api/migration/vorschau").json()
        assert _uebernehmen(admin, vorschau).status_code == 200
        stand = admin.client.get("/api/migration/stand").json()
        assert stand["migriert"] is True
        assert stand["status"] in ("erfolg", "warnung")
        assert "Offene_Auftraege" in stand["dateien"]
        assert stand["ergebnis"]["kontrollsummen"]["teamliste"]["projekte"] == 12


class TestVorschau:
    def test_kontrollsummen_und_zuordnungen(self, admin, quellordner):
        koerper = admin.client.get("/api/migration/vorschau").json()
        assert koerper["kennung"]
        assert koerper["kontrollsummen"]["auftragsliste"]["zeilen"] > 0
        assert koerper["zuordnungen"]
        assert koerper["kandidaten"]
        # Für die Maske: jede Zuordnung sagt, ob sie eine Entscheidung braucht.
        assert any(z["offen"] for z in koerper["zuordnungen"])
        assert any(not z["offen"] for z in koerper["zuordnungen"])

    def test_kandidaten_tragen_was_zur_unterscheidung_noetig_ist(self, admin, quellordner):
        """Zwei Projekte desselben Kunden unterscheiden sich nur über Leistung und Datum."""
        kandidaten = admin.client.get("/api/migration/vorschau").json()["kandidaten"]
        huber = [k for k in kandidaten if k["kunde"].startswith("Huber")]
        assert len(huber) == 2
        assert huber[0]["pv_kwp"] != huber[1]["pv_kwp"]
        assert all(k["auftrag_vom"] or k["ab_wert_netto"] for k in huber)

    def test_befunde_kommen_mit(self, admin, quellordner):
        befunde = admin.client.get("/api/migration/vorschau").json()["befunde"]
        assert befunde
        assert {b["schwere"] for b in befunde} <= {"warnung", "hinweis"}
        assert all(b["zeile"] and b["spalte"] for b in befunde)

    def test_ohne_eingerichteten_ordner_deutscher_hinweis(self, admin, test_einstellungen):
        test_einstellungen.pfade.migration = None
        antwort = admin.client.get("/api/migration/vorschau")
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "migration_pfad_fehlt"
        assert "[pfade]" in koerper["naechster_schritt"]
        assert "migration" in koerper["naechster_schritt"]

    def test_fehlende_datei_nennt_die_vorhandenen(self, admin, test_einstellungen, tmp_path):
        ordner = tmp_path / "halb"
        ordner.mkdir()
        teamliste_bauen(ordner / "Teambesprechung_NEU.xlsx")
        test_einstellungen.pfade.migration = ordner
        antwort = admin.client.get("/api/migration/vorschau")
        assert antwort.status_code == 400
        assert "Teambesprechung_NEU.xlsx" in antwort.json()["naechster_schritt"]


class TestUebernahme:
    def test_uebernahme_schreibt_und_meldet(self, admin, quellordner):
        vorschau = admin.client.get("/api/migration/vorschau").json()
        antwort = _uebernehmen(admin, vorschau)
        assert antwort.status_code == 200, antwort.text
        koerper = antwort.json()
        assert koerper["projekte"] >= 12
        assert koerper["kunden"] > 0
        assert koerper["zahlungsplan"] > 0
        assert koerper["importlauf_id"]
        assert "übernommen" in koerper["meldung"]
        with lese_sitzung() as sitzung:
            assert len(list(sitzung.scalars(select(Projekt)))) == koerper["projekte"]

    def test_geaenderte_dateien_werden_abgewiesen(self, admin, quellordner):
        """Der wichtigste Schutz: eine veraltete Vorschau darf nicht angewendet werden.

        Die Entscheidungen verweisen auf Zeilennummern der Teamliste. Verschiebt sich eine
        Zeile, würde der Betrag am falschen Projekt landen.
        """
        vorschau = admin.client.get("/api/migration/vorschau").json()
        # Datei ändern: eine Zeile mehr verschiebt alles darunter.
        from openpyxl import load_workbook

        pfad = quellordner / "Teambesprechung_NEU.xlsx"
        mappe = load_workbook(pfad)
        mappe.active.insert_rows(9)
        mappe.active["B9"] = "Neuer Kunde, Neustadt"
        mappe.save(pfad)

        antwort = _uebernehmen(admin, vorschau)
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "migration_dateien_geaendert"
        assert "Vorschau neu laden" in koerper["naechster_schritt"]
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Projekt).limit(1)) is None

    def test_offene_zuordnungen_werden_abgewiesen(self, admin, quellordner):
        vorschau = admin.client.get("/api/migration/vorschau").json()
        antwort = admin.schreiben(
            "POST",
            "/api/migration/uebernehmen",
            json={"kennung": vorschau["kennung"], "entscheidungen": {}},
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "migration_zuordnung_offen"
        assert "Zuordnungsmaske" in antwort.json()["naechster_schritt"]

    def test_unbekannter_kunde_in_den_entscheidungen(self, admin, quellordner):
        """Ein Tippfehler in der Maske darf nicht als Erfolg durchgehen."""
        vorschau = admin.client.get("/api/migration/vorschau").json()
        antwort = admin.schreiben(
            "POST",
            "/api/migration/uebernehmen",
            json={
                "kennung": vorschau["kennung"],
                "entscheidungen": {"Gibt es nicht, Nirgendwo": 8},
            },
        )
        # Kein Stacktrace, sondern eine Meldung mit nächstem Schritt.
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "migration_kunde_unbekannt"
        assert "Gibt es nicht" in koerper["meldung"]
        assert "neu laden" in koerper["naechster_schritt"]

    def test_zweiter_lauf_wird_abgewiesen(self, admin, quellordner):
        vorschau = admin.client.get("/api/migration/vorschau").json()
        assert _uebernehmen(admin, vorschau).status_code == 200
        zweite = admin.client.get("/api/migration/vorschau").json()
        antwort = _uebernehmen(admin, zweite)
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "migration_bereits_gelaufen"
        with lese_sitzung() as sitzung:
            assert len(list(sitzung.scalars(select(Importlauf)))) == 1

    def test_uebernahme_steht_im_aenderungsprotokoll(self, admin, quellordner):
        """CLAUDE.md Regel 7: jede schreibende Aktion ins audit_log."""
        from app.modelle import AuditEintrag

        vorschau = admin.client.get("/api/migration/vorschau").json()
        assert _uebernehmen(admin, vorschau).status_code == 200
        with lese_sitzung() as sitzung:
            eintraege = list(
                sitzung.scalars(
                    select(AuditEintrag).where(AuditEintrag.aktion == "migration.uebernommen")
                )
            )
        assert len(eintraege) == 1
        assert eintraege[0].user_id is not None
        assert "Offene_Auftraege" in str(eintraege[0].neu)
