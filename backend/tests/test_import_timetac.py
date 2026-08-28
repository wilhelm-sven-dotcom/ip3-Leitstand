"""TimeTac: Verrechnungssätze, Projektzuordnung und Übernahme (PLAN §6.6, §8).

Die drei Punkte, an denen die Marge kippen würde, wenn hier etwas falsch ist:

* Der Satz wird beim Import eingefroren. Ändert Sven ihn später, dürfen abgeschlossene Monate
  sich nicht bewegen.
* ``ist_kosten`` ist die einzige Summenquelle. ``stunden`` ist Detail – wer beides addiert,
  zählt die Eigenleistung doppelt.
* Zugeordnet wird nur, was eindeutig ist. Geratene Stunden auf einem fremden Projekt fallen
  niemandem auf.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.importe.timetac import (
    REFERENZ,
    Stundenlieferung,
    Zeitbuchung,
    projekte_zuordnen,
    projektnummer_aus_text,
    uebernehmen,
)
from app.konfiguration import StundensaetzeEinstellungen
from app.modelle import Firma, Importlauf, IstKosten, Kunde, Projekt, Stunden

SAETZE = StundensaetzeEinstellungen(
    mitarbeiter={"Wilhelm, Sven": "planung", "Bäumler, Michael": "obermonteur"}
)


def buchung(
    projekt_text: str,
    mitarbeiter: str,
    tag: str,
    stunden: str,
    zeile: int = 2,
) -> Zeitbuchung:
    return Zeitbuchung(
        herkunft="test.csv",
        zeile=zeile,
        projekt_text=projekt_text,
        mitarbeiter=mitarbeiter,
        datum=date.fromisoformat(tag),
        stunden=Decimal(stunden),
    )


def lieferung(*buchungen: Zeitbuchung, monate: list[str] | None = None) -> Stundenlieferung:
    return Stundenlieferung(
        herkunft="test.csv",
        monate=monate or ["2026-07"],
        buchungen=list(buchungen),
    )


# ---------------------------------------------------------------------------
# Sätze
# ---------------------------------------------------------------------------


def test_satz_nach_zuordnung() -> None:
    assert SAETZE.satz_fuer("Wilhelm, Sven") == (8500, "planung")
    assert SAETZE.satz_fuer("Bäumler, Michael") == (7500, "obermonteur")


def test_schreibweise_entscheidet_nicht() -> None:
    """TimeTac schreibt 'Wilhelm, Sven', die config vielleicht 'Wilhelm,Sven'."""
    assert SAETZE.satz_fuer("wilhelm,   sven")[0] == 8500


def test_unbekannter_mitarbeiter_bekommt_den_standardsatz() -> None:
    assert SAETZE.satz_fuer("Neu, Kollege") == (6500, None)


def test_gruppe_ohne_satz_wird_beim_laden_abgewiesen() -> None:
    with pytest.raises(ValueError, match="nicht gibt"):
        StundensaetzeEinstellungen(mitarbeiter={"Wer, Auch": "gibtsnicht"})


# ---------------------------------------------------------------------------
# Projektnummer aus dem Namen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("26001 Mustermann, Weiden", 26001),
        ("26001_Mustermann", 26001),
        ("Mustermann, Weiden [26001]", 26001),
        ("Mustermann, Weiden (26001)", 26001),
        ("Mustermann, Weiden", None),
        ("Urlaub", None),
        ("2026 Jahresplanung", 2026),
    ],
)
def test_projektnummer_aus_text(text: str, erwartet: int | None) -> None:
    assert projektnummer_aus_text(text) == erwartet


# ---------------------------------------------------------------------------
# Zuordnung gegen die Datenbank
# ---------------------------------------------------------------------------


@pytest.fixture
def projekte(gesäte_db) -> dict[int, int]:
    """26001 Mustermann/Weiden und 26002 Schmidt/Vohenstrauß."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        zuordnung = {}
        for nummer, name, ort in (
            (26001, "Mustermann", "Weiden"),
            (26002, "Schmidt", "Vohenstrauß"),
        ):
            kunde = Kunde(kunden_nr=16000 + nummer % 100, name=name, ort=ort, typ="b2c")
            sitzung.add(kunde)
            sitzung.flush()
            eintrag = Projekt(
                projekt_nr=nummer,
                firma_id=firma_id,
                kunde_id=kunde.id,
                status="in_bau",
                standort=ort,
                ab_wert_netto=5000000,
            )
            sitzung.add(eintrag)
            sitzung.flush()
            zuordnung[nummer] = eintrag.id
        return zuordnung


