"""Zeitplan der Hintergrundläufe (PLAN §2).

APScheduler im Backend-Prozess, nicht als eigener Dienst: ein Prozess ist leichter zu betreiben
und zu überwachen, und die Läufe sind kurz.

**Genau ein Arbeitsprozess.** Mit mehreren Uvicorn-Prozessen hätte jeder seinen eigenen Zeitplan,
und die Sicherung liefe mehrfach – später auch die Importe, was Daten doppelt zählen würde. Der
Start warnt deshalb, wenn er Anzeichen für mehrere Prozesse findet.
"""

from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.backup import backup_job, sitzungen_aufraeumen_job
from app.konfiguration import Einstellungen
from app.protokoll import logger
from app.zeit import ORTSZEIT

log = logger(__name__)

_scheduler: BackgroundScheduler | None = None


def _naechtlicher_lauf(werte: Einstellungen) -> None:
    """Alles, was nachts passiert – in einer Funktion, damit die Reihenfolge feststeht."""
    backup_job("zeitplan", werte)
    sitzungen_aufraeumen_job("zeitplan")


def starten(werte: Einstellungen) -> BackgroundScheduler | None:
    """Zeitplan starten. Gibt ``None`` zurück, wenn keine Jobs eingerichtet sind."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    if werte.pfade.backup is None:
        log.warning(
            "Kein Backup-Ziel eingerichtet – der nächtliche Zeitplan wird nicht gestartet. "
            "Nächster Schritt: in config.toml unter [pfade] backup setzen."
        )
        return None

    # Zeitplan in Ortszeit: „01:30" soll auch nach der Zeitumstellung 01:30 Uhr im Büro bedeuten.
    ausloeser = CronTrigger(
        hour=werte.jobs.backup_stunde,
        minute=werte.jobs.backup_minute,
        timezone=ORTSZEIT,
    )
    scheduler = BackgroundScheduler(timezone=ORTSZEIT)
    scheduler.add_job(
        _naechtlicher_lauf,
        trigger=ausloeser,
        args=[werte],
        id="naechtlicher_lauf",
        name="Nächtliche Sicherung",
        # Verpasste Läufe (Rechner war aus) einmal nachholen, aber nicht stapeln.
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info(
        "Zeitplan gestartet: nächtliche Sicherung um %s Ortszeit, %d Generationen",
        werte.jobs.backup_uhrzeit,
        werte.jobs.backup_generationen,
    )
    _auf_mehrere_prozesse_pruefen()
    return scheduler


def beenden() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("Zeitplan beendet")


def _auf_mehrere_prozesse_pruefen() -> None:
    """Warnen, wenn Uvicorn mit mehreren Arbeitsprozessen läuft.

    Nur ein Hinweis, keine Sperre: die Anwendung soll auch dann starten, wenn jemand die
    Startparameter verändert hat. Aber im Protokoll muss stehen, warum plötzlich mehrere
    Sicherungen je Nacht entstehen.
    """
    arbeiter = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
    if arbeiter and arbeiter.isdigit() and int(arbeiter) > 1:
        log.warning(
            "Es sind %s Arbeitsprozesse eingestellt. Der Leitstand ist für genau einen "
            "gedacht – sonst laufen die nächtlichen Jobs mehrfach (doppelte Sicherungen, "
            "später doppelte Importe). Nächster Schritt: den Dienst mit einem Prozess starten.",
            arbeiter,
        )


def zustand() -> dict[str, object]:
    """Auskunft über den Zeitplan – für den Systemstatus."""
    if _scheduler is None:
        return {"laeuft": False, "naechster_lauf": None}
    job = _scheduler.get_job("naechtlicher_lauf")
    return {
        "laeuft": _scheduler.running,
        "naechster_lauf": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }
