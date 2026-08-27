"""OpenAPI-Spezifikation: Frische und Verwendbarkeit für den TypeScript-Client (PLAN §2).

Der wichtigste Test hier ist der Frische-Test. Aus ``backend/openapi.json`` erzeugt das
Frontend seine Typen; ist die Datei veraltet, übersetzt das Frontend gegen eine Schnittstelle,
die es nicht mehr gibt – und der Fehler zeigt sich erst im Betrieb.
"""

from __future__ import annotations

import json

from app.werkzeuge.openapi_export import als_text, ist_aktuell, spezifikation, standardpfad


class TestFrische:
    def test_datei_ist_auf_dem_stand_der_anwendung(self, test_einstellungen):
        """Nach jeder Änderung an Routen oder Schemas neu erzeugen.

        Befehl: ``uv run ip3-leitstand openapi``, danach im Frontend ``npm run api``.
        """
        assert standardpfad().exists(), (
            "backend/openapi.json fehlt. Erzeugen mit: uv run ip3-leitstand openapi"
        )
        assert ist_aktuell(), (
            "backend/openapi.json ist nicht auf dem Stand der Anwendung.\n"
            "Nächster Schritt: 'uv run ip3-leitstand openapi' ausführen, "
            "danach im Ordner frontend 'npm run api'."
        )

    def test_export_ist_wiederholbar(self, test_einstellungen):
        """Zwei Läufe müssen dasselbe ergeben, sonst wäre der Frische-Test wertlos."""
        assert als_text() == als_text()

    def test_datei_ist_lesbares_json(self):
        inhalt = json.loads(standardpfad().read_text(encoding="utf-8"))
        assert inhalt["info"]["title"] == "ip³ Leitstand"


class TestVertrag:
    def test_alle_pfade_liegen_unter_api(self, test_einstellungen):
        """Die Oberfläche wird unter / ausgeliefert; die API muss abgegrenzt bleiben."""
        abweichend = [pfad for pfad in spezifikation()["paths"] if not pfad.startswith("/api")]
        assert abweichend == []

    def test_jede_operation_hat_id_und_zusammenfassung(self, test_einstellungen):
        """Ohne operationId erzeugt der Client unlesbare Namen, ohne summary keine Hilfe."""
        for pfad, methoden in spezifikation()["paths"].items():
            for methode, operation in methoden.items():
                assert operation.get("operationId"), f"{methode.upper()} {pfad}: operationId fehlt"
                assert operation.get("summary"), f"{methode.upper()} {pfad}: summary fehlt"

    def test_geschuetzte_routen_dokumentieren_401_und_403(self, test_einstellungen):
        """Sonst fehlen dem Client die Typen für die Fehlerbehandlung.

        Ausgenommen sind die Anmelderoutinen und die Gesundheitsprüfung: dort gibt es
        naturgemäß keine Berechtigungsprüfung.
        """
        ohne_anmeldung = {
            "/api/gesundheit",
            "/api/auth/anmelden",
            "/api/auth/abmelden",
        }
        fehlend: list[str] = []
        for pfad, methoden in spezifikation()["paths"].items():
            if pfad in ohne_anmeldung:
                continue
            for methode, operation in methoden.items():
                antworten = operation.get("responses", {})
                if "401" not in antworten:
                    fehlend.append(f"{methode.upper()} {pfad}: 401 nicht dokumentiert")
        assert fehlend == [], "\n".join(fehlend)

    def test_operationen_sind_eindeutig(self, test_einstellungen):
        """Zwei Routen mit derselben operationId ergeben im Client eine überschriebene Funktion."""
        ids: list[str] = []
        for methoden in spezifikation()["paths"].values():
            for operation in methoden.values():
                ids.append(operation["operationId"])
        assert len(ids) == len(set(ids)), "Doppelte operationId"

    def test_fehlerkoerper_ist_beschrieben(self, test_einstellungen):
        """Der Aufbau {code, meldung, naechster_schritt} soll aus der Spezifikation hervorgehen."""
        spez = spezifikation()
        beschreibung = spez["info"].get("description", "")
        assert "code" in beschreibung
        assert "naechster_schritt" in beschreibung
