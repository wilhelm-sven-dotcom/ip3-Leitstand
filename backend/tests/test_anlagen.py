"""Anlagenregister-Automatik und Gewährleistung (PLAN §6.9, §7 Phase 6).

Der Wechsel eines Projekts auf ``abgeschlossen`` ist der Moment, in dem aus einem Bauvorhaben
eine Anlage wird: ein Bestandsobjekt mit Wartungsbedarf und einer Gewährleistung, die Jahre
später fällig wird. Diese Tests halten drei Zusagen fest:

* **Die Dauer hängt an der Vertragsart, nicht an der Laune des Erfassers.** VOB vier Jahre,
  BGB fünf, vorbelegt nach Kundentyp und beim Abschluss änderbar (Entscheidung 32).
* **Gerechnet wird ab Abnahme.** Fehlt das Datum, entsteht die Anlage ohne Frist und mit einem
  Hinweis – ein erfundenes Datum wäre schlimmer als eine fehlende Überwachung.
* **Ein zweiter Abschluss legt keine zweite Anlage an.** Der Status lässt sich beliebig oft
  setzen; die Anlage gibt es einmal.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import delete, select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import anlagen as dienst
from app.modelle import Anlage, AuditEintrag, Firma, Frist, Kunde, Meilenstein, Projekt
from tests.conftest_auth import anmelden

VORBELEGUNG = {"b2b": "vob", "b2c": "bgb"}


# ---------------------------------------------------------------------------
# Rechnen ohne Datenbank
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kundentyp", "erwartet"),
    [
        ("b2b", "vob"),
        ("b2c", "bgb"),
        # Unbekannter oder fehlender Kundentyp: BGB ist die längere Frist und damit die
        # vorsichtige Annahme – zu lange zu überwachen kostet nichts.
        ("gewerbe", "bgb"),
        (None, "bgb"),
    ],
)
def test_vertragsart_wird_nach_kundentyp_vorbelegt(kundentyp, erwartet) -> None:
    assert dienst.vertragsart_vorbelegen(kundentyp, VORBELEGUNG) == erwartet


def test_unsinnige_vorbelegung_faellt_auf_bgb_zurueck() -> None:
    """Selbst wenn jemand die config.toml verbogen hat, entsteht keine erfundene Dauer."""
    assert dienst.vertragsart_vorbelegen("b2b", {"b2b": "handschlag"}) == "bgb"


def test_vob_vier_jahre_bgb_fuenf() -> None:
    abnahme = date(2026, 7, 15)
    assert dienst.gewaehrleistung_ende(abnahme, "vob") == date(2030, 7, 15)
    assert dienst.gewaehrleistung_ende(abnahme, "bgb") == date(2031, 7, 15)


def test_ohne_abnahme_kein_ende() -> None:
    assert dienst.gewaehrleistung_ende(None, "bgb") is None


def test_schalttag_wird_auf_den_ersten_maerz_gelegt() -> None:
    """2028 ist ein Schaltjahr, 2032 auch – 2032 hat den 29. Februar, 2031 nicht.

    Einen Tag zu spät zu erinnern ist der billigere Fehler: am 1. März ist die Frist sicher
    abgelaufen, am 28. Februar wäre sie es vielleicht noch nicht.
    """
    assert dienst.gewaehrleistung_ende(date(2028, 2, 29), "vob") == date(2032, 2, 29)
    assert dienst.gewaehrleistung_ende(date(2028, 2, 29), "bgb") == date(2033, 3, 1)


# ---------------------------------------------------------------------------
# Abschluss über die Route
# ---------------------------------------------------------------------------


def _projekt_anlegen(kundentyp: str = "b2b", *, abnahme: date | None = date(2026, 7, 15)) -> int:
    """Ein Projekt in Bau, wahlweise mit erledigtem Abnahme-Meilenstein."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=30001, name="Solarhof GmbH", ort="Weiden", typ=kundentyp)
        sitzung.add(kunde)
        sitzung.flush()
        projekt = Projekt(
            projekt_nr=26100,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            standort="Theisseil, Am Hang 4",
            pv_kwp=29.7,
            speicher_kwh=20.0,
        )
        sitzung.add(projekt)
        sitzung.flush()
        if abnahme is not None:
            sitzung.add(
                Meilenstein(
                    projekt_id=projekt.id, typ="abnahme", erledigt_am=abnahme, geplant_kw="2026-29"
                )
            )
        sitzung.add(
            Meilenstein(projekt_id=projekt.id, typ="inbetriebnahme", erledigt_am=date(2026, 7, 10))
        )
        return projekt.projekt_nr


