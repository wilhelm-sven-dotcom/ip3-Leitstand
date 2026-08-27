"""Projekte, Meilensteine und die Zuordnung der Projektleiter (PLAN §4, §5, §7 Phase 1).

Schwerpunkt ist die **Finanzsichtbarkeit**: PLAN §4 trennt `projekte.lesen` von
`projekte.werte_lesen`, damit ein Monteur Termine und Anlagendaten sieht, aber keine Beträge.
Umgesetzt ist das nicht durch Ausblenden in der Oberfläche – die Antwort enthält die Felder
nicht. Genau das prüfen die Tests hier, und zwar am direkten Aufruf der Schnittstelle.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import Firma, Kunde, Projekt, Zahlungsplanposition
from tests.conftest_auth import anmelden


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen):
    nutzer_erzeugen("buha-pr@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha-pr@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen):
    nutzer_erzeugen("team-pr@ip3-energie.de", "team")
    return anmelden(client, "team-pr@ip3-energie.de")


@pytest.fixture
def bestand(gesäte_db) -> dict:
    """Zwei Kunden, drei Projekte, ein Zahlungsplan – direkt in der Datenbank."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde_a = Kunde(kunden_nr=11001, name="Pöllath", ort="Weiden", typ="b2c")
        kunde_b = Kunde(kunden_nr=11002, name="HPZ", ort="Irchenrieth", typ="b2b")
        sitzung.add_all([kunde_a, kunde_b])
        sitzung.flush()

        projekte = [
            Projekt(
                projekt_nr=24001,
                firma_id=firma_id,
                kunde_id=kunde_a.id,
                bezeichnung=None,
                standort="Weiden",
                anlagenart="aufdach_speicher",
                pv_kwp=29.58,
                speicher_kwh=13.5,
                ab_wert_netto=3300000,
                pl_name="Stefan",
                status="abgeschlossen",
            ),
            Projekt(
                projekt_nr=26001,
                firma_id=firma_id,
                kunde_id=kunde_b.id,
                bezeichnung="Dachanlage Halle 2",
                standort="Irchenrieth",
                anlagenart="aufdach",
                pv_kwp=514.08,
                ab_wert_netto=38428424,
                pl_name="Günther",
                status="in_bau",
            ),
            Projekt(
                projekt_nr=26002,
                firma_id=firma_id,
                kunde_id=kunde_a.id,
                anlagenart="freiflaeche",
                pv_kwp=299.7,
                ab_wert_netto=30099100,
                pl_name="Stefan",
                status="beauftragt",
            ),
        ]
        sitzung.add_all(projekte)
        sitzung.flush()
        sitzung.add_all(
            [
                Zahlungsplanposition(
                    projekt_id=projekte[1].id,
                    pos_nr=1,
                    bezeichnung="1. Abschlag PV",
                    gewerk="pv",
                    art="abschlag",
                    betrag_netto=11528527,
                    plan_monat="2026-09",
                    migriert_gestellt=True,
                    quelle_migration="Offene_Auftraege.xlsx Zeile 42",
                ),
                Zahlungsplanposition(
                    projekt_id=projekte[1].id,
                    pos_nr=2,
                    bezeichnung="Schlussrechnung PV",
                    gewerk="pv",
                    art="schluss",
                    betrag_netto=26899897,
                    plan_monat="2026-11",
                    migriert_gestellt=False,
                ),
            ]
        )
        return {"kunde_a": kunde_a.id, "kunde_b": kunde_b.id}