def test_nummer_im_projektnamen_wird_bevorzugt(projekte: dict[int, int]) -> None:
    daten = lieferung(buchung("26002 Irgendwas", "Wilhelm, Sven", "2026-07-06", "8"))
    with lese_sitzung() as sitzung:
        gefunden = projekte_zuordnen(sitzung, daten)
    assert gefunden == {26002: projekte[26002]}
    assert daten.buchungen[0].projekt_nr == 26002


def test_ohne_nummer_wird_ueber_den_kundennamen_zugeordnet(projekte: dict[int, int]) -> None:
    daten = lieferung(buchung("Mustermann Weiden", "Wilhelm, Sven", "2026-07-06", "8"))
    with lese_sitzung() as sitzung:
        projekte_zuordnen(sitzung, daten)
    assert daten.buchungen[0].projekt_nr == 26001
    assert daten.befunde == []


def test_unauffindbares_projekt_ergibt_einen_befund(projekte: dict[int, int]) -> None:
    """Lieber eine gemeldete Lücke als Stunden auf einem fremden Projekt."""
    daten = lieferung(buchung("Interne Besprechung", "Wilhelm, Sven", "2026-07-06", "2"))
    with lese_sitzung() as sitzung:
        projekte_zuordnen(sitzung, daten)
    assert daten.buchungen[0].projekt_nr is None
    assert len(daten.befunde) == 1
    assert daten.befunde[0].wert == "Interne Besprechung"


def test_dasselbe_projekt_wird_nur_einmal_gemeldet(projekte: dict[int, int]) -> None:
    daten = lieferung(
        buchung("Urlaub", "Wilhelm, Sven", "2026-07-06", "8"),
        buchung("Urlaub", "Wilhelm, Sven", "2026-07-07", "8", zeile=3),
    )
    with lese_sitzung() as sitzung:
        projekte_zuordnen(sitzung, daten)
    assert len(daten.befunde) == 1


def test_nummer_eines_unbekannten_projekts_wird_gemeldet(projekte: dict[int, int]) -> None:
    daten = lieferung(buchung("29999 Fremd", "Wilhelm, Sven", "2026-07-06", "4"))
    with lese_sitzung() as sitzung:
        assert projekte_zuordnen(sitzung, daten) == {}
    assert len(daten.befunde) == 1


# ---------------------------------------------------------------------------
# Übernehmen
# ---------------------------------------------------------------------------


def stundenzeilen(sitzung) -> list[Stunden]:
    return list(sitzung.scalars(select(Stunden).order_by(Stunden.id)))


def kostenzeilen(sitzung) -> list[IstKosten]:
    return list(
        sitzung.scalars(
            select(IstKosten).where(IstKosten.quelle == "timetac").order_by(IstKosten.id)
        )
    )


