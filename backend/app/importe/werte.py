"""Zellinhalte und Textfelder deuten, für alle wiederkehrenden Importe (PLAN §8).

Diese Funktionen stammen aus dem Leser der Bestandsdateien (``app/migration/quellen.py``,
PLAN §9) und stehen jetzt hier, weil DATEV-Export, TimeTac-Bericht und Kalkulationsblatt
dieselben Fälle antreffen: deutsche Dezimalkommas, Excel-Fehlerwerte, Datumsseriennummern.
Zwei Fassungen davon würden irgendwann unterschiedlich runden, und dann stimmen zwei
Auswertungen nicht mehr überein.

Sie urteilen nicht und werfen nichts weg: was sich nicht sicher deuten lässt, ergibt ``None``.
Ob daraus ein :class:`~app.importe.befunde.Befund`, eine Vorbelegung oder ein Abbruch wird,
entscheidet die aufrufende Stelle – sie allein weiß, ob der Wert für ihren Zweck tragend ist.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

# Excel zählt Tage ab dem 1.1.1900 und rechnet den nicht existierenden 29.2.1900 mit; der
# Nullpunkt liegt deshalb auf dem 30.12.1899.
EXCEL_NULLTAG = date(1899, 12, 30)

# Alles darunter ist keine plausible Datumszahl (1902), sondern ein Tippfehler; alles darüber
# liegt jenseits des Jahres 2118.
DATUM_MINDESTZAHL = 1000
DATUM_HOECHSTZAHL = 80000


def text(wert: Any) -> str:
    """Zellinhalt als getrimmter Text; ``None`` wird zum Leerstring."""
    if wert is None:
        return ""
    if isinstance(wert, str):
        return wert.strip()
    return str(wert).strip()


def ist_fehlerwert(inhalt: str) -> bool:
    """Excel-Fehlerwerte wie ``#VALUE!`` oder ``#REF!``."""
    return inhalt.startswith("#") and inhalt.endswith("!")


def zahl(inhalt: str) -> Decimal | None:
    """Dezimalzahl aus einem Zellinhalt, oder ``None`` wenn es keine ist.

    Für Zellen aus Excel gedacht: openpyxl liefert echte Zahlen, ein Komma steht dann nur in
    handeingetragenem Text. Zahlen mit Tausenderpunkt aus Textdateien wandelt
    :func:`deutsche_zahl`.
    """
    if not inhalt:
        return None
    try:
        return Decimal(inhalt.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def excel_datum(wert: Any) -> date | None:
    """Excel-Datumszahl oder echtes Datum in ein ``date`` wandeln.

    openpyxl wandelt formatierte Zellen selbst um; unformatierte kommen als Zahl an.
    """
    if wert is None:
        return None
    if isinstance(wert, date):
        return wert
    seriennummer = zahl(text(wert))
    if seriennummer is None:
        return None
    tage = int(seriennummer)
    if tage < DATUM_MINDESTZAHL or tage > DATUM_HOECHSTZAHL:
        return None
    return EXCEL_NULLTAG + timedelta(days=tage)


def zellen(zeile: tuple[Any, ...]) -> dict[str, Any]:
    """Belegte Zellen einer Zeile als ``{Spaltenbuchstabe: Wert}``.

    Im ``read_only``-Modus liefert openpyxl für unbelegte Stellen ``EmptyCell``-Objekte, die
    weder ``column_letter`` noch ``row`` kennen. Sie werden hier weggefiltert.
    """
    belegt: dict[str, Any] = {}
    for zelle in zeile:
        buchstabe = getattr(zelle, "column_letter", None)
        if buchstabe is not None and zelle.value is not None:
            belegt[buchstabe] = zelle.value
    return belegt
