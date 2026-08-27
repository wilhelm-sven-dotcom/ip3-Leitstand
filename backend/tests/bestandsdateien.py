"""Nachbauten der beiden Excel-Bestandsdateien für die Tests.

Die echten Dateien enthalten 530 Kundennamen mit Orten und Auftragswerten und gehören damit
nicht ins Repository (PLAN §13.11). Die Tests arbeiten stattdessen mit diesen Nachbauten: gleiche
Blattnamen, gleiches Spaltenraster, erfundene Namen – und **jede Eigenheit**, die in den echten
Dateien gefunden wurde, als eigene Zeile.

Die Liste der Eigenheiten ist der eigentliche Wert dieser Datei. Sie ist am Original nachgemessen
und dokumentiert, womit der Leser umgehen muss:

* Rechnungsarten in 21 Schreibweisen, darunter ``3 .Abschlag`` mit Leerzeichen vor dem Punkt und
  ``Schlussrechnung - PV`` neben ``Schlussrechnung PV``
* Abschlagsnummern bis 5, obwohl die Teamliste nur vier Spalten dafür hat
* Zeilen ohne Rechnungsart (Auftragssummen ohne Zahlungsplan)
* Zeilen ohne Monatsmarker (unterminiert)
* Beträge mit zwei Trennzeichen (``22.604.28 €``), Fragezeichen statt Zahl, Striche
* Datumsangaben als Excel-Seriennummer, dazu ein Tippfehler (``30.11.222``)
* Speicherangaben als Produkttext (``2x BYD HVM 22.1``), teils mit Dezimalkomma
* Termin- und Statusspalten mit ``x``, ``-``, ``o``, Kalenderwochen (``28/22``), ``x, x`` und
  Freitext, der dort nichts zu suchen hat
* Excel-Fehlerwerte (``#VALUE!``) und eine Rechenspalte mit Bruchzahlen
* Summenformeln, die auf einen falschen Bereich zeigen
* Leerzeilen mitten in den Daten und ein Projektleitername mit Leerzeichen am Rand
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.migration.quellen import (
    ABSCHLAGSSPALTEN,
    BLATT_AUFTRAEGE,
    BLATT_PROJEKTE,
    ERSTE_DATENZEILE,
    MARKERSPALTEN,
    SPALTE_AB_WERT,
    SPALTE_AUFTRAG_VOM,
    SPALTE_BEMERKUNG,
    SPALTE_BETRAG,
    SPALTE_GESTELLT,
    SPALTE_KUNDE,
    SPALTE_LADESTATION,
    SPALTE_MODULE_RESERVIERT,
    SPALTE_PL,
    SPALTE_PV_KWP,
    SPALTE_SPEICHER,
    SPALTE_TEXT,
    SPALTE_WR,
    STATUSSPALTEN,
    TERMINSPALTEN,
    VORPLANUNGSSPALTEN,
)

# Monatsnummer 1..11 auf die zugehörige Markerspalte.
MARKER_JE_MONAT = dict(enumerate(MARKERSPALTEN, start=1))


def auftragsliste_bauen(ziel: Path) -> Path:
    """Nachbau der Auftragsliste. Erwartete Werte stehen in :func:`auftragsliste_soll`."""
    mappe = Workbook()
    blatt = mappe.active
    blatt.title = BLATT_AUFTRAEGE
    blatt["A1"] = "Einnahmen / Ausgaben"
    blatt["B1"] = "Kosten"
    blatt["E1"] = "erledigt"
    for monat, spalte in MARKER_JE_MONAT.items():
        blatt[f"{_nachbar(spalte)}1"] = f"Monat {monat}"
    # Falsche Summenformel wie im Original: ein Rechteck statt einer Spalte.
    juli = MARKER_JE_MONAT[7]
    blatt[f"{_nachbar(juli)}5"] = f"=SUM({_nachbar(juli)}8:{_nachbar(MARKER_JE_MONAT[8])}3243)"

    zeile = ERSTE_DATENZEILE
    for text, betrag, monat, gestellt in _auftragszeilen():
        if text is None:  # Leerzeile mitten in den Daten
            zeile += 1
            continue
        blatt[f"{SPALTE_TEXT}{zeile}"] = text
        blatt[f"{SPALTE_BETRAG}{zeile}"] = betrag
        if gestellt:
            blatt[f"{SPALTE_GESTELLT}{zeile}"] = "x"
        if monat is not None:
            marker = MARKER_JE_MONAT[monat]
            blatt[f"{marker}{zeile}"] = "x"
            blatt[f"{_nachbar(marker)}{zeile}"] = f'=IF({marker}{zeile}="x",$B{zeile},"")'
        zeile += 1
    mappe.save(ziel)
    return ziel


def _nachbar(spalte: str) -> str:
    """Wertspalte rechts neben einer Markerspalte."""
    if len(spalte) == 1:
        return chr(ord(spalte) + 1) if spalte != "Z" else "AA"
    return spalte[0] + chr(ord(spalte[1]) + 1)


def _auftragszeilen() -> list[tuple[str | None, object, int | None, bool]]:
    """(Freitext, Betrag, Planmonat, erledigt). ``None`` als Text ist eine Leerzeile."""
    return [
        # Abschlagsreihe eines Projekts, teils gestellt – der Regelfall.
        ("Aigner, Mitterteich - 1. Abschlag PV", 5000.00, 1, True),
        ("Aigner, Mitterteich - 2. Abschlag PV", 3000.00, 2, True),
        ("Aigner, Mitterteich - 3. Abschlag PV", 2000.50, 9, False),
        ("Aigner, Mitterteich - Schlussrechnung PV", 1000.25, 11, False),
        # Zwei Dinge in einer Zeile: Trennstrich vor dem Gewerk.
        ("Brunner Hof, Erbendorf - Schlussrechnung - Speicher", 2789.25, 9, True),
        # Tippfehler: Leerzeichen vor dem Punkt.
        ("Cramer, Floß - 3 .Abschlag Speicher", 1500.00, 10, False),
        # Abschlag Nummer 5, für den die Teamliste keine Spalte hat.
        ("Denk, Wiesau - 5. Abschlag PV", 700.00, 10, False),
        # Einmalrechnung in zwei Schreibweisen.
        ("Eder, Bärnau - Rechnung 100 % Wallbox", 2400.00, 5, True),
        ("Fuchs, Neustadt - 100% Notstromfunktion", 1800.00, 6, True),
        # Abschlag ohne Gewerk im Text – muss aus dem Projekt abgeleitet werden.
        ("Gruber, Bechtsrieth - 1. Abschlag", 4000.00, 7, False),
        # Ohne Monatsmarker: unterminiert.
        ("Huber, Pressath - 2. Abschlag Speicher", 2500.00, None, True),
        # Auftragssummen ohne Rechnungsart und ohne Zahlungsplan.
        ("Speicherprojekt Irlbacher, Störnstein", 160000, None, False),
        ("Gewerbepark Konnersreuth", 80000, 11, False),
        (None, None, None, False),  # Leerzeile
        (None, None, None, False),
        # Betrag unlesbar: die Zeile darf nicht stillschweigend verschwinden.
        ("Lang, Waldsassen - 1. Abschlag PV", "?", 3, False),
        # Kunde ohne Ort (Firmenname).
        ("Ärztehaus Weiden - Schlussrechnung PV", 9500.00, 4, False),
    ]


def auftragsliste_soll() -> dict[str, object]:
    """Erwartungswerte zum Nachbau – einmal von Hand gerechnet."""
    zeilen = [z for z in _auftragszeilen() if z[0] is not None]
    lesbar = [z for z in zeilen if not isinstance(z[1], str)]
    return {
        "zeilen": len(lesbar),
        "summe_euro": sum(float(z[1]) for z in lesbar),
        "gestellt_euro": sum(float(z[1]) for z in lesbar if z[3]),
        "gestellt_zeilen": sum(1 for z in lesbar if z[3]),
        "unterminiert_euro": sum(float(z[1]) for z in lesbar if z[2] is None),
        "projektsummen": 2,
        "unlesbare_betraege": len(zeilen) - len(lesbar),
    }


def teamliste_bauen(ziel: Path) -> Path:
    """Nachbau der Teamliste. Erwartete Werte stehen in :func:`teamliste_soll`."""
    mappe = Workbook()
    blatt = mappe.active
    blatt.title = BLATT_PROJEKTE
    blatt[f"{SPALTE_KUNDE}5"] = "Kunde"
    blatt[f"{SPALTE_AB_WERT}5"] = "AB-Wert\n€"
    blatt[f"{SPALTE_AUFTRAG_VOM}6"] = "[tt.mm.jj]"
    # Falsche Summenformel wie im Original: der Bereich beginnt zu spät.
    blatt[f"{SPALTE_AB_WERT}7"] = f"=SUM({SPALTE_AB_WERT}24:{SPALTE_AB_WERT}527)"

    zeile = ERSTE_DATENZEILE
    for satz in _projektzeilen():
        if satz is None:  # Leerzeile mitten in den Daten
            zeile += 1
            continue
        for spalte, wert in satz.items():
            blatt[f"{spalte}{zeile}"] = wert
        zeile += 1
    mappe.save(ziel)
    return ziel


def _projektzeilen() -> list[dict[str, object] | None]:
    """Projektzeilen des Nachbaus, jede mit einer eigenen Eigenheit."""
    montage_uk = _spalte(TERMINSPALTEN, "montage_uk")
    montage_elektro = _spalte(TERMINSPALTEN, "montage_elektro")
    lieferung_wr_pv = _spalte(TERMINSPALTEN, "lieferung_wr_pv")
    lieferung_speicher = _spalte(TERMINSPALTEN, "lieferung_speicher")
    abnahme = _spalte(STATUSSPALTEN, "abnahme")
    mastr = _spalte(STATUSSPALTEN, "mastr")
    fertigmeldung = _spalte(STATUSSPALTEN, "fertigmeldung")
    pv1 = next(s for s, w in ABSCHLAGSSPALTEN.items() if w == ("pv", 1))
    sp1 = next(s for s, w in ABSCHLAGSSPALTEN.items() if w == ("speicher", 1))
    vorplanung = next(iter(VORPLANUNGSSPALTEN))

    return [
        # Abgeschlossenes Projekt mit Mehrfachspeicher und Excel-Seriendatum.
        {
            SPALTE_KUNDE: "Aigner, Mitterteich",
            SPALTE_PV_KWP: 84.48,
            SPALTE_WR: "Sigenergy 25.0",
            SPALTE_SPEICHER: "2x BYD HVM 22.1",
            SPALTE_LADESTATION: "1x KEBA",
            SPALTE_AUFTRAG_VOM: 44123,  # 19.10.2020
            SPALTE_AB_WERT: 85093.60,
            SPALTE_PL: "Stefan",
            montage_uk: "x",
            montage_elektro: "x",
            abnahme: "x",
            mastr: "x",
            pv1: "x",
            sp1: "x",
            SPALTE_BEMERKUNG: "Kommunikation KW 47",
        },
        # Speicher mit Dezimalkomma, Projektleitername mit Leerzeichen am Rand.
        {
            SPALTE_KUNDE: "Brunner Hof, Erbendorf",
            SPALTE_PV_KWP: 11.25,
            SPALTE_SPEICHER: "Tesla 13,5",
            SPALTE_AUFTRAG_VOM: 44346,  # 30.05.2021
            SPALTE_AB_WERT: 21385.28,
            SPALTE_PL: "  Stefan ",
            montage_uk: "x",
            abnahme: "x",
        },
        # Kalenderwoche statt Kreuz, 'o' für offen, kein PV (Strich).
        {
            SPALTE_KUNDE: "Cramer, Floß",
            SPALTE_PV_KWP: "-",
            SPALTE_SPEICHER: "BYD HVS 10.2",
            SPALTE_AUFTRAG_VOM: 45000,
            SPALTE_AB_WERT: 15000,
            SPALTE_PL: "Günther",
            lieferung_speicher: "26/23",
            montage_uk: "o",
            abnahme: "-",
        },
        # Mehrfachkreuz und Freitext, der im Terminblock nichts zu suchen hat.
        {
            SPALTE_KUNDE: "Denk, Wiesau",
            SPALTE_PV_KWP: 29.58,
            SPALTE_AUFTRAG_VOM: 45500,
            SPALTE_AB_WERT: 30000,
            SPALTE_PL: "Frank",
            lieferung_wr_pv: "x, x",
            fertigmeldung: "Benjamin",
            montage_uk: "x",
        },
        # Betrag mit zwei Trennzeichen – darf nicht geraten werden.
        {
            SPALTE_KUNDE: "Eder, Bärnau",
            SPALTE_PV_KWP: 12.0,
            SPALTE_AUFTRAG_VOM: 45600,
            SPALTE_AB_WERT: "22.604.28 €",
            SPALTE_PL: "Stefan",
            abnahme: "x",
        },
        # Datum mit Tippfehler und Fehlerwert in der Rechenspalte.
        {
            SPALTE_KUNDE: "Fuchs, Neustadt",
            SPALTE_PV_KWP: 20.5,
            SPALTE_AUFTRAG_VOM: "30.11.222",
            SPALTE_AB_WERT: 18000,
            SPALTE_PL: "Benjamin",
            SPALTE_MODULE_RESERVIERT: "#VALUE!",
            abnahme: "x",
        },
        None,  # Leerzeile mitten in den Daten
        # Ganz ohne Auftragsdatum, dafür mit Vorplanungswert.
        {
            SPALTE_KUNDE: "Gruber, Bechtsrieth",
            SPALTE_PV_KWP: 9.9,
            SPALTE_AB_WERT: 14000,
            SPALTE_PL: "Sven/Stephan",
            vorplanung: "x",
            montage_uk: "-",
        },
        # Firmenkunde ohne Ort, laufendes Projekt.
        {
            SPALTE_KUNDE: "Ärztehaus Weiden",
            SPALTE_PV_KWP: 210.67,
            SPALTE_AUFTRAG_VOM: 46000,
            SPALTE_AB_WERT: 80000,
            SPALTE_PL: "Michl",
            montage_uk: "x",
        },
        # Zwei Projekte desselben Kunden, im Original über die kWp unterschieden.
        {
            SPALTE_KUNDE: "Huber, Pressath",
            SPALTE_PV_KWP: 29.58,
            SPALTE_AUFTRAG_VOM: 46100,
            SPALTE_AB_WERT: 25000,
            SPALTE_PL: "Stefan",
        },
        {
            SPALTE_KUNDE: "Huber, Pressath",
            SPALTE_PV_KWP: 210.67,
            SPALTE_AUFTRAG_VOM: 46100,
            SPALTE_AB_WERT: 190000,
            SPALTE_PL: "Stefan",
        },
        # Kunde, den es in der Auftragsliste nicht gibt, mit ähnlichem Namen zu 'Lang'.
        {
            SPALTE_KUNDE: "Lang-Wittmann, Waldsassen",
            SPALTE_PV_KWP: 15.0,
            SPALTE_AUFTRAG_VOM: 46200,
            SPALTE_AB_WERT: 20000,
            SPALTE_PL: "Daniel",
        },
    ]


def _spalte(karte: dict[str, str], typ: str) -> str:
    return next(s for s, t in karte.items() if t == typ)


def teamliste_soll() -> dict[str, object]:
    """Erwartungswerte zum Nachbau – einmal von Hand gerechnet."""
    zeilen = [z for z in _projektzeilen() if z is not None]
    lesbar = [
        z for z in zeilen if not isinstance(z.get(SPALTE_AB_WERT), str) and SPALTE_AB_WERT in z
    ]
    return {
        "projekte": len(zeilen),
        "ab_wert_euro": sum(float(z[SPALTE_AB_WERT]) for z in lesbar),
        "mit_ab_wert": len(lesbar),
        "unlesbare_ab_werte": 1,
        "ohne_auftragsdatum": 2,  # eines ganz ohne, eines mit Tippfehler
        # Stefan, Günther, Frank, Benjamin, Sven/Stephan, Michl, Daniel.
        # '  Stefan ' fällt nach dem Trimmen mit 'Stefan' zusammen.
        "projektleiter": 7,
    }
