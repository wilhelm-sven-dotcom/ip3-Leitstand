"""OpenAPI-Spezifikation als Datei exportieren.

Aus dieser Datei erzeugt das Frontend seine TypeScript-Typen (``npm run api``). Damit können
Oberfläche und Schnittstelle nicht auseinanderlaufen: eine geänderte Route bricht die
Übersetzung des Frontends, statt erst im Betrieb aufzufallen (PLAN §2).

Die Datei liegt im Repo, weil sie zwei Aufgaben hat: sie ist Erzeugungsquelle für den Client
**und** der überprüfbare Stand der Schnittstelle. Ein Test vergleicht sie mit der laufenden
Anwendung und schlägt fehl, wenn sie veraltet ist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.konfiguration import Einstellungen
from app.main import anwendung_erzeugen


def spezifikation(werte: Einstellungen | None = None) -> dict[str, Any]:
    """OpenAPI-Spezifikation der Anwendung."""
    app = anwendung_erzeugen(werte, zeitplan_starten=False)
    return app.openapi()


def als_text(werte: Einstellungen | None = None) -> str:
    """Spezifikation als formatierter JSON-Text.

    ``sort_keys`` und feste Einrückung, damit zwei Läufe byteweise dasselbe ergeben – sonst
    erzeugt jeder Export einen Unterschied im Repo, und der Frische-Test wäre wertlos.
    """
    return json.dumps(spezifikation(werte), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def standardpfad() -> Path:
    return Path(__file__).resolve().parents[2] / "openapi.json"


def schreiben(ziel: Path | None = None, werte: Einstellungen | None = None) -> Path:
    pfad = ziel or standardpfad()
    pfad.write_text(als_text(werte), encoding="utf-8")
    return pfad


def ist_aktuell(werte: Einstellungen | None = None) -> bool:
    pfad = standardpfad()
    if not pfad.exists():
        return False
    return pfad.read_text(encoding="utf-8") == als_text(werte)
