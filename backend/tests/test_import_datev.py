"""CSV-Leser und DATEV-Kostenträgerimport (PLAN §8, §6.5).

Svens echter Kanzlei-Export liegt noch nicht vor. Entwickelt und geprüft wird deshalb gegen
selbst erzeugte Dateien im dokumentierten Standardformat – und, das ist der eigentliche Punkt
dieser Datei, **gegen dieselben Daten mit anderen Spaltennamen**. Wenn der echte Export kommt,
soll sich die config.toml ändern und nicht der Code (PLAN §8: „Mapping in config").

Die drei Regeln, die hier abgesichert werden:

* Nur Kosten aus den konfigurierten Kontenbereichen; Erlöse bleiben draußen.
* Jeder Lauf ersetzt seinen Monat und lässt die anderen stehen (PLAN §8).
* Eine kaputte Zeile hält den Lauf nicht auf, sie wird zum Befund.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.importe import csv_leser
from app.importe.datev import (
    MonatUnbekannt,
    kostentraeger_lesen,
    monat_aus_dateiname,
    uebernehmen,
)
from app.konfiguration import KostentraegerEinstellungen
from app.modelle import Firma, Importlauf, IstKosten, Kunde, Projekt

# Kopfzeile im Standardformat der DATEV-Kostenträgerauswertung.
KOPF = (
    "Belegdatum;Konto;Kontobezeichnung;Buchungstext;Belegfeld 1;Umsatz;Soll/Haben-Kennzeichen;KOST2"
)

ZEILEN = [
    "05.07.2026;3400;Wareneingang 19 % VSt;Module Trina;RE-4711;12.480,50;S;26001",
    "08.07.2026;3400;Wareneingang 19 % VSt;Wechselrichter;RE-4712;3.200,00;S;26001",
    "09.07.2026;4830;Fremdleistungen;Gerüst;RE-88;1.750,00;S;26002",
    "12.07.2026;3400;Wareneingang 19 % VSt;Gutschrift Module;GS-12;480,50;H;26001",
    "31.07.2026;8400;Erlöse 19 % USt;Abschlag 1;RE-2026-0001;25.000,00;H;26001",
    "31.07.2026;4210;Miete;Halle;;900,00;S;",
]


def datei_schreiben(
    pfad: Path, zeilen: list[str], *, kopf: str = KOPF, zeichensatz: str = "utf-8"
) -> Path:
    pfad.write_text("\n".join([kopf, *zeilen]) + "\n", encoding=zeichensatz)
    return pfad


def standarddatei(ordner: Path, name: str = "kostentraeger_2026-07.csv") -> Path:
    return datei_schreiben(ordner / name, ZEILEN)


@pytest.fixture
def einstellungen() -> KostentraegerEinstellungen:
    return KostentraegerEinstellungen()


# ---------------------------------------------------------------------------
# CSV-Leser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("-1.234,56", Decimal("-1234.56")),
        ("1.234,56-", Decimal("-1234.56")),  # DATEV schreibt das Minus hinten
        ("(1.234,56)", Decimal("-1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),  # englische Schreibweise
        ("0", Decimal("0")),
        ("12.480,50 €", Decimal("12480.50")),
        ("", None),
        ("keine Zahl", None),
    ],
)
def test_deutsche_zahl(eingabe: str, erwartet: Decimal | None) -> None:
    assert csv_leser.deutsche_zahl(eingabe) == erwartet


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("05.07.2026", "2026-07-05"),
        ("05.07.26", "2026-07-05"),
        ("2026-07-05", "2026-07-05"),
        ("", None),
        ("Juli", None),
    ],
)
def test_deutsches_datum(eingabe: str, erwartet: str | None) -> None:
    gelesen = csv_leser.deutsches_datum(eingabe)
    assert (gelesen.isoformat() if gelesen else None) == erwartet


def test_vierstelliges_datum_nur_mit_bekanntem_jahr() -> None:
    """Der DATEV-Buchungsstapel schreibt TTMM; das Jahr steht nur im Dateikopf."""
    assert csv_leser.deutsches_datum("0507") is None
    assert csv_leser.deutsches_datum("0507", jahr=2026).isoformat() == "2026-07-05"


@pytest.mark.parametrize("zeichensatz", ["utf-8", "utf-8-sig", "cp1252"])
def test_zeichensaetze_werden_erkannt(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen, zeichensatz: str
) -> None:
    """Kanzlei-Exporte kommen als ANSI oder als UTF-8, mit und ohne Marke am Anfang."""
    pfad = datei_schreiben(tmp_path / "kostentraeger_2026-07.csv", ZEILEN, zeichensatz=zeichensatz)
    datei = kostentraeger_lesen(pfad, einstellungen)
    assert datei.buchungen[0].kontobezeichnung == "Wareneingang 19 % VSt"


def test_komma_getrennte_datei_wird_erkannt(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    """Komma als Trennzeichen geht nur mit Anführungszeichen um die deutschen Beträge.

    Genau so schreibt ein Programm eine solche Datei auch; ohne Anführungszeichen wäre
    '12.480,50' zwei Felder, und das ließe sich auch nicht mehr reparieren.
    """
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        [",".join(f'"{feld}"' for feld in zeile.split(";")) for zeile in ZEILEN],
        kopf=",".join(f'"{spalte}"' for spalte in KOPF.split(";")),
    )
    assert len(kostentraeger_lesen(pfad, einstellungen).buchungen) == 4


def test_fehlende_pflichtspalte_nennt_gesuchtes_und_vorhandenes(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        ["05.07.2026;3400;12.480,50"],
        kopf="Belegdatum;Konto;Umsatz",
    )
    with pytest.raises(csv_leser.SpaltenFehlen) as fehler:
        kostentraeger_lesen(pfad, einstellungen)
    assert "kostentraeger" in str(fehler.value)
    assert "'Belegdatum'" in fehler.value.naechster_schritt


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------


def test_monat_aus_dateiname(tmp_path: Path) -> None:
    assert monat_aus_dateiname(tmp_path / "kostentraeger_2026-07.csv") == "2026-07"
    assert monat_aus_dateiname(tmp_path / "KOSTENTRAEGER_2026_07.CSV") == "2026-07"
    assert monat_aus_dateiname(tmp_path / "kostentraeger.csv") is None
    assert monat_aus_dateiname(tmp_path / "kostentraeger_2026-13.csv") is None


def test_datei_ohne_monat_im_namen_wird_abgewiesen(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    pfad = datei_schreiben(tmp_path / "export.csv", ZEILEN)
    with pytest.raises(MonatUnbekannt) as fehler:
        kostentraeger_lesen(pfad, einstellungen)
    assert "kostentraeger_JJJJ-MM.csv" in fehler.value.naechster_schritt


def test_nur_kostenkonten_werden_uebernommen(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    """Eine Kostenträgerauswertung führt auch Erlöse – die dürfen die Marge nicht umdrehen."""
    datei = kostentraeger_lesen(standarddatei(tmp_path), einstellungen)

    assert [b.konto for b in datei.buchungen] == ["3400", "3400", "4830", "3400"]
    gruende = [e["grund"] for e in datei.nicht_uebernommen]
    assert any("8400" in str(g) for g in gruende), "Erlöskonto muss draußen bleiben"
    assert any("ohne Kostenträger" in str(g) for g in gruende)


def test_haben_mindert_die_kosten(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    datei = kostentraeger_lesen(standarddatei(tmp_path), einstellungen)
    assert datei.je_projekt() == {26001: 1520000, 26002: 175000}
    assert datei.summe_cent == 1695000


def test_unbekanntes_soll_haben_kennzeichen_ergibt_befund(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        ["05.07.2026;3400;Wareneingang;Module;RE-1;100,00;X;26001"],
    )
    datei = kostentraeger_lesen(pfad, einstellungen)
    assert datei.buchungen[0].betrag_cent == 10000
    assert datei.befunde[0].spalte == "soll_haben"


def test_kaputte_zeile_haelt_den_lauf_nicht_auf(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        [
            "05.07.2026;3400;Wareneingang;Module;RE-1;12.480,50;S;26001",
            "06.07.2026;3400;Wareneingang;Kaputt;RE-2;bar bezahlt;S;26001",
            "07.07.2026;3400;Wareneingang;Kabel;RE-3;250,00;S;Halle Nord",
            "08.07.2026;3400;Wareneingang;Schienen;RE-4;500,00;S;26001",
        ],
    )
    datei = kostentraeger_lesen(pfad, einstellungen)

    assert [b.buchungstext for b in datei.buchungen] == ["Module", "Schienen"]
    assert {b.spalte for b in datei.befunde} == {"betrag", "kostentraeger"}


def test_buchung_aus_einem_fremden_monat_wird_gemeldet(
    tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    """Der Dateiname entscheidet, welcher Monat ersetzt wird – das muss stimmen."""
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        [
            "05.07.2026;3400;Wareneingang;Module;RE-1;100,00;S;26001",
            "05.06.2026;3400;Wareneingang;Vormonat;RE-0;900,00;S;26001",
        ],
    )
    datei = kostentraeger_lesen(pfad, einstellungen)
    assert len(datei.buchungen) == 2
    assert "2026-06" in datei.befunde[0].wert


def test_abweichende_spaltennamen_ergeben_dasselbe(tmp_path: Path) -> None:
    """Der Kern der Sache: eine andere Kanzlei, dieselben Zahlen, nur config.toml geändert."""
    eigener_kopf = "Datum;Sachkonto;Konto-Bezeichnung;Text;Beleg;Betrag;S/H;Kostenträger"
    pfad = datei_schreiben(tmp_path / "kostentraeger_2026-07.csv", ZEILEN, kopf=eigener_kopf)

    # Die Vorbelegung kennt 'Datum', 'Sachkonto', 'Betrag', 'S/H' und 'Kostenträger' bereits.
    datei = kostentraeger_lesen(pfad, KostentraegerEinstellungen())
    assert datei.je_projekt() == {26001: 1520000, 26002: 175000}


def test_ganz_fremde_spaltennamen_ueber_die_konfiguration(tmp_path: Path) -> None:
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        ["05.07.2026;3400;Module;12.480,50;26001"],
        kopf="Buchungstag;Aufwandskonto;Vorgang;Wert in EUR;Projektschluessel",
    )
    eigene = KostentraegerEinstellungen(
        spalten={
            "kostentraeger": ["Projektschluessel"],
            "konto": ["Aufwandskonto"],
            "betrag": ["Wert in EUR"],
            "datum": ["Buchungstag"],
            "buchungstext": ["Vorgang"],
            "kontobezeichnung": ["gibt es hier nicht"],
            "soll_haben": ["gibt es hier auch nicht"],
            "beleg": ["fehlt ebenfalls"],
        }
    )
    datei = kostentraeger_lesen(pfad, eigene)
    assert datei.je_projekt() == {26001: 1248050}


def test_eigener_kontenbereich(tmp_path: Path) -> None:
    """SKR04 statt SKR03: die Aufwandskonten liegen woanders."""
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        ["05.07.2026;5400;Materialaufwand;Module;RE-1;100,00;S;26001"],
    )
    assert kostentraeger_lesen(pfad, KostentraegerEinstellungen()).buchungen == []
    skr04 = KostentraegerEinstellungen(kostenkonten=["5000-7999"])
    assert len(kostentraeger_lesen(pfad, skr04).buchungen) == 1


def test_unsinniger_kontenbereich_wird_beim_laden_abgewiesen() -> None:
    with pytest.raises(ValueError, match="kein Kontenbereich"):
        KostentraegerEinstellungen(kostenkonten=["dreitausend bis viertausend"])
    with pytest.raises(ValueError, match="Untergrenze"):
        KostentraegerEinstellungen(kostenkonten=["4999-3000"])


# ---------------------------------------------------------------------------
# Übernehmen
# ---------------------------------------------------------------------------


@pytest.fixture
def projekte(gesäte_db) -> dict[int, int]:
    """Projekte 26001 und 26002. Liefert ``{projekt_nr: id}``."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=15001, name="DATEV GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        zuordnung = {}
        for nummer in (26001, 26002):
            eintrag = Projekt(
                projekt_nr=nummer,
                firma_id=firma_id,
                kunde_id=kunde.id,
                status="in_bau",
                ab_wert_netto=5000000,
            )
            sitzung.add(eintrag)
            sitzung.flush()
            zuordnung[nummer] = eintrag.id
        return zuordnung


