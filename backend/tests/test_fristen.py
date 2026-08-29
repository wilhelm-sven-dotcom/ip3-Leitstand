"""Fristenwächter und nächtlicher Lauf (PLAN §6.9, §7 Phase 6).

Der Fristenwächter ist der einzige Teil des Leitstands, der sich von selbst meldet. Was er
meldet, muss deshalb stimmen – und vor allem darf er nichts wieder aufmachen, was jemand
geschlossen hat.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import fristen as dienst
from app.jobs.fristen import fristen_job
from app.modelle import Anlage, Firma, Frist, JobLauf, Kunde, Projekt

HEUTE = date(2026, 8, 29)


# ---------------------------------------------------------------------------
# Zustand einer Frist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("faellig", "vorlauf", "erwartet"),
    [
        # Gestern fällig: überfällig, egal wie groß der Vorlauf war.
        (date(2026, 8, 28), 90, dienst.STATUS_UEBERFAELLIG),
        # Heute fällig ist noch nicht überfällig – der Tag gehört der Frist.
        (date(2026, 8, 29), 90, dienst.STATUS_FAELLIG),
        (date(2026, 11, 27), 90, dienst.STATUS_FAELLIG),
        # Einen Tag außerhalb des Vorlaufs: noch nicht dran.
        (date(2026, 11, 28), 90, dienst.STATUS_OFFEN),
        # Ohne Vorlauf meldet sich die Frist erst am Tag selbst.
        (date(2026, 8, 30), 0, dienst.STATUS_OFFEN),
        (date(2026, 8, 29), 0, dienst.STATUS_FAELLIG),
    ],
)
def test_status_haengt_am_eigenen_vorlauf(faellig, vorlauf, erwartet) -> None:
    assert dienst.status_fuer(faellig, vorlauf, HEUTE) == erwartet


# ---------------------------------------------------------------------------
# Liste mit aufgelöstem Bezug
# ---------------------------------------------------------------------------


@pytest.fixture
def bestand(gesäte_db) -> dict[str, int]:
    """Eine Anlage mit Gewährleistung, ein Projekt mit Reservierung, eine erledigte Frist."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=40001, name="Hofgut Sonnenberg", ort="Vohenstrauß", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()

        projekt = Projekt(
            projekt_nr=26200,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            bezeichnung="Freifläche Süd",
        )
        anlage = Anlage(
            kunde_id=kunde.id,
            standort="Vohenstrauß, Hofgut 1",
            inbetriebnahme=date(2026, 8, 20),
        )
        sitzung.add_all([projekt, anlage])
        sitzung.flush()

        sitzung.add_all(
            [
                # Überfällig.
                Frist(
                    bezug="anlage",
                    bezug_id=anlage.id,
                    typ="gewaehrleistung",
                    bezeichnung="Gewährleistung endet",
                    faellig_am=date(2026, 8, 1),
                    vorlauf_tage=90,
                ),
                # Im Vorlauf.
                Frist(
                    bezug="projekt",
                    bezug_id=projekt.id,
                    typ="reservierung",
                    bezeichnung="Netzanschluss-Reservierung läuft ab",
                    faellig_am=date(2026, 9, 15),
                    vorlauf_tage=30,
                ),
                # Weit weg.
                Frist(
                    bezug="projekt",
                    bezug_id=projekt.id,
                    typ="fertigmeldung",
                    bezeichnung="Fertigmeldung beim Netzbetreiber",
                    faellig_am=date(2027, 6, 1),
                    vorlauf_tage=30,
                ),
                # Abgehakt: taucht nicht mehr auf.
                Frist(
                    bezug="anlage",
                    bezug_id=anlage.id,
                    typ="sonstig",
                    bezeichnung="Übergabeprotokoll nachreichen",
                    faellig_am=date(2026, 7, 1),
                    vorlauf_tage=14,
                    erledigt_am=date(2026, 6, 28),
                ),
            ]
        )
        return {"anlage": anlage.id, "projekt": projekt.id}


def test_liste_loest_den_bezug_auf(bestand) -> None:
    with lese_sitzung() as sitzung:
        zeilen = dienst.liste(sitzung, stichtag=HEUTE)

    # Das Dringendste zuerst: überfällig, dann fällig, dann offen.
    assert [z.status for z in zeilen] == [
        dienst.STATUS_UEBERFAELLIG,
        dienst.STATUS_FAELLIG,
        dienst.STATUS_OFFEN,
    ]
    erste, zweite, *_ = zeilen
    assert erste.betreff == "Vohenstrauß, Hofgut 1"
    assert erste.kunde == "Hofgut Sonnenberg"
    assert erste.tage_bis == -28
    assert zweite.betreff == "26200 – Freifläche Süd"
    assert zweite.tage_bis == 17