@pytest.fixture
def admin(client, nutzer_erzeugen):
    nutzer_erzeugen("chef@ip3-energie.de", "admin")
    return anmelden(client, "chef@ip3-energie.de")


def _abschliessen(admin, projekt_nr: int, **zusatz) -> dict:
    """Projekt über die normale Änderungsmaske auf 'abgeschlossen' setzen."""
    stand = admin.client.get(f"/api/projekte/{projekt_nr}").json()
    koerper = {
        "kunde_id": stand["kunde_id"],
        "bezeichnung": stand["bezeichnung"],
        "typ": stand["typ"],
        "standort": stand["standort"],
        "pv_kwp": stand["pv_kwp"],
        "speicher_kwh": stand["speicher_kwh"],
        "ust_kz": stand["ust_kz"],
        "status": "abgeschlossen",
        "stand": stand["stand"],
        **zusatz,
    }
    antwort = admin.schreiben("PUT", f"/api/projekte/{projekt_nr}", json=koerper)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_abschluss_legt_anlage_und_frist_an(admin) -> None:
    nr = _projekt_anlegen("b2b")
    daten = _abschliessen(admin, nr)
    assert daten["status"] == "abgeschlossen"
    assert daten["hinweise"] == []

    with lese_sitzung() as sitzung:
        anlage = sitzung.scalar(select(Anlage))
        assert anlage is not None
        assert anlage.standort == "Theisseil, Am Hang 4"
        assert float(anlage.pv_kwp) == 29.7
        assert anlage.abnahme_datum == date(2026, 7, 15)
        # b2b ist mit VOB vorbelegt: vier Jahre.
        assert anlage.gewaehrleistung_ende == date(2030, 7, 15)
        assert anlage.wartungsvertrag is False

        frist = sitzung.scalar(select(Frist).where(Frist.typ == "gewaehrleistung"))
        assert frist is not None
        assert frist.bezug == "anlage"
        assert frist.bezug_id == anlage.id
        assert frist.faellig_am == date(2030, 7, 15)
        assert frist.vorlauf_tage == 90
        assert "VOB" in frist.bezeichnung
        assert frist.erledigt_am is None


def test_privatkunde_bekommt_fuenf_jahre(admin) -> None:
    nr = _projekt_anlegen("b2c")
    _abschliessen(admin, nr)
    with lese_sitzung() as sitzung:
        anlage = sitzung.scalar(select(Anlage))
        assert anlage.gewaehrleistung_ende == date(2031, 7, 15)
        frist = sitzung.scalar(select(Frist))
        assert "BGB" in frist.bezeichnung


def test_vertragsart_aus_der_anfrage_schlaegt_die_vorbelegung(admin) -> None:
    """Die Vorbelegung ist ein Vorschlag – am Bau wird auch mit Privatkunden nach VOB gebaut."""
    nr = _projekt_anlegen("b2c")
    _abschliessen(admin, nr, vertragsart="vob")
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Anlage)).gewaehrleistung_ende == date(2030, 7, 15)


def test_nachgereichte_vertragsart_rechnet_die_frist_neu(admin) -> None:
    """Wer sich beim Abschluss vergriffen hat, berichtigt es an derselben Stelle."""
    nr = _projekt_anlegen("b2c")
    _abschliessen(admin, nr)
    _abschliessen(admin, nr, vertragsart="vob")

    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Anlage)).gewaehrleistung_ende == date(2030, 7, 15)
        fristen = list(sitzung.scalars(select(Frist)))
        # Eine Frist, nicht zwei: die vorhandene wandert mit.
        assert len(fristen) == 1
        assert fristen[0].faellig_am == date(2030, 7, 15)


def test_zweiter_abschluss_legt_keine_zweite_anlage_an(admin) -> None:
    nr = _projekt_anlegen("b2b")
    _abschliessen(admin, nr)
    # Zurück in den Bau und wieder abschließen – der Alltag, wenn ein Mangel nachgearbeitet wird.
    stand = admin.client.get(f"/api/projekte/{nr}").json()
    admin.schreiben(
        "PUT",
        f"/api/projekte/{nr}",
        json={"kunde_id": stand["kunde_id"], "status": "in_bau", "stand": stand["stand"]},
    )
    _abschliessen(admin, nr)

    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Anlage).where(Anlage.projekt_id_ursprung.is_not(None)))
        assert len(list(sitzung.scalars(select(Anlage)))) == 1
        assert len(list(sitzung.scalars(select(Frist)))) == 1