def ist_kosten(sitzung, quelle: str = "datev") -> list[IstKosten]:
    return list(
        sitzung.scalars(select(IstKosten).where(IstKosten.quelle == quelle).order_by(IstKosten.id))
    )


def test_uebernahme_verdichtet_auf_projekt_und_konto(
    projekte: dict[int, int], tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    datei = kostentraeger_lesen(standarddatei(tmp_path), einstellungen)
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, datei)

    assert ergebnis.zeilen == 2 and ergebnis.projekte == 2
    assert ergebnis.summe_cent == 1695000
    with lese_sitzung() as sitzung:
        zeilen = ist_kosten(sitzung)
        assert {(z.projekt_id, z.referenz, z.betrag) for z in zeilen} == {
            (projekte[26001], "3400 Wareneingang 19 % VSt", 1520000),
            (projekte[26002], "4830 Fremdleistungen", 175000),
        }
        assert all(z.monat == "2026-07" for z in zeilen)


def test_zweiter_lauf_ersetzt_den_monat_statt_zu_verdoppeln(
    projekte: dict[int, int], tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    """PLAN §8. Ein nachgelieferter oder korrigierter Monat ist der Normalfall."""
    pfad = standarddatei(tmp_path)
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, kostentraeger_lesen(pfad, einstellungen))

    datei_schreiben(pfad, ZEILEN[:1])  # die Kanzlei liefert den Monat korrigiert nach
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, kostentraeger_lesen(pfad, einstellungen))

    assert ergebnis.geloescht == 2
    with lese_sitzung() as sitzung:
        zeilen = ist_kosten(sitzung)
        assert len(zeilen) == 1
        assert zeilen[0].betrag == 1248050


