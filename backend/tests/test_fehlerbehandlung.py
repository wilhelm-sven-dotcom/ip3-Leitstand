"""Fehlerantworten: deutsch, ohne Stacktrace, mit nächstem Schritt (PLAN §14)."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.fehler import (
    FachFehler,
    KeineBerechtigung,
    Konflikt,
    NichtAngemeldet,
    NichtGefunden,
    ZuVieleVersuche,
    handler_registrieren,
)


class Eingabe(BaseModel):
    """Auf Modulebene, nicht in der Fixture: mit ``from __future__ import annotations`` löst
    FastAPI Typangaben über die Modul-Namensräume auf und findet lokale Klassen nicht."""

    bezeichnung: str = Field(min_length=3)
    betrag_cent: int
    monat: str


@pytest.fixture
def testanwendung() -> FastAPI:
    """Kleine Anwendung, die jeden Fehlerweg auslöst."""
    app = FastAPI()
    handler_registrieren(app)

    @app.post("/api/pruefen")
    def _pruefen(eingabe: Eingabe) -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/nicht-angemeldet")
    def _nicht_angemeldet() -> None:
        raise NichtAngemeldet()

    @app.get("/api/keine-berechtigung")
    def _keine_berechtigung() -> None:
        raise KeineBerechtigung()

    @app.get("/api/nicht-gefunden")
    def _nicht_gefunden() -> None:
        raise NichtGefunden()

    @app.get("/api/konflikt")
    def _konflikt() -> None:
        raise Konflikt(
            "Das Projekt wurde zwischenzeitlich von Michael geändert.",
            "Bitte neu laden und die Eingabe wiederholen.",
        )

    @app.get("/api/gesperrt")
    def _gesperrt() -> None:
        raise ZuVieleVersuche("Zu viele Fehlversuche.", "Bitte 15 Minuten warten.")

    @app.get("/api/kaputt")
    def _kaputt() -> None:
        raise RuntimeError("interne Einzelheit, die niemand sehen soll")

    return app


@pytest.fixture
def client(testanwendung: FastAPI) -> TestClient:
    return TestClient(testanwendung, raise_server_exceptions=False)


def test_jeder_fehler_hat_code_meldung_und_schritt(client: TestClient):
    for pfad in (
        "/api/nicht-angemeldet",
        "/api/keine-berechtigung",
        "/api/nicht-gefunden",
        "/api/konflikt",
        "/api/gesperrt",
        "/api/kaputt",
    ):
        antwort = client.get(pfad)
        koerper = antwort.json()
        assert set(koerper) >= {"code", "meldung", "naechster_schritt"}, pfad
        assert koerper["meldung"], pfad
        assert koerper["naechster_schritt"], pfad


@pytest.mark.parametrize(
    ("pfad", "status", "code"),
    [
        ("/api/nicht-angemeldet", 401, "nicht_angemeldet"),
        ("/api/keine-berechtigung", 403, "keine_berechtigung"),
        ("/api/nicht-gefunden", 404, "nicht_gefunden"),
        ("/api/konflikt", 409, "konflikt"),
        ("/api/gesperrt", 429, "zu_viele_versuche"),
    ],
)
def test_status_und_code_passen(client: TestClient, pfad: str, status: int, code: str):
    antwort = client.get(pfad)
    assert antwort.status_code == status
    assert antwort.json()["code"] == code


def test_unerwarteter_fehler_zeigt_keine_einzelheiten(client: TestClient):
    antwort = client.get("/api/kaputt")
    assert antwort.status_code == 500
    text = antwort.text
    assert "interne Einzelheit" not in text
    assert "RuntimeError" not in text
    assert "Traceback" not in text
    assert "Vorgangsnummer" in antwort.json()["meldung"]


def test_unerwarteter_fehler_ist_ueber_die_vorgangsnummer_auffindbar(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.ERROR):
        antwort = client.get("/api/kaputt")
    meldung = antwort.json()["meldung"]
    # Die Nummer aus "Vorgangsnummer abc12345." herauslösen
    nummer = meldung.split("Vorgangsnummer ")[1].rstrip(".")
    assert nummer in caplog.text, "Ohne die Nummer im Protokoll ist sie für den Nutzer wertlos"
    assert "interne Einzelheit" in caplog.text, "Der Stacktrace gehört ins Protokoll"


def test_validierungsfehler_nennt_felder_auf_deutsch(client: TestClient):
    antwort = client.post("/api/pruefen", json={"bezeichnung": "ab"})
    assert antwort.status_code == 422
    koerper = antwort.json()
    assert koerper["code"] == "eingabe_unvollstaendig"
    assert koerper["felder"]["bezeichnung"] == "Die Angabe ist zu kurz."
    assert koerper["felder"]["betrag_cent"] == "Diese Angabe fehlt."
    assert koerper["felder"]["monat"] == "Diese Angabe fehlt."


def test_validierungsfehler_bei_falschem_typ(client: TestClient):
    antwort = client.post(
        "/api/pruefen", json={"bezeichnung": "Abschlag", "betrag_cent": "viel", "monat": "2026-03"}
    )
    assert antwort.json()["felder"]["betrag_cent"] == "Hier wird eine ganze Zahl erwartet."


def test_unbekannter_pfad_bleibt_json(client: TestClient):
    """Wichtig für später: der SPA-Fallback darf API-Pfade nicht verschlucken."""
    antwort = client.get("/api/gibt-es-nicht")
    assert antwort.status_code == 404
    assert antwort.headers["content-type"].startswith("application/json")
    assert antwort.json()["code"] == "nicht_gefunden"


def test_falsche_methode(client: TestClient):
    antwort = client.get("/api/pruefen")
    assert antwort.status_code == 405
    assert antwort.json()["code"] == "methode_nicht_erlaubt"


def test_fachfehler_mit_eigenem_code():
    fehler = FachFehler(
        "Die Schlussrechnung braucht einen Absetzungsblock.",
        "Zuerst die Abschlagsrechnungen festschreiben.",
        code="absetzungsblock_fehlt",
        status_code=409,
    )
    koerper = fehler.als_koerper()
    assert koerper["code"] == "absetzungsblock_fehlt"
    assert koerper["naechster_schritt"].startswith("Zuerst")


def test_fachfehler_mit_feldhinweisen():
    fehler = FachFehler(
        "Bei gemischten Steuersätzen ist der Satz je Position anzugeben.",
        "Steuersatz bei den markierten Positionen ergänzen.",
        code="ust_kz_gemischt",
        felder={"positionen.2.ust_satz": "Steuersatz fehlt."},
    )
    assert fehler.als_koerper()["felder"]["positionen.2.ust_satz"] == "Steuersatz fehlt."
