"""Routen /api/anlagen und /api/fristen (PLAN §4, §7 Phase 6).

Zwei Fragen entscheiden sich hier:

* **Wer darf was.** Team und Buchhaltung sehen das Register (``anlagen.lesen``), ändern dürfen
  es nur Nutzer mit ``anlagen.schreiben`` – dort stehen Zusagen mit Rechtsfolge, kein Notizbuch.
* **Was mit erledigten Dingen passiert.** Fristen werden abgehakt, nicht gelöscht; Anlagen gibt
  es überhaupt nicht zum Löschen (CLAUDE.md Regel 5).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import Anlage, AuditEintrag, Firma, Frist, Kunde, Projekt
from tests.conftest_auth import anmelden


@pytest.fixture
def bestand(gesäte_db) -> dict[str, int]:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=50001, name="Gut Sonnenhang", ort="Floß", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()

        anlage = Anlage(
            kunde_id=kunde.id,
            standort="Floß, Sonnenhang 7",
            pv_kwp=99.5,
            speicher_kwh=60.0,
            inbetriebnahme=date(2026, 5, 12),
            abnahme_datum=date(2026, 5, 20),
            gewaehrleistung_ende=date(2030, 5, 20),
        )
        zweite = Anlage(
            kunde_id=kunde.id,
            standort="Floß, Lagerhalle",
            inbetriebnahme=date(2024, 3, 1),
            wartungsvertrag=True,
            mastr_nr="SEE900000099999",
        )
        sitzung.add_all([anlage, zweite])
        sitzung.flush()

        sitzung.add_all(
            [
                Frist(
                    bezug="anlage",
                    bezug_id=anlage.id,
                    typ="gewaehrleistung",
                    bezeichnung="Gewährleistung endet (VOB, 4 Jahre)",
                    faellig_am=date(2030, 5, 20),
                    vorlauf_tage=90,
                ),
                # Frist an der zweiten Anlage: sie darf im Blatt der ersten nicht auftauchen.
                Frist(
                    bezug="anlage",
                    bezug_id=zweite.id,
                    typ="sonstig",
                    bezeichnung="Zählerwechsel Lagerhalle",
                    faellig_am=date(2027, 2, 1),
                    vorlauf_tage=30,
                ),
            ]
        )
        # Ein Serviceauftrag zur ersten Anlage – die Historie im Anlagenblatt.
        sitzung.add(
            Projekt(
                projekt_nr=26900,
                firma_id=firma_id,
                kunde_id=kunde.id,
                typ="service",
                anlage_id=anlage.id,
                status="abgeschlossen",
                bezeichnung="Wechselrichtertausch",
                auftrag_vom=date(2026, 7, 1),
            )
        )
        return {"anlage": anlage.id, "zweite": zweite.id, "kunde": kunde.id}


@pytest.fixture
def admin(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("chef@ip3-energie.de", "admin")
    return anmelden(client, "chef@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("team@ip3-energie.de", "team")
    return anmelden(client, "team@ip3-energie.de")


# ---------------------------------------------------------------------------
# Rechte
# ---------------------------------------------------------------------------


def test_team_sieht_das_register_aber_aendert_nichts(team, bestand) -> None:
    assert team.client.get("/api/anlagen").status_code == 200
    assert team.client.get("/api/fristen").status_code == 200

    antwort = team.schreiben(
        "PUT",
        f"/api/anlagen/{bestand['anlage']}",
        json={"kunde_id": bestand["kunde"], "stand": "2026-01-01T00:00:00Z"},
    )
    assert antwort.status_code == 403
    assert team.schreiben("POST", "/api/fristen", json={}).status_code == 403


def test_ohne_anmeldung_401(client) -> None:
    assert client.get("/api/anlagen").status_code == 401
    assert client.get("/api/fristen").status_code == 401


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


def test_liste_juengste_zuerst(admin) -> None:
    daten = admin.client.get("/api/anlagen").json()
    assert daten["gesamt"] == 2
    assert [a["standort"] for a in daten["anlagen"]] == [
        "Floß, Sonnenhang 7",
        "Floß, Lagerhalle",
    ]
    assert daten["anlagen"][0]["pv_kwp"] == 99.5


def test_liste_ohne_wartungsvertrag(admin) -> None:
    """Die Liste, aus der Servicegeschäft entsteht (PLAN §7 Phase 6)."""
    daten = admin.client.get("/api/anlagen?ohne_wartungsvertrag=true").json()
    assert [a["standort"] for a in daten["anlagen"]] == ["Floß, Sonnenhang 7"]


def test_suche_ueber_standort_kunde_und_mastr(admin) -> None:
    for suche, erwartet in (
        ("sonnenhang", 2),  # Standort der einen, Kundenname beider Anlagen
        ("lagerhalle", 1),
        ("SEE900000099999", 1),
        ("gibtesnicht", 0),
    ):
        daten = admin.client.get(f"/api/anlagen?suche={suche}").json()
        assert daten["gesamt"] == erwartet, suche


def test_anlagenblatt_zeigt_fristen_und_servicehistorie(admin, bestand) -> None:
    daten = admin.client.get(f"/api/anlagen/{bestand['anlage']}").json()
    assert daten["abnahme_datum"] == "2026-05-20"
    # Nur die eigenen Fristen: die der zweiten Anlage bleibt draußen.
    assert [f["typ"] for f in daten["fristen"]] == ["gewaehrleistung"]
    assert daten["fristen"][0]["stand"]
    assert daten["fristen"][0]["betreff"] == "Floß, Sonnenhang 7"
    assert [s["projekt_nr"] for s in daten["servicehistorie"]] == [26900]
    assert daten["servicehistorie"][0]["bezeichnung"] == "Wechselrichtertausch"


def test_unbekannte_anlage_gibt_verstaendliches_404(admin) -> None:
    antwort = admin.client.get("/api/anlagen/9999")
    assert antwort.status_code == 404
    assert "Anlagenregister" in antwort.json()["naechster_schritt"]
    assert "Traceback" not in antwort.text


def test_altbestand_von_hand_anlegen(admin, bestand) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/anlagen",
        json={
            "kunde_id": bestand["kunde"],
            "standort": "Floß, Altbau",
            "inbetriebnahme": "2018-06-01",
            "pv_kwp": 9.9,
        },
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["standort"] == "Floß, Altbau"

    with lese_sitzung() as sitzung:
        assert len(list(sitzung.scalars(select(Anlage)))) == 3


def test_anlage_ohne_kunden_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben("POST", "/api/anlagen", json={"kunde_id": 9999})
    assert antwort.status_code == 404
    assert "Stammdaten" in antwort.json()["naechster_schritt"]


def test_speichern_mit_veraltetem_stand_ergibt_konflikt(admin, bestand) -> None:
    stand = admin.client.get(f"/api/anlagen/{bestand['anlage']}").json()
    admin.schreiben(
        "PUT",
        f"/api/anlagen/{bestand['anlage']}",
        json={**_koerper(stand), "bemerkung": "erste Änderung"},
    )
    antwort = admin.schreiben(
        "PUT",
        f"/api/anlagen/{bestand['anlage']}",
        json={**_koerper(stand), "bemerkung": "zweite Änderung"},
    )
    assert antwort.status_code == 409
    assert "Traceback" not in antwort.text


def _koerper(stand: dict) -> dict:
    return {
        "kunde_id": stand["kunde_id"],
        "standort": stand["standort"],
        "pv_kwp": stand["pv_kwp"],
        "speicher_kwh": stand["speicher_kwh"],
        "inbetriebnahme": stand["inbetriebnahme"],
        "abnahme_datum": stand["abnahme_datum"],
        "gewaehrleistung_ende": stand["gewaehrleistung_ende"],
        "wartungsvertrag": stand["wartungsvertrag"],
        "mastr_nr": stand["mastr_nr"],
        "bemerkung": stand["bemerkung"],
        "stand": stand["stand"],
    }


def test_wartungsvertrag_setzen_steht_im_audit(admin, bestand) -> None:
    stand = admin.client.get(f"/api/anlagen/{bestand['anlage']}").json()
    antwort = admin.schreiben(
        "PUT",
        f"/api/anlagen/{bestand['anlage']}",
        json={**_koerper(stand), "wartungsvertrag": True},
    )
    assert antwort.status_code == 200
    assert antwort.json()["wartungsvertrag"] is True

    with lese_sitzung() as sitzung:
        eintrag = sitzung.scalar(
            select(AuditEintrag).where(AuditEintrag.aktion == "anlage.geaendert")
        )
        assert eintrag.neu == {"wartungsvertrag": True}


def test_nachgetragene_mastr_nummer_hakt_die_frist_sofort_ab(admin, bestand) -> None:
    """Sonst bliebe die Frist bis zum nächtlichen Lauf rot – für den Erfasser unerklärlich."""
    with schreib_sitzung() as sitzung:
        sitzung.add(
            Frist(
                bezug="anlage",
                bezug_id=bestand["anlage"],
                typ="mastr",
                bezeichnung="Registrierung im Marktstammdatenregister",
                faellig_am=date(2026, 6, 11),
                vorlauf_tage=15,
            )
        )

    stand = admin.client.get(f"/api/anlagen/{bestand['anlage']}").json()
    admin.schreiben(
        "PUT",
        f"/api/anlagen/{bestand['anlage']}",
        json={**_koerper(stand), "mastr_nr": "SEE900000012345"},
    )

    with lese_sitzung() as sitzung:
        frist = sitzung.scalar(select(Frist).where(Frist.typ == "mastr"))
        assert frist.erledigt_am == date.today()


# ---------------------------------------------------------------------------
# Fristen
# ---------------------------------------------------------------------------


def test_fristenliste_mit_zaehlung(admin, bestand) -> None:
    daten = admin.client.get("/api/fristen").json()
    # Gleicher Zustand, also nach Fälligkeit: die nähere Frist zuerst.
    assert [f["typ"] for f in daten["fristen"]] == ["sonstig", "gewaehrleistung"]
    assert daten["zaehlung"]["offen"] == 2
    gewaehrleistung = daten["fristen"][1]
    assert gewaehrleistung["betreff"] == "Floß, Sonnenhang 7"
    assert gewaehrleistung["kunde"] == "Gut Sonnenhang"


def test_widget_zeigt_nur_anstehende(admin, bestand) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(
            Frist(
                bezug="anlage",
                bezug_id=bestand["anlage"],
                typ="sonstig",
                bezeichnung="Übergabeprotokoll",
                faellig_am=date.today() - timedelta(days=2),
                vorlauf_tage=14,
            )
        )
    daten = admin.client.get("/api/fristen?nur_anstehende=true").json()
    assert [f["typ"] for f in daten["fristen"]] == ["sonstig"]
    assert daten["fristen"][0]["status"] == "ueberfaellig"
    assert daten["fristen"][0]["tage_bis"] == -2


def test_grenze_kuerzt_die_liste_aber_nicht_die_zaehlung(admin, bestand) -> None:
    """„3 überfällig" darf nicht davon abhängen, wie viele Zeilen ins Widget passen."""
    with schreib_sitzung() as sitzung:
        for tage in (1, 2, 3):
            sitzung.add(
                Frist(
                    bezug="anlage",
                    bezug_id=bestand["anlage"],
                    typ="sonstig",
                    bezeichnung=f"Nachweis {tage}",
                    faellig_am=date.today() - timedelta(days=tage),
                    vorlauf_tage=14,
                )
            )
    daten = admin.client.get("/api/fristen?nur_anstehende=true&grenze=2").json()
    assert len(daten["fristen"]) == 2
    assert daten["zaehlung"]["ueberfaellig"] == 3


