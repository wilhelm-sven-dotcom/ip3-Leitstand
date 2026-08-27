"""Änderungsprotokoll (PLAN §5: „Jede schreibende Aktion landet im audit_log").

Der Filter ist der wichtigste Teil dieses Moduls. Ohne ihn landen Passwörter und Sitzungsschlüssel
im Protokoll – und das Protokoll geht jede Nacht als Teil der Datenbank in den OneDrive-Ordner.
Deshalb werden verdächtige Feldnamen ersetzt, statt sich darauf zu verlassen, dass jeder Aufrufer
daran denkt.

Einträge werden nur geschrieben. Es gibt in der Anwendung keinen Weg, einen Eintrag zu ändern oder
zu löschen; ein Test prüft das.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modelle.system import AuditEintrag, User
from app.zeit import jetzt_utc

# Feldnamen, deren Werte nie im Protokoll stehen. Geprüft wird auf Teilstrings in Kleinschreibung,
# damit auch 'pw_hash', 'neues_passwort' oder 'csrf_token' erfasst werden.
GEHEIME_FELDER = (
    "passwort",
    "password",
    "pw_hash",
    "hash",
    "token",
    "secret",
    "schluessel",
    "geheim",
)

ERSATZTEXT = "(nicht protokolliert)"


def _feld_ist_geheim(name: str) -> bool:
    klein = name.lower()
    return any(kennzeichen in klein for kennzeichen in GEHEIME_FELDER)


def filtern(daten: dict[str, Any] | None) -> dict[str, Any] | None:
    """Geheime Felder ersetzen, verschachtelte Strukturen eingeschlossen."""
    if daten is None:
        return None
    ergebnis: dict[str, Any] = {}
    for name, wert in daten.items():
        if _feld_ist_geheim(name):
            ergebnis[name] = ERSATZTEXT
        elif isinstance(wert, dict):
            ergebnis[name] = filtern(wert)
        elif isinstance(wert, list):
            ergebnis[name] = [filtern(e) if isinstance(e, dict) else e for e in wert]
        else:
            ergebnis[name] = wert
    return ergebnis


def eintragen(
    sitzung: Session,
    aktion: str,
    *,
    nutzer: User | str | None = None,
    tabelle: str | None = None,
    datensatz_id: int | None = None,
    alt: dict[str, Any] | None = None,
    neu: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEintrag:
    """Einen Protokolleintrag anlegen.

    Läuft in der Transaktion des Aufrufers: scheitert die fachliche Änderung, verschwindet auch
    der Protokolleintrag. Ein Eintrag über eine Änderung, die nie passiert ist, wäre schlimmer
    als kein Eintrag.

    ``aktion`` ist ein kurzer Bezeichner wie ``anmeldung.erfolg`` oder ``projekt.geaendert``.
    """
    if isinstance(nutzer, User):
        name = nutzer.email
        nutzer_id = nutzer.id
    else:
        name = nutzer
        nutzer_id = None

    eintrag = AuditEintrag(
        ts=jetzt_utc(),
        user=name,
        user_id=nutzer_id,
        aktion=aktion,
        tabelle=tabelle,
        datensatz_id=datensatz_id,
        alt=filtern(alt),
        neu=filtern(neu),
        ip=ip,
    )
    sitzung.add(eintrag)
    return eintrag
