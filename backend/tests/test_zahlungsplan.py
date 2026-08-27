"""Zahlungsplan und Nachträge (PLAN §5, §6.12, §7 Phase 1).

Zwei Sperren, die verschiedene Dinge bedeuten, und ein Soll-Ist-Vergleich, der warnt statt zu
verbieten. Die Sperren sitzen zusätzlich als Trigger in der Datenbank (tests/test_trigger.py);
hier wird geprüft, dass der Nutzer statt eines Datenbankfehlers eine Meldung mit dem nächsten
Schritt bekommt (CLAUDE.md Regel 8).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import AuditEintrag, Firma, Kunde, Nachtrag, Projekt, Zahlungsplanposition
from tests.conftest_auth import anmelden


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen):
    nutzer_erzeugen("buha-zp@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha-zp@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen):
    nutzer_erzeugen("team-zp@ip3-energie.de", "team")
    return anmelden(client, "team-zp@ip3-energie.de")


@pytest.fixture
def projekt(gesäte_db) -> dict:
    """Ein Projekt mit drei Positionen: offen, migriert-gestellt, berechnet."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=12001, name="Maschinenbau Köstler GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        eintrag = Projekt(
            projekt_nr=26014,
            firma_id=firma_id,
            kunde_id=kunde.id,
            standort="Neustadt a. d. Waldnaab",
            anlagenart="aufdach_speicher",
            pv_kwp=499.2,
            speicher_kwh=420,
            ab_wert_netto=61250000,
            pl_name="Michl",
            status="in_bau",
        )
        sitzung.add(eintrag)
        sitzung.flush()
        offen = Zahlungsplanposition(
            projekt_id=eintrag.id,
            pos_nr=1,
            bezeichnung="Schlussrechnung PV",
            gewerk="pv",
            art="schluss",
            betrag_netto=3062500,
            plan_monat="2026-11",
        )
        gestellt = Zahlungsplanposition(
            projekt_id=eintrag.id,
            pos_nr=2,
            bezeichnung="1. Abschlag PV",
            gewerk="pv",
            art="abschlag",
            betrag_netto=18375000,
            plan_monat="2026-03",
            migriert_gestellt=True,
            quelle_migration="Offene_Auftraege_2025.xlsx Zeile 42",
        )
        sitzung.add_all([offen, gestellt])
        sitzung.flush()
        return {
            "projekt_nr": eintrag.projekt_nr,
            "projekt_id": eintrag.id,
            "offen": offen.id,
            "gestellt": gestellt.id,
        }


def _position(antwort: dict, position_id: int) -> dict:
    return next(p for p in antwort["zahlungsplan"] if p["id"] == position_id)


