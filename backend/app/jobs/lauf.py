"""Protokollierung von Hintergrundläufen.

Jeder Lauf schreibt einen Datensatz in ``job_laeufe``: Beginn, Ende, Ergebnis, Meldung. Der
Kontextmanager stellt sicher, dass das auch dann passiert, wenn der Job mit einer Ausnahme endet –
sonst wäre ein abgestürzter Job nicht von einem nie gestarteten zu unterscheiden, und genau
diesen Unterschied verlangt PLAN §2.

Aus dem Job selbst darf keine Ausnahme entweichen: der Scheduler würde sie schlucken, und beim
nächsten Lauf stünde niemand davor. Deshalb wird sie hier protokolliert und in eine Meldung
verwandelt, die auf der Startseite lesbar ist.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.datenbank import schreib_sitzung
from app.jobs.katalog import definition
from app.modelle.system import JobLauf
from app.protokoll import logger
from app.zeit import jetzt_utc

log = logger(__name__)


@dataclass
class LaufErgebnis:
    """Wird vom Job gefüllt und am Ende in den Datensatz geschrieben."""

    meldung: str = ""
    kennzahlen: dict[str, Any] = field(default_factory=dict)
    warnung: bool = False

    def warnen(self, meldung: str) -> None:
        """Lauf als „mit Einschränkung erfolgreich" kennzeichnen."""
        self.warnung = True
        self.meldung = meldung


@contextmanager
def protokollierter_lauf(job: str, ausgeloest_von: str = "zeitplan") -> Iterator[LaufErgebnis]:
    """Einen Hintergrundlauf ausführen und in ``job_laeufe`` festhalten.

    Verwendung::

        with protokollierter_lauf("backup") as ergebnis:
            ...
            ergebnis.meldung = "Sicherung nach ... geschrieben"
            ergebnis.kennzahlen = {"groesse_mb": 12.4}

    Eine Ausnahme im Block wird protokolliert, in eine deutsche Meldung übersetzt und **nicht**
    weitergeworfen.
    """
    definition(job)  # Prüft, dass der Job im Katalog steht.
    beginn = jetzt_utc()
    ergebnis = LaufErgebnis()

    with schreib_sitzung() as sitzung:
        lauf = JobLauf(
            job=job,
            gestartet=beginn,
            status="laeuft",
            ausgeloest_von=ausgeloest_von,
            created_by=ausgeloest_von,
        )
        sitzung.add(lauf)
        sitzung.flush()
        lauf_id = lauf.id

    log.info("Job %s gestartet (%s)", job, ausgeloest_von)
    fehler: Exception | None = None
    try:
        yield ergebnis
    except Exception as ausnahme:
        fehler = ausnahme
        log.exception("Job %s abgebrochen", job)

    ende = jetzt_utc()
    dauer_ms = int((ende - beginn).total_seconds() * 1000)

    if fehler is not None:
        status = "fehler"
        meldung = _fehlermeldung(job, fehler)
    elif ergebnis.warnung:
        status = "warnung"
        meldung = ergebnis.meldung
    else:
        status = "erfolg"
        meldung = ergebnis.meldung or "Ohne Besonderheiten abgeschlossen."

    with schreib_sitzung() as sitzung:
        gespeichert = sitzung.get(JobLauf, lauf_id)
        if gespeichert is not None:
            gespeichert.beendet = ende
            gespeichert.status = status
            gespeichert.meldung = meldung
            gespeichert.dauer_ms = dauer_ms
            gespeichert.kennzahlen = ergebnis.kennzahlen or None

    log.info("Job %s beendet: %s (%d ms)", job, status, dauer_ms)


def _fehlermeldung(job: str, fehler: Exception) -> str:
    """Aus einer Ausnahme einen Satz machen, der auf der Startseite stehen darf."""
    bezeichnung = definition(job).bezeichnung
    art = type(fehler).__name__
    text = str(fehler).strip()

    if isinstance(fehler, PermissionError):
        return (
            f"{bezeichnung} fehlgeschlagen: keine Schreibrechte auf dem Zielverzeichnis. "
            "Rechte des Dienstkontos prüfen."
        )
    if isinstance(fehler, FileNotFoundError):
        return (
            f"{bezeichnung} fehlgeschlagen: ein Verzeichnis oder eine Datei fehlt. "
            "Pfade in der config.toml prüfen."
        )
    if isinstance(fehler, OSError):
        return (
            f"{bezeichnung} fehlgeschlagen: Zugriff auf das Dateisystem nicht möglich "
            f"({text or art}). Verbindung zum Zielordner und freien Speicherplatz prüfen."
        )
    # Alles Übrige: die Fehlerart nennen, ohne Stacktrace. Der steht im Protokoll.
    return (
        f"{bezeichnung} fehlgeschlagen ({art}). Einzelheiten stehen im Protokoll unter logs/. "
        "Bitte Sven informieren."
    )