def test_erledigte_fristen_bleiben_draussen(bestand) -> None:
    with lese_sitzung() as sitzung:
        offen = dienst.liste(sitzung, stichtag=HEUTE)
        alle = dienst.liste(sitzung, stichtag=HEUTE, mit_erledigten=True)
    assert len(offen) == 3
    assert len(alle) == 4
    assert any(z.erledigt_am == date(2026, 6, 28) for z in alle)


def test_nur_anstehende_fuer_das_widget(bestand) -> None:
    with lese_sitzung() as sitzung:
        zeilen = dienst.liste(sitzung, stichtag=HEUTE, nur_anstehende=True)
    assert [z.typ for z in zeilen] == ["gewaehrleistung", "reservierung"]
    assert dienst.zaehlung(zeilen) == {"ueberfaellig": 1, "faellig": 1, "offen": 0}


def test_grenze_kuerzt_nach_dringlichkeit(bestand) -> None:
    with lese_sitzung() as sitzung:
        zeilen = dienst.liste(sitzung, stichtag=HEUTE, grenze=1)
    assert len(zeilen) == 1
    assert zeilen[0].status == dienst.STATUS_UEBERFAELLIG


def test_frist_ohne_auffindbaren_bezug_verschwindet_nicht(gesäte_db) -> None:
    """Lieber eine karge Zeile als eine Frist, die niemand mehr sieht."""
    with schreib_sitzung() as sitzung:
        sitzung.add(
            Frist(
                bezug="anlage",
                bezug_id=9999,
                typ="sonstig",
                bezeichnung="Verwaiste Frist",
                faellig_am=date(2026, 9, 1),
                vorlauf_tage=30,
            )
        )
    with lese_sitzung() as sitzung:
        zeilen = dienst.liste(sitzung, stichtag=HEUTE)
    assert len(zeilen) == 1
    assert zeilen[0].betreff == "anlage 9999"
    assert zeilen[0].kunde is None


# ---------------------------------------------------------------------------
# MaStR-Automatik
# ---------------------------------------------------------------------------


def _anlage_anlegen(**felder) -> int:
    with schreib_sitzung() as sitzung:
        kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
        if kunde_id is None:
            kunde = Kunde(kunden_nr=40002, name="Testkunde", ort="Weiden", typ="b2c")
            sitzung.add(kunde)
            sitzung.flush()
            kunde_id = kunde.id
        anlage = Anlage(kunde_id=kunde_id, standort="Prüfstelle", **felder)
        sitzung.add(anlage)
        sitzung.flush()
        return anlage.id


def test_mastr_frist_entsteht_aus_der_inbetriebnahme(gesäte_db) -> None:
    """§ 5 Abs. 1 MaStRV: Registrierung binnen eines Monats nach Inbetriebnahme."""
    _anlage_anlegen(inbetriebnahme=date(2026, 8, 20))
    with schreib_sitzung() as sitzung:
        ergebnis = dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
    assert ergebnis.gesetzt == 1

    with lese_sitzung() as sitzung:
        frist = sitzung.scalar(select(Frist).where(Frist.typ == "mastr"))
        assert frist.faellig_am == date(2026, 9, 19)
        # Kurze Frist, kurzer Vorlauf – sonst steht sie vom ersten Tag an im Widget.
        assert frist.vorlauf_tage == 15
        assert "Marktstammdatenregister" in frist.bezeichnung


def test_ohne_inbetriebnahme_keine_mastr_frist(gesäte_db) -> None:
    _anlage_anlegen(inbetriebnahme=None)
    with schreib_sitzung() as sitzung:
        assert dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE).gesetzt == 0
    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(Frist)) is None


def test_vorhandene_mastr_nummer_erzeugt_keine_frist(gesäte_db) -> None:
    _anlage_anlegen(inbetriebnahme=date(2026, 8, 20), mastr_nr="SEE900000012345")
    with schreib_sitzung() as sitzung:
        assert dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE).gesetzt == 0


def test_leerer_string_gilt_nicht_als_registrierung(gesäte_db) -> None:
    """Ein leeres Feld ist keine Nummer – sonst reichte ein Leerzeichen als Erledigung."""
    _anlage_anlegen(inbetriebnahme=date(2026, 8, 20), mastr_nr="")
    with schreib_sitzung() as sitzung:
        assert dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE).gesetzt == 1


def test_nachgetragene_nummer_hakt_die_frist_ab(gesäte_db) -> None:
    anlage_id = _anlage_anlegen(inbetriebnahme=date(2026, 8, 20))
    with schreib_sitzung() as sitzung:
        dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
    with schreib_sitzung() as sitzung:
        sitzung.get(Anlage, anlage_id).mastr_nr = "SEE900000012345"

    with schreib_sitzung() as sitzung:
        ergebnis = dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
    assert ergebnis.erledigt == 1

    with lese_sitzung() as sitzung:
        frist = sitzung.scalar(select(Frist).where(Frist.typ == "mastr"))
        # Erfüllt, nicht verfallen: die Frist bleibt als Beleg stehen.
        assert frist.erledigt_am == HEUTE
        assert dienst.liste(sitzung, stichtag=HEUTE) == []


