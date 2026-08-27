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

# Kennzeichen an unseren Handlern. Damit lässt sich die Protokollierung neu einrichten, ohne
# fremde Handler (die von pytest oder von einem Dienstverwalter) anzufassen.
MERKMAL = "_ip3_leitstand"


def einrichten(
    verzeichnis: Path | None,
    stufe: str = "INFO",
    datei_max_mb: int = 10,
    generationen: int = 10,
) -> None:
    """Protokollierung einrichten.

    Bei mehrfachem Aufruf werden die eigenen Handler ersetzt, nicht ergänzt. Ein Schalter „schon
    eingerichtet" wäre bequemer, würde aber bedeuten: wer die Anwendung ein zweites Mal mit
    anderer Konfiguration erzeugt, protokolliert weiter ins alte Verzeichnis. Genau das ist in
    der Testsuite aufgefallen, wo jeder Test ein eigenes Verzeichnis hat.
    """
    wurzel = logging.getLogger()
    _eigene_handler_entfernen(wurzel)
    wurzel.setLevel(getattr(logging, stufe.upper(), logging.INFO))
    formatierer = logging.Formatter(FORMAT, datefmt=ZEITFORMAT)

    # Immer auf die Konsole: im Dienstbetrieb fängt der Dienstverwalter das ein.
    konsole = logging.StreamHandler(sys.stderr)
    konsole.setFormatter(formatierer)
    setattr(konsole, MERKMAL, True)
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
            setattr(datei, MERKMAL, True)
            wurzel.addHandler(datei)
            # Erste Zeile sofort schreiben, damit die Datei entsteht und ein fehlendes
            # Schreibrecht beim Start auffällt und nicht erst beim ersten Fehler.
            wurzel.info("Protokollierung eingerichtet: %s", verzeichnis / "leitstand.log")
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


def _eigene_handler_entfernen(wurzel: logging.Logger) -> None:
    """Nur die selbst gesetzten Handler abräumen.

    Fremde Handler bleiben stehen – in der Testsuite hängt dort die Aufzeichnung von pytest, und
    wer sie entfernt, nimmt den Tests die Möglichkeit, Meldungen zu prüfen.
    """
    for handler in list(wurzel.handlers):
        if getattr(handler, MERKMAL, False):
            wurzel.removeHandler(handler)
            handler.close()


def zuruecksetzen() -> None:
    """Eigene Handler abräumen – für Tests und vor einem Neuaufbau der Anwendung."""
    _eigene_handler_entfernen(logging.getLogger())


def logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
