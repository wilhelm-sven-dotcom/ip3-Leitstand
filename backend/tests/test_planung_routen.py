"""Routen /api/kapazitaet, /api/mitarbeiter und /api/angebote (PLAN §4, §7 Phase 7).

Die Rechtefrage ist hier eine echte: die Wochenauslastung zeigt Stunden und geht das Team an,
die Angebotssummen sind Beträge und tun das nicht (PLAN §4). Dazu die Zusagen, die keine sein
dürfen – die Antwort trägt ihre eigene Einordnung.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import (
    Angebot,
    AuditEintrag,
    Firma,
    Kunde,
    Meilenstein,
    Mitarbeiter,
    Projekt,
    SollKalkulation,
)
from tests.conftest_auth import anmelden


@pytest.fixture
def bestand(gesäte_db) -> dict[str, int]:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=80001, name="Planungskunde GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()

        projekt = Projekt(
            projekt_nr=26500,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            bezeichnung="Halle Süd",
        )
        sitzung.add(projekt)
        sitzung.flush()
        sitzung.add(SollKalkulation(projekt_id=projekt.id, stunden_soll=160))
        sitzung.add(Meilenstein(projekt_id=projekt.id, typ="montage_uk", geplant_kw="36/26"))
        sitzung.add(Mitarbeiter(name="Monteur, Max", wochenstunden=38.5, satzgruppe="monteur"))
        sitzung.add(
            Angebot(
                angebot_nr="A-2027-001",
                kunde_name="Solarpark Nord GmbH",
                summe_netto=1_000_000_00,
                wahrscheinlichkeit_promille=600,
                erwarteter_monat="2027-03",
                status="offen",
            )
        )
        return {"kunde": kunde.id, "projekt": projekt.id}


@pytest.fixture
def admin(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("chef@ip3-energie.de", "admin")
    return anmelden(client, "chef@ip3-energie.de")


@pytest.fixture
def team(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("team@ip3-energie.de", "team")
    return anmelden(client, "team@ip3-energie.de")


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen, bestand):
    nutzer_erzeugen("buha@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha@ip3-energie.de")


# ---------------------------------------------------------------------------
# Rechte (PLAN §4)
# ---------------------------------------------------------------------------


def test_team_sieht_die_auslastung(team) -> None:
    """Stunden, keine Beträge: die Wochenauslastung ist der eigene Terminplan."""
    assert team.client.get("/api/kapazitaet").status_code == 200
    assert team.client.get("/api/mitarbeiter").status_code == 200


def test_team_sieht_keine_angebote(team) -> None:
    """Eine Angebotssumme ist ein Betrag – Beträge sind in PLAN §4 abgetrennt."""
    assert team.client.get("/api/angebote").status_code == 403
    assert team.client.get("/api/angebote/pipeline").status_code == 403


def test_team_pflegt_keine_mitarbeiter(team) -> None:
    antwort = team.schreiben("POST", "/api/mitarbeiter", json={"name": "Neu, Nina"})
    assert antwort.status_code == 403


def test_buchhaltung_sieht_die_auslastung_aber_keine_angebote(buchhaltung) -> None:
    assert buchhaltung.client.get("/api/kapazitaet").status_code == 200
    assert buchhaltung.client.get("/api/angebote").status_code == 403


def test_ohne_anmeldung_401(client) -> None:
    assert client.get("/api/kapazitaet").status_code == 401
    assert client.get("/api/angebote").status_code == 401


# ---------------------------------------------------------------------------
# Kapazität
# ---------------------------------------------------------------------------


def test_kapazitaet_rechnet_durch(admin) -> None:
    daten = admin.client.get("/api/kapazitaet?ab=2026-08-31&wochen=4").json()

    assert [w["schluessel"] for w in daten["wochen"]] == [
        "2026-W36",
        "2026-W37",
        "2026-W38",
        "2026-W39",
    ]
    woche = daten["wochen"][0]
    assert woche["bedarf"] == 160
    assert woche["kapazitaet"] == 38.5
    assert woche["rest"] == -121.5
    # 160 von 38,5 Stunden sind gut das Vierfache.
    assert woche["auslastung_promille"] == 4156
    assert woche["projekte"][0]["projekt_nr"] == 26500


def test_antwort_traegt_die_einordnung(admin) -> None:
    """Urlaub und Krankheit fehlen – das darf die Oberfläche nicht weglassen können."""
    daten = admin.client.get("/api/kapazitaet").json()
    assert "Urlaub und Krankheit" in daten["einordnung"]
    assert "keine Zusage" in daten["einordnung"]


def test_warnschwelle_kommt_aus_der_konfiguration(admin) -> None:
    assert admin.client.get("/api/kapazitaet").json()["warnung_ab_promille"] == 900


def test_mitarbeiterliste_nennt_fremde_timetac_namen(admin) -> None:
    daten = admin.client.get("/api/mitarbeiter").json()
    assert [m["name"] for m in daten["mitarbeiter"]] == ["Monteur, Max"]
    assert daten["summe_wochenstunden"] == 38.5
    assert daten["ohne_datensatz"] == []


def test_mitarbeiter_anlegen_und_aendern(admin) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/mitarbeiter",
        json={"name": "Bäumler, Michael", "wochenstunden": 40, "satzgruppe": "obermonteur"},
    )
    assert antwort.status_code == 201, antwort.text
    angelegt = antwort.json()

    geaendert = admin.schreiben(
        "PUT",
        f"/api/mitarbeiter/{angelegt['id']}",
        json={
            "name": "Bäumler, Michael",
            "wochenstunden": 30,
            "satzgruppe": "obermonteur",
            "aktiv": True,
            "stand": angelegt["stand"],
        },
    )
    assert geaendert.status_code == 200
    assert geaendert.json()["wochenstunden"] == 30

    with lese_sitzung() as sitzung:
        assert sitzung.scalar(
            select(AuditEintrag).where(AuditEintrag.aktion == "mitarbeiter.geaendert")
        )


def test_doppelter_name_wird_abgewiesen(admin) -> None:
    """Zwei Zeilen für einen Menschen verdoppelten seine Wochenstunden."""
    antwort = admin.schreiben("POST", "/api/mitarbeiter", json={"name": "Monteur, Max"})
    assert antwort.status_code == 409
    assert antwort.json()["code"] == "mitarbeiter_doppelt"


def test_austritt_vor_eintritt_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/mitarbeiter",
        json={"name": "Verdreht, Vera", "von": "2027-01-01", "bis": "2026-01-01"},
    )
    assert antwort.status_code == 400
    assert antwort.json()["code"] == "zeitraum_verdreht"
    assert "Traceback" not in antwort.text


def test_unbekannte_satzgruppe_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST", "/api/mitarbeiter", json={"name": "Neu, Nina", "satzgruppe": "hausmeister"}
    )
    assert antwort.status_code == 422


def test_mitarbeiter_wird_deaktiviert_statt_geloescht(admin) -> None:
    liste = admin.client.get("/api/mitarbeiter").json()["mitarbeiter"][0]
    admin.schreiben(
        "PUT",
        f"/api/mitarbeiter/{liste['id']}",
        json={
            "name": liste["name"],
            "wochenstunden": 38.5,
            "aktiv": False,
            "stand": liste["stand"],
        },
    )
    daten = admin.client.get("/api/mitarbeiter").json()
    # Noch in der Liste, aber nicht mehr in der Kapazität.
    assert len(daten["mitarbeiter"]) == 1
    assert daten["summe_wochenstunden"] == 0
    assert admin.client.get("/api/kapazitaet").json()["kapazitaet_gesamt"] == 0


def test_veralteter_stand_ergibt_konflikt(admin) -> None:
    liste = admin.client.get("/api/mitarbeiter").json()["mitarbeiter"][0]
    koerper = {"name": liste["name"], "wochenstunden": 20, "stand": liste["stand"]}
    assert (
        admin.schreiben("PUT", f"/api/mitarbeiter/{liste['id']}", json=koerper).status_code == 200
    )
    antwort = admin.schreiben("PUT", f"/api/mitarbeiter/{liste['id']}", json=koerper)
    assert antwort.status_code == 409


# ---------------------------------------------------------------------------
# Angebote und Pipeline
# ---------------------------------------------------------------------------


def test_angebotsliste_mit_gewichteter_summe(admin) -> None:
    daten = admin.client.get("/api/angebote").json()
    assert daten["gesamt"] == 1
    assert daten["roh_netto"] == 1_000_000_00
    assert daten["gewichtet_netto"] == 600_000_00
    assert daten["angebote"][0]["gewichtet_netto"] == 600_000_00


def test_pipeline_traegt_die_einordnung(admin) -> None:
    """Die Oberfläche darf nie vergessen, dass das keine Aufträge sind."""
    daten = admin.client.get("/api/angebote/pipeline?jahr=2027").json()
    assert "keine Aufträge" in daten["einordnung"]
    assert "nicht zum Auftragsbestand" in daten["einordnung"]

    maerz = next(m for m in daten["monate"] if m["monat"] == "2027-03")
    assert maerz["roh_netto"] == 1_000_000_00
    assert maerz["gewichtet_netto"] == 600_000_00
    assert daten["jahre"] == [2027]


def test_angebot_erfassen_und_aendern(admin, bestand) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/angebote",
        json={
            "kunde_name": "Neuer Interessent",
            "summe_netto": 50_000_00,
            "wahrscheinlichkeit_promille": 300,
            "erwarteter_monat": "2027-06",
        },
    )
    assert antwort.status_code == 201, antwort.text
    angelegt = antwort.json()
    assert angelegt["gewichtet_netto"] == 15_000_00

    geaendert = admin.schreiben(
        "PUT",
        f"/api/angebote/{angelegt['id']}",
        json={
            "kunde_name": "Neuer Interessent",
            "summe_netto": 50_000_00,
            "wahrscheinlichkeit_promille": 800,
            "erwarteter_monat": "2027-06",
            "status": "offen",
            "stand": angelegt["stand"],
        },
    )
    assert geaendert.status_code == 200
    assert geaendert.json()["gewichtet_netto"] == 40_000_00


def test_gewonnen_ohne_projekt_wird_abgewiesen(admin) -> None:
    """Sonst stünde der Wert weder in der Pipeline noch im Auftragsbestand."""
    angebot = admin.client.get("/api/angebote").json()["angebote"][0]
    antwort = admin.schreiben(
        "PUT",
        f"/api/angebote/{angebot['id']}",
        json={
            "kunde_name": angebot["kunde_name"],
            "summe_netto": angebot["summe_netto"],
            "wahrscheinlichkeit_promille": angebot["wahrscheinlichkeit_promille"],
            "erwarteter_monat": angebot["erwarteter_monat"],
            "status": "gewonnen",
            "stand": angebot["stand"],
        },
    )
    assert antwort.status_code == 409
    assert antwort.json()["code"] == "gewonnen_ohne_projekt"


def test_gewonnen_mit_projekt_geht(admin, bestand) -> None:
    angebot = admin.client.get("/api/angebote").json()["angebote"][0]
    antwort = admin.schreiben(
        "PUT",
        f"/api/angebote/{angebot['id']}",
        json={
            "kunde_name": angebot["kunde_name"],
            "summe_netto": angebot["summe_netto"],
            "wahrscheinlichkeit_promille": angebot["wahrscheinlichkeit_promille"],
            "erwarteter_monat": angebot["erwarteter_monat"],
            "status": "gewonnen",
            "projekt_id": bestand["projekt"],
            "stand": angebot["stand"],
        },
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["projekt_nr"] == 26500
    # Und es zählt nicht mehr in der Pipeline.
    assert admin.client.get("/api/angebote/pipeline?jahr=2027").json()["anzahl"] == 0


def test_unsinniger_monat_wird_verstaendlich_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST", "/api/angebote", json={"kunde_name": "X", "erwarteter_monat": "Juni"}
    )
    assert antwort.status_code == 422
    assert "Traceback" not in antwort.text


def test_unbekanntes_projekt_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben("POST", "/api/angebote", json={"kunde_name": "X", "projekt_id": 9999})
    assert antwort.status_code == 404
    assert "Projekt anlegen" in antwort.json()["naechster_schritt"]


def test_doppelte_angebotsnummer_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST", "/api/angebote", json={"kunde_name": "X", "angebot_nr": "A-2027-001"}
    )
    assert antwort.status_code == 409
    assert antwort.json()["code"] == "angebot_doppelt"


def test_statusfilter(admin, bestand) -> None:
    assert admin.client.get("/api/angebote?status=verloren").json()["gesamt"] == 0
    assert admin.client.get("/api/angebote?status=alle").json()["gesamt"] == 1
    antwort = admin.client.get("/api/angebote?status=vielleicht")
    assert antwort.status_code == 400
    assert antwort.json()["code"] == "status_ungueltig"


def test_negative_summe_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST", "/api/angebote", json={"kunde_name": "X", "summe_netto": -100}
    )
    assert antwort.status_code == 422


# ---------------------------------------------------------------------------
# Import der Angebotsliste
# ---------------------------------------------------------------------------


def _angebotsdatei(ordner, zeilen: list[list[object]]):
    from openpyxl import Workbook

    ordner.mkdir(parents=True, exist_ok=True)
    mappe = Workbook()
    blatt = mappe.active
    blatt.append(
        [
            "Angebotsnummer",
            "Kunde",
            "Bezeichnung",
            "Angebotssumme",
            "Wahrscheinlichkeit",
            "Erwarteter Auftrag",
            "Status",
        ]
    )
    for zeile in zeilen:
        blatt.append(zeile)
    pfad = ordner / "angebote.xlsx"
    mappe.save(pfad)
    return pfad


def test_import_ohne_eingerichteten_ordner_nennt_die_config(admin, test_einstellungen) -> None:
    test_einstellungen.pfade.angebote = None
    antwort = admin.client.get("/api/importe/angebote/vorschau")
    assert antwort.status_code == 409
    assert "config.toml" in antwort.json()["naechster_schritt"]
    assert "Traceback" not in antwort.text


def test_import_ohne_datei_nennt_den_erwarteten_namen(admin, test_einstellungen, tmp_path) -> None:
    ordner = tmp_path / "05_Angebote"
    ordner.mkdir()
    test_einstellungen.pfade.angebote = ordner
    antwort = admin.client.get("/api/importe/angebote/vorschau")
    assert antwort.status_code == 409
    assert "angebote" in antwort.json()["naechster_schritt"]


def test_vorschau_schreibt_nichts(admin, test_einstellungen, tmp_path) -> None:
    test_einstellungen.pfade.angebote = tmp_path / "05_Angebote"
    _angebotsdatei(
        test_einstellungen.pfade.angebote,
        [["A-2027-050", "Neuer Kunde", "Dach", "80.000,00", "40 %", "05/2027", "offen"]],
    )

    daten = admin.client.get("/api/importe/angebote/vorschau").json()
    assert daten["kontrollsummen"]["zeilen"] == 1
    assert daten["kontrollsummen"]["summe_netto"] == 80_000_00
    assert daten["kontrollsummen"]["gewichtet_netto"] == 32_000_00
    assert any("keine Aufträge" in h for h in daten["hinweise"])

    with lese_sitzung() as sitzung:
        # Nur das eine Angebot aus dem Bestand.
        assert len(list(sitzung.scalars(select(Angebot)))) == 1


def test_uebernehmen_schreibt_und_protokolliert(admin, test_einstellungen, tmp_path) -> None:
    test_einstellungen.pfade.angebote = tmp_path / "05_Angebote"
    _angebotsdatei(
        test_einstellungen.pfade.angebote,
        [["A-2027-050", "Neuer Kunde", "Dach", "80.000,00", "40 %", "05/2027", "offen"]],
    )
    kennung = admin.client.get("/api/importe/angebote/vorschau").json()["kennung"]

    antwort = admin.schreiben(
        "POST", "/api/importe/angebote/uebernehmen", json={"kennung": kennung}
    )
    assert antwort.status_code == 200, antwort.text
    assert "1 Angebote neu" in antwort.json()["meldung"]

    with lese_sitzung() as sitzung:
        angebot = sitzung.scalar(select(Angebot).where(Angebot.angebot_nr == "A-2027-050"))
        assert angebot.summe_netto == 80_000_00
        assert angebot.quelle_datei == "angebote.xlsx"
        assert sitzung.scalar(select(AuditEintrag).where(AuditEintrag.aktion == "import.angebote"))


def test_veraltete_kennung_wird_abgewiesen(admin, test_einstellungen, tmp_path) -> None:
    """Zwischen Ansehen und Übernehmen darf sich die Datei nicht unbemerkt geändert haben."""
    test_einstellungen.pfade.angebote = tmp_path / "05_Angebote"
    _angebotsdatei(
        test_einstellungen.pfade.angebote,
        [["A-1", "Kunde", "", "1.000,00", "50 %", "05/2027", "offen"]],
    )
    kennung = admin.client.get("/api/importe/angebote/vorschau").json()["kennung"]
    _angebotsdatei(
        test_einstellungen.pfade.angebote,
        [["A-1", "Kunde", "", "2.000,00", "50 %", "05/2027", "offen"]],
    )

    antwort = admin.schreiben(
        "POST", "/api/importe/angebote/uebernehmen", json={"kennung": kennung}
    )
    assert antwort.status_code == 409
    assert "Traceback" not in antwort.text


def test_team_darf_nicht_importieren(team, test_einstellungen, tmp_path) -> None:
    test_einstellungen.pfade.angebote = tmp_path / "05_Angebote"
    assert team.client.get("/api/importe/angebote/vorschau").status_code == 403
