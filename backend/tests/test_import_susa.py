"""Summen- und Saldenliste und die Kontenzuordnung (PLAN §8, Phase 5).

Wie beim Kostenträgerimport liegt Svens echter Kanzlei-Export noch nicht vor; entwickelt wird
gegen selbst erzeugte Dateien im dokumentierten Format und gegen dieselben Daten mit anderen
Spaltennamen.

Die Punkte, an denen der Fixkostenblock kippen würde:

* **Periode statt Kumulativ.** Führt die Datei beides, zählt die Monatsbewegung. Führt sie nur
  den Saldo, muss das im Protokoll stehen – sonst wandern kumulierte Werte als Monatswerte ins
  Cockpit und die Fixkosten wachsen ab Februar von allein.
* **Der engste Kontenbereich gewinnt.** Sonst ließe sich ein Sonderkonto nicht aus einem
  umgebenden Bereich herauslösen.
* **Ohne Zuordnung kein Block.** Das Konto wird eingelesen, zählt aber nicht mit, und der Lauf
  bekommt eine Warnung: ein fehlender Betrag im Fixkostenblock lässt die Überdeckung besser
  aussehen, als sie ist.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import konten
from app.importe.susa import MonatUnbekannt, monat_aus_dateiname, susa_lesen, uebernehmen
from app.konfiguration import SusaEinstellungen
from app.modelle import DatevSaldo, Importlauf, KontenMapping

KOPF = "Konto;Kontobezeichnung;Saldo;Soll/Haben-Kennzeichen;Monatssaldo"

ZEILEN = [
    "4120;Löhne und Gehälter;210.000,00;S;30.000,00",
    "4130;Gesetzliche Soziale Aufwendungen;70.000,00;S;10.000,00",
    "4210;Miete Halle;12.600,00;S;1.800,00",
    "4530;Laufende Kfz-Betriebskosten;21.000,00;S;3.000,00",
    "4360;Versicherungen;5.600,00;S;800,00",
    "4600;Werbekosten;3.500,00;S;500,00",
    "4970;Nebenkosten des Geldverkehrs;840,00;S;120,00",
    "1600;Verbindlichkeiten aus L+L;90.000,00;H;12.000,00",
    ";Summe;413.540,00;S;58.220,00",  # Summenzeile ohne Konto
]

# Die Zuordnung, wie sie nach der Abstimmung mit der Buchhaltung aussieht.
ZUORDNUNG = [
    ("4100", "4199", "personal"),
    ("4200", "4299", "raum"),
    ("4300", "4399", "versicherung"),
    ("4500", "4599", "fahrzeuge"),
    ("4600", "4699", "werbung"),
    ("4900", "4999", "zins"),
    ("1600", "1699", "neutral"),
]


def datei_schreiben(pfad: Path, zeilen: list[str], *, kopf: str = KOPF) -> Path:
    pfad.write_text("\n".join([kopf, *zeilen]) + "\n", encoding="cp1252")
    return pfad


def standarddatei(ordner: Path, name: str = "susa_2026-07.csv") -> Path:
    return datei_schreiben(ordner / name, ZEILEN)


@pytest.fixture
def zuordnung(gesäte_db) -> None:
    with schreib_sitzung() as sitzung:
        for von, bis, block in ZUORDNUNG:
            sitzung.add(KontenMapping(konto_von=von, konto_bis=bis, block=block))


def bereiche() -> list[konten.Bereich]:
    with lese_sitzung() as sitzung:
        return konten.bereiche_laden(sitzung)


def einlesen(pfad: Path, **kwargs) -> object:
    return susa_lesen(pfad, SusaEinstellungen(), bereiche(), **kwargs)


# ---------------------------------------------------------------------------
# Dateiname und Lesen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "erwartet"),
    [
        ("susa_2026-07.csv", "2026-07"),
        ("susa_2026_07.csv", "2026-07"),
        ("SuSa 2026-12 endgültig.csv", "2026-12"),
        ("susa.csv", None),
        ("susa_2026-13.csv", None),
    ],
)
def test_monat_aus_dateiname(name: str, erwartet: str | None) -> None:
    assert monat_aus_dateiname(Path(name)) == erwartet


def test_ohne_monat_im_namen_kommt_eine_verstaendliche_meldung(zuordnung, tmp_path) -> None:
    pfad = datei_schreiben(tmp_path / "salden.csv", ZEILEN)
    with pytest.raises(MonatUnbekannt) as fehler:
        einlesen(pfad)
    assert "susa_JJJJ-MM.csv" in fehler.value.naechster_schritt


def test_monatsbewegung_wird_der_saldospalte_vorgezogen(zuordnung, tmp_path) -> None:
    """Der Kern der Sache: 30.000 statt 210.000 für den Monat Juli."""
    datei = einlesen(standarddatei(tmp_path))

    personal = [z for z in datei.zeilen if z.konto == "4120"]
    assert len(personal) == 1
    assert personal[0].betrag_cent == 3_000_000
    assert datei.kumuliert_gelesen is False


def test_ohne_monatsspalte_wird_der_saldo_genommen_und_gemeldet(zuordnung, tmp_path) -> None:
    """Ein kumulierter Saldo als Monatswert ist der teuerste stille Fehler dieser Phase."""
    pfad = datei_schreiben(
        tmp_path / "susa_2026-07.csv",
        ["4120;Löhne und Gehälter;210.000,00;S", "4210;Miete Halle;12.600,00;S"],
        kopf="Konto;Kontobezeichnung;Saldo;Soll/Haben-Kennzeichen",
    )
    datei = einlesen(pfad)

    assert datei.kumuliert_gelesen is True
    assert [z.betrag_cent for z in datei.zeilen] == [21_000_000, 1_260_000]
    assert any("kumuliert" in b.meldung for b in datei.befunde)


def test_summenzeile_ohne_konto_wird_still_uebergangen(zuordnung, tmp_path) -> None:
    """In jeder SuSa stehen mehrere davon – sie zu melden wäre nur Lärm."""
    datei = einlesen(standarddatei(tmp_path))

    assert len(datei.zeilen) == 8
    assert not any(b.spalte == "konto" for b in datei.befunde)


def test_haben_saldo_wird_negativ(zuordnung, tmp_path) -> None:
    datei = einlesen(standarddatei(tmp_path))

    verbindlichkeiten = [z for z in datei.zeilen if z.konto == "1600"]
    assert verbindlichkeiten[0].betrag_cent == -1_200_000


def test_andere_spaltennamen_ergeben_dasselbe(zuordnung, tmp_path) -> None:
    """Kommt Svens echter Export anders, ändert sich die config.toml, nicht der Code."""
    standard = einlesen(standarddatei(tmp_path))

    ordner = tmp_path / "fremd"
    ordner.mkdir()
    fremd = datei_schreiben(
        ordner / "susa_2026-07.csv",
        ZEILEN,
        kopf="Sachkonto;Bezeichnung;Endsaldo;S/H;Periodensaldo",
    )
    eigene = SusaEinstellungen(
        spalten={
            "konto": ["Sachkonto"],
            "bezeichnung": ["Bezeichnung"],
            "saldo": ["Endsaldo"],
            "soll_haben": ["S/H"],
            "monatssaldo": ["Periodensaldo"],
        }
    )
    anders = susa_lesen(fremd, eigene, bereiche())

    assert [(z.konto, z.betrag_cent, z.block) for z in anders.zeilen] == [
        (z.konto, z.betrag_cent, z.block) for z in standard.zeilen
    ]


def test_kaputte_zeile_haelt_den_lauf_nicht_auf(zuordnung, tmp_path) -> None:
    pfad = datei_schreiben(
        tmp_path / "susa_2026-07.csv",
        [
            "4120;Löhne;210.000,00;S;30.000,00",
            "viertausend;Unfug;1,00;S;1,00",
            "4210;Miete;12.600,00;S;kein Betrag",
            "4530;Kfz;21.000,00;S;3.000,00",
        ],
    )
    datei = einlesen(pfad)

    assert [z.konto for z in datei.zeilen] == ["4120", "4530"]
    assert {b.spalte for b in datei.befunde} == {"konto", "monatssaldo"}


# ---------------------------------------------------------------------------
# Kontenzuordnung
# ---------------------------------------------------------------------------


def test_bloecke_werden_beim_lesen_gesetzt(zuordnung, tmp_path) -> None:
    datei = einlesen(standarddatei(tmp_path))

    assert {z.konto: z.block for z in datei.zeilen} == {
        "4120": "personal",
        "4130": "personal",
        "4210": "raum",
        "4530": "fahrzeuge",
        "4360": "versicherung",
        "4600": "werbung",
        "4970": "zins",
        "1600": "neutral",
    }


def test_engster_bereich_gewinnt(gesäte_db) -> None:
    """Ein Sonderkonto muss sich aus einem umgebenden Bereich herauslösen lassen."""
    with schreib_sitzung() as sitzung:
        sitzung.add(KontenMapping(konto_von="4000", konto_bis="4999", block="sonstiges"))
        sitzung.add(KontenMapping(konto_von="4100", konto_bis="4199", block="personal"))

    with lese_sitzung() as sitzung:
        gefunden = konten.bereiche_laden(sitzung)

    assert konten.block_fuer("4120", gefunden) == "personal"
    assert konten.block_fuer("4700", gefunden) == "sonstiges"
    assert konten.block_fuer("9999", gefunden) is None


def test_konto_ohne_zuordnung_bleibt_blocklos_und_warnt(gesäte_db, tmp_path) -> None:
    """Ohne Zuordnung fehlt der Betrag im Fixkostenblock – der Lauf darf nicht 'erfolg' heißen."""
    datei = einlesen(standarddatei(tmp_path))
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, datei)

    assert len(ergebnis.ohne_zuordnung) == 8
    # Das größte Konto steht oben, damit die Pflegeliste sinnvoll abzuarbeiten ist.
    assert ergebnis.ohne_zuordnung[0]["konto"] == "4120"

    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(Importlauf).where(Importlauf.quelle == "susa"))
        assert lauf is not None
        assert lauf.status == "warnung"


def test_nachtraegliche_zuordnung_wirkt_auf_vorhandene_monate(zuordnung, tmp_path) -> None:
    """Sonst zeigte das Cockpit für zwei Monate verschiedene Blöcke bei gleichem Konto."""
    pfad = datei_schreiben(tmp_path / "susa_2026-07.csv", ["4700;Sonstiges;700,00;S;100,00"])
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(pfad))

    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(DatevSaldo.block).where(DatevSaldo.konto == "4700")) is None

    with schreib_sitzung() as sitzung:
        sitzung.add(KontenMapping(konto_von="4700", konto_bis="4799", block="sonstiges"))
        sitzung.flush()
        assert konten.salden_neu_zuordnen(sitzung) == 1

    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(DatevSaldo.block).where(DatevSaldo.konto == "4700")) == (
            "sonstiges"
        )


def test_unzugeordnete_nach_betrag_sortiert(gesäte_db, tmp_path) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))

    with lese_sitzung() as sitzung:
        offene = konten.unzugeordnete(sitzung)

    # Nach Betrag, nicht nach Vorzeichen: der Habensaldo 1600 (−12.000 €) gehört genauso
    # angesehen wie ein Aufwandskonto derselben Größe.
    assert [k.konto for k in offene[:3]] == ["4120", "1600", "4130"]
    assert offene[0].summe_cent == 3_000_000
    assert offene[0].bezeichnung == "Löhne und Gehälter"


# ---------------------------------------------------------------------------
# Übernahme: jeder Lauf ersetzt seinen Monat
# ---------------------------------------------------------------------------


def test_zweiter_lauf_ersetzt_statt_zu_verdoppeln(zuordnung, tmp_path) -> None:
    pfad = standarddatei(tmp_path)
    with schreib_sitzung() as sitzung:
        erst = uebernehmen(sitzung, einlesen(pfad))
    with schreib_sitzung() as sitzung:
        zweit = uebernehmen(sitzung, einlesen(pfad))

    assert erst.geloescht == 0
    assert zweit.geloescht == erst.zeilen
    assert zweit.summe_cent == erst.summe_cent

    with lese_sitzung() as sitzung:
        assert sitzung.scalar(select(func.count()).select_from(DatevSaldo)) == erst.zeilen


def test_anderer_monat_laesst_den_ersten_stehen(zuordnung, tmp_path) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))
    august = datei_schreiben(tmp_path / "susa_2026-08.csv", ["4120;Löhne;240.000,00;S;30.000,00"])
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(august))

    with lese_sitzung() as sitzung:
        monate = sitzung.scalars(select(DatevSaldo.monat).distinct()).all()
    assert sorted(monate) == ["2026-07", "2026-08"]


def test_konto_mehrfach_in_der_datei_wird_verdichtet(zuordnung, tmp_path) -> None:
    """Mehrere Kostenstellen auf ein Konto – die Tabelle führt es je Monat einmal."""
    pfad = datei_schreiben(
        tmp_path / "susa_2026-07.csv",
        ["4210;Miete Halle;12.600,00;S;1.800,00", "4210;Miete Büro;7.000,00;S;1.000,00"],
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, einlesen(pfad))

    assert ergebnis.zeilen == 1
    with lese_sitzung() as sitzung:
        saldo = sitzung.scalar(select(DatevSaldo).where(DatevSaldo.konto == "4210"))
        assert saldo is not None
        assert saldo.saldo == 280_000


def test_protokoll_fuehrt_die_bloecke(zuordnung, tmp_path) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, einlesen(standarddatei(tmp_path)))

    with lese_sitzung() as sitzung:
        lauf = sitzung.scalar(select(Importlauf).where(Importlauf.quelle == "susa"))
        assert lauf is not None
        assert lauf.status == "erfolg"
        assert lauf.zeitraum == "2026-07"
        assert lauf.ergebnis["je_block"]["personal"] == 4_000_000
        assert lauf.ergebnis["kontrollsummen"]["konten"] == 8
