"""API der Fakturierung (PLAN §7 Phase 3, §4).

Geprüft wird hier nicht die Rechnung – das tun test_belege.py und test_belegarten.py –, sondern
was über die Schnittstelle geht: welche Berechtigung welche Route öffnet, dass der
Sichtbarkeits-Scope auch in der Belegliste wirkt, und dass jede Sperre als deutscher Satz mit
nächstem Schritt ankommt und nicht als Datenbankfehler (CLAUDE.md Regel 8).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import (
    AuditEintrag,
    Firma,
    Kunde,
    Meilenstein,
    Projekt,
    User,
    Zahlungsplanposition,
)
from tests.conftest_auth import anmelden


@pytest.fixture
def admin(client, nutzer_erzeugen, vollstaendige_firma):
    nutzer_erzeugen("admin-re@ip3-energie.de", "admin")
    return anmelden(client, "admin-re@ip3-energie.de")


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen, vollstaendige_firma):
    nutzer_erzeugen("buha-re@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha-re@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen, vollstaendige_firma):
    nutzer_erzeugen("team-re@ip3-energie.de", "team")
    return anmelden(client, "team-re@ip3-energie.de")


@pytest.fixture
def bestand(gesäte_db) -> dict:
    """Zwei Projekte mit Zahlungsplan, das zweite mit einem anderen Projektleiter."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(
            kunden_nr=15001,
            name="Maschinenbau Köstler GmbH",
            strasse="Bahnhofstraße 12",
            plz="92660",
            ort="Neustadt a. d. Waldnaab",
            ust_id="DE123456789",
            typ="b2b",
        )
        sitzung.add(kunde)
        sitzung.flush()
        eigenes = Projekt(
            projekt_nr=26014,
            firma_id=firma_id,
            kunde_id=kunde.id,
            ab_wert_netto=36750000,
            ust_kz="19",
            status="in_bau",
        )
        fremdes = Projekt(
            projekt_nr=26015,
            firma_id=firma_id,
            kunde_id=kunde.id,
            ab_wert_netto=1000000,
            ust_kz="19",
            status="in_bau",
        )
        sitzung.add_all([eigenes, fremdes])
        sitzung.flush()
        positionen = [
            Zahlungsplanposition(
                projekt_id=projekt.id,
                pos_nr=nummer,
                bezeichnung=f"{nummer}. Abschlag",
                gewerk="pv",
                art="abschlag",
                betrag_netto=9187500,
                plan_monat="2026-09",
                trigger_status="lieferung" if nummer == 2 else None,
            )
            for projekt in (eigenes, fremdes)
            for nummer in (1, 2)
        ]
        sitzung.add_all(positionen)
        sitzung.flush()
        return {
            "firma": firma_id,
            "kunde": kunde.id,
            "eigenes": eigenes.id,
            "fremdes": fremdes.id,
            "positionen": [p.id for p in positionen],
        }