class TestFinanzsichtbarkeit:
    def test_buchhaltung_sieht_betraege(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/projekte/26001").json()
        assert antwort["ab_wert_netto"] == 38428424
        assert antwort["zahlungsplan_summe"] == 11528527 + 26899897
        assert len(antwort["zahlungsplan"]) == 2
        assert antwort["darf_werte_sehen"] is True

    def test_team_sieht_projekt_aber_keine_betraege(self, team, bestand):
        """Kein Ausblenden in der Oberfläche: die Felder fehlen in der Antwort."""
        antwort = team.client.get("/api/projekte/26001")
        assert antwort.status_code == 200
        koerper = antwort.json()
        # Termine und Anlagendaten sind da …
        assert koerper["pv_kwp"] == 514.08
        assert koerper["standort"] == "Irchenrieth"
        assert koerper["status"] == "in_bau"
        # … Beträge nicht.
        assert koerper["ab_wert_netto"] is None
        assert koerper["zahlungsplan"] == []
        assert koerper["zahlungsplan_summe"] is None
        assert koerper["darf_werte_sehen"] is False

    def test_team_sieht_in_der_liste_keine_betraege(self, team, bestand):
        eintraege = team.client.get("/api/projekte").json()["eintraege"]
        assert len(eintraege) == 3
        assert all(e["ab_wert_netto"] is None for e in eintraege)
        assert all(e["pv_kwp"] is not None for e in eintraege)

    def test_team_darf_keinen_auftragswert_setzen(self, team, bestand):
        """Wer den Wert nicht lesen darf, darf ihn auch nicht setzen."""
        antwort = team.schreiben(
            "POST",
            "/api/projekte",
            json={"kunde_id": bestand["kunde_a"], "ab_wert_netto": 100000},
        )
        # team hat schon projekte.schreiben nicht – die Berechtigung greift zuerst.
        assert antwort.status_code == 403

    def test_auftragswert_ohne_werterecht_wird_nicht_ueberschrieben(
        self, client, nutzer_erzeugen, bestand
    ):
        """Eine Rolle mit Schreib-, aber ohne Werterecht darf den Betrag nicht verändern.

        Der Fall entsteht, sobald jemand eine eigene Rolle anlegt. Ohne diese Prüfung könnte ein
        mitgeschickter Wert – den die Maske gar nicht angezeigt hat – den echten überschreiben.
        """
        from app.datenbank import schreib_sitzung as schreiben
        from app.modelle import Berechtigung, Rolle

        with schreiben() as sitzung:
            rolle = Rolle(name="planer", beschreibung="Planung ohne Beträge")
            # Erst in die Sitzung, dann verknüpfen: beim Anhängen löst SQLAlchemy einen Autoflush
            # aus und verwirft die Verknüpfung eines noch unbekannten Objekts stillschweigend.
            sitzung.add(rolle)
            # Berechtigungen sind gemeinsame Zeilen mit n:m-Verknüpfung – der Seed hat sie schon
            # angelegt, die neue Rolle bekommt Verweise darauf.
            for schluessel in ("projekte.lesen", "projekte.schreiben"):
                recht = sitzung.scalar(
                    select(Berechtigung).where(
                        Berechtigung.schluessel == schluessel, Berechtigung.scope.is_(None)
                    )
                )
                assert recht is not None, schluessel
                rolle.berechtigungen.append(recht)
            sitzung.flush()
        nutzer_erzeugen("planer@ip3-energie.de", "planer")
        planer = anmelden(client, "planer@ip3-energie.de")

        vorher = planer.client.get("/api/projekte/26001").json()
        assert vorher["ab_wert_netto"] is None

        antwort = planer.schreiben(
            "PUT",
            "/api/projekte/26001",
            json={
                "kunde_id": bestand["kunde_b"],
                "standort": "Irchenrieth",
                "ab_wert_netto": 1,
                "stand": vorher["stand"],
            },
        )
        assert antwort.status_code == 409
        assert antwort.json()["code"] == "werte_ohne_berechtigung"

        with lese_sitzung() as sitzung:
            projekt = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26001))
            assert projekt.ab_wert_netto == 38428424


