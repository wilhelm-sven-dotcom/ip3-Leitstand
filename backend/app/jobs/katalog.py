"""Katalog der Hintergrundläufe (PLAN §2: „stille Job-Ausfälle darf es nicht geben").

Die Liste enthält auch Jobs, die erst in späteren Phasen entstehen. Das ist gewollt: der
Systemstatus zeigt sie mit dem Hinweis „ab Phase n", damit auf der Startseite von Anfang an
sichtbar ist, welche Datenquellen der Leitstand einmal bedienen wird und welche schon laufen.
Ein Job, der still fehlt, ist schlimmer als einer, der als „noch nicht eingerichtet" dasteht.
"""

from __future__ import annotations

from typing import NamedTuple


class JobDefinition(NamedTuple):
    schluessel: str
    bezeichnung: str
    # Wie alt darf der letzte erfolgreiche Lauf sein, bevor der Status warnt?
    max_alter_stunden: int
    # Ab welcher Phase gibt es diesen Job?
    ab_phase: int
    beschreibung: str


KATALOG: tuple[JobDefinition, ...] = (
    JobDefinition(
        "backup",
        "Datensicherung",
        max_alter_stunden=26,
        ab_phase=0,
        beschreibung="Nächtliche Kopie der Datenbank in den OneDrive-Backup-Ordner",
    ),
    JobDefinition(
        "datev_import",
        "DATEV-Import",
        # Die Kanzlei liefert monatlich; nach 45 Tagen fehlt sicher etwas.
        max_alter_stunden=24 * 45,
        ab_phase=4,
        beschreibung="Kostenträger, Summen- und Saldenliste und offene Posten aus 02_DATEV",
    ),
    JobDefinition(
        "timetac_sync",
        "TimeTac-Stunden",
        max_alter_stunden=26,
        ab_phase=4,
        beschreibung="Arbeitsstunden des laufenden und des vorigen Monats",
    ),
    JobDefinition(
        "kalkulation_scan",
        "Kalkulationsblätter",
        max_alter_stunden=26,
        ab_phase=4,
        beschreibung="Sollwerte aus den Kalkulationsblättern in 03_Kalkulation",
    ),
    JobDefinition(
        "fristen",
        "Fristenprüfung",
        max_alter_stunden=26,
        ab_phase=6,
        beschreibung="Fällige Fristen für die Startseite ermitteln",
    ),
)

SCHLUESSEL: frozenset[str] = frozenset(eintrag.schluessel for eintrag in KATALOG)

# Bis zu welcher Phase die Jobs im Katalog tatsächlich laufen. Alles darüber zeigt der
# Systemstatus als „ab Phase n" an, statt es stillschweigend wegzulassen.
AKTIVE_PHASE = 5


def definition(schluessel: str) -> JobDefinition:
    for eintrag in KATALOG:
        if eintrag.schluessel == schluessel:
            return eintrag
    raise KeyError(
        f"Unbekannter Job: {schluessel}. Bekannt sind: {', '.join(sorted(SCHLUESSEL))}. "
        "Neue Jobs gehören in app/jobs/katalog.py."
    )


def ist_eingerichtet(eintrag: JobDefinition) -> bool:
    """Ob der Job in dieser Programmfassung überhaupt läuft."""
    return eintrag.ab_phase <= AKTIVE_PHASE
