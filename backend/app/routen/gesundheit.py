"""Gesundheitsprüfung – die eine Route ohne Anmeldung.

Wird von Caddy, vom Dienstverwalter und beim Update nach dem Neustart abgefragt. Sie verrät
absichtlich nichts über Daten oder Konfiguration, sondern nur, ob die Anwendung antwortet und ob
die Datenbank erreichbar ist.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.datenbank import engine
from app.protokoll import logger

log = logger(__name__)

router = APIRouter(prefix="/api", tags=["System"])


class Gesundheit(BaseModel):
    status: str
    version: str
    datenbank: str


@router.get(
    "/gesundheit",
    operation_id="gesundheit_abrufen",
    summary="Antwortet, solange die Anwendung läuft",
    response_model=Gesundheit,
)
def gesundheit_abrufen() -> Gesundheit:
    datenbank = "erreichbar"
    try:
        with engine().connect() as verbindung:
            verbindung.execute(text("SELECT 1"))
    except Exception as fehler:
        log.warning("Gesundheitsprüfung: Datenbank nicht erreichbar (%s)", fehler)
        datenbank = "nicht erreichbar"
    return Gesundheit(
        status="bereit" if datenbank == "erreichbar" else "eingeschraenkt",
        version=__version__,
        datenbank=datenbank,
    )