class TestPositionenPflegen:
    def test_anlegen_zaehlt_die_positionsnummer_weiter(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={
                "bezeichnung": "2. Abschlag PV",
                "gewerk": "pv",
                "art": "abschlag",
                "betrag_netto": 15312500,
                "plan_monat": "2026-05",
                "trigger_status": "montage_uk",
            },
        )
        assert antwort.status_code == 201, antwort.text
        neu = antwort.json()
        assert neu["pos_nr"] == 3
        assert neu["berechnet"] is False
        assert neu["sperrgrund"] is None
        assert neu["trigger_status"] == "montage_uk"

    def test_aendern_mit_stand(self, buchhaltung, projekt):
        vorher = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        position = _position(vorher, projekt["offen"])
        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/zahlungsplan/{projekt['offen']}",
            json={
                "bezeichnung": "Schlussrechnung PV und Speicher",
                "gewerk": "pv",
                "art": "schluss",
                "betrag_netto": 4000000,
                "plan_monat": "2026-12",
                "stand": position["stand"],
            },
        )
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["betrag_netto"] == 4000000
        assert antwort.json()["plan_monat"] == "2026-12"

    def test_veralteter_stand_ergibt_konflikt(self, buchhaltung, projekt):
        vorher = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        position = _position(vorher, projekt["offen"])
        koerper = {
            "bezeichnung": "Schlussrechnung PV",
            "gewerk": "pv",
            "art": "schluss",
            "betrag_netto": 3062500,
            "plan_monat": "2026-11",
            "stand": position["stand"],
        }
        erste = buchhaltung.schreiben(
            "PUT", f"/api/zahlungsplan/{projekt['offen']}", json={**koerper, "betrag_netto": 1}
        )
        assert erste.status_code == 200
        zweite = buchhaltung.schreiben(
            "PUT", f"/api/zahlungsplan/{projekt['offen']}", json={**koerper, "betrag_netto": 2}
        )
        assert zweite.status_code == 409
        assert zweite.json()["code"] == "stand_veraltet"

    def test_offene_position_darf_geloescht_werden(self, buchhaltung, projekt):
        """Eine offene Position ist eine Planung, kein Beleg."""
        antwort = buchhaltung.schreiben("DELETE", f"/api/zahlungsplan/{projekt['offen']}")
        assert antwort.status_code == 204
        with lese_sitzung() as sitzung:
            assert sitzung.get(Zahlungsplanposition, projekt["offen"]) is None

    def test_unterminierte_position_ist_erlaubt(self, buchhaltung, projekt):
        """Kein stiller Vorschlagsmonat: ohne Planmonat gilt „unterminiert" (PLAN §7 Phase 2)."""
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={
                "bezeichnung": "Restbetrag",
                "gewerk": "pv",
                "art": "einmal",
                "betrag_netto": 100000,
            },
        )
        assert antwort.status_code == 201
        assert antwort.json()["plan_monat"] is None

    def test_falscher_planmonat_wird_abgewiesen(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={
                "bezeichnung": "Abschlag",
                "gewerk": "pv",
                "art": "abschlag",
                "betrag_netto": 1000,
                "plan_monat": "2026-13",
            },
        )
        assert antwort.status_code == 422

    def test_leere_bezeichnung_wird_abgewiesen(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={"bezeichnung": "   ", "gewerk": "pv", "art": "abschlag", "betrag_netto": 1000},
        )
        assert antwort.status_code == 422

    def test_anlegen_steht_im_protokoll(self, buchhaltung, projekt):
        buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={
                "bezeichnung": "2. Abschlag PV",
                "gewerk": "pv",
                "art": "abschlag",
                "betrag_netto": 15312500,
            },
        )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalars(
                select(AuditEintrag)
                .where(AuditEintrag.aktion == "zahlungsplan.angelegt")
                .order_by(AuditEintrag.id.desc())
            ).first()
        assert eintrag is not None
        assert eintrag.neu["projekt_nr"] == 26014
        assert eintrag.neu["betrag_netto"] == 15312500


