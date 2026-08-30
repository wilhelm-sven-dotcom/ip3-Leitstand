"""CSV-Dateien aus deutschen Fachprogrammen lesen (PLAN §8).

DATEV und TimeTac liefern Textdateien, die drei Dinge gemeinsam haben und in jedem Detail
abweichen können: Semikolon statt Komma als Trennzeichen, Dezimalkomma statt Punkt, und einen
Zeichensatz, der oft noch Windows-1252 ist. Alles davon wird hier einmal behandelt, damit die
beiden Importe sich um ihre Fachlichkeit kümmern können.

**Spaltennamen stehen in der Konfiguration, nicht im Code** (PLAN §8: „Spaltenbezeichnungen
variieren je Kanzlei-Export, deshalb Mapping in config"). Je Feld darf eine Liste von
Schreibweisen hinterlegt sein; die erste im Kopf gefundene gewinnt. Verglichen wird über eine
Vergleichsform ohne Leerzeichen, Bindestriche und Groß-/Kleinschreibung – „Soll/Haben-Kennzeichen"
und „soll/haben kennzeichen" sind dieselbe Spalte, und daran soll kein Import scheitern.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.fehler import FachFehler

# Zeichensätze in der Reihenfolge, in der sie probiert werden. utf-8-sig zuerst, weil es ein
# UTF-8 mit BOM erkennt und die Marke gleich entfernt – sonst hinge sie am ersten Spaltennamen.
ZEICHENSAETZE: tuple[str, ...] = ("utf-8-sig", "cp1252", "latin-1")

# Trennzeichen in der Reihenfolge der Wahrscheinlichkeit. latin-1 nimmt jede Bytefolge an, ist
# also der Notnagel am Ende und kann nicht scheitern.
TRENNZEICHEN: tuple[str, ...] = (";", ",", "\t", "|")

# Datumsformate, die in deutschen Exporten vorkommen. Reihenfolge zählt: '%d.%m.%y' würde
# '01.02.2026' nicht annehmen, '%d.%m.%Y' aber '01.02.26' auch nicht – beide braucht es.
DATUMSFORMATE: tuple[str, ...] = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y")

_NICHT_VERGLEICHBAR = re.compile(r"[^a-z0-9]+")


class CsvFehler(FachFehler):
    code = "csv_fehler"


class DateiUnlesbar(CsvFehler):
    code = "csv_unlesbar"

    def __init__(self, pfad: Path, grund: str) -> None:
        super().__init__(
            f"Die Datei '{pfad.name}' lässt sich nicht lesen: {grund}",
            "Bitte prüfen, ob die Datei vollständig übertragen wurde und ob es wirklich eine "
            "CSV-Datei ist (nicht etwa eine Excel-Datei mit der Endung .csv).",
        )


class SpaltenFehlen(CsvFehler):
    """Pflichtspalten sind im Kopf der Datei nicht zu finden.

    Das ist der erwartete Fall beim ersten echten Export einer Kanzlei. Die Meldung nennt
    deshalb beides: was gesucht wurde und was tatsächlich dasteht – daraus lässt sich die
    Zuordnung in der config.toml in einem Zug ergänzen.
    """

    code = "csv_spalten_fehlen"

    def __init__(self, pfad: Path, fehlend: dict[str, list[str]], gefunden: list[str]) -> None:
        gesucht = "; ".join(f"{feld}: {' oder '.join(namen)}" for feld, namen in fehlend.items())
        super().__init__(
            f"In der Datei '{pfad.name}' fehlen Spalten: {gesucht}.",
            "Vorhandene Spalten: "
            + (", ".join(f"'{s}'" for s in gefunden) or "keine")
            + ". Die tatsächlichen Namen in der config.toml unter der Spaltenzuordnung des "
            "Imports eintragen; der Leitstand muss dafür nicht geändert werden.",
        )


def vergleichsform(name: str) -> str:
    """Spaltenname ohne Groß-/Kleinschreibung, Leerzeichen und Sonderzeichen."""
    return _NICHT_VERGLEICHBAR.sub("", name.casefold())


@dataclass
class Zeile:
    """Eine Datenzeile mit ihrer Nummer in der Datei (1-basiert, Kopfzeile mitgezählt)."""

    nummer: int
    felder: dict[str, str]

    def wert(self, feld: str) -> str:
        return self.felder.get(feld, "")


@dataclass
class CsvDatei:
    pfad: Path
    zeichensatz: str
    trennzeichen: str
    spaltenkoepfe: list[str]
    # Felder des Leitstands, die im Kopf tatsächlich gefunden wurden. Nicht dasselbe wie die
    # Schlüssel einer Zeile abzufragen: eine Datei ohne Datenzeilen hätte sonst gar keine
    # Auskunft, und ein optionales Feld ließe sich nicht von einem leeren unterscheiden.
    felder: list[str] = field(default_factory=list)
    zeilen: list[Zeile] = field(default_factory=list)

    def hat(self, feld: str) -> bool:
        return feld in self.felder


def lesen(pfad: Path, zuordnung: dict[str, list[str]], *, pflicht: tuple[str, ...]) -> CsvDatei:
    """Liest eine CSV-Datei und benennt die Spalten nach ``zuordnung`` um.

    ``zuordnung`` bildet Feldnamen des Leitstands auf mögliche Spaltennamen der Quelle ab.
    ``pflicht`` nennt die Felder, ohne die der Import keinen Sinn ergibt – fehlt eines, ist das
    ein :class:`SpaltenFehlen` und keine stille Leerspalte.
    """
    text, zeichensatz = _text_lesen(pfad)
    trennzeichen = _trennzeichen_erkennen(text)
    zeilen = list(csv.reader(text.splitlines(), delimiter=trennzeichen))
    if not zeilen:
        raise DateiUnlesbar(pfad, "die Datei ist leer")

    return aus_zeilen(
        pfad,
        zeilen[0],
        zeilen[1:],
        zuordnung,
        pflicht=pflicht,
        zeichensatz=zeichensatz,
        trennzeichen=trennzeichen,
    )


def _text_lesen(pfad: Path) -> tuple[str, str]:
    """Dateiinhalt als Text und der Zeichensatz, mit dem es geklappt hat."""
    try:
        rohdaten = pfad.read_bytes()
    except OSError as fehler:
        raise DateiUnlesbar(pfad, str(fehler)) from fehler
    for zeichensatz in ZEICHENSAETZE:
        try:
            return rohdaten.decode(zeichensatz), zeichensatz
        except UnicodeDecodeError:
            continue
    # Unerreichbar, solange latin-1 in der Liste steht: es nimmt jede Bytefolge an.
    raise DateiUnlesbar(pfad, "unbekannter Zeichensatz")


def _trennzeichen_erkennen(text: str) -> str:
    """Das Trennzeichen, das in der Kopfzeile am häufigsten vorkommt.

    Kein ``csv.Sniffer``: der rät bei einer Kopfzeile mit Klammern und Schrägstrichen –
    „Umsatz (ohne Soll/Haben-Kz)" – gern das Komma, obwohl die Datei Semikolon trennt.
    """
    kopfzeile = text.splitlines()[0] if text else ""
    treffer = {zeichen: kopfzeile.count(zeichen) for zeichen in TRENNZEICHEN}
    bestes = max(treffer, key=lambda z: treffer[z])
    return bestes if treffer[bestes] else TRENNZEICHEN[0]


def aus_zeilen(
    pfad: Path,
    kopf: list[str],
    datenzeilen: list[list[str]],
    zuordnung: dict[str, list[str]],
    *,
    pflicht: tuple[str, ...],
    zeichensatz: str = "-",
    trennzeichen: str = "-",
) -> CsvDatei:
    """Wie :func:`lesen`, aber auf schon eingelesenen Zeilen.

    Für Quellen, die keine Textdatei sind – die Angebotsliste kommt als Excel-Mappe. Die
    Spaltenzuordnung, die Pflichtprüfung und die Form des Ergebnisses sollen trotzdem dieselben
    sein: an einer Tabelle darf es keinen Unterschied machen, in welchem Dateiformat sie
    ankommt.
    """
    kopf = [spalte.strip() for spalte in kopf]
    spalten = _spalten_zuordnen(kopf, zuordnung)
    fehlend = {feld: zuordnung[feld] for feld in pflicht if feld not in spalten}
    if fehlend:
        raise SpaltenFehlen(pfad, fehlend, kopf)

    datei = CsvDatei(
        pfad=pfad,
        zeichensatz=zeichensatz,
        trennzeichen=trennzeichen,
        spaltenkoepfe=kopf,
        felder=sorted(spalten),
    )
    for nummer, rohzeile in enumerate(datenzeilen, start=2):
        if not any(zelle.strip() for zelle in rohzeile):
            continue
        datei.zeilen.append(
            Zeile(
                nummer=nummer,
                felder={
                    feld: (rohzeile[index].strip() if index < len(rohzeile) else "")
                    for feld, index in spalten.items()
                },
            )
        )
    return datei


def _spalten_zuordnen(kopf: list[str], zuordnung: dict[str, list[str]]) -> dict[str, int]:
    """``{Feldname: Spaltenindex}`` – die erste im Kopf gefundene Schreibweise gewinnt."""
    vorhanden = {vergleichsform(name): index for index, name in enumerate(kopf)}
    spalten: dict[str, int] = {}
    for feld, namen in zuordnung.items():
        for name in namen:
            index = vorhanden.get(vergleichsform(name))
            if index is not None:
                spalten[feld] = index
                break
    return spalten


# ---------------------------------------------------------------------------
# Werte deuten
# ---------------------------------------------------------------------------


def deutsche_zahl(inhalt: str) -> Decimal | None:
    """Zahl aus einem deutschen Export: ``1.234,56``, ``-1.234,56``, ``1.234,56-``, ``1234.56``.

    Das nachgestellte Minus ist keine Spielerei: DATEV und andere Hauswährungsprogramme
    schreiben es so. Wer es übersieht, bekommt Kosten mit umgekehrtem Vorzeichen.
    """
    roh = inhalt.strip().replace("€", "").replace("EUR", "").strip()
    if not roh:
        return None
    negativ = False
    if roh.endswith("-"):
        negativ, roh = True, roh[:-1].strip()
    if roh.startswith("(") and roh.endswith(")"):
        negativ, roh = True, roh[1:-1].strip()
    if roh.startswith("-"):
        negativ, roh = True, roh[1:].strip()
    roh = roh.replace(" ", "").replace("\xa0", "")

    # Beide Trennzeichen vorhanden: das hintere ist das Dezimaltrennzeichen.
    if "," in roh and "." in roh:
        if roh.rindex(",") > roh.rindex("."):
            roh = roh.replace(".", "").replace(",", ".")
        else:
            roh = roh.replace(",", "")
    elif "," in roh:
        roh = roh.replace(",", ".")
    try:
        wert = Decimal(roh)
    except (InvalidOperation, ValueError):
        return None
    return -wert if negativ else wert


def deutsches_datum(inhalt: str, *, jahr: int | None = None) -> date | None:
    """Datum aus einem deutschen Export.

    ``jahr`` deutet zusätzlich das vierstellige ``TTMM`` des DATEV-Buchungsstapels, in dem das
    Jahr nur im Dateikopf steht. Ohne ``jahr`` bleibt diese Form ungedeutet – ein geratenes
    Buchungsjahr wäre schlimmer als eine gemeldete Lücke.
    """
    roh = inhalt.strip()
    if not roh:
        return None
    for format_ in DATUMSFORMATE:
        try:
            return datetime.strptime(roh, format_).date()
        except ValueError:
            continue
    if jahr is not None and len(roh) == 4 and roh.isdigit():
        try:
            return date(jahr, int(roh[2:]), int(roh[:2]))
        except ValueError:
            return None
    return None