def test_stunden_und_ist_kosten_entstehen_zusammen(projekte: dict[int, int]) -> None:
    daten = lieferung(
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "8"),
        buchung("26001 Mustermann", "Bäumler, Michael", "2026-07-06", "7.5", zeile=3),
        buchung("26002 Schmidt", "Wilhelm, Sven", "2026-07-07", "4", zeile=4),
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, daten, SAETZE)

    # 8 h * 85,00 € + 7,5 h * 75,00 € = 680,00 € + 562,50 € = 1.242,50 €
    # 4 h * 85,00 € = 340,00 €
    assert ergebnis.stundenzeilen == 3 and ergebnis.kostenzeilen == 2
    assert ergebnis.summe_cent == 124250 + 34000
    with lese_sitzung() as sitzung:
        assert {(z.projekt_id, z.betrag) for z in kostenzeilen(sitzung)} == {
            (projekte[26001], 124250),
            (projekte[26002], 34000),
        }
        assert all(z.referenz == REFERENZ for z in kostenzeilen(sitzung))
        assert len(stundenzeilen(sitzung)) == 3


def test_ist_kosten_stimmen_auf_den_cent_mit_stunden_mal_satz(
    projekte: dict[int, int],
) -> None:
    """Die eine Summe, die niemand nachrechnen können muss und die trotzdem stimmen muss."""
    daten = lieferung(
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "7.33"),
        buchung("26001 Mustermann", "Neu, Kollege", "2026-07-06", "1.17", zeile=3),
    )
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, daten, SAETZE)

    with lese_sitzung() as sitzung:
        aus_detail = sum(round(z.stunden * z.satz) for z in stundenzeilen(sitzung))
        assert kostenzeilen(sitzung)[0].betrag == aus_detail
        # 7,33 h * 85,00 € = 623,05 € ; 1,17 h * 65,00 € = 76,05 €
        assert aus_detail == 62305 + 7605


def test_unbekannter_mitarbeiter_wird_gerechnet_und_gemeldet(projekte: dict[int, int]) -> None:
    """Die Stunde wegzulassen wäre schlimmer: sie fehlte im Ist und die Marge sähe besser aus."""
    daten = lieferung(buchung("26001 Mustermann", "Neu, Kollege", "2026-07-06", "8"))
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, daten, SAETZE)

    assert ergebnis.ohne_satz == ["Neu, Kollege"]
    assert ergebnis.summe_cent == 52000
    hinweis = next(b for b in ergebnis.befunde if b.wert == "Neu, Kollege")
    assert hinweis.schwere == "hinweis"
    assert "[stundensaetze.mitarbeiter]" in hinweis.meldung


def test_satz_bleibt_nach_einer_satzaenderung_stehen(projekte: dict[int, int]) -> None:
    daten = lieferung(buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "8"))
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, daten, SAETZE)

    with lese_sitzung() as sitzung:
        assert stundenzeilen(sitzung)[0].satz == 8500

    # Sven erhöht den Planungssatz. Der Juli ist abgeschlossen und darf sich nicht bewegen.
    neue_saetze = StundensaetzeEinstellungen(
        saetze={"planung": 9500, "monteur": 6500},
        mitarbeiter={"Wilhelm, Sven": "planung"},
    )
    august = lieferung(
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-08-03", "8"),
        monate=["2026-08"],
    )
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, august, neue_saetze)

    with lese_sitzung() as sitzung:
        assert [(z.monat, z.satz) for z in stundenzeilen(sitzung)] == [
            ("2026-07", 8500),
            ("2026-08", 9500),
        ]


def test_zweiter_lauf_ersetzt_den_monat_in_beiden_tabellen(projekte: dict[int, int]) -> None:
    daten = lieferung(
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "8"),
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-07", "8", zeile=3),
    )
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, daten, SAETZE)

    korrigiert = lieferung(buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "6"))
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, korrigiert, SAETZE)

    assert ergebnis.geloescht == 1, "eine Ist-Kosten-Zeile war zu ersetzen"
    with lese_sitzung() as sitzung:
        assert len(stundenzeilen(sitzung)) == 1
        assert len(kostenzeilen(sitzung)) == 1
        assert kostenzeilen(sitzung)[0].betrag == 51000