class TestListeUndFilter:
    def test_nummer_absteigend(self, buchhaltung, bestand):
        """Die neuesten Projekte zuerst – wie im Mockup."""
        nummern = [
            e["projekt_nr"] for e in buchhaltung.client.get("/api/projekte").json()["eintraege"]
        ]
        assert nummern == sorted(nummern, reverse=True)

    def test_bezeichnung_faellt_auf_den_kunden_zurueck(self, buchhaltung, bestand):
        eintraege = {
            e["projekt_nr"]: e for e in buchhaltung.client.get("/api/projekte").json()["eintraege"]
        }
        assert eintraege[26001]["bezeichnung"] == "Dachanlage Halle 2"
        # Die migrierten Projekte haben keine – die Oberfläche zeigt dann den Kundennamen.
        assert eintraege[24001]["bezeichnung"] is None
        assert eintraege[24001]["kunde"] == "Pöllath"

    @pytest.mark.parametrize(
        ("filter_name", "wert", "erwartet"),
        [
            ("status", "in_bau", [26001]),
            ("status", "abgeschlossen", [24001]),
            ("projektleiter", "Stefan", [26002, 24001]),
            ("projektleiter", "Günther", [26001]),
            ("anlagenart", "freiflaeche", [26002]),
            ("anlagenart", "aufdach", [26001]),
        ],
    )
    def test_filter(self, buchhaltung, bestand, filter_name, wert, erwartet):
        antwort = buchhaltung.client.get("/api/projekte", params={filter_name: wert}).json()
        assert [e["projekt_nr"] for e in antwort["eintraege"]] == erwartet

    def test_jahresfilter_ueber_die_projektnummer(self, buchhaltung, bestand):
        """Über die Nummer, nicht über auftrag_vom: 41 migrierte Projekte haben kein Datum."""
        assert [
            e["projekt_nr"]
            for e in buchhaltung.client.get("/api/projekte", params={"jahr": 2026}).json()[
                "eintraege"
            ]
        ] == [26002, 26001]
        assert [
            e["projekt_nr"]
            for e in buchhaltung.client.get("/api/projekte", params={"jahr": 2024}).json()[
                "eintraege"
            ]
        ] == [24001]

    def test_filterwerte_kommen_aus_den_daten(self, buchhaltung, bestand):
        """Ein Jahr ohne Projekte gehört nicht in die Auswahl."""
        antwort = buchhaltung.client.get("/api/projekte").json()
        assert antwort["jahre"] == [2026, 2024]
        assert antwort["projektleiter"] == ["Günther", "Stefan"]

    @pytest.mark.parametrize(
        ("suche", "erwartet"),
        [
            ("poellath", [26002, 24001]),
            ("irchenrieth", [26001]),
            ("halle", [26001]),
            ("26001", [26001]),
            ("guenther", [26001]),
        ],
    )
    def test_suche(self, buchhaltung, bestand, suche, erwartet):
        antwort = buchhaltung.client.get("/api/projekte", params={"suche": suche}).json()
        assert [e["projekt_nr"] for e in antwort["eintraege"]] == erwartet


