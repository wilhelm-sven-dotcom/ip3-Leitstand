"""Protokollierung mit Rotation in ``logs/`` (PLAN §2).

Absichtlich schlicht: eine Textzeile je Ereignis mit Zeitstempel in UTC, Stufe, Logger und
Meldung. Fachliche Ereignisse (Anmeldung, Importe, Jobs) landen zusätzlich in der Datenbank,
damit die Startseite den Datenstand zeigen kann – Logdateien liest im Alltag niemand.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
ZEITFORMAT = "%Y-%m-%dT%H:%M:%S%z"

_eingerichtet = False


def einrichten(
    verzeichnis: Path | None,
    stufe: str = "INFO",
    datei_max_mb: int = 10,
    generationen: int = 10,
) -> None:
    """Protokollierung einrichten. Mehrfachaufruf ist unschädlich."""
    global _eingerichtet
    if _eingerichtet:
        return

    wurzel = logging.getLogger()
    wurzel.setLevel(getattr(logging, stufe.upper(), logging.INFO))
    formatierer = logging.Formatter(FORMAT, datefmt=ZEITFORMAT)

    # Immer auf die Konsole: im Dienstbetrieb fängt der Dienstverwalter das ein.
    konsole = logging.StreamHandler(sys.stderr)
    konsole.setFormatter(formatierer)
    wurzel.addHandler(konsole)

    if verzeichnis is not None:
        try:
            verzeichnis.mkdir(parents=True, exist_ok=True)
            # delay=True: die Datei wird erst beim ersten Schreiben geöffnet. Auf Windows scheitert
            # das Rollen sonst, wenn jemand die Datei offen hält.
            datei = logging.handlers.RotatingFileHandler(
                verzeichnis / "leitstand.log",
                maxBytes=datei_max_mb * 1024 * 1024,
                backupCount=generationen,
                encoding="utf-8",
                delay=True,
            )
            datei.setFormatter(formatierer)
            wurzel.addHandler(datei)
        except OSError as fehler:
            # Ohne Protokolldatei läuft der Leitstand weiter – nur eben ohne Nachlese.
            wurzel.warning(
                "Protokollverzeichnis %s ist nicht beschreibbar (%s). "
                "Es wird nur auf die Konsole protokolliert. "
                "Nächster Schritt: Rechte des Dienstkontos auf dieses Verzeichnis prüfen.",
                verzeichnis,
                fehler,
            )

    # Uvicorn bringt eigene Handler mit; die Meldungen sollen durch unsere laufen.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    _eingerichtet = True


def zuruecksetzen() -> None:
    """Nur für Tests: Handler abräumen, damit die nächste Einrichtung greift."""
    global _eingerichtet
    wurzel = logging.getLogger()
    for handler in list(wurzel.handlers):
        wurzel.removeHandler(handler)
        handler.close()
    _eingerichtet = False


def logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