class TestGestellteSperre:
    """Der Altbestand: die Rechnung gibt es, den Beleg im Leitstand nicht."""

    def test_aendern_wird_abgewiesen_mit_dem_weg_zur_ruecknahme(self, buchhaltung, projekt):
        vorher = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        position = _position(vorher, projekt["gestellt"])
        assert position["sperrgrund"], "Die Maske muss die Sperre vorher sehen"

        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/zahlungsplan/{projekt['gestellt']}",
            json={
                "bezeichnung": "1. Abschlag PV",
                "gewerk": "pv",
                "art": "abschlag",
                "betrag_netto": 1,
                "plan_monat": "2026-03",
                "stand": position["stand"],
            },
        )
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "zahlungsplan_migriert_gestellt"
        assert "gestellt" in koerper["naechster_schritt"]
        assert "Stacktrace" not in koerper["meldung"]

    def test_loeschen_wird_abgewiesen(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben("DELETE", f"/api/zahlungsplan/{projekt['gestellt']}")
        assert antwort.status_code == 409
        with lese_sitzung() as sitzung:
            assert sitzung.get(Zahlungsplanposition, projekt["gestellt"]) is not None

    def test_ruecknahme_und_dann_aendern(self, buchhaltung, projekt):
        zurueck = buchhaltung.schreiben(
            "PUT", f"/api/zahlungsplan/{projekt['gestellt']}/gestellt-zuruecknehmen"
        )
        assert zurueck.status_code == 200, zurueck.text
        assert zurueck.json()["migriert_gestellt"] is None
        assert zurueck.json()["sperrgrund"] is None

        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/zahlungsplan/{projekt['gestellt']}",
            json={
                "bezeichnung": "1. Abschlag PV (korrigiert)",
                "gewerk": "pv",
                "art": "abschlag",
                "betrag_netto": 18000000,
                "plan_monat": "2026-04",
                "stand": zurueck.json()["stand"],
            },
        )
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["betrag_netto"] == 18000000

    def test_beides_steht_getrennt_im_protokoll(self, buchhaltung, projekt):
        """Die Rücknahme ist eine eigene Entscheidung – und ein eigener Eintrag."""
        zurueck = buchhaltung.schreiben(
            "PUT", f"/api/zahlungsplan/{projekt['gestellt']}/gestellt-zuruecknehmen"
        )
        buchhaltung.schreiben(
            "PUT",
            f"/api/zahlungsplan/{projekt['gestellt']}",
            json={
                "bezeichnung": "1. Abschlag PV",
                "gewerk": "pv",
                "art": "abschlag",
                "betrag_netto": 18000000,
                "plan_monat": "2026-03",
                "stand": zurueck.json()["stand"],
            },
        )
        with lese_sitzung() as sitzung:
            aktionen = [
                e.aktion
                for e in sitzung.scalars(
                    select(AuditEintrag)
                    .where(AuditEintrag.tabelle == "zahlungsplan")
                    .order_by(AuditEintrag.id)
                )
            ]
            ruecknahme = sitzung.scalars(
                select(AuditEintrag).where(
                    AuditEintrag.aktion == "zahlungsplan.gestellt_zurueckgenommen"
                )
            ).first()
        assert aktionen == [
            "zahlungsplan.gestellt_zurueckgenommen",
            "zahlungsplan.geaendert",
        ]
        # Die Herkunft aus der Quelldatei steht im Eintrag: so bleibt nachvollziehbar, welcher
        # Zeile der Auftragsliste der Betrag entstammt.
        assert "Offene_Auftraege_2025.xlsx" in ruecknahme.neu["herkunft"]

    def test_ruecknahme_an_einer_offenen_position_wird_abgewiesen(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben(
            "PUT", f"/api/zahlungsplan/{projekt['offen']}/gestellt-zuruecknehmen"
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "zahlungsplan_nicht_gestellt"


class TestBerechneteSperre:
    @pytest.fixture
    def berechnet(self, projekt) -> int:
        """Eine Position mit Rechnungsbezug – wie ab Phase 3."""
        from datetime import date

        from app.modelle import Projekt, Rechnung

        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            kunde_id = sitzung.scalar(
                select(Projekt.kunde_id).where(Projekt.id == projekt["projekt_id"])
            )
            rechnung = Rechnung(
                firma_id=firma_id,
                art="abschlag",
                projekt_id=projekt["projekt_id"],
                kunde_id=kunde_id,
                datum=date(2026, 3, 1),
                netto=18375000,
                ust=3491250,
                brutto=21866250,
                status="entwurf",
            )
            sitzung.add(rechnung)
            sitzung.flush()
            position = sitzung.get(Zahlungsplanposition, projekt["offen"])
            position.rechnung_id = rechnung.id
            return projekt["offen"]

    def test_berechnete_position_ist_gesperrt(self, buchhaltung, projekt, berechnet):
        vorher = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        position = _position(vorher, berechnet)
        assert position["berechnet"] is True
        assert "Storno" in position["sperrgrund"]

        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/zahlungsplan/{berechnet}",
            json={
                "bezeichnung": "Schlussrechnung PV",
                "gewerk": "pv",
                "art": "schluss",
                "betrag_netto": 1,
                "stand": position["stand"],
            },
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "zahlungsplan_berechnet"

    def test_ruecknahme_hilft_bei_einer_berechneten_position_nicht(
        self, buchhaltung, projekt, berechnet
    ):
        antwort = buchhaltung.schreiben(
            "PUT", f"/api/zahlungsplan/{berechnet}/gestellt-zuruecknehmen"
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "zahlungsplan_berechnet"


class TestNachtraege:
    def test_anlegen_und_status(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={
                "bezeichnung": "Zusätzliche Unterkonstruktion Halle 2",
                "betrag_netto": 1250000,
                "status": "angeboten",
                "datum": "2026-05-12",
            },
        )
        assert antwort.status_code == 201, antwort.text
        neu = antwort.json()
        assert neu["zaehlt_zum_soll"] is False
        assert neu["datum"] == "2026-05-12"

    def test_negativer_nachtrag_ist_erlaubt(self, buchhaltung, projekt):
        """Ein Nachtrag kann auch eine Minderung sein – eine entfallene Leistung."""
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={"bezeichnung": "Wallbox entfällt", "betrag_netto": -180000},
        )
        assert antwort.status_code == 201
        assert antwort.json()["betrag_netto"] == -180000

    def test_berechneter_nachtrag_bleibt_berechnet(self, buchhaltung, projekt):
        angelegt = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={"bezeichnung": "Mehr Module", "betrag_netto": 500000, "status": "berechnet"},
        ).json()
        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/nachtraege/{angelegt['id']}",
            json={
                "bezeichnung": "Mehr Module",
                "betrag_netto": 500000,
                "status": "beauftragt",
                "stand": angelegt["stand"],
            },
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "nachtrag_berechnet"

    def test_berechneter_nachtrag_ist_unloeschbar(self, buchhaltung, projekt):
        angelegt = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={"bezeichnung": "Mehr Module", "betrag_netto": 500000, "status": "berechnet"},
        ).json()
        antwort = buchhaltung.schreiben("DELETE", f"/api/nachtraege/{angelegt['id']}")
        assert antwort.status_code == 409

    def test_angebotener_nachtrag_darf_weg(self, buchhaltung, projekt):
        angelegt = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={"bezeichnung": "Angebot Speicher", "betrag_netto": 900000},
        ).json()
        antwort = buchhaltung.schreiben("DELETE", f"/api/nachtraege/{angelegt['id']}")
        assert antwort.status_code == 204
        with lese_sitzung() as sitzung:
            assert sitzung.get(Nachtrag, angelegt["id"]) is None