def test_ohne_abnahmedatum_entsteht_die_anlage_mit_hinweis(admin) -> None:
    """Kein Datum, keine Frist – aber die Anlage gibt es, und der Hinweis sagt, was fehlt."""
    nr = _projekt_anlegen("b2b", abnahme=None)
    daten = _abschliessen(admin, nr)

    assert any("Abnahmedatum" in h for h in daten["hinweise"])
    assert any("Nächster Schritt" in h for h in daten["hinweise"])

    with lese_sitzung() as sitzung:
        anlage = sitzung.scalar(select(Anlage))
        assert anlage is not None
        assert anlage.gewaehrleistung_ende is None
        assert sitzung.scalar(select(Frist)) is None


def test_nachgetragene_abnahme_setzt_die_frist_nach(admin) -> None:
    nr = _projekt_anlegen("b2b", abnahme=None)
    _abschliessen(admin, nr)

    with schreib_sitzung() as sitzung:
        projekt_id = sitzung.scalar(select(Projekt.id).where(Projekt.projekt_nr == nr))
        sitzung.add(Meilenstein(projekt_id=projekt_id, typ="abnahme", erledigt_am=date(2026, 8, 3)))

    daten = _abschliessen(admin, nr, vertragsart="vob")
    assert daten["hinweise"] == []
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Anlage)).gewaehrleistung_ende == date(2030, 8, 3)
        assert sitzung.scalar(select(Frist)).faellig_am == date(2030, 8, 3)


def test_andere_statuswechsel_legen_keine_anlage_an(admin) -> None:
    nr = _projekt_anlegen("b2b")
    stand = admin.client.get(f"/api/projekte/{nr}").json()
    antwort = admin.schreiben(
        "PUT",
        f"/api/projekte/{nr}",
        json={"kunde_id": stand["kunde_id"], "status": "storniert", "stand": stand["stand"]},
    )
    assert antwort.status_code == 200, antwort.text
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Anlage)) is None


def test_fehlende_inbetriebnahme_wird_benannt(admin) -> None:
    """Ohne Inbetriebnahmedatum lässt sich die MaStR-Frist nicht überwachen (§ 5 MaStRV)."""
    nr = _projekt_anlegen("b2b")
    with schreib_sitzung() as sitzung:
        projekt_id = sitzung.scalar(select(Projekt.id).where(Projekt.projekt_nr == nr))
        sitzung.execute(
            delete(Meilenstein).where(
                Meilenstein.projekt_id == projekt_id, Meilenstein.typ == "inbetriebnahme"
            )
        )

    daten = _abschliessen(admin, nr)
    assert any("MaStR" in h for h in daten["hinweise"])
    # Die Gewährleistung hängt trotzdem: sie zählt ab Abnahme, nicht ab Inbetriebnahme.
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Anlage)).gewaehrleistung_ende == date(2030, 7, 15)


def test_abschluss_steht_im_audit(admin) -> None:
    nr = _projekt_anlegen("b2b")
    _abschliessen(admin, nr)
    with lese_sitzung() as sitzung:
        eintrag = sitzung.scalar(
            select(AuditEintrag).where(AuditEintrag.aktion == "anlage.angelegt")
        )
        assert eintrag is not None
        assert eintrag.tabelle == "anlagen"
        assert eintrag.neu["vertragsart"] == "vob"


def test_unbekannte_vertragsart_wird_abgewiesen(admin) -> None:
    """Kein stiller Standard: 'handschlag' ist keine Vertragsart, das sagt die API auch."""
    nr = _projekt_anlegen("b2b")
    stand = admin.client.get(f"/api/projekte/{nr}").json()
    antwort = admin.schreiben(
        "PUT",
        f"/api/projekte/{nr}",
        json={
            "kunde_id": stand["kunde_id"],
            "status": "abgeschlossen",
            "stand": stand["stand"],
            "vertragsart": "handschlag",
        },
    )
    assert antwort.status_code == 422


# ---------------------------------------------------------------------------
# Liste ohne Wartungsvertrag
# ---------------------------------------------------------------------------


def test_anlagen_ohne_wartungsvertrag_juengste_zuerst(admin) -> None:
    nr = _projekt_anlegen("b2b")
    _abschliessen(admin, nr)
    with schreib_sitzung() as sitzung:
        kunde_id = sitzung.scalar(select(Kunde.id).limit(1))
        sitzung.add(
            Anlage(kunde_id=kunde_id, standort="Altbestand", inbetriebnahme=date(2020, 5, 1))
        )
        sitzung.add(
            Anlage(
                kunde_id=kunde_id,
                standort="Mit Vertrag",
                inbetriebnahme=date(2027, 1, 1),
                wartungsvertrag=True,
            )
        )

    with lese_sitzung() as sitzung:
        offen = dienst.ohne_wartungsvertrag(sitzung)
        assert [a.standort for a in offen] == ["Theisseil, Am Hang 4", "Altbestand"]
