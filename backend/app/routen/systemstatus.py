"""Systemstatus für die Startseite (PLAN §2, §7).

„Stille Job-Ausfälle darf es nicht geben." Diese Route ist die Umsetzung: sie zeigt für jeden
Hintergrundlauf, wann er zuletzt erfolgreich war und wie alt dieser Stand ist. Ein Job, der seit
drei Wochen nicht mehr läuft, fällt damit beim ersten Blick auf die Startseite auf – statt dann,
wenn jemand die Sicherung braucht.

Vier Zustände:

* ``ok`` – der letzte Lauf war erfolgreich und ist frisch genug.
* ``warnung`` – erfolgreich, aber zu alt; oder mit Einschränkung durchgelaufen.
* ``fehler`` – der letzte Lauf ist gescheitert.
* ``unbekannt`` – noch nie gelaufen, oder in dieser Phase noch nicht eingerichtet.

Das Alter wird auf dem Server gerechnet. Die Oberfläche soll nicht aus Zeitstempeln Differenzen
bilden müssen – dabei entstehen die Fehler, wenn die Uhr des Arbeitsplatzes abweicht.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.jobs import katalog
from app.jobs.backup import backup_job
from app.konfiguration import Einstellungen, pruefe_betriebsbereit
from app.modelle.system import JobLauf
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, konfiguration
from app.zeit import alter_in_stunden

log = logger(__name__)

router = APIRouter(prefix="/api/systemstatus", tags=["System"])


class JobStatus(BaseModel):
    schluessel: str
    bezeichnung: str
    beschreibung: str
    status: str
    # Für Menschen lesbarer Text, den die Oberfläche direkt anzeigen kann.
    text: str
    eingerichtet: bool
    ab_phase: int
    letzter_lauf: datetime | None = None
    letzter_erfolg: datetime | None = None
    alter_stunden: float | None = None
    meldung: str | None = None
    dauer_ms: int | None = None


class Systemstatus(BaseModel):
    """Der „Datenstand"-Block der Startseite."""

    gesamtstatus: str
    jobs: list[JobStatus]
    hinweise: list[str]
    zeitplan_laeuft: bool
    naechster_lauf: str | None = None


def _alter_als_text(stunden: float) -> str:
    """Alter in Worten. Deutsche Zahlenformate, keine Dezimalstellen im Alltag."""
    if stunden < 1:
        minuten = max(1, int(stunden * 60))
        return f"vor {minuten} Minute{'n' if minuten != 1 else ''}"
    if stunden < 24:
        gerundet = int(stunden)
        return f"vor {gerundet} Stunde{'n' if gerundet != 1 else ''}"
    tage = int(stunden / 24)
    return f"vor {tage} Tag{'en' if tage != 1 else ''}"


def _status_ermitteln(
    eintrag: katalog.JobDefinition,
    letzter: JobLauf | None,
    letzter_erfolg: JobLauf | None,
    max_alter_stunden: int,
) -> tuple[str, str]:
    """Status und Anzeigetext für einen Job."""
    if not katalog.ist_eingerichtet(eintrag):
        return "unbekannt", f"noch nicht eingerichtet (ab Phase {eintrag.ab_phase})"

    if letzter is None:
        return "unbekannt", "noch nie gelaufen"

    if letzter.status == "fehler":
        return "fehler", "letzter Lauf fehlgeschlagen"

    if letzter.status == "laeuft":
        return "ok", "läuft gerade"

    if letzter_erfolg is None:
        return "fehler", "bisher kein erfolgreicher Lauf"

    alter = alter_in_stunden(letzter_erfolg.gestartet)
    text = _alter_als_text(alter)
    if alter > max_alter_stunden:
        return "warnung", f"{text} – länger her als erwartet"
    if letzter.status == "warnung":
        return "warnung", text
    return "ok", text


