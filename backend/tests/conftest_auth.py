"""Hilfsmittel für die Anmelde- und Berechtigungstests.

Als eigenes Modul, damit conftest.py schlank bleibt; wird dort importiert.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelle import Rolle, User
from app.sicherheit import passwort as pw
from app.sicherheit.csrf import KOPFZEILE

TEST_PASSWORT = "Sonnenstrom-2026!"


@dataclass
class Anmeldung:
    """Ergebnis einer Anmeldung im Test: Client mit Cookie und passendem CSRF-Token."""

    client: TestClient
    nutzer: dict
    csrf_token: str

    def schreiben(self, methode: str, pfad: str, **kwargs) -> object:
        """Schreibende Anfrage mit CSRF-Token."""
        kopf = {KOPFZEILE: self.csrf_token, **kwargs.pop("headers", {})}
        return self.client.request(methode, pfad, headers=kopf, **kwargs)


def nutzer_anlegen(
    db: Session,
    email: str,
    rollenname: str,
    *,
    name: str | None = None,
    passwort: str = TEST_PASSWORT,
    aktiv: bool = True,
    muss_wechseln: bool = False,
) -> User:
    """Nutzer mit einer bestehenden Rolle anlegen."""
    rolle = db.scalar(select(Rolle).where(Rolle.name == rollenname))
    assert rolle is not None, f"Rolle {rollenname} fehlt – wurde der Seed ausgeführt?"
    nutzer = User(
        name=name or email.split("@")[0],
        email=email,
        pw_hash=pw.hashen(passwort),
        aktiv=aktiv,
        muss_passwort_wechseln=muss_wechseln,
    )
    nutzer.rollen.append(rolle)
    db.add(nutzer)
    db.flush()
    return nutzer


def anmelden(
    client: TestClient, email: str, passwort: str = TEST_PASSWORT, angemeldet_bleiben: bool = False
) -> Anmeldung:
    """Anmelden und den Client mit gültigem Cookie zurückgeben."""
    antwort = client.post(
        "/api/auth/anmelden",
        json={"email": email, "passwort": passwort, "angemeldet_bleiben": angemeldet_bleiben},
    )
    assert antwort.status_code == 200, antwort.text
    koerper = antwort.json()
    return Anmeldung(client=client, nutzer=koerper, csrf_token=koerper["csrf_token"])