def test_ein_anderer_monat_laesst_den_ersten_stehen(
    projekte: dict[int, int], tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, kostentraeger_lesen(standarddatei(tmp_path), einstellungen))

    august = datei_schreiben(
        tmp_path / "kostentraeger_2026-08.csv",
        ["05.08.2026;3400;Wareneingang 19 % VSt;Kabel;RE-99;300,00;S;26001"],
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, kostentraeger_lesen(august, einstellungen))

    assert ergebnis.geloescht == 0
    with lese_sitzung() as sitzung:
        assert sorted(z.monat for z in ist_kosten(sitzung)) == ["2026-07", "2026-07", "2026-08"]


def test_unbekannter_kostentraeger_wird_gemeldet_und_ausgelassen(
    projekte: dict[int, int], tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        [
            "05.07.2026;3400;Wareneingang;Module;RE-1;100,00;S;26001",
            "06.07.2026;3400;Wareneingang;Fremd;RE-2;700,00;S;29999",
        ],
    )
    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, kostentraeger_lesen(pfad, einstellungen))

    assert ergebnis.unbekannte_projekte == [{"projekt_nr": 29999, "betrag_cent": 70000}]
    assert "29999" in ergebnis.befunde[0].meldung
    with lese_sitzung() as sitzung:
        assert len(ist_kosten(sitzung)) == 1


