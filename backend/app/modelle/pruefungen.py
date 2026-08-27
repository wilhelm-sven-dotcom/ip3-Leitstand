"""Wiederverwendbare CHECK-Bedingungen.

Absichtlich portabel formuliert: ``GLOB`` und ``REGEXP`` gibt es nur in SQLite, und PLAN §2
verlangt, dass ein Wechsel auf PostgreSQL ohne Umbau der Fachlogik möglich bleibt. ``length`` und
``substr`` gehören zum SQL-Standard und verhalten sich überall gleich.

Die Prüfungen in der Datenbank sind die letzte Verteidigungslinie. Verständliche Meldungen
entstehen weiter oben in den Pydantic-Schemas; hier geht es darum, dass ein Programmierfehler oder
ein Import keinen Unsinn einträgt.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint


def monat_check(spalte: str, name: str | None = None) -> CheckConstraint:
    """Monatsangabe ``'JJJJ-MM'``: Länge, Trennzeichen und Monatsbereich 01 bis 12."""
    bedingung = (
        f"({spalte} IS NULL) OR ("
        f"length({spalte}) = 7 AND substr({spalte}, 5, 1) = '-' "
        f"AND substr({spalte}, 6, 2) >= '01' AND substr({spalte}, 6, 2) <= '12')"
    )
    return CheckConstraint(bedingung, name=name or f"{spalte}_format")


def in_werten(spalte: str, werte: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    """Spalte darf nur einen der genannten Werte tragen (Ersatz für ein Enum)."""
    liste = ", ".join(f"'{wert}'" for wert in werte)
    return CheckConstraint(f"{spalte} IN ({liste})", name=name or f"{spalte}_wert")


def in_werten_oder_leer(
    spalte: str, werte: tuple[str, ...], name: str | None = None
) -> CheckConstraint:
    """Wie :func:`in_werten`, lässt aber NULL zu."""
    liste = ", ".join(f"'{wert}'" for wert in werte)
    return CheckConstraint(
        f"({spalte} IS NULL) OR ({spalte} IN ({liste}))", name=name or f"{spalte}_wert"
    )


def nicht_negativ(spalte: str, name: str | None = None) -> CheckConstraint:
    """Für Mengen und Zähler. **Nicht** für Geldbeträge – Gutschriften und Stornos sind negativ."""
    return CheckConstraint(
        f"({spalte} IS NULL) OR ({spalte} >= 0)", name=name or f"{spalte}_positiv"
    )
