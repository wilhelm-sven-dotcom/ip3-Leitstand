"""Kapazitätsplanung je Kalenderwoche (PLAN §7 Phase 7).

Die Zahl, auf die es ankommt, ist die Auslastung – und die ist nur so ehrlich wie das, was
darin fehlt. Deshalb prüfen diese Tests vor allem die Ränder: Projekte ohne Termin, Projekte
ohne Sollwert, unlesbare Wochenangaben, Mitarbeiter mit Ein- und Austritt.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import kapazitaet as dienst
from app.modelle import Firma, Kunde, Meilenstein, Mitarbeiter, Projekt, SollKalkulation, Stunden
from app.zeit import woche_lesen, woche_schluessel, wochen_ab, wochenbeginn

MONTAGE = ["montage_uk", "montage_elektro", "zaehlerschrank", "montage"]
STATUS = ["beauftragt", "in_bau"]
# Ein Montag, damit die Fensterrechnung nicht vom Wochentag des Testlaufs abhängt.
START = date(2026, 8, 31)


# ---------------------------------------------------------------------------
# Kalenderwochen lesen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        # Schreibweise der Teamliste.
        ("29/26", (2026, 29)),
        ("29/2026", (2026, 29)),
        ("KW 29/26", (2026, 29)),
        ("kw29/26", (2026, 29)),
        ("2026-W29", (2026, 29)),
        ("2026W29", (2026, 29)),
        ("01/27", (2027, 1)),
        # 2026 hat 53 Wochen (der 1. Januar ist ein Donnerstag), 2025 nicht.
        ("53/26", (2026, 53)),
        ("53/25", None),
        ("54/26", None),
        ("00/26", None),
        ("x", None),
        ("", None),
        (None, None),
    ],
)
def test_kalenderwoche_lesen(roh, erwartet) -> None:
    assert woche_lesen(roh) == erwartet


def test_jahreswechsel_haengt_am_iso_jahr() -> None:
    """Der 1. Januar 2027 liegt in der letzten Woche von 2026 – ISO-Jahr, nicht Kalenderjahr."""
    assert wochenbeginn(2026, 53) == date(2026, 12, 28)
    assert woche_schluessel(2026, 53) == "2026-W53"


def test_fenster_beginnt_in_der_laufenden_woche() -> None:
    # Ein Sonntag gehört noch zur laufenden Woche, nicht zur nächsten.
    assert wochen_ab(date(2026, 8, 30), 3) == [(2026, 35), (2026, 36), (2026, 37)]
    assert wochen_ab(date(2026, 8, 31), 3) == [(2026, 36), (2026, 37), (2026, 38)]


# ---------------------------------------------------------------------------
# Bestand
# ---------------------------------------------------------------------------


def _projekt(
    nr: int,
    *,
    stunden_soll: float | None,
    wochen: list[str],
    status: str = "in_bau",
    erledigt: bool = False,
) -> int:
    """Ein Projekt mit Sollstunden und geplanten Montagewochen."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
        if kunde_id is None:
            kunde = Kunde(kunden_nr=60001, name="Kapazitätskunde", ort="Weiden", typ="b2b")
            sitzung.add(kunde)
            sitzung.flush()
            kunde_id = kunde.id

        projekt = Projekt(
            projekt_nr=nr,
            firma_id=firma_id,
            kunde_id=kunde_id,
            status=status,
            bezeichnung=f"Projekt {nr}",
        )
        sitzung.add(projekt)
        sitzung.flush()

        for i, kw in enumerate(wochen):
            sitzung.add(
                Meilenstein(
                    projekt_id=projekt.id,
                    typ=MONTAGE[i % len(MONTAGE)],
                    geplant_kw=kw,
                    erledigt_am=date(2026, 8, 1) if erledigt else None,
                )
            )
        if stunden_soll is not None:
            sitzung.add(SollKalkulation(projekt_id=projekt.id, stunden_soll=stunden_soll))
        return projekt.id


def _mitarbeiter(name: str, stunden: float, **felder) -> None:
    with schreib_sitzung() as sitzung:
        sitzung.add(Mitarbeiter(name=name, wochenstunden=stunden, **felder))