def test_importprotokoll_haelt_kontrollsummen_und_einzelbuchungen(
    projekte: dict[int, int], tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    """Verdichtet wird in ist_kosten; nachlesbar bleibt es im Protokoll."""
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, kostentraeger_lesen(standarddatei(tmp_path), einstellungen))

    with lese_sitzung() as sitzung:
        lauf = sitzung.scalars(select(Importlauf).order_by(Importlauf.id.desc())).first()
        assert lauf.quelle == "datev"
        assert lauf.zeitraum == "2026-07", "der Zeitraum trägt den ersetzten Monat"
        assert lauf.status == "erfolg"
        assert lauf.ergebnis["kontrollsummen"]["buchungen"] == 4
        assert lauf.ergebnis["kontrollsummen"]["summe_cent"] == 1695000
        assert len(lauf.ergebnis["einzelbuchungen"]) == 4
        assert len(lauf.ergebnis["nicht_uebernommen"]) == 2


def test_lauf_mit_unbekanntem_projekt_bekommt_den_status_warnung(
    projekte: dict[int, int], tmp_path: Path, einstellungen: KostentraegerEinstellungen
) -> None:
    pfad = datei_schreiben(
        tmp_path / "kostentraeger_2026-07.csv",
        ["06.07.2026;3400;Wareneingang;Fremd;RE-2;700,00;S;29999"],
    )
    with schreib_sitzung() as sitzung:
        uebernehmen(sitzung, kostentraeger_lesen(pfad, einstellungen))
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalars(select(Importlauf).order_by(Importlauf.id.desc())).first()
        assert lauf.status == "warnung"
