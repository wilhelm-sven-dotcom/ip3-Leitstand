"""Routen /api/cockpit (PLAN §4, §7 Phase 5).

Zwei Dinge stehen hier im Vordergrund:

* **Die Finanzsichtbarkeit ist eine eigene Entscheidung** (PLAN §4). ``cockpit.lesen`` hat nur
  ``admin``; ``team`` sieht Projekte, ``buchhaltung`` darf importieren – das Firmen-Cockpit
  sieht keiner von beiden. Ohne diese Trennung wäre die Rollentabelle des Plans sinnlos.
* **Die Antwort trägt ihre eigene Einordnung.** ``steuerungssicht`` steht im Antwortkörper,
  damit die Oberfläche den Hinweis „keine handelsrechtliche BWA" nicht vergessen kann.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.datenbank import schreib_sitzung
from app.modelle import (
    DatevSaldo,
    Firma,
    IstKosten,
    Kunde,
    Opos,
    Projekt,
    Rechnung,
    Zahlungsplanposition,
)
from tests.conftest_auth import anmelden

MONAT = "2026-07"


@pytest.fixture
def bestand(gesäte_db) -> None:
    """Ein Monat mit Umsatz, variablen Kosten, Fixkosten und einem offenen Posten."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=20001, name="Cockpit GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        projekt = Projekt(
            projekt_nr=26001,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            standort="Weiden",
            ab_wert_netto=50_000_000,
        )
        sitzung.add(projekt)
        sitzung.flush()

        rechnung = Rechnung(
            rechnung_nr="RE-2026-0001",
            firma_id=firma_id,
            art="abschlag",
            projekt_id=projekt.id,
            kunde_id=kunde.id,
            kunde_snapshot={"name": "Cockpit GmbH"},
            datum=date(2026, 7, 15),
            faellig_am=date(2026, 7, 29),
            netto=20_000_000,
            brutto=20_000_000,
            zahlbetrag=20_000_000,
            status="festgeschrieben",
        )
        sitzung.add(rechnung)
        sitzung.flush()
        sitzung.add(
            Zahlungsplanposition(
                projekt_id=projekt.id,
                pos_nr=1,
                bezeichnung="1. Abschlag",
                gewerk="pv",
                art="abschlag",
                betrag_netto=20_000_000,
                plan_monat=MONAT,
                rechnung_id=rechnung.id,
                created_by="test",
            )
        )
        sitzung.add(
            IstKosten(
                projekt_id=projekt.id,
                quelle="datev",
                monat=MONAT,
                betrag=12_000_000,
                referenz="3400 Wareneingang",
            )
        )
        sitzung.add(
            DatevSaldo(
                monat=MONAT, konto="4120", bezeichnung="Löhne", saldo=4_000_000, block="personal"
            )
        )
        # Ein Konto ohne Zuordnung: es fehlt im Fixkostenblock und gehört auf die Pflegeliste.
        sitzung.add(
            DatevSaldo(
                monat=MONAT, konto="4700", bezeichnung="Sonstiges", saldo=900_000, block=None
            )
        )
        sitzung.add(
            Opos(
                rechnung_nr="RE-2026-0001",
                kunde="Cockpit GmbH",
                betrag=20_000_000,
                faellig_am=date(2026, 7, 29),
                offen_betrag=20_000_000,
                stand_datum=date(2026, 8, 31),
            )
        )