def _bild(wochen_voraus: int = 4):
    with lese_sitzung() as sitzung:
        return dienst.bild(
            sitzung,
            select(Projekt),
            wochen_voraus=wochen_voraus,
            montage_meilensteine=MONTAGE,
            status_mit_bedarf=STATUS,
            ab=START,
        )


# ---------------------------------------------------------------------------
# Bedarf
# ---------------------------------------------------------------------------


def test_sollstunden_verteilen_sich_auf_die_geplanten_wochen(gesäte_db) -> None:
    """120 Stunden auf zwei Montagewochen sind 60 je Woche – nicht 120 in der ersten."""
    _projekt(26301, stunden_soll=120, wochen=["36/26", "37/26"])

    bild = _bild()
    je_woche = {w.schluessel: w.bedarf for w in bild.wochen}
    assert je_woche["2026-W36"] == Decimal("60.00")
    assert je_woche["2026-W37"] == Decimal("60.00")
    assert je_woche["2026-W38"] == Decimal("0")
    assert bild.bedarf_gesamt == Decimal("120.00")


def test_anteil_nennt_die_zahl_der_wochen(gesäte_db) -> None:
    """Ohne die Zahl bliebe unerklärlich, warum von 120 Stunden nur 40 in der Woche stehen."""
    _projekt(26302, stunden_soll=120, wochen=["36/26", "37/26", "38/26"])

    woche = next(w for w in _bild().wochen if w.schluessel == "2026-W36")
    anteil = woche.projekte[0]
    assert anteil.projekt_nr == 26302
    assert anteil.stunden == Decimal("40.00")
    assert anteil.wochen == 3


def test_erledigte_montage_bindet_nichts_mehr(gesäte_db) -> None:
    _projekt(26303, stunden_soll=80, wochen=["36/26"], erledigt=True)

    bild = _bild()
    assert bild.bedarf_gesamt == Decimal("0")
    # Das Projekt gilt als unverplant – es hat Sollstunden und keine offene Montagewoche.
    assert [o.projekt_nr for o in bild.ohne_termin] == [26303]


def test_wochen_ausserhalb_des_fensters_zaehlen_nicht(gesäte_db) -> None:
    """Eine Montage in acht Monaten sagt nichts über die Auslastung der nächsten Wochen."""
    _projekt(26304, stunden_soll=200, wochen=["20/27"])

    bild = _bild()
    assert bild.bedarf_gesamt == Decimal("0")
    # Und sie gilt nicht als unverplant: der Termin steht, er liegt nur weiter weg.
    assert bild.ohne_termin == []


def test_status_ohne_bedarf_bindet_keine_mannschaft(gesäte_db) -> None:
    _projekt(26305, stunden_soll=100, wochen=["36/26"], status="angebot")
    _projekt(26306, stunden_soll=100, wochen=["36/26"], status="abgeschlossen")

    assert _bild().bedarf_gesamt == Decimal("0")


# ---------------------------------------------------------------------------
# Kapazität
# ---------------------------------------------------------------------------


def test_kapazitaet_summiert_die_aktive_mannschaft(gesäte_db) -> None:
    _mitarbeiter("Bäumler, Michael", 38.5, satzgruppe="obermonteur")
    _mitarbeiter("Wilhelm, Sven", 40, satzgruppe="planung")
    _mitarbeiter("Ausgeschieden, Anna", 38.5, aktiv=False)

    bild = _bild()
    assert all(w.kapazitaet == Decimal("78.50") for w in bild.wochen)
    assert bild.kapazitaet_gesamt == Decimal("314.00")


def test_eintritt_und_austritt_begrenzen_die_kapazitaet(gesäte_db) -> None:
    """Wer im Oktober anfängt, zählt im September nicht."""
    _mitarbeiter("Dauerhaft, Detlef", 40)
    _mitarbeiter("Neu, Nina", 20, von=date(2026, 9, 21))
    _mitarbeiter("Geht, Gerd", 10, bis=date(2026, 9, 6))

    je_woche = {w.schluessel: w.kapazitaet for w in _bild().wochen}
    # KW 36 beginnt am 31.08.: Gerd ist noch da, Nina noch nicht.
    assert je_woche["2026-W36"] == Decimal("50.00")
    # KW 37 ab 07.09.: Gerd ist weg.
    assert je_woche["2026-W37"] == Decimal("40.00")
    # KW 39 ab 21.09.: Nina ist da.
    assert _bild(5).wochen[-1].schluessel == "2026-W40"
    je_woche5 = {w.schluessel: w.kapazitaet for w in _bild(5).wochen}
    assert je_woche5["2026-W39"] == Decimal("60.00")