def test_frist_von_hand_anlegen(admin, bestand) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/fristen",
        json={
            "bezug": "anlage",
            "bezug_id": bestand["anlage"],
            "typ": "reservierung",
            "bezeichnung": "Netzanschluss-Reservierung läuft ab",
            "faellig_am": "2027-03-31",
            "vorlauf_tage": 60,
        },
    )
    assert antwort.status_code == 201, antwort.text
    daten = antwort.json()
    assert daten["betreff"] == "Floß, Sonnenhang 7"
    assert daten["status"] == "offen"


def test_frist_ohne_bezug_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/fristen",
        json={
            "bezug": "anlage",
            "bezug_id": 9999,
            "typ": "sonstig",
            "bezeichnung": "Erinnerung an nichts",
            "faellig_am": "2027-01-01",
        },
    )
    assert antwort.status_code == 404
    assert "Bezug" in antwort.json()["naechster_schritt"]


def test_unbekannter_fristtyp_wird_abgewiesen(admin, bestand) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/fristen",
        json={
            "bezug": "anlage",
            "bezug_id": bestand["anlage"],
            "typ": "kaffeepause",
            "bezeichnung": "…",
            "faellig_am": "2027-01-01",
        },
    )
    assert antwort.status_code == 422


def test_frist_abhaken_und_wieder_oeffnen(admin, bestand) -> None:
    frist_id = _gewaehrleistung(admin)["id"]

    daten = admin.schreiben("POST", f"/api/fristen/{frist_id}/erledigt").json()
    assert daten["erledigt_am"] == f"{date.today():%Y-%m-%d}"
    # Abgehakt heißt aus der Liste, nicht aus der Datenbank.
    assert [f["typ"] for f in admin.client.get("/api/fristen").json()["fristen"]] == ["sonstig"]
    with lese_sitzung() as sitzung:
        assert sitzung.get(Frist, frist_id) is not None

    wieder = admin.schreiben("POST", f"/api/fristen/{frist_id}/erledigt?erledigt=false").json()
    assert wieder["erledigt_am"] is None
    assert len(admin.client.get("/api/fristen").json()["fristen"]) == 2


