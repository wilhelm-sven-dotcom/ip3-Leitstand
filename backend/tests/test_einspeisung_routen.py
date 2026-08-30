"""Routen für eigene Anlagen, Vergütung und Unterlagen (PLAN §4, §7 Phase 7).

Der Schwerpunkt liegt auf den Rechten: eigene Erlöse sind dem Team entzogen (PLAN §4), der
Befund über einen Projektordner nicht – er ist Projektsicht und kein Betrag.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import EigeneAnlage, EinspeiseAbrechnung, Firma, Kunde, Projekt
from tests.conftest_auth import anmelden


@pytest.fixture
def admin(client, nutzer_erzeugen, vollstaendige_firma):
    nutzer_erzeugen("chef@ip3-energie.de", "admin", name="Sven Wilhelm")
    return anmelden(client, "chef@ip3-energie.de")


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen, vollstaendige_firma):
    nutzer_erzeugen("buha@ip3-energie.de", "buchhaltung", name="Buchhaltung")
    return anmelden(client, "buha@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen, vollstaendige_firma):
    nutzer_erzeugen("monteur@ip3-energie.de", "team", name="Monteur")
    return anmelden(client, "monteur@ip3-energie.de")


def _anlage(bezeichnung: str = "Halle Süd", **felder) -> int:
    with schreib_sitzung() as sitzung:
        anlage = EigeneAnlage(bezeichnung=bezeichnung, **felder)
        sitzung.add(anlage)
        sitzung.flush()
        return anlage.id


def _projekt(nummer: int) -> int:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
        if kunde_id is None:
            kunde = Kunde(kunden_nr=80001, name="Ordnerkunde", ort="Weiden", typ="b2b")
            sitzung.add(kunde)
            sitzung.flush()
            kunde_id = kunde.id
        projekt = Projekt(
            firma_id=firma_id,
            kunde_id=kunde_id,
            projekt_nr=nummer,
            bezeichnung=f"Projekt {nummer}",
            status="in_bau",
        )
        sitzung.add(projekt)
        sitzung.flush()
        return projekt.id


# ------------------------------------------------------------------------------------------
# Rechte
# ------------------------------------------------------------------------------------------


class TestBerechtigungen:
    def test_team_sieht_keine_eigenen_erloese(self, team):
        """PLAN §4: Beträge sind von der Projektsicht getrennt."""
        assert team.client.get("/api/einspeisung").status_code == 403
        assert team.client.get("/api/eigene-anlagen").status_code == 403

    def test_team_darf_keine_anlage_anlegen(self, team):
        antwort = team.schreiben("POST", "/api/eigene-anlagen", json={"bezeichnung": "Test"})
        assert antwort.status_code == 403

    def test_buchhaltung_darf_lesen_und_pflegen(self, buchhaltung):
        """Sie verarbeitet die Abrechnungen des Netzbetreibers (Entscheidung 53)."""
        assert buchhaltung.client.get("/api/einspeisung").status_code == 200
        antwort = buchhaltung.schreiben(
            "POST", "/api/eigene-anlagen", json={"bezeichnung": "Halle Süd"}
        )
        assert antwort.status_code == 201, antwort.text

    def test_team_darf_die_unterlagen_sehen(self, team):
        """Der Befund über einen Projektordner ist Projektsicht, kein Betrag."""
        assert team.client.get("/api/unterlagen").status_code == 200

    def test_team_darf_nicht_scannen(self, team):
        """Ein Scan von Hand ist ein Lauf über das Dateisystem."""
        antwort = team.schreiben("POST", "/api/unterlagen/scannen", json={})
        assert antwort.status_code == 403


# ------------------------------------------------------------------------------------------
# Eigene Anlagen
# ------------------------------------------------------------------------------------------


class TestAnlagen:
    def test_anlegen_und_lesen(self, admin):
        antwort = admin.schreiben(
            "POST",
            "/api/eigene-anlagen",
            json={
                "bezeichnung": "Halle Süd",
                "verguetungsart": "einspeisung",
                "verguetung_ct_kwh": 8.11,
                "zaehler_nr": "1ESY0012345",
                "inbetriebnahme": "2026-05-01",
            },
        )
        assert antwort.status_code == 201, antwort.text
        angelegt = antwort.json()
        assert angelegt["verguetung_ct_kwh"] == 8.11

        liste = admin.client.get("/api/eigene-anlagen").json()
        assert [a["bezeichnung"] for a in liste] == ["Halle Süd"]

    def test_doppelte_bezeichnung_wird_abgewiesen(self, admin):
        """Die Bezeichnung dient auch der Zuordnung der Abrechnungen."""
        admin.schreiben("POST", "/api/eigene-anlagen", json={"bezeichnung": "Halle Süd"})
        antwort = admin.schreiben("POST", "/api/eigene-anlagen", json={"bezeichnung": "Halle Süd"})
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "anlage_doppelt"

    def test_unbekannte_verguetungsart_nennt_die_erlaubten(self, admin):
        antwort = admin.schreiben(
            "POST",
            "/api/eigene-anlagen",
            json={"bezeichnung": "Test", "verguetungsart": "eigenverbrauch"},
        )
        assert antwort.status_code == 422
        assert "direktvermarktung" in antwort.text

    def test_aendern_mit_veraltetem_stand_ergibt_einen_konflikt(self, admin):
        angelegt = admin.schreiben(
            "POST", "/api/eigene-anlagen", json={"bezeichnung": "Halle Süd"}
        ).json()
        admin.schreiben(
            "PUT",
            f"/api/eigene-anlagen/{angelegt['id']}",
            json={"bezeichnung": "Halle Nord", "stand": angelegt["stand"]},
        )
        # Zweiter Versuch mit demselben, inzwischen veralteten Stand.
        antwort = admin.schreiben(
            "PUT",
            f"/api/eigene-anlagen/{angelegt['id']}",
            json={"bezeichnung": "Halle West", "stand": angelegt["stand"]},
        )
        assert antwort.status_code == 409

    def test_stilllegen_statt_loeschen(self, admin):
        """Nichts löschen, was Bezüge hat (CLAUDE.md Regel 5)."""
        angelegt = admin.schreiben(
            "POST", "/api/eigene-anlagen", json={"bezeichnung": "Alt"}
        ).json()
        antwort = admin.schreiben(
            "PUT",
            f"/api/eigene-anlagen/{angelegt['id']}",
            json={"bezeichnung": "Alt", "aktiv": False, "stand": angelegt["stand"]},
        )
        assert antwort.status_code == 200
        assert antwort.json()["aktiv"] is False
        assert admin.client.get("/api/eigene-anlagen?nur_aktive=true").json() == []


# ------------------------------------------------------------------------------------------
# Abrechnungen
# ------------------------------------------------------------------------------------------


class TestAbrechnungen:
    def test_erfassen_und_im_bild_wiederfinden(self, admin):
        anlage_id = _anlage(verguetungsart="einspeisung", verguetung_ct_kwh=Decimal("8.00"))
        antwort = admin.schreiben(
            "PUT",
            f"/api/eigene-anlagen/{anlage_id}/abrechnungen",
            json={"monat": "2026-07", "kwh": 10000, "betrag_cent": 80000},
        )
        assert antwort.status_code == 200, antwort.text

        bild = admin.client.get("/api/einspeisung?bis=2026-07").json()
        teil = bild["anlagen"][0]
        assert teil["erwartet_cent"] == 80000
        assert teil["abgerechnet_cent"] == 80000
        assert teil["monate"][0]["abweichung_cent"] == 0
        assert bild["einordnung"].startswith("Kontrollrechnung")

    def test_derselbe_monat_wird_aktualisiert_nicht_verdoppelt(self, admin):
        anlage_id = _anlage()
        pfad = f"/api/eigene-anlagen/{anlage_id}/abrechnungen"
        erst = admin.schreiben(
            "PUT", pfad, json={"monat": "2026-07", "kwh": 100, "betrag_cent": 800}
        ).json()
        admin.schreiben(
            "PUT",
            pfad,
            json={"monat": "2026-07", "kwh": 120, "betrag_cent": 960, "stand": erst["stand"]},
        )

        with lese_sitzung() as sitzung:
            zeilen = sitzung.execute(select(EinspeiseAbrechnung)).scalars().all()
        assert len(zeilen) == 1
        assert zeilen[0].betrag_cent == 960

    def test_zahlungseingang_vermerken(self, admin):
        anlage_id = _anlage()
        pfad = f"/api/eigene-anlagen/{anlage_id}/abrechnungen"
        erst = admin.schreiben(
            "PUT", pfad, json={"monat": "2026-07", "kwh": 100, "betrag_cent": 800}
        ).json()
        assert erst["bezahlt_am"] is None

        antwort = admin.schreiben(
            "PUT",
            pfad,
            json={
                "monat": "2026-07",
                "kwh": 100,
                "betrag_cent": 800,
                "bezahlt_am": "2026-08-20",
                "stand": erst["stand"],
            },
        )
        assert antwort.json()["bezahlt_am"] == "2026-08-20"

    def test_unlesbarer_monat_wird_abgewiesen(self, admin):
        anlage_id = _anlage()
        antwort = admin.schreiben(
            "PUT",
            f"/api/eigene-anlagen/{anlage_id}/abrechnungen",
            json={"monat": "Juli 2026", "kwh": 100, "betrag_cent": 800},
        )
        assert antwort.status_code == 422
        assert "JJJJ-MM" in antwort.text

    def test_unbekannte_anlage_ergibt_404(self, admin):
        antwort = admin.schreiben(
            "PUT",
            "/api/eigene-anlagen/9999/abrechnungen",
            json={"monat": "2026-07", "kwh": 100, "betrag_cent": 800},
        )
        assert antwort.status_code == 404

    def test_ungueltiger_monatsfilter_nennt_das_format(self, admin):
        antwort = admin.client.get("/api/einspeisung?bis=Juli")
        assert antwort.status_code == 409
        assert "JJJJ-MM" in antwort.json()["meldung"]


# ------------------------------------------------------------------------------------------
# Unterlagen
# ------------------------------------------------------------------------------------------


class TestUnterlagen:
    def test_ohne_scan_steht_nie_geprueft_da(self, admin):
        _projekt(26201)
        koerper = admin.client.get("/api/unterlagen").json()
        assert koerper["gesamt"] == 1
        assert koerper["nie_geprueft"] == 1
        # Nie geprüft heißt: es fehlt nichts, es ist nur nichts bekannt.
        assert koerper["ordner"][0]["fehlende_pflicht"] == []
        assert koerper["einordnung"].startswith("Der Scan sieht nur Dateinamen")

    def test_scan_von_hand_ohne_konfigurierten_ordner(self, admin):
        antwort = admin.schreiben("POST", "/api/unterlagen/scannen", json={})
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "projektordner_fehlt"
        assert "config.toml" in koerper["naechster_schritt"]

    def test_scan_von_hand_findet_und_meldet(self, admin, test_einstellungen, tmp_path: Path):
        projekt_id = _projekt(26202)
        wurzel = tmp_path / "projekte"
        (wurzel / "26202").mkdir(parents=True)
        (wurzel / "26202" / "Anlagendokumentation.pdf").write_text("x")
        test_einstellungen.pfade.projekte = wurzel

        antwort = admin.schreiben("POST", "/api/unterlagen/scannen", json={})

        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["mit_ordner"] == 1
        assert antwort.json()["unvollstaendig"] == 0

        koerper = admin.client.get("/api/unterlagen").json()
        zeile = next(o for o in koerper["ordner"] if o["projekt_id"] == projekt_id)
        assert zeile["gefunden"] is True
        assert zeile["fehlende_pflicht"] == []
        # Die deutsche Bezeichnung steht dabei, nicht nur der Schlüssel.
        namen = {u["bezeichnung"] for u in zeile["unterlagen"]}
        assert "Anlagendokumentation" in namen

    def test_filter_auf_unvollstaendige(self, admin, test_einstellungen, tmp_path: Path):
        _projekt(26203)
        _projekt(26204)
        wurzel = tmp_path / "projekte"
        (wurzel / "26203").mkdir(parents=True)
        (wurzel / "26203" / "Anlagendokumentation.pdf").write_text("x")
        (wurzel / "26204").mkdir(parents=True)
        test_einstellungen.pfade.projekte = wurzel
        admin.schreiben("POST", "/api/unterlagen/scannen", json={})

        koerper = admin.client.get("/api/unterlagen?nur_unvollstaendig=true").json()

        assert [o["projekt_nr"] for o in koerper["ordner"]] == [26204]
        assert koerper["ordner"][0]["fehlende_pflicht"] == ["anlagendoku"]

    def test_scan_steht_im_aenderungsprotokoll(self, admin, test_einstellungen, tmp_path: Path):
        from app.modelle import AuditEintrag

        _projekt(26205)
        wurzel = tmp_path / "projekte"
        wurzel.mkdir()
        test_einstellungen.pfade.projekte = wurzel
        admin.schreiben("POST", "/api/unterlagen/scannen", json={})

        with lese_sitzung() as sitzung:
            eintrag = sitzung.execute(
                select(AuditEintrag)
                .where(AuditEintrag.aktion == "unterlagen.gescannt")
                .order_by(AuditEintrag.id.desc())
                .limit(1)
            ).scalar_one()
        assert eintrag.neu["projekte"] == 1
