"""Kunden und Ansprechpartner (PLAN §5, §7 Phase 1).

Die erste Bearbeitungsmaske; was hier geprüft wird, gilt danach für alle weiteren. Zwei Dinge
stehen im Mittelpunkt: die Konfliktprüfung – der Fehler, den ein Werkzeug für drei Personen am
ehesten macht – und dass die Suche findet, was jemand tippt.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung
from app.modelle import AuditEintrag, Kunde
from tests.conftest_auth import anmelden

BEISPIEL = {
    "name": "Pöllath",
    "ort": "Weiden i. d. OPf.",
    "strasse": "Bahnhofstraße 7",
    "plz": "92637",
    "typ": "b2c",
}


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen):
    nutzer_erzeugen("buha-sd@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha-sd@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen):
    nutzer_erzeugen("team-sd@ip3-energie.de", "team")
    return anmelden(client, "team-sd@ip3-energie.de")


@pytest.fixture
def kunde(buchhaltung) -> dict:
    antwort = buchhaltung.schreiben("POST", "/api/kunden", json=BEISPIEL)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _kunden_anlegen(anmeldung, namen: list[str]) -> None:
    for name in namen:
        teile = name.split(", ")
        koerper = {"name": teile[0], "ort": teile[1] if len(teile) > 1 else None}
        antwort = anmeldung.schreiben("POST", "/api/kunden", json=koerper)
        assert antwort.status_code == 201, antwort.text


class TestBerechtigung:
    def test_ohne_anmeldung_401(self, client):
        assert client.get("/api/kunden").status_code == 401

    def test_team_darf_lesen(self, team, kunde):
        """PLAN §4: team sieht Kunden – nur die Beträge der Projekte bleiben verborgen."""
        antwort = team.client.get("/api/kunden")
        assert antwort.status_code == 200
        assert antwort.json()["gesamt"] >= 1

    def test_team_darf_nicht_schreiben(self, team, kunde):
        neu = team.schreiben("POST", "/api/kunden", json={"name": "Heimlich"})
        assert neu.status_code == 403
        geaendert = team.schreiben(
            "PUT", f"/api/kunden/{kunde['id']}", json={**BEISPIEL, "stand": kunde["stand"]}
        )
        assert geaendert.status_code == 403
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Kunde).where(Kunde.name == "Heimlich")) is None

    def test_ohne_csrf_kein_schreiben(self, buchhaltung):
        antwort = buchhaltung.client.post("/api/kunden", json={"name": "Ohne Token"})
        assert antwort.status_code == 403


class TestAnlegen:
    def test_kundennummer_kommt_aus_dem_nummernkreis(self, kunde):
        """PLAN §3: fortlaufend ab 10001."""
        assert kunde["kunden_nr"] >= 10001

    def test_zweiter_kunde_bekommt_die_naechste_nummer(self, buchhaltung, kunde):
        zweiter = buchhaltung.schreiben("POST", "/api/kunden", json={"name": "Hößl"})
        assert zweiter.json()["kunden_nr"] == kunde["kunden_nr"] + 1

    def test_leerraum_wird_gekuerzt(self, buchhaltung):
        """Führende Leerzeichen sind der häufigste Grund für Doppelte in einer Liste.

        In der Teamliste stand derselbe Projektleiter 16-mal verschieden geschrieben, in 11
        Fällen nur wegen eines Leerzeichens.
        """
        antwort = buchhaltung.schreiben(
            "POST", "/api/kunden", json={"name": "  Weisser  ", "ort": " Weiden "}
        )
        koerper = antwort.json()
        assert koerper["name"] == "Weisser"
        assert koerper["ort"] == "Weiden"

    def test_leerer_name_wird_abgewiesen(self, buchhaltung):
        antwort = buchhaltung.schreiben("POST", "/api/kunden", json={"name": "   "})
        assert antwort.status_code == 422
        koerper = antwort.json()
        assert koerper["code"]
        assert koerper["meldung"]

    def test_anlegen_steht_im_aenderungsprotokoll(self, kunde):
        with lese_sitzung() as sitzung:
            eintraege = list(
                sitzung.scalars(select(AuditEintrag).where(AuditEintrag.aktion == "kunde.angelegt"))
            )
        assert len(eintraege) == 1
        assert eintraege[0].datensatz_id == kunde["id"]
        assert "Pöllath" in str(eintraege[0].neu)


class TestKonfliktpruefung:
    def test_veralteter_stand_wird_abgewiesen(self, buchhaltung, kunde):
        """Zwei Personen, dasselbe Formular: der zweite darf nicht stillschweigend gewinnen."""
        erste = buchhaltung.schreiben(
            "PUT",
            f"/api/kunden/{kunde['id']}",
            json={**BEISPIEL, "telefon": "0961 111", "stand": kunde["stand"]},
        )
        assert erste.status_code == 200
        neuer_stand = erste.json()["stand"]
        assert neuer_stand != kunde["stand"]

        zweite = buchhaltung.schreiben(
            "PUT",
            f"/api/kunden/{kunde['id']}",
            json={**BEISPIEL, "telefon": "0961 222", "stand": kunde["stand"]},
        )
        assert zweite.status_code == 409
        koerper = zweite.json()
        assert koerper["code"] == "stand_veraltet"
        assert "geändert" in koerper["meldung"]
        assert "neu laden" in koerper["naechster_schritt"]

        # Die erste Änderung steht noch, die zweite ist nicht durchgekommen.
        aktuell = buchhaltung.client.get(f"/api/kunden/{kunde['id']}").json()
        assert aktuell["telefon"] == "0961 111"

    def test_stand_waechst_bei_jeder_aenderung(self, buchhaltung, kunde):
        stand = kunde["stand"]
        for nummer in ("1", "2", "3"):
            antwort = buchhaltung.schreiben(
                "PUT",
                f"/api/kunden/{kunde['id']}",
                json={**BEISPIEL, "zusatz": nummer, "stand": stand},
            )
            assert antwort.status_code == 200, antwort.text
            stand = antwort.json()["stand"]


class TestAendern:
    def test_nur_geaenderte_felder_im_protokoll(self, buchhaltung, kunde):
        """Ein Protokoll, das jedes Mal den ganzen Datensatz wiederholt, ist nicht lesbar."""
        buchhaltung.schreiben(
            "PUT",
            f"/api/kunden/{kunde['id']}",
            json={**BEISPIEL, "telefon": "0961 40191 360", "stand": kunde["stand"]},
        )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "kunde.geaendert")
            )
        assert eintrag is not None
        assert set(eintrag.neu) == {"telefon"}
        assert eintrag.alt == {"telefon": None}

    def test_ohne_aenderung_kein_protokolleintrag(self, buchhaltung, kunde):
        antwort = buchhaltung.schreiben(
            "PUT", f"/api/kunden/{kunde['id']}", json={**BEISPIEL, "stand": kunde["stand"]}
        )
        assert antwort.status_code == 200
        with lese_sitzung() as sitzung:
            assert (
                sitzung.scalar(select(AuditEintrag).where(AuditEintrag.aktion == "kunde.geaendert"))
                is None
            )

    def test_kunde_wird_inaktiv_statt_geloescht(self, buchhaltung, kunde):
        """CLAUDE.md Regel 5: an Kunden hängen Projekte."""
        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/kunden/{kunde['id']}",
            json={**BEISPIEL, "status": "inaktiv", "stand": kunde["stand"]},
        )
        assert antwort.status_code == 200
        assert antwort.json()["status"] == "inaktiv"
        # Es gibt keine Löschroute für Kunden.
        assert buchhaltung.schreiben("DELETE", f"/api/kunden/{kunde['id']}").status_code == 405

    def test_unbekannter_kunde_ergibt_404_mit_hinweis(self, buchhaltung):
        antwort = buchhaltung.client.get("/api/kunden/9999")
        assert antwort.status_code == 404
        assert "Kundenliste" in antwort.json()["naechster_schritt"]


class TestSuche:
    @pytest.fixture
    def bestand(self, buchhaltung):
        _kunden_anlegen(
            buchhaltung,
            [
                "Pöllath, Weiden",
                "Pöllath, Erbendorf",
                "Hößl, Grafenwöhr",
                "Ertl, Vohenstrauß",
                "Nicolella, Tännesberg",
                "Weisser, Weiden",
            ],
        )

    @pytest.mark.parametrize(
        ("suche", "erwartet"),
        [
            # Aufgelöst und ohne Punkte – beides muss finden. Niemand tippt „Pöllath".
            ("poellath", 2),
            ("pollath", 2),
            ("Pöllath", 2),
            ("hoessl", 1),
            ("hossl", 1),
            ("vohenstrauss", 1),
            ("vohenstrauß", 1),
            ("taennesberg", 1),
            ("tannesberg", 1),
            # Mehrere Wörter über Name und Ort hinweg, Reihenfolge frei.
            ("poellath weiden", 1),
            ("weiden poellath", 1),
            ("weiden", 2),
            ("gibtesnicht", 0),
        ],
    )
    def test_umlaute_beliebig(self, buchhaltung, bestand, suche, erwartet):
        antwort = buchhaltung.client.get("/api/kunden", params={"suche": suche})
        assert antwort.status_code == 200
        assert antwort.json()["gesamt"] == erwartet, suche

    def test_zahl_im_namen_wird_auch_gefunden(self, buchhaltung):
        """Eine Zahl kann Kundennummer oder Namensteil sein – beides muss finden."""
        buchhaltung.schreiben("POST", "/api/kunden", json={"name": "Volksfestplatz Weiden 2"})
        assert buchhaltung.client.get("/api/kunden", params={"suche": "2"}).json()["gesamt"] >= 1

    def test_kundennummer_findet_direkt(self, buchhaltung, kunde):
        antwort = buchhaltung.client.get("/api/kunden", params={"suche": str(kunde["kunden_nr"])})
        assert antwort.json()["gesamt"] == 1
        assert antwort.json()["eintraege"][0]["id"] == kunde["id"]

    def test_inaktive_sind_standardmaessig_ausgeblendet(self, buchhaltung, kunde):
        buchhaltung.schreiben(
            "PUT",
            f"/api/kunden/{kunde['id']}",
            json={**BEISPIEL, "status": "inaktiv", "stand": kunde["stand"]},
        )
        assert buchhaltung.client.get("/api/kunden").json()["gesamt"] == 0
        assert (
            buchhaltung.client.get("/api/kunden", params={"status": "inaktiv"}).json()["gesamt"]
            == 1
        )
        assert (
            buchhaltung.client.get("/api/kunden", params={"status": "alle"}).json()["gesamt"] == 1
        )


class TestSeitenwechsel:
    @pytest.fixture
    def viele(self, buchhaltung):
        _kunden_anlegen(buchhaltung, [f"Kunde {n:03d}, Weiden" for n in range(1, 31)])

    def test_erste_seite_und_gesamtzahl(self, buchhaltung, viele):
        antwort = buchhaltung.client.get("/api/kunden", params={"anzahl": 10}).json()
        assert antwort["gesamt"] == 30
        assert len(antwort["eintraege"]) == 10
        assert antwort["versatz"] == 0

    def test_zweite_seite_ueberschneidet_sich_nicht(self, buchhaltung, viele):
        erste = buchhaltung.client.get("/api/kunden", params={"anzahl": 10}).json()
        zweite = buchhaltung.client.get("/api/kunden", params={"anzahl": 10, "versatz": 10}).json()
        ids_erste = {e["id"] for e in erste["eintraege"]}
        ids_zweite = {e["id"] for e in zweite["eintraege"]}
        assert ids_erste.isdisjoint(ids_zweite)
        assert zweite["versatz"] == 10

    def test_hoechstwert_wird_erzwungen(self, buchhaltung):
        """Ohne Deckel wäre eine Anfrage ein Export der ganzen Tabelle."""
        antwort = buchhaltung.client.get("/api/kunden", params={"anzahl": 5000})
        assert antwort.status_code == 422

    def test_sortierung_ist_stabil(self, buchhaltung, viele):
        """Ohne feste Sortierung kann eine Zeile auf zwei Seiten auftauchen oder fehlen."""
        alle: list[int] = []
        for versatz in (0, 10, 20):
            seite = buchhaltung.client.get(
                "/api/kunden", params={"anzahl": 10, "versatz": versatz}
            ).json()
            alle += [e["id"] for e in seite["eintraege"]]
        assert len(alle) == len(set(alle)) == 30

    def test_projektzahl_je_kunde(self, buchhaltung, kunde, gesäte_db):
        """Die Liste zeigt, an wie vielen Projekten ein Kunde hängt – vor dem Deaktivieren."""
        from app.datenbank import schreib_sitzung
        from app.modelle import Firma, Projekt

        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            sitzung.add(
                Projekt(projekt_nr=26900, firma_id=firma_id, kunde_id=kunde["id"], typ="projekt")
            )
        eintrag = buchhaltung.client.get("/api/kunden").json()["eintraege"][0]
        assert eintrag["anzahl_projekte"] == 1


class TestAnsprechpartner:
    def test_anlegen_und_lesen(self, buchhaltung, kunde):
        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/kunden/{kunde['id']}/ansprechpartner",
            json={"name": "Michael Bäumler", "funktion": "technik", "telefon": "0961 40191 360"},
        )
        assert antwort.status_code == 201, antwort.text
        assert antwort.json()["name"] == "Michael Bäumler"

        geladen = buchhaltung.client.get(f"/api/kunden/{kunde['id']}").json()
        assert len(geladen["ansprechpartner"]) == 1
        assert geladen["ansprechpartner"][0]["funktion"] == "technik"

    def test_doppelter_name_wird_verstaendlich_abgewiesen(self, buchhaltung, kunde):
        koerper = {"name": "Doppelt"}
        assert (
            buchhaltung.schreiben(
                "POST", f"/api/kunden/{kunde['id']}/ansprechpartner", json=koerper
            ).status_code
            == 201
        )
        zweite = buchhaltung.schreiben(
            "POST", f"/api/kunden/{kunde['id']}/ansprechpartner", json=koerper
        )
        assert zweite.status_code == 409
        assert zweite.json()["code"] == "ansprechpartner_doppelt"
        assert "Vornamen" in zweite.json()["naechster_schritt"]

    def test_aendern_mit_konfliktpruefung(self, buchhaltung, kunde):
        angelegt = buchhaltung.schreiben(
            "POST", f"/api/kunden/{kunde['id']}/ansprechpartner", json={"name": "Erst so"}
        ).json()
        erste = buchhaltung.schreiben(
            "PUT",
            f"/api/ansprechpartner/{angelegt['id']}",
            json={"name": "Dann so", "stand": angelegt["stand"]},
        )
        assert erste.status_code == 200
        zweite = buchhaltung.schreiben(
            "PUT",
            f"/api/ansprechpartner/{angelegt['id']}",
            json={"name": "Und so", "stand": angelegt["stand"]},
        )
        assert zweite.status_code == 409
        assert zweite.json()["code"] == "stand_veraltet"

    def test_loeschen_bleibt_im_protokoll(self, buchhaltung, kunde):
        """Die einzige Löschroute im Leitstand – der Name muss nachvollziehbar bleiben."""
        angelegt = buchhaltung.schreiben(
            "POST",
            f"/api/kunden/{kunde['id']}/ansprechpartner",
            json={"name": "Geht wieder", "telefon": "0961 1"},
        ).json()
        antwort = buchhaltung.schreiben("DELETE", f"/api/ansprechpartner/{angelegt['id']}")
        assert antwort.status_code == 204

        with lese_sitzung() as sitzung:
            from app.modelle import Ansprechpartner

            assert sitzung.get(Ansprechpartner, angelegt["id"]) is None
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "ansprechpartner.geloescht")
            )
        assert eintrag is not None
        assert "Geht wieder" in str(eintrag.alt)

    def test_team_darf_nicht_loeschen(self, team, gesäte_db):
        """Der Ansprechpartner wird direkt in der Datenbank angelegt, nicht über die API.

        Zwei Anmeldungen am selben Testclient teilen ein Cookie: die zweite entwertet das
        CSRF-Token der ersten – der Schutz greift also, aber der Test käme nicht bis zum
        eigentlichen Prüfpunkt.
        """
        from app.datenbank import schreib_sitzung
        from app.modelle import Ansprechpartner, Kunde

        with schreib_sitzung() as sitzung:
            kunde = Kunde(kunden_nr=19999, name="Nur zum Löschen", typ="b2c")
            sitzung.add(kunde)
            sitzung.flush()
            partner = Ansprechpartner(kunde_id=kunde.id, name="Bleibt")
            sitzung.add(partner)
            sitzung.flush()
            partner_id = partner.id

        assert team.schreiben("DELETE", f"/api/ansprechpartner/{partner_id}").status_code == 403
        with lese_sitzung() as sitzung:
            assert sitzung.get(Ansprechpartner, partner_id) is not None

    def test_unbekannter_ansprechpartner_ergibt_404(self, buchhaltung):
        antwort = buchhaltung.schreiben(
            "PUT", "/api/ansprechpartner/9999", json={"name": "X", "stand": "2026-01-01T00:00:00Z"}
        )
        assert antwort.status_code == 404
        assert "neu laden" in antwort.json()["naechster_schritt"]