def test_auslastung_und_rest(gesäte_db) -> None:
    _mitarbeiter("Monteur, Max", 40)
    _projekt(26307, stunden_soll=30, wochen=["36/26"])

    woche = next(w for w in _bild().wochen if w.schluessel == "2026-W36")
    assert woche.auslastung_promille == 750
    assert woche.rest == Decimal("10.00")


def test_ueberbuchung_hat_ein_vorzeichen(gesäte_db) -> None:
    _mitarbeiter("Monteur, Max", 40)
    _projekt(26308, stunden_soll=100, wochen=["36/26"])

    woche = next(w for w in _bild().wochen if w.schluessel == "2026-W36")
    assert woche.auslastung_promille == 2500
    assert woche.rest == Decimal("-60.00")


def test_ohne_mannschaft_gibt_es_keine_auslastung(gesäte_db) -> None:
    """Bedarf durch null ist keine Zahl, sondern eine fehlende Angabe."""
    _projekt(26309, stunden_soll=40, wochen=["36/26"])

    woche = next(w for w in _bild().wochen if w.schluessel == "2026-W36")
    assert woche.auslastung_promille is None


# ---------------------------------------------------------------------------
# Hinweise
# ---------------------------------------------------------------------------


def test_projekt_ohne_montagewoche_wird_genannt(gesäte_db) -> None:
    """Unverplante Arbeit ist der Grund, warum eine Woche später überraschend voll ist."""
    _mitarbeiter("Monteur, Max", 40)
    _projekt(26310, stunden_soll=90, wochen=[])

    bild = _bild()
    assert [o.projekt_nr for o in bild.ohne_termin] == [26310]
    assert bild.stunden_ohne_termin == Decimal("90.00")
    assert any("keine geplante Montagewoche" in h for h in bild.hinweise)
    assert any("zu günstig" in h for h in bild.hinweise)


def test_projekt_ohne_sollwert_wird_genannt(gesäte_db) -> None:
    _mitarbeiter("Monteur, Max", 40)
    _projekt(26311, stunden_soll=None, wochen=["36/26"])

    bild = _bild()
    assert bild.ohne_sollwert == [26311]
    assert any("Kalkulationsblatt" in h for h in bild.hinweise)


def test_unlesbare_wochenangabe_wird_genannt_statt_verschluckt(gesäte_db) -> None:
    _mitarbeiter("Monteur, Max", 40)
    _projekt(26312, stunden_soll=40, wochen=["nach Absprache"])

    bild = _bild()
    assert any("nach Absprache" in eintrag for eintrag in bild.unlesbare_wochen)
    assert any("KW/JJ" in h for h in bild.hinweise)


def test_fehlende_mannschaft_ist_der_erste_hinweis(gesäte_db) -> None:
    _projekt(26313, stunden_soll=40, wochen=["36/26"])

    hinweise = _bild().hinweise
    assert "keine Mitarbeiter" in hinweise[0]
    assert "Nächster Schritt" in hinweise[0]


def test_timetac_namen_ohne_mitarbeiter_fallen_auf(gesäte_db) -> None:
    """Ein Tippfehler im Namen ist sonst unsichtbar – die Stunden zählen einfach nirgends."""
    _mitarbeiter("Bäumler, Michael", 38.5)
    projekt_id = _projekt(26314, stunden_soll=40, wochen=["36/26"])
    with schreib_sitzung() as sitzung:
        # Groß-/Kleinschreibung und aufgelöste Umlaute sind derselbe Mensch, „Fremd" nicht.
        for name in ("Bäumler, Michael", "BAEUMLER, MICHAEL", "Fremd, Franz"):
            sitzung.add(
                Stunden(
                    projekt_id=projekt_id,
                    monat="2026-08",
                    mitarbeiter=name,
                    stunden=8,
                    satz=6500,
                )
            )

    with lese_sitzung() as sitzung:
        # Schreibweise und Umlaute egal, alles andere nicht.
        assert dienst.namen_ohne_mitarbeiter(sitzung) == ["Fremd, Franz"]
    assert any("Fremd, Franz" in h for h in _bild().hinweise)
