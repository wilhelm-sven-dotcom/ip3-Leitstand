"""Deutsche Zahlenformate für die Ausgabe (PLAN §6.10, §11).

Das Gegenstück zu ``frontend/src/format/formate.ts``. Beide Seiten brauchen es: die Oberfläche
für den Bildschirm, das Backend für Kommandozeile, Importprotokolle und ab Phase 3 die
Rechnungs-PDFs. Geldbeträge bleiben in ``app.geld`` – dort gehören sie zur Rechnung dazu.

Regeln: Tausenderpunkt, Dezimalkomma, geschütztes Leerzeichen vor der Einheit, echtes
Minuszeichen statt Bindestrich.
"""

from __future__ import annotations

from decimal import Decimal

GESCHUETZTES_LEERZEICHEN = " "
MINUSZEICHEN = "−"


def dezimal(wert: Decimal | float | int | None, stellen: int = 2) -> str:
    """Zahl in deutscher Schreibweise, z. B. ``15.423,20``.

    ``None`` wird zum Gedankenstrich – eine fehlende Angabe ist nicht dasselbe wie null.
    """
    if wert is None:
        return "–"
    text = f"{Decimal(str(wert)):,.{stellen}f}"
    # Erst die englischen Trennzeichen tauschen, ohne sich selbst in die Quere zu kommen.
    text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return text.replace("-", MINUSZEICHEN)


def mit_einheit(wert: Decimal | float | int | None, einheit: str, stellen: int = 2) -> str:
    """Zahl mit geschütztem Leerzeichen vor der Einheit, z. B. ``5.695,00 kWp``."""
    return f"{dezimal(wert, stellen)}{GESCHUETZTES_LEERZEICHEN}{einheit}"


def leistung(kwp: Decimal | float | int | None) -> str:
    """PV-Leistung in kWp mit zwei Nachkommastellen."""
    return mit_einheit(kwp, "kWp")


def kapazitaet(kwh: Decimal | float | int | None) -> str:
    """Speicherkapazität in kWh mit einer Nachkommastelle."""
    return mit_einheit(kwh, "kWh", stellen=1)


def anzahl(wert: int) -> str:
    """Ganze Zahl mit Tausenderpunkt, z. B. ``5.848``."""
    return dezimal(wert, stellen=0)
