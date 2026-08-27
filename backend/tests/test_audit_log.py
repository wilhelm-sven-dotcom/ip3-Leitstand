"""Änderungsprotokoll (PLAN §5).

Der Feldfilter ist der Kern dieser Datei. Die Datenbank – und damit das Protokoll – liegt nach
jeder Nacht als Sicherungskopie im OneDrive-Ordner. Was hier hineingerät, ist dauerhaft dort.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import audit
from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import AuditEintrag, User
from tests.conftest_auth import TEST_PASSWORT, anmelden


@pytest.fixture
def buchhaltung(nutzer_erzeugen) -> int:
    return nutzer_erzeugen("bh@ip3-energie.de", "buchhaltung", name="Buchhaltung")


class TestFeldfilter:
    @pytest.mark.parametrize(
        "feldname",
        [
            "passwort",
            "neues_passwort",
            "altes_passwort",
            "password",
            "pw_hash",
            "hash",
            "token",
            "csrf_token",
            "token_hash",
            "sitzung_schluessel",
            "api_secret",
        ],
    )
    def test_geheime_felder_werden_ersetzt(self, feldname: str):
        gefiltert = audit.filtern({feldname: "streng geheim", "ort": "Weiden"})
        assert gefiltert[feldname] == audit.ERSATZTEXT
        assert gefiltert["ort"] == "Weiden"

    def test_gross_und_kleinschreibung_ist_unerheblich(self):
        gefiltert = audit.filtern({"Passwort": "geheim", "PW_HASH": "geheim"})
        assert all(wert == audit.ERSATZTEXT for wert in gefiltert.values())

    def test_verschachtelte_strukturen_werden_gefiltert(self):
        gefiltert = audit.filtern({"nutzer": {"email": "a@b.de", "pw_hash": "geheim"}})
        assert gefiltert["nutzer"]["email"] == "a@b.de"
        assert gefiltert["nutzer"]["pw_hash"] == audit.ERSATZTEXT

    def test_listen_von_strukturen_werden_gefiltert(self):
        gefiltert = audit.filtern({"nutzer": [{"passwort": "geheim"}, {"name": "Sven"}]})
        assert gefiltert["nutzer"][0]["passwort"] == audit.ERSATZTEXT
        assert gefiltert["nutzer"][1]["name"] == "Sven"

    def test_none_bleibt_none(self):
        assert audit.filtern(None) is None

    def test_gewoehnliche_felder_bleiben_unveraendert(self):
        daten = {"betrag_netto": 9187500, "plan_monat": "2026-09", "aktiv": True}
        assert audit.filtern(daten) == daten


class TestEintragen:
    def test_eintrag_mit_nutzerobjekt(self, gesäte_db, buchhaltung):
        with schreib_sitzung() as sitzung:
            nutzer = sitzung.get(User, buchhaltung)
            audit.eintragen(
                sitzung, "test.aktion", nutzer=nutzer, tabelle="projekte", datensatz_id=1
            )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "test.aktion")
            )
            assert eintrag.user == "bh@ip3-energie.de"
            assert eintrag.user_id == buchhaltung
            assert eintrag.tabelle == "projekte"
            assert eintrag.datensatz_id == 1

    def test_eintrag_mit_kennung_ohne_nutzer(self, gesäte_db):
        """Fehlversuche mit unbekannter Kennung brauchen einen Eintrag ohne Nutzerbezug."""
        with schreib_sitzung() as sitzung:
            audit.eintragen(sitzung, "anmeldung.fehlversuch", nutzer="unbekannt@example.com")
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(AuditEintrag))
            assert eintrag.user == "unbekannt@example.com"
            assert eintrag.user_id is None

    def test_zeitstempel_in_utc(self, gesäte_db):
        with schreib_sitzung() as sitzung:
            audit.eintragen(sitzung, "test.zeit")
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(AuditEintrag))
            assert eintrag.ts.tzinfo is not None
            assert eintrag.ts.utcoffset().total_seconds() == 0

    def test_alt_und_neu_werden_gefiltert(self, gesäte_db):
        with schreib_sitzung() as sitzung:
            audit.eintragen(
                sitzung,
                "nutzer.geaendert",
                alt={"email": "alt@ip3.de", "pw_hash": "$2b$alter-hash"},
                neu={"email": "neu@ip3.de", "pw_hash": "$2b$neuer-hash"},
            )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(AuditEintrag))
            assert eintrag.alt["email"] == "alt@ip3.de"
            assert eintrag.alt["pw_hash"] == audit.ERSATZTEXT
            assert eintrag.neu["pw_hash"] == audit.ERSATZTEXT

    def test_eintrag_verschwindet_mit_der_zurueckgerollten_aenderung(self, gesäte_db):
        """Ein Protokolleintrag über eine Änderung, die nie passiert ist, wäre schlimmer als keiner."""
        from app.datenbank import schreib_transaktion, session_factory

        sitzung = session_factory()()
        try:
            with pytest.raises(RuntimeError), schreib_transaktion(sitzung):
                audit.eintragen(sitzung, "test.abgebrochen")
                raise RuntimeError("Die fachliche Änderung scheitert")
        finally:
            sitzung.close()

        with lese_sitzung() as pruefung:
            assert (
                pruefung.scalar(
                    select(AuditEintrag).where(AuditEintrag.aktion == "test.abgebrochen")
                )
                is None
            )


class TestProtokollierteVorgaenge:
    def test_anmeldung_wird_protokolliert(self, client: TestClient, buchhaltung):
        anmelden(client, "bh@ip3-energie.de")
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "anmeldung.erfolg")
            )
            assert eintrag is not None
            assert eintrag.user == "bh@ip3-energie.de"

    def test_abmeldung_wird_protokolliert(self, client: TestClient, buchhaltung):
        anmelden(client, "bh@ip3-energie.de")
        client.post("/api/auth/abmelden")
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "anmeldung.abmeldung")
            )

    def test_passwortwechsel_wird_protokolliert_ohne_passwort(
        self, client: TestClient, buchhaltung
    ):
        angemeldet = anmelden(client, "bh@ip3-energie.de")
        angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
        )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "passwort.geaendert")
            )
            assert eintrag is not None
            assert eintrag.tabelle == "users"
            assert eintrag.datensatz_id == buchhaltung
            # Nirgendwo im Eintrag steht das Passwort.
            als_text = f"{eintrag.alt} {eintrag.neu}"
            assert TEST_PASSWORT not in als_text
            assert "NeuesPasswort-2026!" not in als_text

    def test_kein_passwort_und_kein_token_im_gesamten_protokoll(
        self, client: TestClient, buchhaltung
    ):
        """Gesamtschau über alle Einträge nach einem vollständigen Ablauf."""
        angemeldet = anmelden(client, "bh@ip3-energie.de")
        client.post("/api/auth/anmelden", json={"email": "bh@ip3-energie.de", "passwort": "falsch"})
        angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
        )
        client.post("/api/auth/abmelden")

        with lese_sitzung() as sitzung:
            alle = sitzung.scalars(select(AuditEintrag)).all()
            gesamttext = " ".join(f"{e.user} {e.aktion} {e.alt} {e.neu}" for e in alle)
        assert alle
        assert TEST_PASSWORT not in gesamttext
        assert "NeuesPasswort-2026!" not in gesamttext
        assert "$2b$" not in gesamttext, "Ein bcrypt-Hash ist ins Protokoll geraten"
        assert angemeldet.csrf_token not in gesamttext

    def test_absenderadresse_wird_vermerkt(self, client: TestClient, buchhaltung):
        anmelden(client, "bh@ip3-energie.de")
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "anmeldung.erfolg")
            )
            assert eintrag.ip is not None


class TestUnveraenderbarkeit:
    def test_es_gibt_keine_route_die_das_protokoll_aendert(self, test_einstellungen):
        """Das Protokoll wird nur geschrieben (PLAN §5, GoBD)."""
        from app.main import anwendung_erzeugen
        from tests.test_rbac import _routen

        app = anwendung_erzeugen(test_einstellungen)
        verdaechtig = [
            f"{methode} {route.path}"
            for route in _routen(app)
            for methode in (route.methods or set())
            if "audit" in route.path.lower() and methode in ("PUT", "PATCH", "DELETE", "POST")
        ]
        assert verdaechtig == [], f"Schreibende Routen auf das Protokoll: {verdaechtig}"

    def test_nutzer_werden_nicht_geloescht(self, test_einstellungen):
        """PLAN §5: Nutzer werden nie gelöscht, nur deaktiviert.

        Ein gelöschter Nutzer würde die Protokolleinträge unlesbar machen, die auf ihn verweisen.
        """
        from app.main import anwendung_erzeugen
        from tests.test_rbac import _routen

        app = anwendung_erzeugen(test_einstellungen)
        loeschroutinen = [
            route.path
            for route in _routen(app)
            for methode in (route.methods or set())
            if methode == "DELETE" and "nutzer" in route.path.lower()
        ]
        assert loeschroutinen == []
