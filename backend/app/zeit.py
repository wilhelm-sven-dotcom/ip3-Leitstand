"""Zeitrechnung: gespeichert wird in UTC, gezeigt und zugeordnet wird in Europe/Berlin (PLAN §2).

Der Unterschied ist keine Formsache. Eine Rechnung, die am 1. April um 00:30 Ortszeit
festgeschrieben wird, gehört in den April – gespeichert ist sie mit dem 31. März 22:30 UTC. Wer
den Monat aus dem UTC-Zeitstempel liest, ordnet sie dem März zu und verschiebt damit den Umsatz
über eine Monatsgrenze. Deshalb gibt es hier eine einzige Stelle, die Monate bestimmt.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
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