def _gewaehrleistung(admin) -> dict:
    """Die Gewährleistungsfrist der ersten Anlage aus der Liste."""
    fristen = admin.client.get("/api/fristen").json()["fristen"]
    return next(f for f in fristen if f["typ"] == "gewaehrleistung")


def test_abhaken_steht_im_audit(admin, bestand) -> None:
    frist_id = _gewaehrleistung(admin)["id"]
    admin.schreiben("POST", f"/api/fristen/{frist_id}/erledigt")
    with lese_sitzung() as sitzung:
        eintrag = sitzung.scalar(
            select(AuditEintrag).where(AuditEintrag.aktion == "frist.erledigt")
        )
        assert eintrag.datensatz_id == frist_id


def test_frist_verschieben(admin, bestand) -> None:
    zeile = _gewaehrleistung(admin)
    antwort = admin.schreiben(
        "PUT",
        f"/api/fristen/{zeile['id']}",
        json={
            "bezeichnung": zeile["bezeichnung"],
            "faellig_am": "2031-05-20",
            "vorlauf_tage": 90,
            "stand": zeile["stand"],
        },
    )
    assert antwort.status_code == 200
    assert antwort.json()["faellig_am"] == "2031-05-20"


def test_frist_verschieben_mit_veraltetem_stand(admin, bestand) -> None:
    zeile = _gewaehrleistung(admin)
    koerper = {
        "bezeichnung": zeile["bezeichnung"],
        "faellig_am": "2031-05-20",
        "vorlauf_tage": 90,
        "stand": zeile["stand"],
    }
    admin.schreiben("PUT", f"/api/fristen/{zeile['id']}", json=koerper)
    antwort = admin.schreiben(
        "PUT", f"/api/fristen/{zeile['id']}", json={**koerper, "faellig_am": "2032-01-01"}
    )
    assert antwort.status_code == 409