def test_lauf_ist_wiederholbar(gesäte_db) -> None:
    """Zweimal derselbe Lauf ergibt denselben Stand – keine zweite Frist."""
    _anlage_anlegen(inbetriebnahme=date(2026, 8, 20))
    with schreib_sitzung() as sitzung:
        dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
        dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
    with lese_sitzung() as sitzung:
        assert len(list(sitzung.scalars(select(Frist)))) == 1


def test_von_hand_erledigte_frist_wird_nicht_wieder_aufgemacht(gesäte_db) -> None:
    """Wer eine Frist abhakt, hat es getan – der Lauf legt keine zweite an."""
    _anlage_anlegen(inbetriebnahme=date(2026, 8, 20))
    with schreib_sitzung() as sitzung:
        dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
    with schreib_sitzung() as sitzung:
        sitzung.scalar(select(Frist)).erledigt_am = date(2026, 8, 25)

    with schreib_sitzung() as sitzung:
        # Ohne Nummer entsteht wieder eine offene Frist – das ist gewollt: die Registrierung
        # fehlt ja weiterhin. Die erledigte bleibt aber unangetastet daneben stehen.
        dienst.mastr_pflegen(sitzung, tage=30, stichtag=HEUTE)
    with lese_sitzung() as sitzung:
        fristen = sorted(sitzung.scalars(select(Frist)), key=lambda f: f.id)
        assert [f.erledigt_am for f in fristen] == [date(2026, 8, 25), None]


# ---------------------------------------------------------------------------
# Nächtlicher Lauf
# ---------------------------------------------------------------------------


def test_job_meldet_ueberfaellige_als_warnung(bestand, test_einstellungen) -> None:
    fristen_job("manuell", test_einstellungen)
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "fristen"))
        assert lauf.status == "warnung"
        # Numerus richtig: „1 Frist ist überfällig", nicht „1 Fristen sind überfällig".
        assert lauf.meldung.startswith("1 Frist ist überfällig.")
        assert "Nächster Schritt" in lauf.meldung
        # Die MaStR-Frist der Anlage ist im selben Lauf entstanden.
        assert lauf.kennzahlen["mastr_gesetzt"] == 1


def test_job_zaehlt_anstehende_im_plural(gesäte_db, test_einstellungen) -> None:
    """Zwei anstehende, keine überfällige: der Lauf bleibt grün und sagt die Zahl."""
    with schreib_sitzung() as sitzung:
        kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
        if kunde_id is None:
            kunde = Kunde(kunden_nr=40003, name="Zählkunde", ort="Weiden", typ="b2b")
            sitzung.add(kunde)
            sitzung.flush()
            kunde_id = kunde.id
        anlage = Anlage(kunde_id=kunde_id, standort="Zählstelle")
        sitzung.add(anlage)
        sitzung.flush()
        for tage in (2, 5):
            sitzung.add(
                Frist(
                    bezug="anlage",
                    bezug_id=anlage.id,
                    typ="sonstig",
                    bezeichnung=f"Nachweis in {tage} Tagen",
                    faellig_am=date.today() + timedelta(days=tage),
                    vorlauf_tage=30,
                )
            )

    fristen_job("manuell", test_einstellungen)
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "fristen"))
        assert lauf.status == "erfolg"
        assert lauf.meldung == "2 Fristen stehen an, keine überfällig."


def test_job_ohne_fristen_meldet_das_ruhig(gesäte_db, test_einstellungen) -> None:
    fristen_job("manuell", test_einstellungen)
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "fristen"))
        assert lauf.status == "erfolg"
        assert lauf.meldung == "Keine Frist steht an."


def test_job_verschickt_nichts(gesäte_db, test_einstellungen, monkeypatch) -> None:
    """Entscheidung 34: kein Mailversand (PLAN §12). Der Lauf öffnet keine Verbindung."""
    import smtplib

    def keine_verbindung(*args, **kwargs):  # pragma: no cover – darf nie gerufen werden
        raise AssertionError("Der Fristenwächter darf keine Mail verschicken.")

    monkeypatch.setattr(smtplib, "SMTP", keine_verbindung)
    monkeypatch.setattr(smtplib, "SMTP_SSL", keine_verbindung)
    _anlage_anlegen(inbetriebnahme=date(2026, 8, 20))
    fristen_job("manuell", test_einstellungen)


def test_job_faellt_nicht_ueber_eine_verwaiste_frist(gesäte_db, test_einstellungen) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(
            Frist(
                bezug="projekt",
                bezug_id=9999,
                typ="sonstig",
                bezeichnung="Verwaist",
                faellig_am=date.today() - timedelta(days=3),
                vorlauf_tage=30,
            )
        )
    fristen_job("manuell", test_einstellungen)
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(JobLauf).where(JobLauf.job == "fristen"))
        assert lauf.status == "warnung"
        assert "projekt 9999" in lauf.meldung