def test_ein_anderer_monat_bleibt_unberuehrt(projekte: dict[int, int]) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(
            sitzung,
            lieferung(buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "8")),
            SAETZE,
        )
    with schreib_sitzung() as sitzung:
        uebernehmen(
            sitzung,
            lieferung(
                buchung("26001 Mustermann", "Wilhelm, Sven", "2026-08-03", "4"),
                monate=["2026-08"],
            ),
            SAETZE,
        )
    with lese_sitzung() as sitzung:
        assert sorted(z.monat for z in kostenzeilen(sitzung)) == ["2026-07", "2026-08"]


def test_buchung_ausserhalb_der_gelieferten_monate_wird_nicht_geschrieben(
    projekte: dict[int, int],
) -> None:
    """Sonst stünde ein Monat halb da: geliefert wurde er nicht, geleert also auch nicht."""
    daten = lieferung(
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "8"),
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-06-30", "8", zeile=3),
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, daten, SAETZE)
    assert ergebnis.stundenzeilen == 1


def test_importprotokoll_haelt_kontrollsummen(projekte: dict[int, int]) -> None:
    daten = lieferung(
        buchung("26001 Mustermann", "Wilhelm, Sven", "2026-07-06", "8"),
        buchung("Urlaub", "Wilhelm, Sven", "2026-07-07", "8", zeile=3),
    )
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, daten, SAETZE)

    with lese_sitzung() as sitzung:
        lauf = sitzung.scalars(select(Importlauf).order_by(Importlauf.id.desc())).first()
        assert lauf.quelle == "timetac"
        assert lauf.zeitraum == "2026-07"
        assert lauf.status == "warnung", "ein nicht zugeordnetes Projekt ist kein Vollerfolg"
        assert lauf.ergebnis["kontrollsummen"]["buchungen"] == 2
        assert lauf.ergebnis["geschrieben"]["stundenzeilen"] == 1


# ---------------------------------------------------------------------------
# Rückfallebene: CSV-Berichtsexport
# ---------------------------------------------------------------------------


CSV_KOPF = "Datum;Mitarbeiter;Projekt;Aufgabe;Dauer"
CSV_ZEILEN = [
    "06.07.2026;Wilhelm, Sven;26001 Mustermann, Weiden;Planung;8,00",
    "06.07.2026;Bäumler, Michael;26001 Mustermann, Weiden;Dachmontage;07:30",
    "07.07.2026;Wilhelm, Sven;26002 Schmidt, Vohenstrauß;Inbetriebnahme;4,00",
]


def bericht_schreiben(pfad, zeilen: list[str] | None = None, kopf: str = CSV_KOPF):
    pfad.write_text("\n".join([kopf, *(zeilen or CSV_ZEILEN)]) + "\n", encoding="cp1252")
    return pfad


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("7,5", Decimal("7.50")),
        ("7.5", Decimal("7.50")),
        ("07:30", Decimal("7.50")),  # Uhrzeit: siebeneinhalb Stunden
        ("7,30", Decimal("7.30")),  # Dezimal: sieben Stunden und achtzehn Minuten
        ("07:30:00", Decimal("7.50")),
        ("8 h", Decimal("8.00")),
        ("0:45", Decimal("0.75")),
        ("", None),
        ("halbtags", None),
    ],
)
def test_dauer_deuten(eingabe: str, erwartet: Decimal | None) -> None:
    from app.importe.timetac import dauer_deuten

    assert dauer_deuten(eingabe) == erwartet


def test_bericht_lesen(tmp_path) -> None:
    from app.importe.timetac import bericht_lesen
    from app.konfiguration import TimeTacEinstellungen

    pfad = bericht_schreiben(tmp_path / "timetac_2026-07.csv")
    lieferung = bericht_lesen(pfad, TimeTacEinstellungen())

    assert lieferung.monate == ["2026-07"], "der Bericht bringt seinen Zeitraum selbst mit"
    assert [b.stunden for b in lieferung.buchungen] == [
        Decimal("8.00"),
        Decimal("7.50"),
        Decimal("4.00"),
    ]
    assert lieferung.buchungen[1].aufgabe == "Dachmontage"


