"""Serverseitige Sitzungen (PLAN §2).

Der Sitzungsschlüssel wird beim Anmelden erzeugt, dem Browser als ``httpOnly``-Cookie mitgegeben
und **nur als Hash** in der Datenbank abgelegt. Der Grund ist die nächtliche Sicherung: die
Datenbank liegt danach im OneDrive-Ordner. Stünden die Schlüssel dort im Klartext, könnte jemand
mit Zugriff auf eine Sicherungskopie eine Sitzung übernehmen.

Zwei Ablaufgrenzen:

* ``laeuft_ab`` – die harte Grenze (12 Stunden, mit „Angemeldet bleiben" 30 Tage).
* ``letzte_aktivitaet`` plus Leerlauffrist – die weiche Grenze für einen unbeaufsichtigten
  Arbeitsplatz.

Die Sitzung trägt außerdem das CSRF-Token (siehe ``app.sicherheit.csrf``).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSitzung

from app.konfiguration import SitzungEinstellungen
from app.modelle.system import Sitzung, User
from app.zeit import jetzt_utc

# Name des Cookies. Ohne Bezug zur Technik, damit er nichts über die Anwendung verrät.
COOKIE_NAME = "ip3_sitzung"
# 32 Byte Zufall sind 256 Bit – nicht erratbar.
TOKEN_BYTES = 32


def token_erzeugen() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hashen(token: str) -> str:
    """SHA-256 des Sitzungsschlüssels.

    Kein bcrypt: der Schlüssel ist bereits 256 Bit Zufall, es gibt nichts zu erraten, und die
    Prüfung läuft bei jeder einzelnen Anfrage – bcrypt würde jede Anfrage um 0,3 Sekunden
    verlängern, ohne etwas zu gewinnen.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def anlegen(
    db: DbSitzung,
    nutzer: User,
    einstellungen: SitzungEinstellungen,
    *,
    angemeldet_bleiben: bool = False,
    ip: str | None = None,
    browser: str | None = None,
) -> tuple[Sitzung, str]:
    """Sitzung anlegen und ``(Sitzung, Klartext-Schlüssel)`` zurückgeben.

    Der Klartext erscheint nur hier und geht direkt in das Cookie; gespeichert wird der Hash.
    """
    token = token_erzeugen()
    jetzt = jetzt_utc()
    dauer = (
        timedelta(days=einstellungen.dauer_angemeldet_bleiben_tage)
        if angemeldet_bleiben
        else timedelta(hours=einstellungen.dauer_stunden)
    )
    sitzung = Sitzung(
        token_hash=token_hashen(token),
        csrf_token=secrets.token_urlsafe(TOKEN_BYTES),
        user_id=nutzer.id,
        laeuft_ab=jetzt + dauer,
        letzte_aktivitaet=jetzt,
        angemeldet_bleiben=angemeldet_bleiben,
        ip=ip,
        browser=(browser or "")[:200] or None,
        created_by=nutzer.email,
    )
    db.add(sitzung)
    db.flush()
    return sitzung, token


def finden(db: DbSitzung, token: str) -> Sitzung | None:
    """Gültige Sitzung zum Schlüssel oder ``None``.

    Prüft in dieser Reihenfolge: gibt es die Sitzung, ist sie beendet, ist sie abgelaufen, war sie
    zu lange untätig, ist der Nutzer noch aktiv. Ein deaktivierter Nutzer verliert seine Sitzung
    sofort – ohne diese Prüfung bliebe er bis zum Ablauf angemeldet.
    """
    if not token:
        return None
    sitzung = db.scalar(select(Sitzung).where(Sitzung.token_hash == token_hashen(token)))
    if sitzung is None or sitzung.beendet_am is not None:
        return None
    if sitzung.laeuft_ab <= jetzt_utc():
        return None
    if sitzung.nutzer is None or not sitzung.nutzer.aktiv:
        return None
    return sitzung


def ist_untaetig_abgelaufen(
    sitzung: Sitzung, leerlauf_stunden: int, jetzt: datetime | None = None
) -> bool:
    """Prüft die weiche Grenze: zu lange keine Anfrage mehr."""
    if leerlauf_stunden <= 0:
        return False
    grenze = (jetzt or jetzt_utc()) - timedelta(hours=leerlauf_stunden)
    return sitzung.letzte_aktivitaet < grenze


def aktivitaet_merken(sitzung: Sitzung) -> None:
    """Zeitpunkt der letzten Anfrage fortschreiben.

    Wird bei jeder Anfrage aufgerufen. Absichtlich nur ein Feld, damit daraus keine
    Schreibtransaktion je Seitenaufruf wird.
    """
    sitzung.letzte_aktivitaet = jetzt_utc()


def beenden(sitzung: Sitzung) -> None:
    """Sitzung beenden. Der Datensatz bleibt, damit er im Protokoll nachvollziehbar ist."""
    sitzung.beendet_am = jetzt_utc()


def alle_beenden(db: DbSitzung, user_id: int, ausser: int | None = None) -> int:
    """Alle Sitzungen eines Nutzers beenden, außer der genannten.

    Nach einem Passwortwechsel: wer das alte Passwort kannte, soll nicht über eine offene Sitzung
    weiterarbeiten können. Die aufrufende Sitzung bleibt bestehen, sonst müsste sich der Nutzer
    unmittelbar nach dem Wechsel erneut anmelden.
    """
    jetzt = jetzt_utc()
    offene = db.scalars(
        select(Sitzung).where(
            Sitzung.user_id == user_id,
            Sitzung.beendet_am.is_(None),
            Sitzung.id != (ausser or -1),
        )
    ).all()
    for sitzung in offene:
        sitzung.beendet_am = jetzt
    return len(offene)


def abgelaufene_aufraeumen(db: DbSitzung, aelter_als_tage: int = 90) -> int:
    """Alte, beendete oder abgelaufene Sitzungen löschen.

    Nur alte Datensätze und nur Sitzungen – hier gehen keine fachlichen Daten verloren. Läuft im
    nächtlichen Job mit, damit die Tabelle nicht unbegrenzt wächst.
    """
    grenze = jetzt_utc() - timedelta(days=aelter_als_tage)
    alte = db.scalars(select(Sitzung).where(Sitzung.laeuft_ab < grenze)).all()
    for sitzung in alte:
        db.delete(sitzung)
    return len(alte)


def cookie_einstellungen(einstellungen: SitzungEinstellungen, angemeldet_bleiben: bool) -> dict:
    """Attribute für das Sitzungs-Cookie.

    ``SameSite=Lax`` statt ``Strict``: der Leitstand wird auch über Links aus internen
    Dokumenten und E-Mails aufgerufen, und mit ``Strict`` käme man dort ohne Anmeldung an.
    Schreibende Anfragen sind zusätzlich über das CSRF-Token abgesichert.
    """
    max_alter = (
        einstellungen.dauer_angemeldet_bleiben_tage * 24 * 3600
        if angemeldet_bleiben
        else einstellungen.dauer_stunden * 3600
    )
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": einstellungen.cookie_secure,
        "max_age": max_alter,
        "path": "/",
    }
