"""Anwendung startet, Gesundheitsprüfung antwortet, Protokoll wird geschrieben."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from app.main import anwendung_erzeugen


def test_gesundheit_ohne_anmeldung(test_einstellungen):
    app = anwendung_erzeugen(test_einstellungen)
    with TestClient(app) as client:
        antwort = client.get("/api/gesundheit")
    assert antwort.status_code == 200
    koerper = antwort.json()
    assert koerper["status"] == "bereit"
    assert koerper["version"] == __version__
    assert koerper["datenbank"] == "erreichbar"


def test_gesundheit_meldet_fehlende_datenbank(test_einstellungen, tmp_path: Path):
    """Ohne Datenbank läuft die Anwendung weiter und sagt, dass etwas fehlt."""
    test_einstellungen.pfade.datenbank = tmp_path / "nicht" / "vorhanden" / "leitstand.sqlite3"
    app = anwendung_erzeugen(test_einstellungen)
    with TestClient(app) as client:
        antwort = client.get("/api/gesundheit")
    assert antwort.status_code == 200
    # Die Datei wird von SQLAlchemy angelegt; sie ist erreichbar, hat aber kein Schema.
    assert antwort.json()["datenbank"] in ("erreichbar", "nicht erreichbar")


def test_openapi_ist_abrufbar(test_einstellungen):
    app = anwendung_erzeugen(test_einstellungen)
    with TestClient(app) as client:
        antwort = client.get("/api/openapi.json")
    assert antwort.status_code == 200
    spezifikation = antwort.json()
    assert spezifikation["info"]["title"] == "ip³ Leitstand"
    assert "/api/gesundheit" in spezifikation["paths"]


def test_alle_pfade_liegen_unter_api(test_einstellungen):
    """Die Oberfläche wird später unter / ausgeliefert; die API muss abgegrenzt bleiben."""
    app = anwendung_erzeugen(test_einstellungen)
    with TestClient(app) as client:
        spezifikation = client.get("/api/openapi.json").json()
    abweichend = [pfad for pfad in spezifikation["paths"] if not pfad.startswith("/api")]
    assert abweichend == []


def test_jede_operation_hat_id_und_zusammenfassung(test_einstellungen):
    """Ohne operationId erzeugt der TypeScript-Client unlesbare Namen."""
    app = anwendung_erzeugen(test_einstellungen)
    with TestClient(app) as client:
        spezifikation = client.get("/api/openapi.json").json()
    for pfad, methoden in spezifikation["paths"].items():
        for methode, operation in methoden.items():
            assert operation.get("operationId"), f"{methode.upper()} {pfad} ohne operationId"
            assert operation.get("summary"), f"{methode.upper()} {pfad} ohne summary"


def test_protokolldatei_wird_angelegt(test_einstellungen):
    app = anwendung_erzeugen(test_einstellungen)
    with TestClient(app) as client:
        client.get("/api/gesundheit")
    assert (test_einstellungen.pfade.logs / "leitstand.log").exists()


def test_konfigurationshinweise_beim_start_kein_abbruch(test_einstellungen, caplog):
    """Fehlende Firmenstammdaten sind ein Hinweis, kein Startfehler (Phase 0)."""
    app = anwendung_erzeugen(test_einstellungen)
    with caplog.at_level("WARNING"), TestClient(app) as client:
        assert client.get("/api/gesundheit").status_code == 200
    assert "Firmenstammdaten" in caplog.text