def test_kaputte_zeile_im_bericht_haelt_den_lauf_nicht_auf(tmp_path) -> None:
    from app.importe.timetac import bericht_lesen
    from app.konfiguration import TimeTacEinstellungen

    pfad = bericht_schreiben(
        tmp_path / "timetac_2026-07.csv",
        [
            "06.07.2026;Wilhelm, Sven;26001 Mustermann;Planung;8,00",
            "irgendwann;Wilhelm, Sven;26001 Mustermann;Planung;8,00",
            "07.07.2026;;26001 Mustermann;Planung;8,00",
            "08.07.2026;Wilhelm, Sven;26001 Mustermann;Planung;ganzer Tag",
        ],
    )
    lieferung = bericht_lesen(pfad, TimeTacEinstellungen())

    assert len(lieferung.buchungen) == 1
    assert {b.spalte for b in lieferung.befunde} == {"datum", "mitarbeiter", "dauer"}


def test_beide_wege_ergeben_dieselben_zeilen(projekte: dict[int, int], tmp_path) -> None:
    """Der Kern der Rückfallebene: die Quelle darf an der Rechnung nichts ändern."""
    import httpx

    from app.importe.timetac import bericht_lesen
    from app.importe.timetac_api import TimeTacClient, abholen
    from app.konfiguration import TimeTacEinstellungen

    # Weg 1: der CSV-Bericht.
    pfad = bericht_schreiben(tmp_path / "timetac_2026-07.csv")
    with schreib_sitzung() as sitzung:
        ueber_csv = uebernehmen(sitzung, bericht_lesen(pfad, TimeTacEinstellungen()), SAETZE)
    with lese_sitzung() as sitzung:
        aus_csv = sorted((z.projekt_id, z.monat, z.betrag) for z in kostenzeilen(sitzung))
        stunden_csv = sorted(
            (z.mitarbeiter, str(z.stunden), z.satz) for z in stundenzeilen(sitzung)
        )

    # Weg 2: dieselbe Buchungslage über die Schnittstelle.
    antwort = {
        "Success": True,
        "Results": [
            {
                "user_name": "Wilhelm, Sven",
                "project_number": "26001",
                "project_name": "Mustermann, Weiden",
                "date": "2026-07-06",
                "duration": 28800,
            },
            {
                "user_name": "Bäumler, Michael",
                "project_number": "26001",
                "project_name": "Mustermann, Weiden",
                "date": "2026-07-06",
                "duration": 27000,
            },
            {
                "user_name": "Wilhelm, Sven",
                "project_number": "26002",
                "project_name": "Schmidt, Vohenstrauß",
                "date": "2026-07-07",
                "duration": 14400,
            },
        ],
    }

    def transport(anfrage: httpx.Request) -> httpx.Response:
        if anfrage.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        return httpx.Response(200, json=antwort)

    client = TimeTacClient(
        TimeTacEinstellungen(),
        client_id="a",
        client_secret="b",
        konto="ip3energie",
        transport=httpx.MockTransport(transport),
    )
    with schreib_sitzung() as sitzung:
        ueber_api = uebernehmen(sitzung, abholen(client, ["2026-07"]), SAETZE)

    with lese_sitzung() as sitzung:
        aus_api = sorted((z.projekt_id, z.monat, z.betrag) for z in kostenzeilen(sitzung))
        stunden_api = sorted(
            (z.mitarbeiter, str(z.stunden), z.satz) for z in stundenzeilen(sitzung)
        )

    assert aus_csv == aus_api
    assert stunden_csv == stunden_api
    assert ueber_csv.summe_cent == ueber_api.summe_cent == 124250 + 34000
