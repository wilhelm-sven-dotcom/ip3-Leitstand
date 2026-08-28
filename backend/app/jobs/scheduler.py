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
from app.jobs.importe import datev_job, kalkulation_job, timetac_job
from app.konfiguration import Einstellungen
from app.protokoll import logger
from app.zeit import ORTSZEIT

log = logger(__name__)

_scheduler: BackgroundScheduler | None = None


def _naechtlicher_lauf(werte: Einstellungen) -> None:
    """Alles, was nachts passiert – in einer Funktion, damit die Reihenfolge feststeht.

    Erst sichern, dann einlesen: geht beim Import etwas schief, liegt die Sicherung des
    vorigen Standes bereits daneben. Jeder Lauf prüft seine eigene Voraussetzung und
    protokolliert eine Warnung, wenn sie fehlt – keiner wirft.
    """
    backup_job("zeitplan", werte)
    sitzungen_aufraeumen_job("zeitplan")
    kalkulation_job("zeitplan", werte)
    datev_job("zeitplan", werte)
    # TimeTac zuletzt: der Lauf hängt am Netz und dauert am längsten.
    timetac_job("zeitplan", werte)


def starten(werte: Einstellungen) -> BackgroundScheduler | None:
    """Zeitplan starten.

    Der Plan startet, sobald **ein** Lauf etwas zu tun hat. Bis Phase 3 hing das allein am
    Backup-Ziel; seit die Importe dazugekommen sind, wäre das falsch: ein Haus ohne
    Backup-Ordner soll trotzdem nachts seine Stunden holen. Jeder Lauf prüft seine eigene
    Voraussetzung und meldet sie im Systemstatus, wenn sie fehlt.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    fehlend = _fehlende_voraussetzungen(werte)
    if len(fehlend) == len(_VORAUSSETZUNGEN):
        log.warning(
            "Kein Hintergrundlauf ist eingerichtet – der nächtliche Zeitplan wird nicht "
            "gestartet. Nächster Schritt: in config.toml unter [pfade] mindestens backup, "
            "datev oder kalkulation setzen, oder in der .env die TimeTac-Zugangsdaten."
        )
        return None
    for hinweis in fehlend:
        log.warning("Nächtlicher Lauf ohne Voraussetzung: %s", hinweis)

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


# Was ein Lauf braucht, um überhaupt etwas tun zu können. Der Zeitplan startet, sobald eine
# dieser Voraussetzungen erfüllt ist.
_VORAUSSETZUNGEN = ("Datensicherung", "DATEV-Import", "Kalkulationsblätter", "TimeTac-Stunden")


def _fehlende_voraussetzungen(werte: Einstellungen) -> list[str]:
    """Läufe, die mangels Einrichtung nichts tun können – als lesbare Hinweise."""
    fehlend = []
    if werte.pfade.backup is None:
        fehlend.append("Datensicherung: [pfade] backup ist nicht gesetzt")
    if werte.pfade.datev is None:
        fehlend.append("DATEV-Import: [pfade] datev ist nicht gesetzt")
    if werte.pfade.kalkulation is None:
        fehlend.append("Kalkulationsblätter: [pfade] kalkulation ist nicht gesetzt")
    if not (werte.timetac.aktiv and werte.timetac_client_id and werte.timetac_konto):
        fehlend.append("TimeTac-Stunden: Zugangsdaten fehlen in der .env")
    return fehlend


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