class TestDeckung:
    """PLAN §6.12: Warnung, keine Sperre."""

    def test_luecke_wird_ausgewiesen(self, buchhaltung, projekt):
        antwort = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        assert antwort["soll_netto"] == 61250000
        assert antwort["zahlungsplan_summe"] == 3062500 + 18375000
        assert antwort["deckung_differenz"] == 61250000 - (3062500 + 18375000)

    def test_beauftragter_nachtrag_erhoeht_das_soll(self, buchhaltung, projekt):
        buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={"bezeichnung": "Mehr Module", "betrag_netto": 1000000, "status": "beauftragt"},
        )
        antwort = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        assert antwort["nachtraege_summe"] == 1000000
        assert antwort["soll_netto"] == 61250000 + 1000000

    def test_angebotener_nachtrag_zaehlt_nicht(self, buchhaltung, projekt):
        """Ein Angebot ist kein Auftrag."""
        buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/nachtraege",
            json={"bezeichnung": "Angebot", "betrag_netto": 1000000, "status": "angeboten"},
        )
        antwort = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        assert antwort["nachtraege_summe"] == 0
        assert antwort["soll_netto"] == 61250000

    def test_ueberdeckung_ist_erlaubt(self, buchhaltung, projekt):
        """Mehr verplant als beauftragt: eine Warnung, kein Fehler."""
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={
                "bezeichnung": "Restbetrag",
                "gewerk": "pv",
                "art": "einmal",
                "betrag_netto": 60000000,
            },
        )
        assert antwort.status_code == 201
        projekt_daten = buchhaltung.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        assert projekt_daten["deckung_differenz"] < 0

    def test_ohne_auftragswert_kein_vergleich(self, buchhaltung, gesäte_db):
        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            kunde = Kunde(kunden_nr=12009, name="Ohne Wert", typ="b2c")
            sitzung.add(kunde)
            sitzung.flush()
            sitzung.add(
                Projekt(
                    projekt_nr=26099,
                    firma_id=firma_id,
                    kunde_id=kunde.id,
                    status="angebot",
                )
            )
        antwort = buchhaltung.client.get("/api/projekte/26099").json()
        assert antwort["soll_netto"] is None
        assert antwort["deckung_differenz"] is None