class TestMeilensteine:
    """Die Zeitleiste im Projektdetail (design/Projektdetail.dc.html).

    Drei Zustände je Schritt (Migration 0003): offen (``erledigt = NULL``), geplant mit Woche,
    erledigt mit Datum. Gesetzt wird der vollständige Stand in einem Aufruf, nicht Häkchen für
    Häkchen – die Maske bearbeitet mehrere Schritte in einem Zug.
    """

    def test_setzen_und_lesen(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001/meilensteine",
            json=[
                {"typ": "montage_uk", "geplant_kw": "2026-KW38", "erledigt": False},
                {"typ": "lieferung_uk", "erledigt": True, "erledigt_am": "2026-08-20"},
            ],
        )
        assert antwort.status_code == 200
        schritte = {m["typ"]: m for m in antwort.json()}
        assert schritte["montage_uk"]["geplant_kw"] == "2026-KW38"
        assert schritte["montage_uk"]["erledigt"] is False
        assert schritte["lieferung_uk"]["erledigt"] is True
        assert schritte["lieferung_uk"]["erledigt_am"] == "2026-08-20"

    def test_reihenfolge_wie_im_bauablauf(self, buchhaltung, bestand):
        """Nicht nach Anlagezeitpunkt, sondern in der Reihenfolge aus MEILENSTEIN_TYPEN."""
        from app.modelle.projekte import MEILENSTEIN_TYPEN

        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001/meilensteine",
            json=[
                {"typ": "abnahme"},
                {"typ": "lieferung_uk"},
                {"typ": "montage_uk"},
            ],
        )
        typen = [
            m["typ"] for m in buchhaltung.client.get("/api/projekte/26001").json()["meilensteine"]
        ]
        assert typen == sorted(typen, key=MEILENSTEIN_TYPEN.index)

    def test_nicht_mitgeschickte_schritte_bleiben(self, buchhaltung, bestand):
        """Wer nur ein Häkchen setzt, darf nicht die übrigen Termine verlieren."""
        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001/meilensteine",
            json=[{"typ": "montage_uk", "geplant_kw": "2026-KW38"}],
        )
        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001/meilensteine",
            json=[{"typ": "abnahme", "erledigt": True, "erledigt_am": "2026-10-01"}],
        )
        schritte = {
            m["typ"]: m
            for m in buchhaltung.client.get("/api/projekte/26001").json()["meilensteine"]
        }
        assert schritte["montage_uk"]["geplant_kw"] == "2026-KW38"
        assert schritte["abnahme"]["erledigt"] is True

    def test_offen_ist_nicht_dasselbe_wie_nicht_erledigt(self, buchhaltung, bestand):
        """``erledigt = NULL`` heißt „noch nicht angefasst", ``False`` heißt „geplant, offen"."""
        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001/meilensteine",
            json=[{"typ": "montage_uk"}, {"typ": "abnahme", "erledigt": False}],
        )
        schritte = {
            m["typ"]: m
            for m in buchhaltung.client.get("/api/projekte/26001").json()["meilensteine"]
        }
        assert schritte["montage_uk"]["erledigt"] is None
        assert schritte["abnahme"]["erledigt"] is False

    def test_unbekannter_typ_wird_abgewiesen(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben(
            "PUT", "/api/projekte/26001/meilensteine", json=[{"typ": "grundsteinlegung"}]
        )
        assert antwort.status_code == 422

    def test_team_darf_keine_meilensteine_setzen(self, team, bestand):
        antwort = team.schreiben(
            "PUT", "/api/projekte/26001/meilensteine", json=[{"typ": "montage_uk"}]
        )
        assert antwort.status_code == 403

    def test_aenderung_steht_im_protokoll(self, buchhaltung, bestand):
        from app.modelle import AuditEintrag

        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001/meilensteine",
            json=[{"typ": "montage_uk", "geplant_kw": "2026-KW38"}],
        )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalars(
                select(AuditEintrag)
                .where(AuditEintrag.aktion == "meilensteine.geaendert")
                .order_by(AuditEintrag.id.desc())
            ).first()
        assert eintrag is not None
        assert eintrag.neu["schritte"]["montage_uk"]["neu"]["geplant_kw"] == "2026-KW38"

    def test_ohne_aenderung_kein_protokolleintrag(self, buchhaltung, bestand):
        """Ein Eintrag über eine Änderung, die keine war, macht das Protokoll unlesbar."""
        from app.modelle import AuditEintrag

        json = [{"typ": "montage_uk", "geplant_kw": "2026-KW38"}]
        buchhaltung.schreiben("PUT", "/api/projekte/26001/meilensteine", json=json)
        with lese_sitzung() as sitzung:
            vorher = sitzung.scalar(
                select(func.count())
                .select_from(AuditEintrag)
                .where(AuditEintrag.aktion == "meilensteine.geaendert")
            )
        buchhaltung.schreiben("PUT", "/api/projekte/26001/meilensteine", json=json)
        with lese_sitzung() as sitzung:
            nachher = sitzung.scalar(
                select(func.count())
                .select_from(AuditEintrag)
                .where(AuditEintrag.aktion == "meilensteine.geaendert")
            )
        assert nachher == vorher


