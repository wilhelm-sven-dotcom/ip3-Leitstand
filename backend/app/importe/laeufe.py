"""Importprotokoll und die Regel „jeder Lauf ersetzt seinen Zeitraum" (PLAN §8).

Zwei Protokolle, zwei Fragen – sie werden gern verwechselt:

* ``job_laeufe`` beantwortet „ist der nächtliche Lauf gelaufen?" (``app/jobs/lauf.py``).
* ``importlaeufe`` beantwortet „was hat dieser Import bewirkt?" – Datei, Zeitraum,
  Kontrollsummen, Befunde. Nur darum geht es hier.

Die Regel selbst steht in :func:`zeitraum_leeren`: vor dem Einfügen wird der Zeitraum gelöscht,
in derselben Schreibtransaktion. Anders als bei der einmaligen Migration ist ein zweiter Lauf
hier der Normalfall – die Kanzlei liefert Monate nach und korrigiert sie. Ein Erstlauf-Riegel
wäre hier also falsch, ein Anhängen aber auch: die Beträge stünden doppelt.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.importe.befunde import Befund, als_liste, laufstatus
from app.modelle import DatevSaldo, Importlauf, IstKosten, Opos
from app.zeit import jetzt_utc


def lauf_beginnen(
    sitzung: Session, *, quelle: str, datei: str, zeitraum: str | None = None
) -> Importlauf:
    """Protokollzeile anlegen und sofort schreiben, damit ein Abbruch sichtbar bleibt."""
    lauf = Importlauf(
        quelle=quelle,
        datei=datei,
        zeitraum=zeitraum,
        gestartet=jetzt_utc(),
        status="laeuft",
    )
    sitzung.add(lauf)
    sitzung.flush()
    return lauf


def lauf_abschliessen(
    sitzung: Session,
    lauf: Importlauf,
    *,
    befunde: Iterable[Befund],
    kontrollsummen: dict[str, Any],
    unvollstaendig: bool = False,
    weiteres: dict[str, Any] | None = None,
) -> Importlauf:
    """Zeitpunkt, Status und Ergebnis nachtragen.

    Ein Lauf, der Zeilen liegen gelassen hat, bekommt ``warnung`` – auf der Startseite darf er
    nicht wie ein glatter Erfolg aussehen.
    """
    gesammelt = list(befunde)
    lauf.beendet = jetzt_utc()
    lauf.status = laufstatus(gesammelt, unvollstaendig=unvollstaendig)
    lauf.ergebnis = {
        "kontrollsummen": kontrollsummen,
        **(weiteres or {}),
        "befunde": als_liste(gesammelt),
    }
    sitzung.flush()
    return lauf


def lauf_gescheitert(sitzung: Session, lauf: Importlauf, meldung: str) -> Importlauf:
    """Einen Lauf als gescheitert festhalten.

    Wird von den nächtlichen Läufen benutzt: eine nicht erreichbare Schnittstelle oder ein
    unlesbares Format darf keinen leeren Protokolleintrag hinterlassen, aus dem später niemand
    schließen kann, warum die Zahlen fehlen.
    """
    lauf.beendet = jetzt_utc()
    lauf.status = "fehler"
    lauf.ergebnis = {"meldung": meldung}
    sitzung.flush()
    return lauf


def zeitraum_leeren(sitzung: Session, *, quelle: str, monat: str) -> int:
    """Ist-Kosten einer Quelle für einen Monat löschen. Gibt die Anzahl zurück.

    Muss in derselben Schreibtransaktion stehen wie das anschließende Einfügen: sonst gibt es
    einen Augenblick, in dem der Monat leer ist, und bei einem Abbruch bliebe er es.
    """
    ergebnis = sitzung.execute(
        delete(IstKosten).where(IstKosten.quelle == quelle, IstKosten.monat == monat)
    )
    return int(ergebnis.rowcount or 0)


def salden_leeren(sitzung: Session, *, monat: str) -> int:
    """Salden der Summen- und Saldenliste eines Monats löschen. Gibt die Anzahl zurück.

    Eigene Funktion statt eines Tabellenparameters an :func:`zeitraum_leeren`: die drei Importe
    räumen unterschiedliche Tabellen nach unterschiedlichen Merkmalen ab (Ist-Kosten je Quelle
    und Monat, Salden je Monat, offene Posten je Stichtag). Eine gemeinsame Funktion müsste das
    verzweigen und wäre an jeder Aufrufstelle schwerer zu lesen als drei kurze.
    """
    ergebnis = sitzung.execute(delete(DatevSaldo).where(DatevSaldo.monat == monat))
    return int(ergebnis.rowcount or 0)


def opos_leeren(sitzung: Session, *, stichtag: date) -> int:
    """Offene Posten eines Stichtags löschen. Gibt die Anzahl zurück.

    Eine OPOS-Liste gilt für einen Tag, nicht für einen Monat: zwei Stände desselben Monats
    stehen nebeneinander, ein zweiter Lauf desselben Tages ersetzt.
    """
    ergebnis = sitzung.execute(delete(Opos).where(Opos.stand_datum == stichtag))
    return int(ergebnis.rowcount or 0)
