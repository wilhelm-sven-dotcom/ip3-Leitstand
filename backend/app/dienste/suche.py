"""Textsuche über Stammdaten (PLAN §2).

Kunden in der Oberpfalz heißen Pöllath, Hößl, Vohenstrauß, Püllersreuth. Wer in einer Liste mit
475 Kunden sucht, tippt „poellath" oder „pollath" – eine Suche, die darauf nichts findet, ist
keine Suche. Verglichen wird deshalb normalisiert, und zwar in **beiden** Schreibweisen:
aufgelöst (ö → oe) und ohne Punkte (ö → o).

Umgesetzt mit ``lower`` und ``replace``, nicht mit ``GLOB`` oder ``REGEXP``: die beiden gibt es
nur in SQLite, und PLAN §2 verlangt, dass ein Wechsel auf PostgreSQL ohne Umbau der Fachlogik
möglich bleibt. Das Gegenstück im Frontend ist ``frontend/src/format/vergleich.ts``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func, or_

# Umlaut aufgelöst – dieselbe Regel wie ``app.migration.vokabular.vergleichsform``.
AUFGELOEST: tuple[tuple[str, str], ...] = (
    ("ä", "ae"),
    ("ö", "oe"),
    ("ü", "ue"),
    ("ß", "ss"),
)

# Umlaut ohne Punkte – so wird häufiger getippt als aufgelöst.
OHNE_PUNKTE: tuple[tuple[str, str], ...] = (
    ("ä", "a"),
    ("ö", "o"),
    ("ü", "u"),
    ("ß", "ss"),
)


def _normalisieren(text: str, regeln: tuple[tuple[str, str], ...]) -> str:
    ergebnis = text.lower()
    for zeichen, ersatz in regeln:
        ergebnis = ergebnis.replace(zeichen, ersatz)
    return ergebnis


def _spalte_normalisiert(spalte: Any, regeln: tuple[tuple[str, str], ...]) -> ColumnElement[str]:
    """Spaltenausdruck mit denselben Ersetzungen, gerechnet in der Datenbank."""
    ausdruck: Any = func.lower(spalte)
    for zeichen, ersatz in regeln:
        ausdruck = func.replace(ausdruck, zeichen, ersatz)
    return ausdruck


def enthaelt(begriff: str, *spalten: Any) -> ColumnElement[bool] | None:
    """Bedingung: der Begriff steckt in einer der Spalten.

    Verglichen wird in beiden Umlautschreibweisen; ein Treffer in einer davon genügt. Ein leerer
    Begriff ergibt ``None`` – dann filtert der Aufrufer nicht, statt eine immer wahre Bedingung
    anzuhängen.
    """
    gesucht = begriff.strip()
    if not gesucht or not spalten:
        return None

    bedingungen = []
    for regeln in (AUFGELOEST, OHNE_PUNKTE):
        muster = f"%{_normalisieren(gesucht, regeln)}%"
        for spalte in spalten:
            bedingungen.append(_spalte_normalisiert(spalte, regeln).like(muster))
    return or_(*bedingungen)


def alle_woerter(begriff: str, *spalten: Any) -> ColumnElement[bool] | None:
    """Wie :func:`enthaelt`, verlangt aber **alle** Wörter des Begriffs.

    „ertl vohenstrauss" soll den Kunden finden, obwohl zwischen Name und Ort ein Komma steht und
    beide in verschiedenen Spalten liegen. Jedes Wort muss irgendwo vorkommen, die Reihenfolge
    ist frei – niemand weiß, ob Name oder Ort zuerst notiert wurde.
    """
    from sqlalchemy import and_

    worte = [w for w in begriff.strip().split() if w]
    if not worte or not spalten:
        return None
    je_wort = [enthaelt(wort, *spalten) for wort in worte]
    vorhanden = [b for b in je_wort if b is not None]
    return and_(*vorhanden) if vorhanden else None
