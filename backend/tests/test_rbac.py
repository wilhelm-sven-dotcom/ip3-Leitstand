"""Berechtigungsprüfung (PLAN §4, §14).

Der wichtigste Test dieser Datei ist :meth:`TestRoutenstruktur.test_jede_schreibende_route_prueft_berechtigungen`.
Er geht die registrierten Routen durch und verlangt für jede schreibende eine
Berechtigungsprüfung. Damit fällt eine vergessene Prüfung beim Testlauf auf und nicht erst, wenn
jemand Daten ändert, die er nicht ändern darf.

**Der Test muss mit jeder Phase mitwachsen.** Wird seine Ausnahmeliste zum Sammelbecken, ist der
Schutz weg – Einträge dort brauchen eine Begründung.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.main import anwendung_erzeugen
from app.modelle import Berechtigung, Projekt, Rolle
from app.sicherheit.abhaengigkeiten import (
    Berechtigungspruefung,
    Zugriff,
    benoetigt,
    scope_filter,
)
from app.sicherheit.katalog import SCHLUESSEL, SEED_ROLLEN
from tests.conftest_auth import anmelden

# Routen, die ohne Berechtigungsprüfung auskommen – mit Begründung. Diese Liste darf nur mit
# gutem Grund wachsen; sie ist die einzige Lücke im Schutz des Struktur-Regressionstests.
AUSNAHMEN: dict[str, str] = {
    "POST /api/auth/anmelden": "Die Anmeldung selbst kann keine Anmeldung voraussetzen.",
    "POST /api/auth/abmelden": (
        "Abmelden ist immer erlaubt und darf auch mit ungültiger Sitzung nicht fehlschlagen, "
        "sonst bleibt ein Cookie im Browser, das niemand mehr loswird."
    ),
    "POST /api/auth/passwort-aendern": (
        "Das eigene Passwort darf jeder Angemeldete ändern; genau dafür gibt es keinen eigenen "
        "Berechtigungsschlüssel. Die Route prüft die Anmeldung und das bisherige Passwort."
    ),
}


def _routen(app: FastAPI) -> list[APIRoute]:
    """Alle API-Routen der Anwendung, auch die in eingebundenen Routern.

    FastAPI hängt eingebundene Router nicht flach in ``app.routes`` ein, sondern als eigene
    Hüllobjekte, die den ursprünglichen Router unter ``original_router`` tragen. Wer nur
    ``app.routes`` durchsieht, bekommt eine leere Liste – und der Struktur-Regressionstest unten
    wäre wirkungslos, ohne fehlzuschlagen. Genau das ist beim Bau passiert, deshalb prüft
    :meth:`TestRoutenstruktur.test_der_test_findet_ueberhaupt_routen`, dass hier etwas ankommt.
    """
    gefunden: list[APIRoute] = []
    gesehen: set[int] = set()

    def absteigen(knoten: object) -> None:
        if id(knoten) in gesehen:
            return
        gesehen.add(id(knoten))
        for route in getattr(knoten, "routes", []):
            if isinstance(route, APIRoute):
                gefunden.append(route)
            else:
                absteigen(route)
        # Hüllobjekt eines eingebundenen Routers
        ursprung = getattr(knoten, "original_router", None)
        if ursprung is not None:
            absteigen(ursprung)

    absteigen(app)
    return gefunden


def _hat_berechtigungspruefung(route: APIRoute) -> bool:
    """Prüft, ob an der Route eine Berechtigungsprüfung hängt (auch mittelbar)."""
    zu_pruefen = list(route.dependant.dependencies)
    while zu_pruefen:
        abhaengigkeit = zu_pruefen.pop()
        if isinstance(abhaengigkeit.call, Berechtigungspruefung):
            return True
        zu_pruefen.extend(abhaengigkeit.dependencies)
    return False


def _geprueft_gegen(route: APIRoute) -> set[str]:
    schluessel: set[str] = set()
    zu_pruefen = list(route.dependant.dependencies)
    while zu_pruefen:
        abhaengigkeit = zu_pruefen.pop()
        if isinstance(abhaengigkeit.call, Berechtigungspruefung):
            schluessel.update(abhaengigkeit.call.schluessel)
        zu_pruefen.extend(abhaengigkeit.dependencies)
    return schluessel


class TestRoutenstruktur:
    def test_der_test_findet_ueberhaupt_routen(self, test_einstellungen):
        """Absicherung des Prüfwerkzeugs selbst.

        Findet ``_routen`` keine Routen, geht der Strukturtest darunter durch, ohne etwas geprüft
        zu haben – der gefährlichste Fall, weil er nach Erfolg aussieht. Genau das ist beim Bau
        passiert: FastAPI legt eingebundene Router als eigene Objekte ab.
        """
        gefunden = _routen(anwendung_erzeugen(test_einstellungen))
        pfade = {route.path for route in gefunden}
        assert "/api/auth/anmelden" in pfade
        assert "/api/gesundheit" in pfade
        assert len(gefunden) >= 5

    def test_jede_schreibende_route_prueft_berechtigungen(self, test_einstellungen):
        """Der Dauerschutz für PLAN §14: Berechtigungen ausschließlich serverseitig.

        Neue Route mit POST, PUT, PATCH oder DELETE unter /api? Dann braucht sie eine
        ``benoetigt(...)``-Abhängigkeit – oder einen Eintrag in AUSNAHMEN mit Begründung.
        """
        app = anwendung_erzeugen(test_einstellungen)
        ohne_pruefung: list[str] = []

        for route in _routen(app):
            if not route.path.startswith("/api"):
                continue
            for methode in route.methods or set():
                if methode in ("GET", "HEAD", "OPTIONS"):
                    continue
                kennung = f"{methode} {route.path}"
                if kennung in AUSNAHMEN:
                    continue
                if not _hat_berechtigungspruefung(route):
                    ohne_pruefung.append(kennung)

        assert ohne_pruefung == [], (
            "Schreibende Routen ohne Berechtigungsprüfung:\n"
            + "\n".join(f"  {eintrag}" for eintrag in ohne_pruefung)
            + "\n\nEntweder benoetigt('ressource.aktion') als Abhängigkeit ergänzen oder – mit "
            "Begründung – in tests/test_rbac.py in AUSNAHMEN aufnehmen."
        )

    def test_ausnahmen_gibt_es_wirklich(self, test_einstellungen):
        """Eine Ausnahme für eine Route, die es nicht mehr gibt, verdeckt später eine echte Lücke."""
        app = anwendung_erzeugen(test_einstellungen)
        vorhandene = {
            f"{methode} {route.path}"
            for route in _routen(app)
            for methode in (route.methods or set())
        }
        veraltet = set(AUSNAHMEN) - vorhandene
        assert veraltet == set(), f"Ausnahmen für nicht vorhandene Routen: {sorted(veraltet)}"

    def test_jede_ausnahme_hat_eine_begruendung(self):
        for kennung, begruendung in AUSNAHMEN.items():
            assert len(begruendung) > 30, f"{kennung}: Begründung fehlt oder ist zu knapp"

    def test_geprueft_wird_nur_gegen_bekannte_schluessel(self, test_einstellungen):
        app = anwendung_erzeugen(test_einstellungen)
        for route in _routen(app):
            for schluessel in _geprueft_gegen(route):
                assert schluessel in SCHLUESSEL, f"{route.path}: {schluessel} nicht im Katalog"


class TestKatalogUndDatenbank:
    def test_seed_legt_jeden_katalogschluessel_an(self, gesäte_db):
        with lese_sitzung() as sitzung:
            in_db = {b.schluessel for b in sitzung.scalars(select(Berechtigung)).all()}
        assert SCHLUESSEL - in_db == set(), "Berechtigungen fehlen in der Datenbank"

    def test_keine_waisen_in_der_datenbank(self, gesäte_db):
        """Ein Schlüssel in der Datenbank, den der Katalog nicht kennt, wird nie geprüft."""
        with lese_sitzung() as sitzung:
            in_db = {b.schluessel for b in sitzung.scalars(select(Berechtigung)).all()}
        assert in_db - SCHLUESSEL == set(), "Berechtigungen ohne Eintrag im Katalog"

    def test_seed_rollen_stehen_in_der_datenbank(self, gesäte_db):
        with lese_sitzung() as sitzung:
            namen = {r.name for r in sitzung.scalars(select(Rolle)).all()}
        assert namen == {r.name for r in SEED_ROLLEN}


class TestDurchsetzung:
    """Prüfung an echten Routen: eine kleine Anwendung mit Routen für jeden Fall."""

    @pytest.fixture
    def app_mit_testrouten(self, test_einstellungen) -> FastAPI:
        from fastapi import APIRouter

        app = anwendung_erzeugen(test_einstellungen)
        router = APIRouter(prefix="/api/pruefstand", tags=["Prüfstand"])

        @router.get(
            "/nur-lesen",
            operation_id="pruefstand_lesen",
            summary="Braucht projekte.lesen",
            dependencies=[Depends(benoetigt("projekte.lesen"))],
        )
        def _lesen() -> dict[str, bool]:
            return {"gelesen": True}

        @router.get(
            "/mit-werten",
            operation_id="pruefstand_werte",
            summary="Braucht projekte.werte_lesen",
            dependencies=[Depends(benoetigt("projekte.werte_lesen"))],
        )
        def _werte() -> dict[str, bool]:
            return {"betraege": True}

        @router.post(
            "/schreiben",
            operation_id="pruefstand_schreiben",
            summary="Braucht projekte.schreiben",
            dependencies=[Depends(benoetigt("projekte.schreiben"))],
        )
        def _schreiben() -> dict[str, bool]:
            return {"geschrieben": True}

        @router.get(
            "/oder-verknuepft",
            operation_id="pruefstand_oder",
            summary="Braucht eine von zwei Berechtigungen",
            dependencies=[Depends(benoetigt("cockpit.lesen", "umsatz.lesen"))],
        )
        def _oder() -> dict[str, bool]:
            return {"gesehen": True}

        app.include_router(router)
        return app

    @pytest.fixture
    def pruefstand(self, app_mit_testrouten: FastAPI, nutzer_erzeugen):
        nutzer_erzeugen("bh@ip3-energie.de", "buchhaltung")
        nutzer_erzeugen("team@ip3-energie.de", "team")
        nutzer_erzeugen("chef@ip3-energie.de", "admin")
        with TestClient(app_mit_testrouten) as client:
            yield client

    def test_ohne_anmeldung_401(self, pruefstand):
        assert pruefstand.get("/api/pruefstand/nur-lesen").status_code == 401

    def test_mit_berechtigung_200(self, pruefstand):
        anmelden(pruefstand, "team@ip3-energie.de")
        assert pruefstand.get("/api/pruefstand/nur-lesen").status_code == 200

    def test_ohne_berechtigung_403_mit_verstaendlicher_meldung(self, pruefstand):
        """Die Rolle team sieht keine Beträge (PLAN §4)."""
        anmelden(pruefstand, "team@ip3-energie.de")
        antwort = pruefstand.get("/api/pruefstand/mit-werten")
        assert antwort.status_code == 403
        koerper = antwort.json()
        assert koerper["code"] == "keine_berechtigung"
        assert "Berechtigung" in koerper["meldung"]
        assert koerper["naechster_schritt"]
        # Kein Fachjargon und kein Schlüsselname in der Meldung.
        assert "projekte.werte_lesen" not in koerper["meldung"]

    def test_buchhaltung_sieht_betraege(self, pruefstand):
        anmelden(pruefstand, "bh@ip3-energie.de")
        assert pruefstand.get("/api/pruefstand/mit-werten").status_code == 200

    def test_team_darf_nicht_schreiben(self, pruefstand):
        angemeldet = anmelden(pruefstand, "team@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/pruefstand/schreiben")
        assert antwort.status_code == 403

    def test_buchhaltung_darf_schreiben(self, pruefstand):
        angemeldet = anmelden(pruefstand, "bh@ip3-energie.de")
        antwort = angemeldet.schreiben("POST", "/api/pruefstand/schreiben")
        assert antwort.status_code == 200

    def test_oder_verknuepfung(self, pruefstand):
        """umsatz.lesen genügt, cockpit.lesen ist nicht nötig."""
        anmelden(pruefstand, "bh@ip3-energie.de")
        assert pruefstand.get("/api/pruefstand/oder-verknuepft").status_code == 200
        pruefstand.post("/api/auth/abmelden")
        anmelden(pruefstand, "team@ip3-energie.de")
        assert pruefstand.get("/api/pruefstand/oder-verknuepft").status_code == 403

    def test_admin_darf_alles(self, pruefstand):
        angemeldet = anmelden(pruefstand, "chef@ip3-energie.de")
        assert pruefstand.get("/api/pruefstand/nur-lesen").status_code == 200
        assert pruefstand.get("/api/pruefstand/mit-werten").status_code == 200
        assert pruefstand.get("/api/pruefstand/oder-verknuepft").status_code == 200
        assert angemeldet.schreiben("POST", "/api/pruefstand/schreiben").status_code == 200

    def test_rollenaenderung_wirkt_ohne_neuanmeldung(self, pruefstand):
        """Die Rechte werden je Anfrage gelesen; ein Zwischenspeicher wäre gefährlich.

        Wird jemandem ein Recht entzogen, darf er nicht bis zum Ablauf seiner Sitzung
        weiterarbeiten.
        """
        anmelden(pruefstand, "team@ip3-energie.de")
        assert pruefstand.get("/api/pruefstand/mit-werten").status_code == 403

        with schreib_sitzung() as sitzung:
            from app.modelle import User

            nutzer = sitzung.scalar(select(User).where(User.email == "team@ip3-energie.de"))
            buchhaltung = sitzung.scalar(select(Rolle).where(Rolle.name == "buchhaltung"))
            nutzer.rollen.append(buchhaltung)

        assert pruefstand.get("/api/pruefstand/mit-werten").status_code == 200

    def test_rechte_stehen_in_der_antwort_von_ich(self, pruefstand):
        """Die Oberfläche blendet danach aus – als Ergänzung, nicht als Sperre."""
        anmelden(pruefstand, "team@ip3-energie.de")
        rechte = pruefstand.get("/api/auth/ich").json()["rechte"]
        assert "projekte.lesen" in rechte
        assert "projekte.werte_lesen" not in rechte


class TestScope:
    def test_scope_eigene_schraenkt_ein(self, gesäte_db, test_einstellungen):
        """Ein Projektleiter mit Scope 'eigene' sieht nur seine Projekte (PLAN §4)."""
        from app.modelle import Firma, Kunde, User

        with schreib_sitzung() as sitzung:
            firma = sitzung.scalar(select(Firma))
            kunde = Kunde(kunden_nr=10500, name="Testkunde", typ="b2b")
            sitzung.add(kunde)
            sitzung.flush()

            eigene_rolle = Rolle(name="projektleiter", beschreibung="Nur eigene Projekte")
            recht = Berechtigung(schluessel="projekte.lesen", scope="eigene")
            eigene_rolle.berechtigungen.append(recht)
            from app.sicherheit import passwort as pw

            pl = User(
                name="Projektleiter",
                email="pl@ip3-energie.de",
                pw_hash=pw.hashen("x"),
                rollen=[eigene_rolle],
            )
            sitzung.add(pl)
            sitzung.flush()

            sitzung.add_all(
                [
                    Projekt(
                        projekt_nr=26101,
                        firma_id=firma.id,
                        kunde_id=kunde.id,
                        pl_user_id=pl.id,
                    ),
                    Projekt(projekt_nr=26102, firma_id=firma.id, kunde_id=kunde.id),
                ]
            )
            sitzung.flush()
            pl_id = pl.id
            rechte = pl.berechtigungsschluessel()

        assert rechte["projekte.lesen"] == "eigene"

        with lese_sitzung() as sitzung:
            nutzer = sitzung.get(User, pl_id)
            zugriff = Zugriff(nutzer=nutzer, sitzung=None, rechte=rechte)
            abfrage = scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)
            nummern = {p.projekt_nr for p in sitzung.scalars(abfrage).all()}
        assert nummern == {26101}

    def test_scope_alle_zeigt_alles(self, gesäte_db):
        from app.modelle import Firma, Kunde, User

        with schreib_sitzung() as sitzung:
            firma = sitzung.scalar(select(Firma))
            kunde = Kunde(kunden_nr=10501, name="Testkunde", typ="b2b")
            sitzung.add(kunde)
            sitzung.flush()
            sitzung.add_all(
                [
                    Projekt(projekt_nr=26201, firma_id=firma.id, kunde_id=kunde.id),
                    Projekt(projekt_nr=26202, firma_id=firma.id, kunde_id=kunde.id),
                ]
            )
            sitzung.flush()
            admin = sitzung.scalar(select(User))
            admin_id = admin.id
            rechte = admin.berechtigungsschluessel()

        with lese_sitzung() as sitzung:
            nutzer = sitzung.get(User, admin_id)
            zugriff = Zugriff(nutzer=nutzer, sitzung=None, rechte=rechte)
            abfrage = scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)
            assert len(sitzung.scalars(abfrage).all()) == 2

    def test_alle_gewinnt_gegen_eigene(self, gesäte_db):
        """Zwei Rollen, eine mit 'eigene', eine mit 'alle': der weitere Scope setzt sich durch."""
        from app.modelle import User
        from app.sicherheit import passwort as pw

        with schreib_sitzung() as sitzung:
            eng = Rolle(name="pl-eng", beschreibung="eigene")
            eng.berechtigungen.append(Berechtigung(schluessel="projekte.lesen", scope="eigene"))
            weit = sitzung.scalar(select(Rolle).where(Rolle.name == "buchhaltung"))
            nutzer = User(
                name="Doppelrolle",
                email="doppel@ip3-energie.de",
                pw_hash=pw.hashen("x"),
                rollen=[eng, weit],
            )
            sitzung.add(nutzer)
            sitzung.flush()
            assert nutzer.berechtigungsschluessel()["projekte.lesen"] == "alle"

    def test_ohne_berechtigung_gilt_der_engste_fall(self, gesäte_db):
        from app.modelle import User

        with lese_sitzung() as sitzung:
            admin = sitzung.scalar(select(User))
            zugriff = Zugriff(nutzer=admin, sitzung=None, rechte={})
            assert zugriff.scope("projekte.lesen") == "eigene"
            assert zugriff.nur_eigene("projekte.lesen") is True
            assert zugriff.darf("projekte.lesen") is False


class TestPruefungBeimAufbau:
    def test_tippfehler_im_schluessel_faellt_sofort_auf(self):
        """Nicht erst bei der ersten Anfrage: sonst wäre die Route bis dahin ungeschützt."""
        with pytest.raises(KeyError, match="steht nicht im Katalog"):
            benoetigt("projekte.leesen")

    def test_lesbare_darstellung(self):
        pruefung = benoetigt("projekte.lesen", "umsatz.lesen")
        assert repr(pruefung) == "benoetigt(projekte.lesen, umsatz.lesen)"