def _abschlag(sitzung_client, position_id: int, zeitraum: str = "Juli 2026") -> dict:
    antwort = sitzung_client.schreiben(
        "POST",
        f"/api/rechnungen/aus-zahlungsplan/{position_id}",
        json={"leistungszeitraum": zeitraum},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


class TestBerechtigungen:
    def test_team_darf_keine_belege_sehen(self, team, bestand):
        assert team.client.get("/api/rechnungen").status_code == 403

    def test_team_darf_nichts_erzeugen(self, team, bestand):
        antwort = team.schreiben(
            "POST", f"/api/rechnungen/aus-zahlungsplan/{bestand['positionen'][0]}", json={}
        )
        assert antwort.status_code == 403

    def test_buchhaltung_darf_erzeugen_und_festschreiben(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        antwort = buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["beleg"]["rechnung_nr"] == "RE-2026-0001"

    def test_buchhaltung_darf_nicht_stornieren(self, buchhaltung, bestand):
        """Eine Korrektur an einem gestellten Beleg ist Sache der Geschäftsführung (PLAN §4)."""
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        antwort = buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/storno", json={})
        assert antwort.status_code == 403

    def test_admin_darf_stornieren(self, admin, bestand):
        beleg = _abschlag(admin, bestand["positionen"][0])
        admin.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        antwort = admin.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/storno", json={"grund": "Falscher Empfänger"}
        )
        assert antwort.status_code == 201, antwort.text
        assert antwort.json()["art"] == "storno"

    def test_ohne_anmeldung_kein_zugriff(self, client, bestand):
        assert client.get("/api/rechnungen").status_code == 401


class TestSichtbarkeit:
    """Der Scope ``eigene`` wirkt über das Projekt (PLAN §4).

    Die Berechtigung mit engem Scope ist im Datenmodell eine **eigene Zeile** in
    ``berechtigungen`` (``schluessel`` plus ``scope``), keine Eigenschaft der Verknüpfung – so
    macht es der Seed, und so wird sie hier gesetzt.
    """

    def _nur_eigene(self, client, nutzer_erzeugen, bestand):
        from app.modelle import Berechtigung, Rolle

        nutzer_id = nutzer_erzeugen("pl-re@ip3-energie.de", "team")
        with schreib_sitzung() as sitzung:
            rolle = Rolle(name="pl-fakturierung", beschreibung="Belege nur eigener Projekte")
            sitzung.add(rolle)
            eigene = Berechtigung(
                schluessel="projekte.lesen", scope="eigene", beschreibung="nur eigene"
            )
            sitzung.add(eigene)
            rolle.berechtigungen.append(eigene)
            for schluessel in ("rechnungen.lesen", "rechnungen.erstellen", "projekte.werte_lesen"):
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
            sitzung.get(Projekt, bestand["eigenes"]).pl_user_id = nutzer_id
        return anmelden(client, "pl-re@ip3-energie.de")

    def test_scope_eigene_beschraenkt_die_belegliste(
        self, client, nutzer_erzeugen, buchhaltung, bestand
    ):
        eigener = _abschlag(buchhaltung, bestand["positionen"][0])
        fremder = _abschlag(buchhaltung, bestand["positionen"][2])
        pl = self._nur_eigene(client, nutzer_erzeugen, bestand)

        nummern = {z["id"] for z in pl.client.get("/api/rechnungen").json()["zeilen"]}
        assert eigener["id"] in nummern
        assert fremder["id"] not in nummern
        assert pl.client.get(f"/api/rechnungen/{fremder['id']}").status_code == 404

    def test_beleg_ohne_projekt_bleibt_beim_engen_scope_verborgen(
        self, client, nutzer_erzeugen, buchhaltung, bestand
    ):
        """Ohne Projekt gibt es keinen Projektleiter, an dem sich „eigene" festmachen ließe."""
        antwort = buchhaltung.schreiben(
            "POST",
            "/api/rechnungen/service",
            json={"kunde_id": bestand["kunde"], "leistungszeitraum": "August 2026"},
        )
        assert antwort.status_code == 201, antwort.text
        service_id = antwort.json()["id"]
        pl = self._nur_eigene(client, nutzer_erzeugen, bestand)
        assert pl.client.get(f"/api/rechnungen/{service_id}").status_code == 404

    def test_nicht_gefunden_erklaert_den_moeglichen_grund(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/rechnungen/98765")
        assert antwort.status_code == 404
        koerper = antwort.json()
        assert "nicht gefunden" in koerper["meldung"]
        assert "Sven oder Michael" in koerper["naechster_schritt"]


class TestEntwuerfePflegen:
    def test_kopf_aendern_mit_stand(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/rechnungen/{beleg['id']}",
            json={
                "stand": beleg["stand"],
                "datum": "2026-08-27",
                "leistungszeitraum": "01.07.–27.08.2026",
                "ust_kz": "19",
                "betreff": "1. Abschlagsrechnung",
                "anschreiben": "Sehr geehrte Damen und Herren,",
                "faellig_am": "2026-09-10",
            },
        )
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["leistungszeitraum"] == "01.07.–27.08.2026"

    def test_veralteter_stand_ergibt_einen_konflikt(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        rumpf = {
            "stand": beleg["stand"],
            "datum": "2026-08-27",
            "leistungszeitraum": "Juli 2026",
            "ust_kz": "19",
        }
        buchhaltung.schreiben(
            "PUT", f"/api/rechnungen/{beleg['id']}", json={**rumpf, "betreff": "Erste Änderung"}
        )
        antwort = buchhaltung.schreiben(
            "PUT", f"/api/rechnungen/{beleg['id']}", json={**rumpf, "betreff": "Zweite Änderung"}
        )
        assert antwort.status_code == 409
        assert "geändert" in antwort.json()["meldung"]

    def test_positionen_anlegen_aendern_loeschen(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        angelegt = buchhaltung.schreiben(
            "POST",
            f"/api/rechnungen/{beleg['id']}/positionen",
            json={"bezeichnung": "Zusatzarbeit", "ep_netto": 50000, "ust_satz": 190},
        )
        assert angelegt.status_code == 201, angelegt.text
        daten = angelegt.json()
        assert len(daten["positionen"]) == 2
        assert daten["netto"] == 9187500 + 50000

        position_id = daten["positionen"][1]["id"]
        geaendert = buchhaltung.schreiben(
            "PUT",
            f"/api/rechnungen/{beleg['id']}/positionen/{position_id}",
            json={"bezeichnung": "Zusatzarbeit", "ep_netto": 60000, "ust_satz": 190},
        )
        assert geaendert.json()["netto"] == 9187500 + 60000

        geloescht = buchhaltung.schreiben(
            "DELETE", f"/api/rechnungen/{beleg['id']}/positionen/{position_id}"
        )
        assert geloescht.json()["netto"] == 9187500

    def test_entwurf_verwerfen_hinterlaesst_keine_luecke(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        assert beleg["rechnung_nr"] is None
        assert buchhaltung.schreiben("DELETE", f"/api/rechnungen/{beleg['id']}").status_code == 204
        naechster = _abschlag(buchhaltung, bestand["positionen"][1])
        antwort = buchhaltung.schreiben("POST", f"/api/rechnungen/{naechster['id']}/festschreiben")
        assert antwort.json()["beleg"]["rechnung_nr"] == "RE-2026-0001"

    def test_festgeschriebener_beleg_laesst_sich_nicht_aendern(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        festgeschrieben = buchhaltung.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/festschreiben"
        ).json()["beleg"]
        antwort = buchhaltung.schreiben(
            "PUT",
            f"/api/rechnungen/{beleg['id']}",
            json={
                "stand": festgeschrieben["stand"],
                "datum": "2026-08-28",
                "leistungszeitraum": "Juli 2026",
                "ust_kz": "19",
            },
        )
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "beleg_festgeschrieben"
        assert "Storno" in koerper["naechster_schritt"]
        assert "aenderbar" not in koerper["meldung"], "Kein Rohtext aus dem Trigger"

    def test_festgeschriebener_beleg_laesst_sich_nicht_verwerfen(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        antwort = buchhaltung.schreiben("DELETE", f"/api/rechnungen/{beleg['id']}")
        assert antwort.status_code == 409


class TestFestschreiben:
    def test_unvollstaendiger_beleg_nennt_alles_fehlende(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben(
            "POST", f"/api/rechnungen/aus-zahlungsplan/{bestand['positionen'][0]}", json={}
        )
        beleg = antwort.json()
        fehler = buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        assert fehler.status_code == 409
        koerper = fehler.json()
        assert koerper["code"] == "beleg_unvollstaendig"
        assert "Leistungszeitraum" in koerper["meldung"]
        assert "§ 14 UStG" in koerper["meldung"]

    def test_festschreiben_setzt_nummer_hash_und_sperrt_die_position(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        antwort = buchhaltung.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/festschreiben"
        ).json()
        assert antwort["beleg"]["status"] == "festgeschrieben"
        assert len(antwort["beleg"]["hash"]) == 64
        assert antwort["berechnete_positionen"] == [bestand["positionen"][0]]
        assert antwort["ablage_offen"] is None

        with lese_sitzung() as sitzung:
            position = sitzung.get(Zahlungsplanposition, bestand["positionen"][0])
            assert position.rechnung_id == beleg["id"]

    def test_festschreiben_steht_im_aenderungsprotokoll(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalar(
                select(AuditEintrag).where(AuditEintrag.aktion == "beleg.festgeschrieben")
            )
        assert eintrag is not None
        assert eintrag.neu["rechnung_nr"] == "RE-2026-0001"
        assert eintrag.user == "buha-re@ip3-energie.de"

    def test_zweimal_festschreiben_ergibt_einen_konflikt(self, buchhaltung, bestand):
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        antwort = buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        assert antwort.status_code == 409
        assert "bereits festgeschrieben" in antwort.json()["meldung"]


class TestSchlussrechnungUeberDieApi:
    def test_absetzungsblock_steht_in_der_antwort(self, buchhaltung, bestand):
        erster = _abschlag(buchhaltung, bestand["positionen"][0])
        buchhaltung.schreiben("POST", f"/api/rechnungen/{erster['id']}/festschreiben")
        antwort = buchhaltung.schreiben(
            "POST",
            "/api/rechnungen/schlussrechnung/26014",
            json={"leistungszeitraum": "März bis Dezember 2026"},
        )
        assert antwort.status_code == 201, antwort.text
        beleg = antwort.json()
        assert len(beleg["absetzungen"]) == 1
        assert beleg["absetzungen"][0]["rechnung_nr"] == "RE-2026-0001"
        assert beleg["absetzung_netto"] == 9187500
        assert beleg["zahlbetrag"] == beleg["brutto"] - beleg["absetzungen"][0]["brutto"]
        assert any("§ 14 Abs. 5 UStG" in h for h in beleg["steuer_hinweise"])

    def test_altprojekt_wird_mit_begruendung_abgelehnt(self, buchhaltung, bestand):
        with schreib_sitzung() as sitzung:
            position = sitzung.get(Zahlungsplanposition, bestand["positionen"][0])
            position.migriert_gestellt = True
            sitzung.flush()
        antwort = buchhaltung.schreiben(
            "POST", "/api/rechnungen/schlussrechnung/26014", json={"leistungszeitraum": "2026"}
        )
        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "altabschlaege_ohne_beleg"
        assert (
            "Abschlagsrechnungen sind für dieses Projekt weiter möglich"
            in (koerper["naechster_schritt"])
        )


class TestAuftragsbestaetigung:
    def test_ab_aus_projekt_und_zahlungsplan(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben("POST", "/api/rechnungen/ab/26014", json={})
        assert antwort.status_code == 201, antwort.text
        beleg = antwort.json()
        assert beleg["art"] == "ab"
        assert len(beleg["positionen"]) == 2
        assert beleg["netto"] == 2 * 9187500

    def test_ab_laesst_sich_ohne_leistungszeitraum_festschreiben(self, buchhaltung, bestand):
        """Die AB ist keine Rechnung (PLAN §10); der Leistungszeitraum ist dort kein Pflichtfeld."""
        beleg = buchhaltung.schreiben("POST", "/api/rechnungen/ab/26014", json={}).json()
        antwort = buchhaltung.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["beleg"]["rechnung_nr"] == "AB-2026-0001"
        assert antwort.json()["berechnete_positionen"] == []


class TestStornoUeberDieApi:
    def test_storno_gibt_die_position_frei(self, admin, bestand):
        beleg = _abschlag(admin, bestand["positionen"][0])
        admin.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        gegenbeleg = admin.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/storno", json={"grund": "Zu früh gestellt"}
        ).json()
        antwort = admin.schreiben(
            "POST", f"/api/rechnungen/{gegenbeleg['id']}/festschreiben"
        ).json()
        assert antwort["beleg"]["rechnung_nr"] == "RE-2026-0002"
        assert antwort["freigegebene_positionen"] == [bestand["positionen"][0]]

        original = admin.client.get(f"/api/rechnungen/{beleg['id']}").json()
        assert original["status"] == "storniert"
        assert original["storniert_durch_nr"] == "RE-2026-0002"

    def test_entwurf_kann_nicht_storniert_werden(self, admin, bestand):
        beleg = _abschlag(admin, bestand["positionen"][0])
        antwort = admin.schreiben("POST", f"/api/rechnungen/{beleg['id']}/storno", json={})
        assert antwort.status_code == 409
        assert "verworfen" in antwort.json()["naechster_schritt"]

    def test_gutschrift_kommt_mit_leeren_positionen(self, admin, bestand):
        beleg = _abschlag(admin, bestand["positionen"][0])
        admin.schreiben("POST", f"/api/rechnungen/{beleg['id']}/festschreiben")
        antwort = admin.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/gutschrift", json={"grund": "Nachlass 2 %"}
        )
        assert antwort.status_code == 201
        assert antwort.json()["positionen"] == []
        assert "Nachlass 2 %" in antwort.json()["anschreiben"]


class TestListeUndFilter:
    def _drei_belege(self, sitzung_client, bestand) -> None:
        erster = _abschlag(sitzung_client, bestand["positionen"][0])
        sitzung_client.schreiben("POST", f"/api/rechnungen/{erster['id']}/festschreiben")
        _abschlag(sitzung_client, bestand["positionen"][1])
        sitzung_client.schreiben("POST", "/api/rechnungen/ab/26015", json={})

    def test_liste_zaehlt_und_summiert(self, buchhaltung, bestand):
        self._drei_belege(buchhaltung, bestand)
        daten = buchhaltung.client.get("/api/rechnungen").json()
        assert daten["anzahl"] == 3
        assert daten["summe_netto"] == 9187500 + 9187500 + 2 * 9187500

    @pytest.mark.parametrize(
        "filter_,erwartet",
        [("art=ab", 1), ("art=abschlag", 2), ("status=entwurf", 2), ("status=festgeschrieben", 1)],
    )
    def test_filter_wirken(self, buchhaltung, bestand, filter_, erwartet):
        self._drei_belege(buchhaltung, bestand)
        daten = buchhaltung.client.get(f"/api/rechnungen?{filter_}").json()
        assert daten["anzahl"] == erwartet

    def test_projektfilter(self, buchhaltung, bestand):
        self._drei_belege(buchhaltung, bestand)
        daten = buchhaltung.client.get("/api/rechnungen?projekt_nr=26015").json()
        assert daten["anzahl"] == 1
        assert daten["zeilen"][0]["art"] == "ab"

    def test_suche_findet_nummer_und_kunde(self, buchhaltung, bestand):
        self._drei_belege(buchhaltung, bestand)
        assert buchhaltung.client.get("/api/rechnungen?suche=RE-2026").json()["anzahl"] == 1
        assert buchhaltung.client.get("/api/rechnungen?suche=Köstler").json()["anzahl"] == 3

    def test_jahr_ohne_belege_ergibt_eine_leere_liste(self, buchhaltung, bestand):
        self._drei_belege(buchhaltung, bestand)
        daten = buchhaltung.client.get("/api/rechnungen?jahr=2024").json()
        assert daten["anzahl"] == 0
        assert daten["summe_netto"] == 0
        assert 2026 in daten["jahre"], "Das aktuelle Jahr steht immer im Filter"

    def test_unbekannte_belegart_wird_abgewiesen(self, buchhaltung, bestand):
        """Ein Tippfehler soll eine Meldung ergeben, keine leere Liste."""
        assert buchhaltung.client.get("/api/rechnungen?art=quittung").status_code == 422


class TestVorschlaege:
    def test_erreichter_meilenstein_erscheint(self, buchhaltung, bestand):
        with schreib_sitzung() as sitzung:
            sitzung.add(
                Meilenstein(
                    projekt_id=bestand["eigenes"],
                    typ="lieferung",
                    erledigt=True,
                    erledigt_am=date(2026, 8, 20),
                )
            )
            sitzung.flush()
        daten = buchhaltung.client.get("/api/rechnungen/vorschlaege").json()
        assert len(daten) == 1
        assert daten[0]["projekt_nr"] == 26014
        assert daten[0]["ausloeser"] == "lieferung"

    def test_team_darf_keine_vorschlaege_sehen(self, team, bestand):
        assert team.client.get("/api/rechnungen/vorschlaege").status_code == 403


class TestOhneRechnungsordner:
    def test_beleg_wird_auch_ohne_ablage_festgeschrieben(self, buchhaltung, bestand):
        """Die Nummer ist die Hauptsache; die Datei lässt sich nachholen."""
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        antwort = buchhaltung.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/festschreiben"
        ).json()
        assert antwort["beleg"]["rechnung_nr"] == "RE-2026-0001"
        assert antwort["beleg"]["pdf_pfad"] is None
        assert antwort["ablage_offen"] is None


class TestFehlendeUnterlagen:
    """Der Schlussrechnungs-Hinweis aus dem Doku-Scan (PLAN §7 Phase 7, Entscheidung 50)."""

    @staticmethod
    def _scannen(wurzel: Path, projekt_nr: int, dateien: list[str]) -> None:
        """Einen Ordner anlegen, füllen und den Scan darüber laufen lassen."""
        from app.dienste.dokumente import scannen

        ordner = wurzel / str(projekt_nr)
        ordner.mkdir(parents=True, exist_ok=True)
        for name in dateien:
            (ordner / name).write_text("x")
        with schreib_sitzung() as sitzung:
            scannen(sitzung, wurzel)

    @staticmethod
    def _schlussrechnung(sitzung_client, projekt_nr: int) -> dict:
        antwort = sitzung_client.schreiben(
            "POST",
            f"/api/rechnungen/schlussrechnung/{projekt_nr}",
            json={"leistungszeitraum": "August 2026"},
        )
        assert antwort.status_code == 201, antwort.text
        return antwort.json()

    def test_ohne_scan_wird_nichts_gemeldet(self, buchhaltung, bestand):
        """Ein Hinweis, nur weil der Scan nie lief, wäre falsch."""
        beleg = self._schlussrechnung(buchhaltung, 26014)
        assert beleg["fehlende_unterlagen"] == []

    def test_fehlende_pflichtunterlage_steht_am_entwurf(self, buchhaltung, bestand, tmp_path: Path):
        self._scannen(tmp_path / "projekte", 26014, ["Abnahmeprotokoll.pdf"])
        beleg = self._schlussrechnung(buchhaltung, 26014)
        assert beleg["fehlende_unterlagen"] == ["anlagendoku"]

    def test_vollstaendiger_ordner_meldet_nichts(self, buchhaltung, bestand, tmp_path: Path):
        self._scannen(tmp_path / "projekte", 26014, ["Anlagendokumentation.pdf"])
        beleg = self._schlussrechnung(buchhaltung, 26014)
        assert beleg["fehlende_unterlagen"] == []

    def test_abschlagsrechnung_fragt_nicht_nach_unterlagen(
        self, buchhaltung, bestand, tmp_path: Path
    ):
        """Eine Abschlagsrechnung geht raus, während gebaut wird."""
        self._scannen(tmp_path / "projekte", 26014, [])
        beleg = _abschlag(buchhaltung, bestand["positionen"][0])
        assert beleg["fehlende_unterlagen"] == []

    def test_festschreiben_ohne_unterlagen_ergibt_einen_konflikt(
        self, buchhaltung, bestand, tmp_path: Path
    ):
        self._scannen(tmp_path / "projekte", 26014, [])
        beleg = self._schlussrechnung(buchhaltung, 26014)

        antwort = buchhaltung.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/festschreiben", json={}
        )

        assert antwort.status_code == 409
        koerper = antwort.json()
        assert koerper["code"] == "unterlagen_fehlen"
        # Der Datenbankschlüssel gehört nicht auf den Bildschirm.
        assert "Anlagendokumentation" in koerper["meldung"]
        assert "anlagendoku" not in koerper["meldung"]
        assert koerper["naechster_schritt"]

    def test_ausdrueckliche_bestaetigung_laesst_festschreiben_zu(
        self, buchhaltung, bestand, tmp_path: Path
    ):
        """Keine harte Sperre: was auf Papier vorliegt, darf keine Rechnung verhindern."""
        self._scannen(tmp_path / "projekte", 26014, [])
        beleg = self._schlussrechnung(buchhaltung, 26014)

        antwort = buchhaltung.schreiben(
            "POST",
            f"/api/rechnungen/{beleg['id']}/festschreiben",
            json={"unterlagen_bestaetigt": True},
        )

        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["beleg"]["rechnung_nr"]

    def test_die_bestaetigung_steht_im_aenderungsprotokoll(
        self, buchhaltung, bestand, tmp_path: Path
    ):
        """Eine bewusste Entscheidung eines Menschen gehört ins audit_log (CLAUDE.md Regel 7)."""
        from app.modelle import AuditEintrag

        self._scannen(tmp_path / "projekte", 26014, [])
        beleg = self._schlussrechnung(buchhaltung, 26014)
        buchhaltung.schreiben(
            "POST",
            f"/api/rechnungen/{beleg['id']}/festschreiben",
            json={"unterlagen_bestaetigt": True},
        )

        with lese_sitzung() as sitzung:
            eintrag = sitzung.execute(
                select(AuditEintrag)
                .where(AuditEintrag.aktion == "beleg.ohne_unterlagen_festgeschrieben")
                .order_by(AuditEintrag.id.desc())
                .limit(1)
            ).scalar_one()
        assert eintrag.neu["fehlende_unterlagen"] == ["anlagendoku"]

    def test_vollstaendiger_ordner_braucht_keine_bestaetigung(
        self, buchhaltung, bestand, tmp_path: Path
    ):
        self._scannen(tmp_path / "projekte", 26014, ["Anlagendokumentation.pdf"])
        beleg = self._schlussrechnung(buchhaltung, 26014)

        antwort = buchhaltung.schreiben(
            "POST", f"/api/rechnungen/{beleg['id']}/festschreiben", json={}
        )

        assert antwort.status_code == 200, antwort.text