class TestProjektleiterZuordnen:
    """Elf Namen, je Name ein Konto – die Lücke, die die Migration hinterlässt.

    In der Teamliste steht ein Vorname, kein Konto. Ohne Zuordnung greift der Scope ``eigene``
    aus PLAN §4 nicht, weil er die Nutzer-ID vergleicht.
    """

    def test_uebersicht_zaehlt_je_name(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/projekte/projektleiter/uebersicht").json()
        namen = {n["pl_name"]: n for n in antwort["namen"]}
        assert namen["Stefan"]["anzahl_projekte"] == 2
        assert namen["Stefan"]["ohne_konto"] == 2
        assert namen["Günther"]["anzahl_projekte"] == 1
        # Häufigster Name zuerst: die Maske arbeitet die Liste von oben ab.
        assert antwort["namen"][0]["pl_name"] == "Stefan"
        assert any(k["email"] == "buha-pr@ip3-energie.de" for k in antwort["konten"])

    def test_zuordnung_wirkt_auf_alle_projekte_des_namens(self, buchhaltung, bestand):
        konto = buchhaltung.client.get("/api/projekte/projektleiter/uebersicht").json()["konten"][0]
        antwort = buchhaltung.schreiben(
            "PUT",
            "/api/projekte/projektleiter/zuordnen",
            json={"zuordnungen": {"Stefan": konto["id"]}},
        )
        assert antwort.status_code == 200
        assert antwort.json()["geaendert"] == 2

        uebersicht = buchhaltung.client.get("/api/projekte/projektleiter/uebersicht").json()
        stefan = next(n for n in uebersicht["namen"] if n["pl_name"] == "Stefan")
        assert stefan["ohne_konto"] == 0
        assert stefan["user_ids"] == [konto["id"]]

    def test_der_name_bleibt_als_herkunftsnachweis(self, buchhaltung, bestand):
        konto = buchhaltung.client.get("/api/projekte/projektleiter/uebersicht").json()["konten"][0]
        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/projektleiter/zuordnen",
            json={"zuordnungen": {"Stefan": konto["id"]}},
        )
        with lese_sitzung() as sitzung:
            projekt = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 24001))
            assert projekt.pl_name == "Stefan"
            assert projekt.pl_user_id == konto["id"]

    def test_zuordnung_kann_geloest_werden(self, buchhaltung, bestand):
        konto = buchhaltung.client.get("/api/projekte/projektleiter/uebersicht").json()["konten"][0]
        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/projektleiter/zuordnen",
            json={"zuordnungen": {"Stefan": konto["id"]}},
        )
        antwort = buchhaltung.schreiben(
            "PUT", "/api/projekte/projektleiter/zuordnen", json={"zuordnungen": {"Stefan": None}}
        )
        assert antwort.json()["geaendert"] == 2
        with lese_sitzung() as sitzung:
            projekt = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 24001))
            assert projekt.pl_user_id is None

    def test_unbekanntes_konto_wird_abgewiesen(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben(
            "PUT", "/api/projekte/projektleiter/zuordnen", json={"zuordnungen": {"Stefan": 9999}}
        )
        assert antwort.status_code == 404
        assert "9999" in antwort.json()["meldung"]

    def test_zweiter_lauf_meldet_nichts_zu_tun(self, buchhaltung, bestand):
        konto = buchhaltung.client.get("/api/projekte/projektleiter/uebersicht").json()["konten"][0]
        json = {"zuordnungen": {"Stefan": konto["id"]}}
        buchhaltung.schreiben("PUT", "/api/projekte/projektleiter/zuordnen", json=json)
        zweiter = buchhaltung.schreiben("PUT", "/api/projekte/projektleiter/zuordnen", json=json)
        assert zweiter.json()["geaendert"] == 0
        assert "nichts zu ändern" in zweiter.json()["meldung"]

    def test_team_darf_nicht_zuordnen(self, team, bestand):
        antwort = team.schreiben(
            "PUT", "/api/projekte/projektleiter/zuordnen", json={"zuordnungen": {"Stefan": 1}}
        )
        assert antwort.status_code == 403


class TestScopeEigene:
    """Der Sichtbarkeits-Scope ``eigene`` aus PLAN §4: nur Projekte, bei denen man PL ist.

    Geprüft wird auch die **Filterleiste**. Sie wird aus den Daten gefüllt, und wenn die
    Einschränkung dort nicht greift, verrät die Auswahlliste Jahre und Kollegennamen aus
    Projekten, die der Nutzer selbst nicht öffnen darf.
    """

    @pytest.fixture
    def monteur(self, client, nutzer_erzeugen, bestand):
        """Ein Konto mit ``projekte.lesen`` im Scope ``eigene``, PL von 26001."""
        from app.datenbank import schreib_sitzung as schreiben
        from app.modelle import Berechtigung, Rolle, User

        nutzer_id = nutzer_erzeugen("monteur@ip3-energie.de", "team")
        with schreiben() as sitzung:
            rolle = Rolle(name="monteur", beschreibung="Nur eigene Projekte")
            sitzung.add(rolle)
            # Den Scope kennt der Seed nur an Rollen, nicht als eigene Katalogzeile – für diesen
            # Fall wird die Berechtigung mit Scope hier angelegt.
            recht = Berechtigung(
                schluessel="projekte.lesen", scope="eigene", beschreibung="nur eigene Projekte"
            )
            sitzung.add(recht)
            rolle.berechtigungen.append(recht)
            nutzer = sitzung.get(User, nutzer_id)
            # Die Rolle team bringt 'projekte.lesen' mit Scope 'alle' mit; der weitere Scope
            # gewinnt (User.berechtigungsschluessel), deshalb muss sie weg.
            nutzer.rollen.clear()
            nutzer.rollen.append(rolle)
            sitzung.flush()

            projekt = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26001))
            projekt.pl_user_id = nutzer_id
        return anmelden(client, "monteur@ip3-energie.de")

    def test_liste_zeigt_nur_eigene(self, monteur):
        antwort = monteur.client.get("/api/projekte").json()
        assert [e["projekt_nr"] for e in antwort["eintraege"]] == [26001]
        assert antwort["gesamt"] == 1

    def test_fremdes_projekt_ist_nicht_erreichbar(self, monteur):
        antwort = monteur.client.get("/api/projekte/24001")
        assert antwort.status_code == 404
        assert "nur eigene" in antwort.json()["naechster_schritt"]

    def test_filterleiste_verraet_keine_fremden_projekte(self, monteur):
        """Sonst stehen dort Jahre und Namen aus Projekten, die der Nutzer nicht öffnen darf."""
        antwort = monteur.client.get("/api/projekte").json()
        assert antwort["jahre"] == [2026]
        assert antwort["projektleiter"] == ["Günther"]


