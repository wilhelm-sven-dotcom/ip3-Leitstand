"""Routen für Umsatz, Forecast und Auftragsbestand (PLAN §7 Phase 2).

Der Dienst dahinter ist in ``tests/test_auswertung.py`` geprüft; hier geht es um das, was die
Schnittstelle zusagt: Berechtigung, Filter, der Hinweis zum unvollständigen Ist und die Frage,
ob ein Jahr ohne Daten eine Auskunft oder ein Fehler ist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.datenbank import schreib_sitzung
from app.modelle import Firma, Kunde, Nachtrag, Projekt, Zahlungsplanposition
from tests.conftest_auth import anmelden


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen):
    nutzer_erzeugen("buha-um@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha-um@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen):
    nutzer_erzeugen("team-um@ip3-energie.de", "team")
    return anmelden(client, "team-um@ip3-energie.de")


@pytest.fixture
def bestand(gesäte_db) -> dict:
    """Zwei laufende Projekte, ein abgeschlossenes; Beträge von Hand gerechnet."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=14001, name="Umsatz GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()

        pv = Projekt(
            projekt_nr=26001,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="beauftragt",
            ab_wert_netto=10000000,
            pl_name="Stefan",
            anlagenart="aufdach",
        )
        speicher = Projekt(
            projekt_nr=26002,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            ab_wert_netto=5000000,
            pl_name="Günther",
            anlagenart="speicher",
        )
        alt = Projekt(
            projekt_nr=25001,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="abgeschlossen",
            ab_wert_netto=2000000,
            pl_name="Stefan",
            anlagenart="aufdach",
        )
        sitzung.add_all([pv, speicher, alt])
        sitzung.flush()

        sitzung.add_all(
            [
                Zahlungsplanposition(
                    projekt_id=pv.id,
                    pos_nr=1,
                    bezeichnung="1. Abschlag",
                    gewerk="pv",
                    art="abschlag",
                    betrag_netto=3000000,
                    plan_monat="2026-05",
                    migriert_gestellt=True,
                ),
                Zahlungsplanposition(
                    projekt_id=pv.id,
                    pos_nr=2,
                    bezeichnung="2. Abschlag",
                    gewerk="pv",
                    art="abschlag",
                    betrag_netto=4000000,
                    plan_monat="2026-09",
                ),
                Zahlungsplanposition(
                    projekt_id=pv.id,
                    pos_nr=3,
                    bezeichnung="Restbetrag",
                    gewerk="pv",
                    art="einmal",
                    betrag_netto=1000000,
                    plan_monat=None,
                ),
                Zahlungsplanposition(
                    projekt_id=speicher.id,
                    pos_nr=1,
                    bezeichnung="Speicher",
                    gewerk="speicher",
                    art="einmal",
                    betrag_netto=2500000,
                    plan_monat="2026-11",
                ),
                Zahlungsplanposition(
                    projekt_id=alt.id,
                    pos_nr=1,
                    bezeichnung="Schluss",
                    gewerk="pv",
                    art="schluss",
                    betrag_netto=2000000,
                    plan_monat="2025-12",
                    migriert_gestellt=True,
                ),
            ]
        )
        return {"kunde": kunde.id}