# ---------------------------------------------------------------------------
# Serviceaufträge (PLAN §7 Phase 6)
# ---------------------------------------------------------------------------


def test_serviceauftrag_bezieht_sich_auf_eine_anlage(admin, bestand) -> None:
    """Positionen entstehen von Hand über den Zahlungsplan (Entscheidung 33)."""
    antwort = admin.schreiben(
        "POST",
        "/api/projekte",
        json={
            "kunde_id": bestand["kunde"],
            "typ": "service",
            "anlage_id": bestand["anlage"],
            "bezeichnung": "Jahreswartung 2027",
            "auftrag_vom": "2027-02-01",
            "status": "beauftragt",
        },
    )
    assert antwort.status_code == 201, antwort.text
    daten = antwort.json()
    # Serviceaufträge tragen die führende 9 im Nummernkreis (PLAN §3).
    assert str(daten["projekt_nr"]).startswith("9")
    assert daten["anlage_standort"] == "Floß, Sonnenhang 7"


def test_bauprojekt_darf_sich_nicht_auf_eine_anlage_beziehen(admin, bestand) -> None:
    """Sonst stünden zwei Wahrheiten nebeneinander: erzeugt und bezieht sich auf."""
    antwort = admin.schreiben(
        "POST",
        "/api/projekte",
        json={"kunde_id": bestand["kunde"], "typ": "projekt", "anlage_id": bestand["anlage"]},
    )
    assert antwort.status_code == 409
    assert antwort.json()["code"] == "anlagenbezug_nur_service"


def test_serviceauftrag_auf_unbekannte_anlage(admin, bestand) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/projekte",
        json={"kunde_id": bestand["kunde"], "typ": "service", "anlage_id": 9999},
    )
    assert antwort.status_code == 404
    assert "Anlagenregister" in antwort.json()["naechster_schritt"]


def test_serviceauftrag_ohne_anlage_ist_erlaubt(admin, bestand) -> None:
    """Nicht jeder Einsatz führt zu einer Anlage im Register."""
    antwort = admin.schreiben(
        "POST",
        "/api/projekte",
        json={"kunde_id": bestand["kunde"], "typ": "service", "bezeichnung": "Störungsdienst"},
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["anlage_id"] is None


def test_projektliste_laesst_sich_auf_service_filtern(admin, bestand) -> None:
    daten = admin.client.get("/api/projekte?typ=service").json()
    assert [p["projekt_nr"] for p in daten["eintraege"]] == [26900]
    assert admin.client.get("/api/projekte?typ=projekt").json()["gesamt"] == 0
    assert admin.client.get("/api/projekte").json()["gesamt"] == 1


def test_neuer_serviceauftrag_erscheint_in_der_servicehistorie(admin, bestand) -> None:
    admin.schreiben(
        "POST",
        "/api/projekte",
        json={
            "kunde_id": bestand["kunde"],
            "typ": "service",
            "anlage_id": bestand["anlage"],
            "bezeichnung": "Modultausch",
            "auftrag_vom": "2027-04-05",
        },
    )
    daten = admin.client.get(f"/api/anlagen/{bestand['anlage']}").json()
    assert [s["bezeichnung"] for s in daten["servicehistorie"]] == [
        "Modultausch",
        "Wechselrichtertausch",
    ]