class TestAuftragsvolumen:
    """Die Kopfzeile des Mockups nennt das Auftragsvolumen (design/Projektliste.dc.html)."""

    def test_summe_ueber_die_ganze_auswahl(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/projekte", params={"anzahl": 1}).json()
        # Nur ein Eintrag auf der Seite, aber die Summe aller drei Projekte: die Kopfzeile
        # nennt das Volumen der Auswahl, nicht das der angezeigten Zeilen.
        assert len(antwort["eintraege"]) == 1
        assert antwort["auftragsvolumen"] == 3300000 + 38428424 + 30099100

    def test_summe_folgt_dem_filter(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/projekte", params={"jahr": 2024}).json()
        assert antwort["auftragsvolumen"] == 3300000

    def test_ohne_werterecht_keine_summe(self, team, bestand):
        assert team.client.get("/api/projekte").json()["auftragsvolumen"] is None

    def test_ohne_treffer_keine_summe(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/projekte", params={"suche": "gibtesnicht"}).json()
        assert antwort["eintraege"] == []
        assert antwort["auftragsvolumen"] is None


class TestSpeichern:
    """Ein Speichervorgang, der durchläuft – und im Protokoll landet.

    Diesen Weg hat lange kein Test genommen: die Prüfungen auf Berechtigungen und Konflikte
    enden vor dem Schreiben. Dass ein erfolgreiches PUT an einem Projekt mit Leistung in kWp
    einen Serverfehler ergab (``Decimal`` passt nicht in die JSON-Spalte des Protokolls), fiel
    erst in der Maske auf.
    """

    def _koerper(self, antwort: dict, **aenderungen) -> dict:
        koerper = {
            "kunde_id": antwort["kunde_id"],
            "bezeichnung": antwort["bezeichnung"],
            "typ": antwort["typ"],
            "standort": antwort["standort"],
            "anlagenart": antwort["anlagenart"],
            "pv_kwp": antwort["pv_kwp"],
            "speicher_kwh": antwort["speicher_kwh"],
            "auftrag_vom": antwort["auftrag_vom"],
            "ab_wert_netto": antwort["ab_wert_netto"],
            "pl_name": antwort["pl_name"],
            "ust_kz": antwort["ust_kz"],
            "status": antwort["status"],
            "stand": antwort["stand"],
        }
        koerper.update(aenderungen)
        return koerper

    def test_anlagendaten_und_datum_aendern(self, buchhaltung, bestand):
        vorher = buchhaltung.client.get("/api/projekte/26001").json()
        antwort = buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001",
            json=self._koerper(
                vorher,
                pv_kwp=600.5,
                speicher_kwh=44.2,
                auftrag_vom="2026-03-10",
                bezeichnung="Dachanlage Halle 2 (erweitert)",
            ),
        )
        assert antwort.status_code == 200, antwort.text
        gespeichert = antwort.json()
        assert gespeichert["pv_kwp"] == 600.5
        assert gespeichert["speicher_kwh"] == 44.2
        assert gespeichert["auftrag_vom"] == "2026-03-10"
        assert gespeichert["stand"] != vorher["stand"]

    def test_protokoll_haelt_die_werte_als_zahl_und_text(self, buchhaltung, bestand):
        """Das Protokoll muss lesbar sein: 514.08 als Zahl, das Datum als Text."""
        from app.modelle import AuditEintrag

        vorher = buchhaltung.client.get("/api/projekte/26001").json()
        buchhaltung.schreiben(
            "PUT",
            "/api/projekte/26001",
            json=self._koerper(vorher, pv_kwp=600.5, auftrag_vom="2026-03-10"),
        )
        with lese_sitzung() as sitzung:
            eintrag = sitzung.scalars(
                select(AuditEintrag)
                .where(AuditEintrag.aktion == "projekt.geaendert")
                .order_by(AuditEintrag.id.desc())
            ).first()
        assert eintrag is not None
        assert eintrag.alt["pv_kwp"] == 514.08
        assert eintrag.neu["pv_kwp"] == 600.5
        assert eintrag.neu["auftrag_vom"] == "2026-03-10"
        assert eintrag.neu["projekt_nr"] == 26001

    def test_zweites_speichern_mit_altem_stand_ergibt_konflikt(self, buchhaltung, bestand):
        """Optimistic Locking über die Maske (PLAN §5, CLAUDE.md Regel 6)."""
        vorher = buchhaltung.client.get("/api/projekte/26001").json()
        erste = buchhaltung.schreiben(
            "PUT", "/api/projekte/26001", json=self._koerper(vorher, standort="Irchenrieth Süd")
        )
        assert erste.status_code == 200
        zweite = buchhaltung.schreiben(
            "PUT", "/api/projekte/26001", json=self._koerper(vorher, standort="Irchenrieth Nord")
        )
        assert zweite.status_code == 409
        assert zweite.json()["code"] == "stand_veraltet"
        # Die erste Änderung ist erhalten – nichts wurde stillschweigend überschrieben.
        assert buchhaltung.client.get("/api/projekte/26001").json()["standort"] == "Irchenrieth Süd"

    def test_ohne_aenderung_kein_protokolleintrag(self, buchhaltung, bestand):
        from app.modelle import AuditEintrag

        vorher = buchhaltung.client.get("/api/projekte/26001").json()
        buchhaltung.schreiben("PUT", "/api/projekte/26001", json=self._koerper(vorher))
        with lese_sitzung() as sitzung:
            anzahl = sitzung.scalar(
                select(func.count())
                .select_from(AuditEintrag)
                .where(AuditEintrag.aktion == "projekt.geaendert")
            )
        assert anzahl == 0

    def test_anlegen_setzt_die_projektnummer_aus_dem_auftragsjahr(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben(
            "POST",
            "/api/projekte",
            json={
                "kunde_id": bestand["kunde_a"],
                "bezeichnung": "Speicher Theisseil I",
                "standort": "Theisseil",
                "anlagenart": "speicher",
                "speicher_kwh": 2400,
                "auftrag_vom": "2026-04-01",
                "ab_wert_netto": 98500000,
                "ust_kz": "19",
                "status": "beauftragt",
            },
        )
        assert antwort.status_code == 201, antwort.text
        neu = antwort.json()
        assert 26000 < neu["projekt_nr"] < 27000
        assert neu["speicher_kwh"] == 2400
        assert neu["ab_wert_netto"] == 98500000

    def test_anlegen_ohne_kunden_wird_abgewiesen(self, buchhaltung, bestand):
        antwort = buchhaltung.schreiben("POST", "/api/projekte", json={"kunde_id": 999999})
        assert antwort.status_code == 404
        assert "Kunden" in antwort.json()["meldung"]
        assert "Stammdaten" in antwort.json()["naechster_schritt"]