def status_erheben(db: Session, werte: Einstellungen) -> Systemstatus:
    """Systemstatus zusammenstellen."""
    jobs: list[JobStatus] = []

    for eintrag in katalog.KATALOG:
        letzter = db.scalar(
            select(JobLauf)
            .where(JobLauf.job == eintrag.schluessel)
            .order_by(JobLauf.gestartet.desc())
            .limit(1)
        )
        letzter_erfolg = db.scalar(
            select(JobLauf)
            .where(
                JobLauf.job == eintrag.schluessel,
                JobLauf.status.in_(("erfolg", "warnung")),
            )
            .order_by(JobLauf.gestartet.desc())
            .limit(1)
        )
        # Für die Sicherung gilt die Grenze aus der Konfiguration, für die übrigen die aus dem
        # Katalog: der Sicherungszeitplan ist einstellbar, die Lieferrhythmen der Kanzlei nicht.
        grenze = (
            werte.jobs.backup_max_alter_stunden
            if eintrag.schluessel == "backup"
            else eintrag.max_alter_stunden
        )
        status, text = _status_ermitteln(eintrag, letzter, letzter_erfolg, grenze)

        jobs.append(
            JobStatus(
                schluessel=eintrag.schluessel,
                bezeichnung=eintrag.bezeichnung,
                beschreibung=eintrag.beschreibung,
                status=status,
                text=text,
                eingerichtet=katalog.ist_eingerichtet(eintrag),
                ab_phase=eintrag.ab_phase,
                letzter_lauf=letzter.gestartet if letzter else None,
                letzter_erfolg=letzter_erfolg.gestartet if letzter_erfolg else None,
                alter_stunden=(
                    round(alter_in_stunden(letzter_erfolg.gestartet), 1) if letzter_erfolg else None
                ),
                meldung=letzter.meldung if letzter else None,
                dauer_ms=letzter.dauer_ms if letzter else None,
            )
        )

    # Konfigurationshinweise gehören in denselben Block: ein fehlender Backup-Pfad ist der
    # häufigste Grund dafür, dass gar nichts läuft.
    hinweise = pruefe_betriebsbereit(werte)

    # Nur eingerichtete Jobs bestimmen den Gesamtstatus. Ein Job „ab Phase 4" darf die Startseite
    # nicht dauerhaft rot färben.
    relevante = [job.status for job in jobs if job.eingerichtet]
    if "fehler" in relevante:
        gesamt = "fehler"
    elif "warnung" in relevante or hinweise:
        gesamt = "warnung"
    elif "unbekannt" in relevante:
        gesamt = "unbekannt"
    else:
        gesamt = "ok"

    from app.jobs import scheduler

    zeitplan = scheduler.zustand()
    return Systemstatus(
        gesamtstatus=gesamt,
        jobs=jobs,
        hinweise=hinweise,
        zeitplan_laeuft=bool(zeitplan["laeuft"]),
        naechster_lauf=zeitplan["naechster_lauf"],  # type: ignore[arg-type]
    )


@router.get(
    "",
    operation_id="systemstatus_abrufen",
    summary="Datenstand und Hintergrundläufe abrufen",
    response_model=Systemstatus,
    responses={
        401: {"description": "Nicht angemeldet"},
        403: {"description": "Berechtigung systemstatus.lesen fehlt"},
    },
    dependencies=[Depends(benoetigt("systemstatus.lesen"))],
)
def systemstatus_abrufen(
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> Systemstatus:
    return status_erheben(db, werte)


class JobStartErgebnis(BaseModel):
    gestartet: bool
    job: str
    meldung: str


@router.post(
    "/jobs/{job}/starten",
    operation_id="job_starten",
    summary="Hintergrundlauf von Hand starten",
    response_model=JobStartErgebnis,
    responses={
        401: {"description": "Nicht angemeldet"},
        403: {"description": "Berechtigung admin.jobs fehlt"},
        404: {"description": "Unbekannter Job"},
        409: {"description": "Der Job ist in dieser Phase noch nicht eingerichtet"},
    },
)
def job_starten(
    job: str,
    zugriff: Zugriff = Depends(benoetigt("admin.jobs")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> JobStartErgebnis:
    """Einen Lauf sofort auslösen – für die Prüfung nach der Einrichtung und nach einer Störung."""
    from app.fehler import Konflikt, NichtGefunden

    try:
        eintrag = katalog.definition(job)
    except KeyError as fehler:
        raise NichtGefunden(
            f"Es gibt keinen Hintergrundlauf mit dem Namen '{job}'.",
            "Bekannte Läufe stehen im Systemstatus auf der Startseite.",
        ) from fehler

    if not katalog.ist_eingerichtet(eintrag):
        raise Konflikt(
            f"{eintrag.bezeichnung} ist in dieser Fassung noch nicht eingerichtet "
            f"(ab Phase {eintrag.ab_phase}).",
            "Dieser Lauf kommt mit einer späteren Erweiterung des Leitstands.",
            code="job_nicht_eingerichtet",
        )

    audit.eintragen(
        db, "job.manuell_gestartet", nutzer=zugriff.nutzer, ip=zugriff.ip, neu={"job": job}
    )
    db.commit()

    from app.jobs.dokumente import doku_scan_job
    from app.jobs.fristen import fristen_job
    from app.jobs.importe import datev_job, kalkulation_job, timetac_job

    laeufe = {
        "backup": backup_job,
        "datev_import": datev_job,
        "timetac_sync": timetac_job,
        "kalkulation_scan": kalkulation_job,
        "fristen": fristen_job,
        "doku_scan": doku_scan_job,
    }
    starten = laeufe.get(job)
    if starten is None:  # pragma: no cover – ein Job im Katalog ohne Funktion dahinter
        raise Konflikt(
            f"{eintrag.bezeichnung} lässt sich noch nicht von Hand starten.",
            "Dieser Lauf kommt mit einer späteren Erweiterung des Leitstands.",
            code="job_nicht_eingerichtet",
        )
    # Die Läufe werfen nicht: eine fehlende Voraussetzung wird zur Warnung im Protokoll.
    starten("manuell", werte)

    return JobStartErgebnis(
        gestartet=True,
        job=job,
        meldung=f"{eintrag.bezeichnung} wurde ausgeführt. Das Ergebnis steht im Systemstatus.",
    )
