"""Berechtigungsprüfung als FastAPI-Abhängigkeit (PLAN §4, §14).

**Die einzige Stelle, an der Berechtigungen durchgesetzt werden.** Das Frontend blendet
zusätzlich aus, ist aber nie die Sperre – wer die Adresse einer Route kennt, käme sonst daran
vorbei.

Verwendung::

    @router.get("/projekte", dependencies=[Depends(benoetigt("projekte.lesen"))])
    def projekte_liste(zugriff: Zugriff = Depends(aktueller_zugriff)) -> ...:
        abfrage = select(Projekt)
        abfrage = scope_filter(abfrage, zugriff, "projekte.lesen", Projekt.pl_user_id)

``benoetigt`` prüft die Berechtigung, ``scope_filter`` schränkt bei Scope ``eigene`` auf die
eigenen Datensätze ein. Beides ist nötig: die Berechtigung entscheidet, *ob* jemand die Liste
sieht, der Scope, *welche Zeilen* darin stehen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, Request, Response
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.datenbank import session_factory
from app.fehler import KeineBerechtigung, NichtAngemeldet
from app.konfiguration import Einstellungen, einstellungen
from app.modelle.system import Sitzung, User
from app.protokoll import logger
from app.sicherheit import csrf, sitzungen
from app.sicherheit.katalog import pruefe_bekannt

log = logger(__name__)


def db_sitzung() -> Iterator[Session]:
    """Datenbanksitzung je Anfrage."""
    sitzung = session_factory()()
    try:
        yield sitzung
    finally:
        sitzung.close()


def konfiguration(anfrage: Request) -> Einstellungen:
    """Konfiguration der laufenden Anwendung.

    Aus ``app.state``, nicht aus der globalen Funktion: :func:`app.main.anwendung_erzeugen` nimmt
    die Konfiguration als Argument, und dann muss die Anwendung mit genau dieser arbeiten. Sonst
    liefe eine mit abweichender Konfiguration erzeugte Instanz – die Testinstanz auf demselben
    Host, ein Test – gegen andere Werte als angegeben.
    """
    aus_zustand = getattr(anfrage.app.state, "einstellungen", None)
    if aus_zustand is not None:
        return aus_zustand
    return einstellungen()


@dataclass
class Zugriff:
    """Wer fragt, und was darf er.

    Wird von den Routen als Abhängigkeit angefordert und trägt alles, was für Prüfung,
    Einschränkung und Protokollierung gebraucht wird.
    """

    nutzer: User
    sitzung: Sitzung
    rechte: dict[str, str] = field(default_factory=dict)
    ip: str | None = None

    def darf(self, schluessel: str) -> bool:
        return schluessel in self.rechte

    def scope(self, schluessel: str) -> str:
        """``alle`` oder ``eigene``; ohne die Berechtigung ``eigene`` als engster Fall."""
        return self.rechte.get(schluessel, "eigene")

    def nur_eigene(self, schluessel: str) -> bool:
        """Ob nur eigene Datensätze sichtbar sind.

        Fehlt die Berechtigung ganz, gilt ebenfalls ``eigene``: Wer die Route erreicht, ohne das
        Recht zu haben – etwa weil eine Abfrage nach einem anderen Schlüssel einschränkt –, soll
        im Zweifel weniger sehen, nicht mehr. Zugelassen wird der Zugriff ohnehin nur über
        :func:`benoetigt`.
        """
        return self.scope(schluessel) == "eigene"

    @property
    def kennung(self) -> str:
        return self.nutzer.email


def _absenderadresse(anfrage: Request) -> str | None:
    """Adresse des Absenders.

    Uvicorn läuft mit ``proxy_headers``, deshalb steht hier die Adresse des Arbeitsplatzes und
    nicht die von Caddy. Ohne das wäre die IP-Drosselung wertlos, weil alle Anfragen von
    127.0.0.1 zu kommen scheinen.
    """
    if anfrage.client is not None:
        return anfrage.client.host
    return None


def aktueller_zugriff(
    anfrage: Request,
    antwort: Response,
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> Zugriff:
    """Angemeldeten Nutzer aus dem Sitzungs-Cookie ermitteln.

    Prüft zugleich das CSRF-Token bei schreibenden Anfragen: so kann keine Route die Prüfung
    vergessen, denn ohne diese Abhängigkeit gibt es keinen angemeldeten Nutzer.
    """
    token = anfrage.cookies.get(sitzungen.COOKIE_NAME, "")
    sitzung = sitzungen.finden(db, token)
    if sitzung is None:
        raise NichtAngemeldet()

    if sitzungen.ist_untaetig_abgelaufen(sitzung, werte.sitzung.leerlauf_stunden):
        sitzungen.beenden(sitzung)
        db.commit()
        antwort.delete_cookie(sitzungen.COOKIE_NAME, path="/")
        raise NichtAngemeldet(
            "Sie waren längere Zeit nicht aktiv und wurden abgemeldet.",
            "Bitte melden Sie sich erneut an.",
        )

    if csrf.braucht_pruefung(anfrage.method):
        csrf.pruefen(anfrage, sitzung.csrf_token, werte.app.erlaubte_herkunft)

    sitzungen.aktivitaet_merken(sitzung)
    db.commit()

    nutzer = sitzung.nutzer
    return Zugriff(
        nutzer=nutzer,
        sitzung=sitzung,
        rechte=nutzer.berechtigungsschluessel(),
        ip=_absenderadresse(anfrage),
    )


def zugriff_mit_passwortpflicht(
    zugriff: Zugriff = Depends(aktueller_zugriff),
) -> Zugriff:
    """Wie :func:`aktueller_zugriff`, sperrt aber Konten mit offenem Passwortwechsel.

    Wer sein Passwort wechseln muss, kommt nur an die Anmelderoutinen. Sonst wäre die Pflicht
    eine Empfehlung: ein Konto mit einem Passwort, das über die Kommandozeile gelaufen ist,
    könnte unbegrenzt weiterarbeiten.
    """
    if zugriff.nutzer.muss_passwort_wechseln:
        raise KeineBerechtigung(
            "Bevor Sie weiterarbeiten können, müssen Sie Ihr Passwort ändern.",
            "Die Anwendung führt Sie zur Passwortänderung.",
        )
    return zugriff


class Berechtigungspruefung:
    """Callable-Abhängigkeit, damit die geprüften Schlüssel auslesbar bleiben.

    Der Regressionstest in ``tests/test_rbac.py`` geht die registrierten Routen durch und
    verlangt für jede schreibende Route eine solche Prüfung. Mit einer Closure wäre der Schlüssel
    von außen nicht erkennbar.
    """

    def __init__(self, *schluessel: str) -> None:
        # Beim Aufbau der Anwendung prüfen, nicht bei der ersten Anfrage: ein Tippfehler würde
        # sonst erst auffallen, wenn jemand die Route benutzt.
        self.schluessel = tuple(pruefe_bekannt(s) for s in schluessel)

    def __call__(self, zugriff: Zugriff = Depends(zugriff_mit_passwortpflicht)) -> Zugriff:
        if not any(zugriff.darf(s) for s in self.schluessel):
            log.info(
                "Zugriff abgelehnt: %s ohne %s", zugriff.kennung, " oder ".join(self.schluessel)
            )
            raise KeineBerechtigung()
        return zugriff

    def __repr__(self) -> str:
        return f"benoetigt({', '.join(self.schluessel)})"


def benoetigt(*schluessel: str) -> Berechtigungspruefung:
    """Abhängigkeit, die mindestens eine der genannten Berechtigungen verlangt.

    Mehrere Schlüssel sind ein Oder: ``benoetigt('rechnungen.erstellen', 'rechnungen.lesen')``
    lässt beide durch. Für ein Und werden zwei Abhängigkeiten angehängt.
    """
    return Berechtigungspruefung(*schluessel)


def scope_filter(
    abfrage: Select[Any],
    zugriff: Zugriff,
    schluessel: str,
    zuordnungsspalte: Any,
) -> Select[Any]:
    """Abfrage auf die eigenen Datensätze einschränken, wenn der Scope ``eigene`` ist.

    ``zuordnungsspalte`` ist die Spalte, die den zuständigen Nutzer trägt – bei Projekten
    ``Projekt.pl_user_id``.
    """
    if zugriff.nur_eigene(schluessel):
        return abfrage.where(zuordnungsspalte == zugriff.nutzer.id)
    return abfrage


def nutzer_aus_kennung(db: Session, kennung: str) -> User | None:
    """Nutzer über die Anmeldekennung suchen, ohne Rücksicht auf Groß- und Kleinschreibung."""
    return db.scalar(select(User).where(User.email == kennung.strip().lower()))


# Für Routen, die nur die Anmeldung, aber keine besondere Berechtigung brauchen.
AngemeldeterZugriff: Callable[..., Zugriff] = zugriff_mit_passwortpflicht