class TestBerechtigungen:
    def test_team_darf_nicht_schreiben(self, team, projekt):
        antwort = team.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={"bezeichnung": "X", "gewerk": "pv", "art": "abschlag", "betrag_netto": 1},
        )
        assert antwort.status_code == 403

    def test_team_sieht_keine_nachtraege(self, team, projekt):
        # Der Nachtrag wird direkt in der Datenbank angelegt: zwei Anmeldungen teilen sich einen
        # Testclient, und die zweite überschreibt das Sitzungs-Cookie der ersten.
        with schreib_sitzung() as sitzung:
            sitzung.add(
                Nachtrag(
                    projekt_id=projekt["projekt_id"],
                    bezeichnung="Mehr Module",
                    betrag_netto=500000,
                    status="beauftragt",
                )
            )
        antwort = team.client.get(f"/api/projekte/{projekt['projekt_nr']}").json()
        assert antwort["nachtraege"] == []
        assert antwort["soll_netto"] is None
        assert antwort["deckung_differenz"] is None

    def test_schreibrecht_ohne_werterecht_reicht_nicht(self, client, nutzer_erzeugen, projekt):
        """Eine eigene Rolle mit zahlungsplan.schreiben, aber ohne projekte.werte_lesen."""
        from app.modelle import Berechtigung, Rolle, User

        nutzer_id = nutzer_erzeugen("planer-zp@ip3-energie.de", "team")
        with schreib_sitzung() as sitzung:
            rolle = Rolle(name="planer-zp", beschreibung="Planung ohne Beträge")
            sitzung.add(rolle)
            for schluessel in ("projekte.lesen", "zahlungsplan.schreiben"):
                recht = sitzung.scalar(
                    select(Berechtigung).where(
                        Berechtigung.schluessel == schluessel, Berechtigung.scope.is_(None)
                    )
                )
                assert recht is not None, schluessel
                rolle.berechtigungen.append(recht)
            nutzer = sitzung.get(User, nutzer_id)
            nutzer.rollen.clear()
            nutzer.rollen.append(rolle)
            sitzung.flush()
        planer = anmelden(client, "planer-zp@ip3-energie.de")

        antwort = planer.schreiben(
            "POST",
            f"/api/projekte/{projekt['projekt_nr']}/zahlungsplan",
            json={"bezeichnung": "X", "gewerk": "pv", "art": "abschlag", "betrag_netto": 1},
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "werte_ohne_berechtigung"

    def test_fremdes_projekt_ist_nicht_erreichbar(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben(
            "POST",
            "/api/projekte/99999/zahlungsplan",
            json={"bezeichnung": "X", "gewerk": "pv", "art": "abschlag", "betrag_netto": 1},
        )
        assert antwort.status_code == 404

    def test_position_die_es_nicht_gibt(self, buchhaltung, projekt):
        antwort = buchhaltung.schreiben("DELETE", "/api/zahlungsplan/999999")
        assert antwort.status_code == 404
        assert "neu laden" in antwort.json()["naechster_schritt"]
