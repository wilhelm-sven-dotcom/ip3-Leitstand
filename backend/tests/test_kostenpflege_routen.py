"""Kontenzuordnung und Fixkostenplanung pflegen (PLAN §5, §7 Phase 5).

Die Punkte, die hier zählen:

* **Eine geänderte Zuordnung wirkt rückwirkend.** Ohne das zeigte das Cockpit für zwei Monate
  verschiedene Blöcke beim selben Konto, je nachdem wann importiert wurde.
* **Optimistic Locking** (CLAUDE.md Regel 6): Speichern mit veraltetem Stand ergibt 409, kein
  stilles Überschreiben.
* **„Vormonat übernehmen" überschreibt nichts.** Wer einen Wert bewusst angepasst hat, soll ihn
  nicht durch einen Klick verlieren.
* Jede schreibende Aktion steht im ``audit_log`` (CLAUDE.md Regel 7).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.modelle import AuditEintrag, DatevSaldo, FixkostenPlan, KontenMapping
from tests.conftest_auth import anmelden

MONAT = "2026-07"


@pytest.fixture
def salden(gesäte_db) -> None:
    """Zwei Konten aus der SuSa, beide noch ohne Zuordnung."""
    with schreib_sitzung() as sitzung:
        sitzung.add(
            DatevSaldo(monat=MONAT, konto="4120", bezeichnung="Löhne", saldo=4_000_000, block=None)
        )
        sitzung.add(
            DatevSaldo(monat=MONAT, konto="4210", bezeichnung="Miete", saldo=180_000, block=None)
        )


@pytest.fixture
def admin(client, nutzer_erzeugen, salden):
    nutzer_erzeugen("chef@ip3-energie.de", "admin")
    return anmelden(client, "chef@ip3-energie.de")


@pytest.fixture
def buchhaltung(client, nutzer_erzeugen, salden):
    nutzer_erzeugen("buha@ip3-energie.de", "buchhaltung")
    return anmelden(client, "buha@ip3-energie.de")


def block_von(konto: str) -> str | None:
    with lese_sitzung() as sitzung:
        return sitzung.scalar(select(DatevSaldo.block).where(DatevSaldo.konto == konto))


# ---------------------------------------------------------------------------
# Rechte
# ---------------------------------------------------------------------------


def test_nur_die_geschaeftsfuehrung_pflegt_fixkosten(buchhaltung) -> None:
    """PLAN §4 führt Fixkosten unter den Rechten der Geschäftsführung."""
    assert buchhaltung.client.get("/api/kostenpflege/konten").status_code == 403
    assert (
        buchhaltung.schreiben(
            "POST",
            "/api/kostenpflege/konten",
            json={"konto_von": "4100", "konto_bis": "4199", "block": "personal"},
        ).status_code
        == 403
    )
    assert (
        buchhaltung.schreiben(
            "POST",
            "/api/kostenpflege/fixkosten",
            json={"monat": MONAT, "block": "personal", "betrag": 100},
        ).status_code
        == 403
    )


def test_ohne_anmeldung_401(client) -> None:
    assert client.get("/api/kostenpflege/konten").status_code == 401


# ---------------------------------------------------------------------------
# Kontenzuordnung
# ---------------------------------------------------------------------------


def test_anlegen_ordnet_vorhandene_salden_sofort_zu(admin) -> None:
    """Der Kern: eine Zuordnung wirkt rückwirkend auf schon eingelesene Monate."""
    assert block_von("4120") is None

    antwort = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4199", "block": "personal"},
    )
    assert antwort.status_code == 201
    assert block_von("4120") == "personal"
    assert block_von("4210") is None, "der Bereich deckt 4210 nicht ab"


def test_aendern_zieht_die_salden_nach(admin) -> None:
    angelegt = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4299", "block": "personal"},
    ).json()
    assert block_von("4210") == "personal"

    geaendert = admin.schreiben(
        "PUT",
        f"/api/kostenpflege/konten/{angelegt['id']}",
        json={
            "konto_von": "4100",
            "konto_bis": "4199",
            "block": "personal",
            "stand": angelegt["stand"],
        },
    )
    assert geaendert.status_code == 200
    assert block_von("4120") == "personal"
    assert block_von("4210") is None, "4210 fällt aus dem verkleinerten Bereich heraus"


def test_entfernen_setzt_die_salden_zurueck(admin) -> None:
    angelegt = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4199", "block": "personal"},
    ).json()
    assert block_von("4120") == "personal"

    assert (
        admin.schreiben("DELETE", f"/api/kostenpflege/konten/{angelegt['id']}").status_code == 204
    )
    assert block_von("4120") is None


def test_veralteter_stand_ergibt_konflikt(admin) -> None:
    """CLAUDE.md Regel 6: kein stilles Überschreiben."""
    angelegt = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4199", "block": "personal"},
    ).json()
    admin.schreiben(
        "PUT",
        f"/api/kostenpflege/konten/{angelegt['id']}",
        json={
            "konto_von": "4100",
            "konto_bis": "4199",
            "block": "raum",
            "stand": angelegt["stand"],
        },
    )

    zweiter = admin.schreiben(
        "PUT",
        f"/api/kostenpflege/konten/{angelegt['id']}",
        json={
            "konto_von": "4100",
            "konto_bis": "4199",
            "block": "fahrzeuge",
            "stand": angelegt["stand"],
        },
    )
    assert zweiter.status_code == 409
    assert "Traceback" not in zweiter.text


def test_verkehrter_bereich_wird_verstaendlich_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4999", "konto_bis": "4100", "block": "personal"},
    )
    assert antwort.status_code == 400
    assert antwort.json()["code"] == "kontenbereich_verkehrt"


def test_doppelter_bereich_wird_abgewiesen(admin) -> None:
    daten = {"konto_von": "4100", "konto_bis": "4199", "block": "personal"}
    assert admin.schreiben("POST", "/api/kostenpflege/konten", json=daten).status_code == 201

    zweiter = admin.schreiben("POST", "/api/kostenpflege/konten", json=daten)
    assert zweiter.status_code == 400
    assert zweiter.json()["code"] == "kontenbereich_doppelt"
    assert "personal" in zweiter.json()["meldung"]


def test_unbekannter_block_wird_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4199", "block": "kaffeekasse"},
    )
    assert antwort.status_code == 422


def test_buchstaben_im_konto_werden_abgewiesen(admin) -> None:
    antwort = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "viertausend", "konto_bis": "4199", "block": "personal"},
    )
    assert antwort.status_code == 422


# ---------------------------------------------------------------------------
# Fixkostenplanung
# ---------------------------------------------------------------------------


def test_planwert_anlegen_und_aendern(admin) -> None:
    angelegt = admin.schreiben(
        "POST",
        "/api/kostenpflege/fixkosten",
        json={"monat": "2026-12", "block": "personal", "betrag": 4_000_000},
    )
    assert angelegt.status_code == 201
    eintrag = angelegt.json()

    geaendert = admin.schreiben(
        "PUT",
        f"/api/kostenpflege/fixkosten/{eintrag['id']}",
        json={"betrag": 4_200_000, "bemerkung": "Tarifrunde", "stand": eintrag["stand"]},
    )
    assert geaendert.status_code == 200
    assert geaendert.json()["betrag"] == 4_200_000
    assert geaendert.json()["bemerkung"] == "Tarifrunde"


def test_doppelter_planwert_wird_abgewiesen(admin) -> None:
    daten = {"monat": "2026-12", "block": "personal", "betrag": 100}
    assert admin.schreiben("POST", "/api/kostenpflege/fixkosten", json=daten).status_code == 201

    zweiter = admin.schreiben("POST", "/api/kostenpflege/fixkosten", json=daten)
    assert zweiter.status_code == 400
    assert zweiter.json()["code"] == "fixkosten_doppelt"


def test_vormonat_uebernehmen(admin) -> None:
    for block, betrag in (("personal", 4_000_000), ("raum", 180_000), ("fahrzeuge", 300_000)):
        admin.schreiben(
            "POST",
            "/api/kostenpflege/fixkosten",
            json={"monat": "2026-11", "block": block, "betrag": betrag},
        )

    antwort = admin.schreiben("POST", "/api/kostenpflege/fixkosten/2026-12/vormonat-uebernehmen")
    assert antwort.status_code == 200
    assert antwort.json() == {
        "monat": "2026-12",
        "quelle_monat": "2026-11",
        "uebernommen": 3,
        "uebersprungen": 0,
    }

    dezember = admin.client.get("/api/kostenpflege/fixkosten?monat=2026-12").json()
    assert {e["block"]: e["betrag"] for e in dezember} == {
        "personal": 4_000_000,
        "raum": 180_000,
        "fahrzeuge": 300_000,
    }


def test_vormonat_uebernehmen_ueberschreibt_nichts(admin) -> None:
    """Wer einen Wert bewusst angepasst hat, verliert ihn nicht durch einen Klick."""
    admin.schreiben(
        "POST",
        "/api/kostenpflege/fixkosten",
        json={"monat": "2026-11", "block": "personal", "betrag": 4_000_000},
    )
    admin.schreiben(
        "POST",
        "/api/kostenpflege/fixkosten",
        json={"monat": "2026-12", "block": "personal", "betrag": 9_900_000},
    )

    antwort = admin.schreiben(
        "POST", "/api/kostenpflege/fixkosten/2026-12/vormonat-uebernehmen"
    ).json()
    assert antwort["uebernommen"] == 0
    assert antwort["uebersprungen"] == 1

    dezember = admin.client.get("/api/kostenpflege/fixkosten?monat=2026-12").json()
    assert dezember[0]["betrag"] == 9_900_000


def test_jahreswechsel_beim_vormonat(admin) -> None:
    admin.schreiben(
        "POST",
        "/api/kostenpflege/fixkosten",
        json={"monat": "2026-12", "block": "personal", "betrag": 4_000_000},
    )

    antwort = admin.schreiben(
        "POST", "/api/kostenpflege/fixkosten/2027-01/vormonat-uebernehmen"
    ).json()
    assert antwort["quelle_monat"] == "2026-12"
    assert antwort["uebernommen"] == 1


def test_leerer_vormonat_wird_verstaendlich_gemeldet(admin) -> None:
    antwort = admin.schreiben("POST", "/api/kostenpflege/fixkosten/2026-12/vormonat-uebernehmen")
    assert antwort.status_code == 400
    assert antwort.json()["code"] == "vormonat_leer"
    assert "2026-11" in antwort.json()["meldung"]


def test_unsinniger_monat_beim_uebernehmen(admin) -> None:
    antwort = admin.schreiben("POST", "/api/kostenpflege/fixkosten/Dezember/vormonat-uebernehmen")
    assert antwort.status_code == 400
    assert antwort.json()["code"] == "monat_ungueltig"


def test_planwert_entfernen(admin) -> None:
    angelegt = admin.schreiben(
        "POST",
        "/api/kostenpflege/fixkosten",
        json={"monat": "2026-12", "block": "personal", "betrag": 100},
    ).json()

    assert (
        admin.schreiben("DELETE", f"/api/kostenpflege/fixkosten/{angelegt['id']}").status_code
        == 204
    )
    with lese_sitzung() as sitzung:
        assert sitzung.scalars(select(FixkostenPlan)).all() == []


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------


def test_jede_aenderung_steht_im_audit(admin) -> None:
    """CLAUDE.md Regel 7."""
    angelegt = admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4199", "block": "personal"},
    ).json()
    admin.schreiben(
        "PUT",
        f"/api/kostenpflege/konten/{angelegt['id']}",
        json={
            "konto_von": "4100",
            "konto_bis": "4199",
            "block": "raum",
            "stand": angelegt["stand"],
        },
    )
    admin.schreiben("DELETE", f"/api/kostenpflege/konten/{angelegt['id']}")

    with lese_sitzung() as sitzung:
        aktionen = sitzung.scalars(
            select(AuditEintrag.aktion).where(AuditEintrag.tabelle == "konten_mapping")
        ).all()
    assert aktionen == [
        "kontenzuordnung.angelegt",
        "kontenzuordnung.geaendert",
        "kontenzuordnung.entfernt",
    ]


def test_audit_haelt_fest_wie_viele_salden_umgezogen_sind(admin) -> None:
    admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4299", "block": "personal"},
    )

    with lese_sitzung() as sitzung:
        eintrag = sitzung.scalar(
            select(AuditEintrag).where(AuditEintrag.aktion == "kontenzuordnung.angelegt")
        )
        assert eintrag is not None
        assert eintrag.neu["salden_neu_zugeordnet"] == 2


def test_kontenzuordnung_bleibt_nach_dem_anlegen_lesbar(admin) -> None:
    admin.schreiben(
        "POST",
        "/api/kostenpflege/konten",
        json={"konto_von": "4100", "konto_bis": "4199", "block": "personal"},
    )
    liste = admin.client.get("/api/kostenpflege/konten").json()

    assert len(liste) == 1
    assert liste[0]["konto_von"] == "4100"
    assert liste[0]["stand"] is not None
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(KontenMapping.block)) == "personal"
