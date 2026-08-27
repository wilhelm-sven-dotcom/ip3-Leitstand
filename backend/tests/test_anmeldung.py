"""Anmeldung, Sitzungen, CSRF-Schutz und Sperre (PLAN §2)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import AuditEintrag, Sitzung, User
from app.sicherheit import sitzungen as sitzungsdienst
from app.sicherheit.csrf import KOPFZEILE
from app.zeit import jetzt_utc
from tests.conftest_auth import TEST_PASSWORT, anmelden


@pytest.fixture
def buchhaltung(nutzer_erzeugen) -> int:
    return nutzer_erzeugen("buchhaltung@ip3-energie.de", "buchhaltung", name="Buchhaltung")


@pytest.fixture
def teammitglied(nutzer_erzeugen) -> int:
    return nutzer_erzeugen("monteur@ip3-energie.de", "team", name="Monteur")


class TestAnmelden:
    def test_richtige_zugangsdaten(self, client: TestClient, buchhaltung):
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 200
        koerper = antwort.json()
        assert koerper["email"] == "buchhaltung@ip3-energie.de"
        assert koerper["rollen"] == ["buchhaltung"]
        assert "rechnungen.festschreiben" in koerper["rechte"]
        assert koerper["csrf_token"]

    def test_cookie_ist_httponly_und_samesite_lax(self, client: TestClient, buchhaltung):
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        rohkopf = antwort.headers["set-cookie"].lower()
        assert sitzungsdienst.COOKIE_NAME in rohkopf
        assert "httponly" in rohkopf
        assert "samesite=lax" in rohkopf
        assert "path=/" in rohkopf

    def test_falsches_passwort(self, client: TestClient, buchhaltung):
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": "falsch"},
        )
        assert antwort.status_code == 401
        assert antwort.json()["code"] == "anmeldung_fehlgeschlagen"

    def test_unbekannte_kennung_gibt_dieselbe_meldung(self, client: TestClient, buchhaltung):
        """Sonst ließe sich über die Anmeldemaske herausfinden, welche Kennungen es gibt."""
        falsch = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": "falsch"},
        )
        unbekannt = client.post(
            "/api/auth/anmelden",
            json={"email": "niemand@ip3-energie.de", "passwort": "falsch"},
        )
        assert falsch.status_code == unbekannt.status_code == 401
        assert falsch.json() == unbekannt.json()

    def test_deaktivierter_nutzer_kommt_nicht_hinein(self, client: TestClient, nutzer_erzeugen):
        nutzer_erzeugen("ausgeschieden@ip3-energie.de", "team", aktiv=False)
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "ausgeschieden@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 401

    def test_kennung_ohne_ruecksicht_auf_grossschreibung(self, client: TestClient, buchhaltung):
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "Buchhaltung@IP3-Energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 200

    def test_angemeldet_bleiben_verlaengert_die_sitzung(self, client: TestClient, buchhaltung):
        kurz = anmelden(client, "buchhaltung@ip3-energie.de")
        client.post("/api/auth/abmelden")
        lang = anmelden(client, "buchhaltung@ip3-energie.de", angemeldet_bleiben=True)

        from datetime import datetime

        kurz_ende = datetime.fromisoformat(kurz.nutzer["sitzung_laeuft_ab"])
        lang_ende = datetime.fromisoformat(lang.nutzer["sitzung_laeuft_ab"])
        assert lang_ende - kurz_ende > timedelta(days=25)

    def test_letzte_anmeldung_wird_vermerkt(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        with lese_sitzung() as sitzung:
            nutzer = sitzung.get(User, buchhaltung)
            assert nutzer.letzte_anmeldung is not None


class TestSitzung:
    def test_sitzungsschluessel_liegt_nur_als_hash_in_der_datenbank(
        self, client: TestClient, buchhaltung
    ):
        """Die Datenbank landet nachts im OneDrive – dort darf kein nutzbarer Schlüssel stehen."""
        anmelden(client, "buchhaltung@ip3-energie.de")
        cookie = client.cookies.get(sitzungsdienst.COOKIE_NAME)
        assert cookie
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(Sitzung))
            assert eintrag.token_hash != cookie
            assert eintrag.token_hash == sitzungsdienst.token_hashen(cookie)
            assert len(eintrag.token_hash) == 64

    def test_ich_liefert_den_angemeldeten_nutzer(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.get("/api/auth/ich")
        assert antwort.status_code == 200
        assert antwort.json()["email"] == "buchhaltung@ip3-energie.de"

    def test_ohne_anmeldung_401_als_json(self, client: TestClient):
        antwort = client.get("/api/auth/ich")
        assert antwort.status_code == 401
        koerper = antwort.json()
        assert koerper["code"] == "nicht_angemeldet"
        assert koerper["meldung"]
        assert koerper["naechster_schritt"]

    def test_erfundenes_cookie_wird_abgewiesen(self, client: TestClient, buchhaltung):
        client.cookies.set(sitzungsdienst.COOKIE_NAME, "irgendein-erfundener-wert")
        assert client.get("/api/auth/ich").status_code == 401

    def test_abgelaufene_sitzung_wird_abgewiesen(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        with schreib_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(Sitzung))
            eintrag.laeuft_ab = jetzt_utc() - timedelta(minutes=1)
        assert client.get("/api/auth/ich").status_code == 401

    def test_zu_lange_untaetig_wird_abgemeldet(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        with schreib_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(Sitzung))
            eintrag.letzte_aktivitaet = jetzt_utc() - timedelta(hours=9)
        antwort = client.get("/api/auth/ich")
        assert antwort.status_code == 401
        assert "nicht aktiv" in antwort.json()["meldung"]

    def test_deaktivierung_beendet_die_sitzung_sofort(self, client: TestClient, buchhaltung):
        """Ohne diese Prüfung bliebe ein ausgeschiedener Mitarbeiter bis zum Ablauf angemeldet."""
        anmelden(client, "buchhaltung@ip3-energie.de")
        assert client.get("/api/auth/ich").status_code == 200
        with schreib_sitzung() as sitzung:
            sitzung.get(User, buchhaltung).aktiv = False
        assert client.get("/api/auth/ich").status_code == 401

    def test_aktivitaet_wird_fortgeschrieben(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        with schreib_sitzung() as sitzung:
            eintrag = sitzung.scalar(select(Sitzung))
            eintrag.letzte_aktivitaet = jetzt_utc() - timedelta(hours=1)
            vorher = eintrag.letzte_aktivitaet
        client.get("/api/auth/ich")
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Sitzung)).letzte_aktivitaet > vorher

    def test_abmelden_beendet_die_sitzung(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.post("/api/auth/abmelden")
        assert antwort.status_code == 200
        assert client.get("/api/auth/ich").status_code == 401
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Sitzung)).beendet_am is not None

    def test_abmelden_ohne_sitzung_ist_kein_fehler(self, client: TestClient):
        """Sonst bleibt ein ungültiges Cookie im Browser, das niemand mehr loswird."""
        assert client.post("/api/auth/abmelden").status_code == 200


class TestCsrf:
    def test_schreibende_anfrage_ohne_token_wird_abgewiesen(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
        )
        assert antwort.status_code == 403
        assert antwort.json()["code"] == "csrf_ungueltig"

    def test_falsches_token_wird_abgewiesen(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
            headers={KOPFZEILE: "erfundenes-token"},
        )
        assert antwort.status_code == 403

    def test_token_einer_anderen_sitzung_wird_abgewiesen(
        self, client: TestClient, buchhaltung, teammitglied, test_einstellungen
    ):
        from app.main import anwendung_erzeugen

        erste = anmelden(client, "buchhaltung@ip3-energie.de")
        with TestClient(anwendung_erzeugen(test_einstellungen)) as zweiter_client:
            anmelden(zweiter_client, "monteur@ip3-energie.de")
            antwort = zweiter_client.post(
                "/api/auth/passwort-aendern",
                json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
                headers={KOPFZEILE: erste.csrf_token},
            )
        assert antwort.status_code == 403

    def test_richtiges_token_geht_durch(self, client: TestClient, buchhaltung):
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
        )
        assert antwort.status_code == 200

    def test_lesende_anfrage_braucht_kein_token(self, client: TestClient, buchhaltung):
        anmelden(client, "buchhaltung@ip3-energie.de")
        assert client.get("/api/auth/ich").status_code == 200

    def test_token_kann_nachgeladen_werden(self, client: TestClient, buchhaltung):
        """Nach einem Neuladen der Seite hat die Oberfläche das Token nicht mehr."""
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.get("/api/auth/csrf")
        assert antwort.status_code == 200
        assert antwort.json()["csrf_token"] == angemeldet.csrf_token

    def test_fremde_herkunft_wird_abgewiesen(
        self, client: TestClient, buchhaltung, test_einstellungen
    ):
        test_einstellungen.app.erlaubte_herkunft = ["https://leitstand.ip3.local"]
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
            headers={KOPFZEILE: angemeldet.csrf_token, "Origin": "https://boese-seite.example"},
        )
        assert antwort.status_code == 403
        assert "Adresse" in antwort.json()["meldung"]

    def test_erlaubte_herkunft_geht_durch(
        self, client: TestClient, buchhaltung, test_einstellungen
    ):
        test_einstellungen.app.erlaubte_herkunft = ["https://leitstand.ip3.local"]
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
            headers={
                KOPFZEILE: angemeldet.csrf_token,
                "Origin": "https://leitstand.ip3.local",
            },
        )
        assert antwort.status_code == 200


class TestSperre:
    def _fehlversuche(self, client: TestClient, anzahl: int, email: str) -> None:
        for _ in range(anzahl):
            client.post("/api/auth/anmelden", json={"email": email, "passwort": "falsch"})

    def test_sperre_nach_fuenf_fehlversuchen(self, client: TestClient, buchhaltung):
        self._fehlversuche(client, 5, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": "falsch"},
        )
        assert antwort.status_code == 429
        koerper = antwort.json()
        assert koerper["code"] == "zu_viele_versuche"
        assert "Minute" in koerper["meldung"]
        assert "läuft von selbst ab" in koerper["naechster_schritt"]

    def test_richtiges_passwort_waehrend_der_sperre_wird_abgelehnt(
        self, client: TestClient, buchhaltung
    ):
        """Sonst wäre die Sperre eine Auskunft darüber, welches Passwort stimmt."""
        self._fehlversuche(client, 5, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 429

    def test_vier_fehlversuche_sperren_nicht(self, client: TestClient, buchhaltung):
        self._fehlversuche(client, 4, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 200

    def test_andere_kennung_bleibt_frei(self, client: TestClient, buchhaltung, teammitglied):
        self._fehlversuche(client, 5, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "monteur@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 200

    def test_erfolgreiche_anmeldung_setzt_den_zaehler_zurueck(
        self, client: TestClient, buchhaltung
    ):
        """Wer sich zweimal vertippt und dann hineinkommt, fängt wieder bei null an."""
        self._fehlversuche(client, 3, "buchhaltung@ip3-energie.de")
        assert (
            client.post(
                "/api/auth/anmelden",
                json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
            ).status_code
            == 200
        )
        self._fehlversuche(client, 3, "buchhaltung@ip3-energie.de")
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 200

    def test_fehlversuche_stehen_im_protokoll(self, client: TestClient, buchhaltung):
        self._fehlversuche(client, 3, "buchhaltung@ip3-energie.de")
        with lese_sitzung() as sitzung:
            eintraege = sitzung.scalars(
                select(AuditEintrag).where(AuditEintrag.aktion == "anmeldung.fehlversuch")
            ).all()
            assert len(eintraege) == 3
            assert all(e.user == "buchhaltung@ip3-energie.de" for e in eintraege)

    def test_sperre_wird_protokolliert(self, client: TestClient, buchhaltung):
        self._fehlversuche(client, 6, "buchhaltung@ip3-energie.de")
        with lese_sitzung() as sitzung:
            gesperrt = sitzung.scalars(
                select(AuditEintrag).where(AuditEintrag.aktion == "anmeldung.gesperrt")
            ).all()
            assert gesperrt

    def test_unbekannte_kennungen_loesen_ip_drosselung_aus(self, client: TestClient, buchhaltung):
        """Durchprobieren vieler Kennungen von einem Rechner aus.

        Die IP-Grenze liegt beim Vierfachen der Kennungsgrenze, hier also bei 20 Versuchen.
        """
        for nummer in range(20):
            client.post(
                "/api/auth/anmelden",
                json={"email": f"versuch{nummer}@ip3-energie.de", "passwort": "falsch"},
            )
        antwort = client.post(
            "/api/auth/anmelden",
            json={"email": "buchhaltung@ip3-energie.de", "passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 429


class TestPasswortAendern:
    def test_wechsel_mit_richtigem_altem_passwort(self, client: TestClient, buchhaltung):
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
        )
        assert antwort.status_code == 200
        assert antwort.json()["muss_passwort_wechseln"] is False

        client.post("/api/auth/abmelden")
        assert (
            client.post(
                "/api/auth/anmelden",
                json={"email": "buchhaltung@ip3-energie.de", "passwort": "NeuesPasswort-2026!"},
            ).status_code
            == 200
        )

    def test_falsches_altes_passwort(self, client: TestClient, buchhaltung):
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": "falsch", "neues_passwort": "NeuesPasswort-2026!"},
        )
        assert antwort.status_code == 403
        assert antwort.json()["code"] == "altes_passwort_falsch"

    def test_falsches_altes_passwort_zaehlt_als_fehlversuch(self, client: TestClient, buchhaltung):
        """Sonst wäre diese Route ein Weg, Passwörter ohne Sperre durchzuprobieren."""
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": "falsch", "neues_passwort": "NeuesPasswort-2026!"},
        )
        with lese_sitzung() as sitzung:
            assert sitzung.scalars(
                select(AuditEintrag).where(AuditEintrag.aktion == "anmeldung.fehlversuch")
            ).all()

    def test_zu_kurzes_neues_passwort(self, client: TestClient, buchhaltung):
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "kurz"},
        )
        assert antwort.status_code == 422
        assert "passwort" in antwort.json()["felder"]

    def test_zu_langes_neues_passwort_ergibt_422_statt_500(self, client: TestClient, buchhaltung):
        """bcrypt weist über 72 Byte ab – das muss ein Feldhinweis sein, keine Fehlerseite."""
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "A" * 80},
        )
        assert antwort.status_code == 422
        assert "72" in antwort.json()["meldung"]

    def test_unveraendertes_passwort_wird_abgewiesen(self, client: TestClient, buchhaltung):
        angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": TEST_PASSWORT},
        )
        assert antwort.status_code == 422
        assert antwort.json()["code"] == "passwort_unveraendert"

    def test_wechsel_beendet_andere_sitzungen(
        self, client: TestClient, buchhaltung, test_einstellungen
    ):
        """Wer das alte Passwort kannte, soll nicht über eine offene Sitzung weiterarbeiten."""
        from app.main import anwendung_erzeugen

        with TestClient(anwendung_erzeugen(test_einstellungen)) as anderer_browser:
            anmelden(anderer_browser, "buchhaltung@ip3-energie.de")
            assert anderer_browser.get("/api/auth/ich").status_code == 200

            angemeldet = anmelden(client, "buchhaltung@ip3-energie.de")
            angemeldet.schreiben(
                "POST",
                "/api/auth/passwort-aendern",
                json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
            )
            # Die andere Sitzung ist beendet, die eigene bleibt.
            assert anderer_browser.get("/api/auth/ich").status_code == 401
        assert client.get("/api/auth/ich").status_code == 200

    def test_offener_wechsel_sperrt_andere_routen(self, client: TestClient, nutzer_erzeugen):
        """Ein Passwort, das über die Kommandozeile gelaufen ist, gilt als kompromittiert."""
        nutzer_erzeugen("neu@ip3-energie.de", "buchhaltung", muss_wechseln=True)
        angemeldet = anmelden(client, "neu@ip3-energie.de")
        assert angemeldet.nutzer["muss_passwort_wechseln"] is True

        # /ich bleibt erreichbar, damit die Oberfläche zur Passwortmaske führen kann.
        assert client.get("/api/auth/ich").status_code == 200

        antwort = angemeldet.schreiben(
            "POST",
            "/api/auth/passwort-aendern",
            json={"altes_passwort": TEST_PASSWORT, "neues_passwort": "NeuesPasswort-2026!"},
        )
        assert antwort.status_code == 200
        assert antwort.json()["muss_passwort_wechseln"] is False
