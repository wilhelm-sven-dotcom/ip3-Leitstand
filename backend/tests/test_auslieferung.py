"""Auslieferung der Oberfläche über das Backend (PLAN §2: ein Dienst).

Die Tests prüfen genau die vier Punkte, die im Betrieb Ärger machen würden: dass tiefe
Adressen nach einem Neuladen funktionieren, dass API-Pfade JSON bleiben, dass die index.html
nicht zwischengespeichert wird und dass ein fehlender Build den Dienst nicht aufhält.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import anwendung_erzeugen


@pytest.fixture
def frontend_build(tmp_path: Path) -> Path:
    """Eine gebaute Oberfläche, wie Vite sie hinterlässt."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html lang="de"><body><div id="wurzel"></div>'
        '<script type="module" src="/assets/index-abc123.js"></script></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log('leitstand')", encoding="utf-8")
    (dist / "assets" / "index-def456.css").write_text(":root{}", encoding="utf-8")
    (dist / "app-icon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


@pytest.fixture
def client_mit_oberflaeche(test_einstellungen, db_pfad: Path, frontend_build: Path):
    test_einstellungen.pfade.frontend = frontend_build
    with TestClient(anwendung_erzeugen(test_einstellungen)) as client:
        yield client


class TestOberflaeche:
    def test_startseite_liefert_index(self, client_mit_oberflaeche):
        antwort = client_mit_oberflaeche.get("/")
        assert antwort.status_code == 200
        assert antwort.headers["content-type"].startswith("text/html")
        assert 'id="wurzel"' in antwort.text

    def test_index_wird_nicht_zwischengespeichert(self, client_mit_oberflaeche):
        """Sonst lädt der Browser nach einem Update altes JavaScript gegen eine neue API.

        Ein Fehler, der nur einzelne Nutzer trifft und von außen kaum zu erkennen ist.
        """
        antwort = client_mit_oberflaeche.get("/")
        assert "no-store" in antwort.headers["cache-control"]

    def test_tiefe_adresse_liefert_ebenfalls_index(self, client_mit_oberflaeche):
        """Ein Verweis auf /projekte/26014 muss auch beim direkten Aufruf funktionieren."""
        antwort = client_mit_oberflaeche.get("/projekte/26014")
        assert antwort.status_code == 200
        assert 'id="wurzel"' in antwort.text

    def test_gehashte_datei_wird_ausgeliefert(self, client_mit_oberflaeche):
        antwort = client_mit_oberflaeche.get("/assets/index-abc123.js")
        assert antwort.status_code == 200
        assert "leitstand" in antwort.text

    def test_einzelne_datei_im_wurzelverzeichnis(self, client_mit_oberflaeche):
        antwort = client_mit_oberflaeche.get("/app-icon.svg")
        assert antwort.status_code == 200
        assert antwort.text == "<svg/>"

    def test_kein_ausbruch_aus_dem_verzeichnis(self, client_mit_oberflaeche):
        """Ein Pfad mit .. darf keine Datei außerhalb der Oberfläche ausliefern."""
        antwort = client_mit_oberflaeche.get("/../../backend/config.toml")
        # Entweder abgewiesen oder der Rückfall auf index.html – niemals Dateiinhalt.
        assert "config.toml" not in antwort.text
        assert "[pfade]" not in antwort.text


class TestApiBleibtGetrennt:
    def test_bekannte_api_route_funktioniert_weiter(self, client_mit_oberflaeche):
        """Der Rückfall darf die API nicht verschlucken."""
        antwort = client_mit_oberflaeche.get("/api/gesundheit")
        assert antwort.status_code == 200
        assert antwort.json()["status"] == "bereit"

    def test_unbekannter_api_pfad_bleibt_json(self, client_mit_oberflaeche):
        """Ein Tippfehler in einem API-Pfad soll einen Fehlerkörper liefern, keine HTML-Seite."""
        antwort = client_mit_oberflaeche.get("/api/gibt-es-nicht")
        assert antwort.status_code == 404
        assert antwort.headers["content-type"].startswith("application/json")
        koerper = antwort.json()
        assert koerper["code"] == "nicht_gefunden"
        assert koerper["naechster_schritt"]

    def test_api_ohne_unterpfad_bleibt_json(self, client_mit_oberflaeche):
        antwort = client_mit_oberflaeche.get("/api")
        assert antwort.headers["content-type"].startswith("application/json")

    def test_geschuetzte_route_antwortet_mit_401_nicht_mit_html(self, client_mit_oberflaeche):
        antwort = client_mit_oberflaeche.get("/api/auth/ich")
        assert antwort.status_code == 401
        assert antwort.json()["code"] == "nicht_angemeldet"


class TestOhneBuild:
    def test_anwendung_startet_ohne_oberflaeche(self, test_einstellungen, db_pfad: Path, caplog):
        """Ein Dienst, der wegen fehlender Oberfläche nicht startet, verhindert die Fehlersuche."""
        test_einstellungen.pfade.frontend = None
        app = anwendung_erzeugen(test_einstellungen)
        with TestClient(app) as client:
            assert client.get("/api/gesundheit").status_code == 200

    def test_hinweis_bei_fehlendem_build(self, test_einstellungen, db_pfad: Path, tmp_path, caplog):
        test_einstellungen.pfade.frontend = tmp_path / "nicht-gebaut"
        with caplog.at_level("WARNING"):
            app = anwendung_erzeugen(test_einstellungen)
            with TestClient(app) as client:
                assert client.get("/api/gesundheit").status_code == 200
        assert "npm run build" in caplog.text

    def test_api_bleibt_ohne_oberflaeche_nutzbar(self, test_einstellungen, db_pfad: Path, tmp_path):
        test_einstellungen.pfade.frontend = tmp_path / "leer"
        app = anwendung_erzeugen(test_einstellungen)
        with TestClient(app) as client:
            assert client.get("/api/openapi.json").status_code == 200