@pytest.fixture
def admin(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("chef@ip3-energie.de", "admin")
    return anmelden(client, "chef@ip3-energie.de")


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("buha@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("team@ip3-energie.de", "team")
    return anmelden(client, "team@ip3-energie.de")


# ---------------------------------------------------------------------------
# Rechte
# ---------------------------------------------------------------------------


def test_team_sieht_projekte_aber_kein_cockpit(team) -> None:
    """PLAN §4: Finanzsichtbarkeit ist von der Projektsicht getrennt."""
    assert team.client.get("/api/projekte").status_code == 200
    assert team.client.get("/api/cockpit").status_code == 403
    assert team.client.get("/api/cockpit/zahlungen").status_code == 403
    assert team.client.get("/api/cockpit/konten-offen").status_code == 403


def test_buchhaltung_darf_importieren_aber_kein_cockpit_sehen(buchhaltung) -> None:
    assert buchhaltung.client.get("/api/importe/laeufe").status_code == 200
    assert buchhaltung.client.get("/api/cockpit").status_code == 403


def test_admin_sieht_alles(admin) -> None:
    assert admin.client.get("/api/cockpit").status_code == 200
    assert admin.client.get("/api/cockpit/zahlungen").status_code == 200
    assert admin.client.get("/api/cockpit/konten-offen").status_code == 200


def test_ohne_anmeldung_401(client) -> None:
    assert client.get("/api/cockpit").status_code == 401


# ---------------------------------------------------------------------------
# Monatsansicht
# ---------------------------------------------------------------------------


def test_monatsansicht_rechnet_durch(admin) -> None:
    antwort = admin.client.get(f"/api/cockpit?monat={MONAT}")
    assert antwort.status_code == 200
    daten = antwort.json()

    aktuell = next(m for m in daten["monate"] if m["monat"] == MONAT)
    assert aktuell["umsatz_netto"] == 20_000_000
    assert aktuell["variable_kosten"] == 12_000_000
    assert aktuell["deckungsbeitrag"] == 8_000_000
    assert aktuell["fixkosten"] == 4_000_000
    assert aktuell["deckung"] == 4_000_000
    assert aktuell["fixkosten_herkunft"] == "susa"


def test_antwort_traegt_den_bwa_hinweis(admin) -> None:
    """Die Einordnung gehört in die Antwort, nicht nur in die Oberfläche (PLAN §7)."""
    daten = admin.client.get("/api/cockpit").json()
    assert "keine handelsrechtliche BWA" in daten["steuerungssicht"]


def test_unzugeordnetes_konto_erscheint_als_hinweis_und_in_der_liste(admin) -> None:
    daten = admin.client.get(f"/api/cockpit?monat={MONAT}").json()
    assert any("keinem Kostenblock zugeordnet" in h for h in daten["hinweise"])

    offene = admin.client.get("/api/cockpit/konten-offen").json()
    assert [k["konto"] for k in offene] == ["4700"]
    assert offene[0]["summe"] == 900_000


def test_ohne_monat_kommt_der_laufende(admin) -> None:
    daten = admin.client.get("/api/cockpit").json()
    assert daten["monat"] == f"{date.today():%Y-%m}"


def test_unsinniger_monat_wird_verstaendlich_abgewiesen(admin) -> None:
    antwort = admin.client.get("/api/cockpit?monat=Juli")
    assert antwort.status_code == 400
    koerper = antwort.json()
    assert koerper["code"] == "monat_ungueltig"
    assert "JJJJ-MM" in koerper["naechster_schritt"]
    assert "Traceback" not in antwort.text


def test_verfuegbare_monate_sind_nie_leer(admin) -> None:
    assert admin.client.get("/api/cockpit").json()["verfuegbare_monate"]


# ---------------------------------------------------------------------------
# Umschalter gestellt / bezahlt
# ---------------------------------------------------------------------------


def test_umschalter_aendert_den_umsatz(admin) -> None:
    gestellt = admin.client.get(f"/api/cockpit?monat={MONAT}&basis=gestellt").json()
    bezahlt = admin.client.get(f"/api/cockpit?monat={MONAT}&basis=bezahlt").json()

    assert next(m for m in gestellt["monate"] if m["monat"] == MONAT)["umsatz_netto"] == 20_000_000
    # Die Rechnung steht am Stichtag noch offen – als Zahlungseingang zählt sie nicht.
    assert next(m for m in bezahlt["monate"] if m["monat"] == MONAT)["umsatz_netto"] == 0
    assert bezahlt["umsatzbasis"] == "bezahlt"


def test_unbekannte_basis_wird_abgewiesen(admin) -> None:
    assert admin.client.get("/api/cockpit?basis=geschaetzt").status_code == 422


# ---------------------------------------------------------------------------
# Zahlungslage
# ---------------------------------------------------------------------------


def test_zahlungslage(admin) -> None:
    daten = admin.client.get("/api/cockpit/zahlungen").json()

    assert daten["stichtag"] == "2026-08-31"
    assert daten["offen"] == 20_000_000
    assert daten["ueberfaellig"] == 20_000_000
    assert [p["rechnung_nr"] for p in daten["posten"]] == ["RE-2026-0001"]
    assert daten["posten"][0]["status"] == "ueberfaellig"
    assert daten["posten"][0]["kunde"] == "Cockpit GmbH"
