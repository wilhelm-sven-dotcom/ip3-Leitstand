"""Zeitrechnung: gespeichert wird in UTC, gezeigt und zugeordnet wird in Europe/Berlin (PLAN §2).

Der Unterschied ist keine Formsache. Eine Rechnung, die am 1. April um 00:30 Ortszeit
festgeschrieben wird, gehört in den April – gespeichert ist sie mit dem 31. März 22:30 UTC. Wer
den Monat aus dem UTC-Zeitstempel liest, ordnet sie dem März zu und verschiebt damit den Umsatz
über eine Monatsgrenze. Deshalb gibt es hier eine einzige Stelle, die Monate bestimmt.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

ORTSZEIT = ZoneInfo("Europe/Berlin")


def jetzt_utc() -> datetime:
    """Aktueller Zeitpunkt als UTC mit Zeitzone."""
    return datetime.now(UTC)


def nach_utc(zeitpunkt: datetime) -> datetime:
    """Zeitpunkt nach UTC umrechnen. Zeitpunkte ohne Zeitzone werden abgewiesen.

    Ein Zeitpunkt ohne Zone ist nicht auswertbar – 14:00 kann Ortszeit oder UTC sein. Raten wäre
    der Anfang von Monatsfehlern, also verlangt der Leitstand die Angabe.
    """
    if zeitpunkt.tzinfo is None:
        raise ValueError(
            "Zeitpunkt ohne Zeitzone ist nicht verwendbar. "
            "Nächster Schritt: Zeitpunkt mit Zeitzone übergeben, "
            "für die Gegenwart jetzt_utc() nutzen."
        )
    return zeitpunkt.astimezone(UTC)


def nach_ortszeit(zeitpunkt: datetime) -> datetime:
    """Zeitpunkt in Europe/Berlin umrechnen – für Anzeige und Monatszuordnung."""
    if zeitpunkt.tzinfo is None:
        # Aus der Datenbank kommen Zeitpunkte immer als UTC; dort ist die Zone bekannt.
        zeitpunkt = zeitpunkt.replace(tzinfo=UTC)
    return zeitpunkt.astimezone(ORTSZEIT)


def monat(zeitpunkt: datetime | date) -> str:
    """Monat als ``'JJJJ-MM'`` nach Ortszeit – die Form, in der Monate in der DB stehen."""
    if isinstance(zeitpunkt, datetime):
        ortszeit = nach_ortszeit(zeitpunkt)
        return f"{ortszeit.year:04d}-{ortszeit.month:02d}"
    return f"{zeitpunkt.year:04d}-{zeitpunkt.month:02d}"


def heute_ortszeit() -> date:
    """Heutiges Datum in Ortszeit – für Fristen und Fälligkeiten."""
    return nach_ortszeit(jetzt_utc()).date()


def monat_gueltig(wert: str) -> bool:
    """Prüft die Schreibweise ``'JJJJ-MM'`` samt plausiblem Monat."""
    if len(wert) != 7 or wert[4] != "-":
        return False
    jahr, monatsteil = wert[:4], wert[5:]
    if not (jahr.isdigit() and monatsteil.isdigit()):
        return False
    return 1 <= int(monatsteil) <= 12


def monat_pruefen(wert: str, feld: str = "monat") -> str:
    """Monatsangabe prüfen und zurückgeben, sonst mit deutschem Text abweisen."""
    if not monat_gueltig(wert):
        raise ValueError(
            f"'{wert}' ist kein Monat im Format JJJJ-MM (Beispiel: 2026-03). Feld: {feld}."
        )
    return wert


def alter_in_stunden(zeitpunkt: datetime, bezug: datetime | None = None) -> float:
    """Alter eines Zeitpunkts in Stunden – Grundlage der Datenstand-Anzeige."""
    if zeitpunkt.tzinfo is None:
        zeitpunkt = zeitpunkt.replace(tzinfo=UTC)
    vergleich = bezug or jetzt_utc()
    return (vergleich - zeitpunkt).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Kalenderwochen (Phase 7)
# ---------------------------------------------------------------------------
#
# Gerechnet wird nach ISO 8601, wie überall in Deutschland: die Woche beginnt am Montag, und
# Woche 1 ist die mit dem ersten Donnerstag des Jahres. Das ist kein Detail – Ende Dezember
# gehören Tage zur ersten Woche des Folgejahres, und eine Montage in „KW 01" liegt dann im
# alten Jahr. Deshalb trägt der Schlüssel immer das **ISO-Jahr**, nicht das Kalenderjahr.

WOCHE_MUSTER = re.compile(
    r"^(?:KW\s*)?(?P<woche>\d{1,2})\s*[/\-.]\s*(?P<jahr>\d{2}|\d{4})$", re.IGNORECASE
)
ISO_MUSTER = re.compile(r"^(?P<jahr>\d{4})-?W(?P<woche>\d{1,2})$", re.IGNORECASE)


def woche_lesen(wert: str | None) -> tuple[int, int] | None:
    """Kalenderwoche aus der Teamliste oder der Maske lesen: ``(ISO-Jahr, Woche)``.

    Erlaubt sind ``'29/26'`` (Schreibweise der Teamliste), ``'29/2026'``, ``'KW 29/26'`` und
    ``'2026-W29'``. Alles andere ergibt ``None`` – der Aufrufer meldet es, statt zu raten.
    Zweistellige Jahre gelten als 20JJ; ein Bauprojekt aus dem letzten Jahrhundert gibt es nicht.
    """
    if not wert:
        return None
    roh = wert.strip()

    treffer = ISO_MUSTER.match(roh) or WOCHE_MUSTER.match(roh)
    if treffer is None:
        return None

    woche = int(treffer.group("woche"))
    jahrteil = treffer.group("jahr")
    jahr = int(jahrteil) if len(jahrteil) == 4 else 2000 + int(jahrteil)
    if not 1 <= woche <= 53:
        return None
    # Woche 53 gibt es nur in Jahren mit 53 Wochen; sonst wäre der Montag im Folgejahr.
    try:
        date.fromisocalendar(jahr, woche, 1)
    except ValueError:
        return None
    return jahr, woche


def woche_schluessel(jahr: int, woche: int) -> str:
    """Stabiler Schlüssel einer Woche: ``'2026-W29'`` – sortierbar und eindeutig."""
    return f"{jahr:04d}-W{woche:02d}"


def woche_von_datum(tag: date) -> tuple[int, int]:
    """ISO-Jahr und Kalenderwoche eines Datums."""
    kalender = tag.isocalendar()
    return kalender.year, kalender.week


def wochenbeginn(jahr: int, woche: int) -> date:
    """Montag der Kalenderwoche."""
    return date.fromisocalendar(jahr, woche, 1)


def wochen_ab(start: date, anzahl: int) -> list[tuple[int, int]]:
    """``anzahl`` aufeinanderfolgende Kalenderwochen ab der Woche von ``start``."""
    erster_montag = start - timedelta(days=start.isoweekday() - 1)
    return [woche_von_datum(erster_montag + timedelta(weeks=i)) for i in range(anzahl)]
