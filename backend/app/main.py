"""Anwendung des ip³ Leitstands (FastAPI).

Ein Prozess liefert API und Oberfläche (PLAN §2). Die Anwendung wird über
:func:`anwendung_erzeugen` gebaut, damit Tests sie mit eigener Konfiguration erzeugen können.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.fehler import handler_registrieren
from app.konfiguration import Einstellungen, einstellungen, pruefe_betriebsbereit
from app.protokoll import einrichten as protokoll_einrichten
from app.protokoll import logger
from app.routen import auth, gesundheit

log = logger(__name__)

BESCHREIBUNG = """
Projekt- und Finanz-Cockpit der ip³ Energietechnik GmbH.

Alle Pfade liegen unter `/api`. Beträge sind ganze Cent, Zeitpunkte in UTC.
Fehlerantworten haben die Form `{code, meldung, naechster_schritt}`.
"""


@asynccontextmanager
async def _lebenszyklus(app: FastAPI) -> AsyncIterator[None]:
    werte: Einstellungen = app.state.einstellungen
    log.info("ip³ Leitstand %s startet (Umgebung: %s)", __version__, werte.app.umgebung)
    for hinweis in pruefe_betriebsbereit(werte):
        # Kein Abbruch: der Leitstand läuft, der Hinweis erscheint zusätzlich im Systemstatus.
        log.warning("Konfigurationshinweis: %s", hinweis)
    yield
    log.info("ip³ Leitstand wird beendet")


def anwendung_erzeugen(werte: Einstellungen | None = None) -> FastAPI:
    """Anwendung zusammensetzen."""
    konfiguration = werte or einstellungen()
    protokoll_einrichten(
        konfiguration.pfade.logs,
        stufe=konfiguration.protokoll.stufe,
        datei_max_mb=konfiguration.protokoll.datei_max_mb,
        generationen=konfiguration.protokoll.generationen,
    )

    app = FastAPI(
        title="ip³ Leitstand",
        description=BESCHREIBUNG,
        version=__version__,
        lifespan=_lebenszyklus,
        # Die interaktive Dokumentation hilft bei der Entwicklung und ist im Firmennetz
        # unbedenklich; sie zeigt nur die Schnittstelle, keine Daten.
        docs_url="/api/dokumentation",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.einstellungen = konfiguration

    handler_registrieren(app)
    app.include_router(gesundheit.router)
    app.include_router(auth.router)

    return app