class TestMonate:
    def test_zwoelf_monate_mit_summen(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/monate", params={"jahr": 2026}).json()
        assert antwort["jahr"] == 2026
        assert len(antwort["monate"]) == 12
        je_monat = {m["monat"]: m for m in antwort["monate"]}
        assert je_monat["2026-05"]["ist_netto"] == 3000000
        assert je_monat["2026-09"]["plan_netto"] == 4000000
        assert je_monat["2026-11"]["plan_netto"] == 2500000
        assert antwort["ist_netto"] == 3000000
        assert antwort["plan_netto"] == 6500000

    def test_unterminiert_wird_ausgewiesen(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/monate", params={"jahr": 2026}).json()
        assert antwort["unterminiert"]["plan_netto"] == 1000000
        assert antwort["unterminiert"]["anzahl"] == 1
        # Nicht in einer Monatssäule: die Summe der Säulen bleibt ohne sie.
        assert sum(m["summe_netto"] for m in antwort["monate"]) == 3000000 + 4000000 + 2500000

    def test_standardjahr_ist_das_laufende(self, buchhaltung, bestand):
        from app.zeit import heute_ortszeit

        antwort = buchhaltung.client.get("/api/umsatz/monate").json()
        assert antwort["jahr"] == heute_ortszeit().year

    def test_jahr_ohne_daten_ist_keine_fehlermeldung(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/monate", params={"jahr": 2030})
        assert antwort.status_code == 200
        koerper = antwort.json()
        assert len(koerper["monate"]) == 12
        assert koerper["ist_netto"] == 0 and koerper["plan_netto"] == 0

    def test_filter_projektleiter(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get(
            "/api/umsatz/monate", params={"jahr": 2026, "projektleiter": "Günther"}
        ).json()
        assert antwort["plan_netto"] == 2500000
        assert antwort["ist_netto"] == 0

    def test_filter_gewerk(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get(
            "/api/umsatz/monate", params={"jahr": 2026, "anlagenart": "aufdach"}
        ).json()
        assert antwort["ist_netto"] == 3000000
        assert antwort["plan_netto"] == 4000000

    def test_filter_status(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get(
            "/api/umsatz/monate", params={"jahr": 2026, "status": "in_bau"}
        ).json()
        assert antwort["plan_netto"] == 2500000

    def test_unbekannter_filterwert_wird_abgewiesen(self, buchhaltung, bestand):
        """Ein Tippfehler darf nicht wie „kein Umsatz" aussehen."""
        antwort = buchhaltung.client.get("/api/umsatz/monate", params={"anlagenart": "dachanlage"})
        assert antwort.status_code == 422

    def test_filterwerte_kommen_aus_den_daten(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/monate").json()
        assert antwort["jahre"] == [2026, 2025]
        assert antwort["projektleiter"] == ["Günther", "Stefan"]

    def test_hinweis_zum_altbestand(self, buchhaltung, bestand):
        """Der Ist ist unvollständig, und das sagt die Antwort (Entscheidung Svens)."""
        antwort = buchhaltung.client.get("/api/umsatz/monate").json()
        assert antwort["hinweise"], "Solange Altpositionen im Ist stecken, gehört der Hinweis dazu"
        assert "Auftragsliste" in antwort["hinweise"][0]
        assert "DATEV" in antwort["hinweise"][0]

    def test_ohne_altbestand_kein_hinweis(self, buchhaltung, bestand):
        with schreib_sitzung() as sitzung:
            for position in sitzung.scalars(
                select(Zahlungsplanposition).where(Zahlungsplanposition.migriert_gestellt.is_(True))
            ):
                position.migriert_gestellt = None
        antwort = buchhaltung.client.get("/api/umsatz/monate").json()
        assert antwort["hinweise"] == []

    def test_team_darf_nicht(self, team, bestand):
        assert team.client.get("/api/umsatz/monate").status_code == 403


class TestAuftragsbestand:
    def test_summe_und_projekte(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/auftragsbestand").json()
        # 100.000 − 30.000 gestellt = 70.000; 50.000 − 0 = 50.000
        assert antwort["bestand_netto"] == 7000000 + 5000000
        assert [p["projekt_nr"] for p in antwort["projekte"]] == [26001, 26002]
        assert antwort["projekte"][0]["rest_netto"] == 7000000
        assert antwort["projekte"][0]["fakturiert_netto"] == 3000000

    def test_abgeschlossene_projekte_zaehlen_nicht(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/auftragsbestand").json()
        assert 25001 not in [p["projekt_nr"] for p in antwort["projekte"]]

    def test_differenz_zum_zahlungsplan(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get("/api/umsatz/auftragsbestand").json()
        assert antwort["zahlungsplan_offen_netto"] == 4000000 + 1000000 + 2500000
        assert antwort["nicht_verplant_netto"] == 12000000 - 7500000

    def test_beauftragter_nachtrag_zaehlt(self, buchhaltung, bestand):
        with schreib_sitzung() as sitzung:
            projekt_id = sitzung.scalar(select(Projekt.id).where(Projekt.projekt_nr == 26001))
            sitzung.add(
                Nachtrag(
                    projekt_id=projekt_id,
                    bezeichnung="Mehr Module",
                    betrag_netto=500000,
                    status="beauftragt",
                )
            )
        antwort = buchhaltung.client.get("/api/umsatz/auftragsbestand").json()
        erstes = next(p for p in antwort["projekte"] if p["projekt_nr"] == 26001)
        assert erstes["nachtraege_netto"] == 500000
        assert erstes["soll_netto"] == 10500000
        assert erstes["rest_netto"] == 7500000

    def test_ohne_auftragswert_wird_ausgewiesen(self, buchhaltung, bestand):
        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
            sitzung.add(
                Projekt(
                    projekt_nr=26003,
                    firma_id=firma_id,
                    kunde_id=kunde_id,
                    status="beauftragt",
                    ab_wert_netto=None,
                )
            )
        antwort = buchhaltung.client.get("/api/umsatz/auftragsbestand").json()
        assert [p["projekt_nr"] for p in antwort["ohne_auftragswert"]] == [26003]
        assert antwort["bestand_netto"] == 12000000

    def test_ueberdeckung_landet_in_zu_pruefen(self, buchhaltung, bestand):
        with schreib_sitzung() as sitzung:
            projekt = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26001))
            projekt.ab_wert_netto = 1000000
        antwort = buchhaltung.client.get("/api/umsatz/auftragsbestand").json()
        assert [p["projekt_nr"] for p in antwort["zu_pruefen"]] == [26001]
        assert antwort["projekte"][-1]["rest_netto"] == -2000000

    def test_filter_wirkt_auch_hier(self, buchhaltung, bestand):
        antwort = buchhaltung.client.get(
            "/api/umsatz/auftragsbestand", params={"anlagenart": "speicher"}
        ).json()
        assert [p["projekt_nr"] for p in antwort["projekte"]] == [26002]
        assert antwort["bestand_netto"] == 5000000

    def test_team_darf_nicht(self, team, bestand):
        assert team.client.get("/api/umsatz/auftragsbestand").status_code == 403


class TestSichtbarkeit:
    def test_scope_eigene_begrenzt_die_summen(self, client, nutzer_erzeugen, bestand):
        """Der Scope `eigene` darf nicht nur Listen, sondern muss auch Summen beschränken."""
        from app.modelle import Berechtigung, Rolle, User

        nutzer_id = nutzer_erzeugen("pl-um@ip3-energie.de", "team")
        with schreib_sitzung() as sitzung:
            rolle = Rolle(name="pl-umsatz", beschreibung="Umsatz nur eigener Projekte")
            sitzung.add(rolle)
            eigene = Berechtigung(
                schluessel="projekte.lesen", scope="eigene", beschreibung="nur eigene"
            )
            sitzung.add(eigene)
            rolle.berechtigungen.append(eigene)
            for schluessel in ("umsatz.lesen",):
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
            # Nur das Speicherprojekt gehört diesem Konto.
            speicher = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26002))
            speicher.pl_user_id = nutzer_id

        pl = anmelden(client, "pl-um@ip3-energie.de")
        monate = pl.client.get("/api/umsatz/monate", params={"jahr": 2026}).json()
        assert monate["ist_netto"] == 0
        assert monate["plan_netto"] == 2500000
        assert monate["unterminiert"]["summe_netto"] == 0
        bestand_antwort = pl.client.get("/api/umsatz/auftragsbestand").json()
        assert [p["projekt_nr"] for p in bestand_antwort["projekte"]] == [26002]
        assert bestand_antwort["bestand_netto"] == 5000000
