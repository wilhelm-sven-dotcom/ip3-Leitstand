"""Anmelden, Abmelden, Passwort ändern (PLAN §2).

Ein Grundsatz durchzieht die Anmeldung: **keine Auskunft darüber, was falsch war.** Ob die
E-Mail-Adresse unbekannt ist, das Passwort nicht stimmt oder das Konto deaktiviert wurde – der
Nutzer sieht immer denselben Satz. Sonst ließe sich über die Anmeldemaske herausfinden, welche
Kennungen es gibt.

Auch der Zeitaufwand darf nichts verraten: bei einer unbekannten Kennung wird trotzdem ein
Passwortvergleich durchgeführt, damit die Antwort nicht messbar schneller kommt.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app import audit
from app.fehler import FachFehler, NichtAngemeldet, ZuVieleVersuche
from app.konfiguration import Einstellungen
from app.protokoll import logger
from app.sicherheit import passwort as pw
from app.sicherheit import sitzungen, sperre
from app.sicherheit.abhaengigkeiten import (
    Zugriff,
    aktueller_zugriff,
    db_sitzung,
    konfiguration,
    nutzer_aus_kennung,
)
from app.zeit import jetzt_utc

log = logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Anmeldung"])

# Ein Hash, gegen den bei unbekannter Kennung geprüft wird, damit die Antwortzeit gleich bleibt.
# Wird beim ersten Bedarf erzeugt, nicht beim Import – sonst kostet jeder Programmstart 0,3 s.
_blindhash: str | None = None


def _blind_pruefen(passwort: str) -> None:
    global _blindhash
    if _blindhash is None:
        _blindhash = pw.hashen("nur-fuer-den-zeitausgleich")
    pw.passt(passwort, _blindhash)


class AnmeldeDaten(BaseModel):
    """Anmeldedaten.

    Die Kennung wird bewusst nur oberflächlich geprüft (enthält ein @, hat Vor- und Nachteil) und
    nicht gegen die vollständigen Regeln für E-Mail-Adressen. Eine strenge Prüfung bräuchte ein
    weiteres Paket und würde in Grenzfällen gültige Firmenadressen abweisen; ob die Kennung
    stimmt, entscheidet ohnehin der Abgleich mit der Nutzertabelle.
    """

    email: str = Field(min_length=3, max_length=200)
    passwort: str = Field(min_length=1, max_length=200)
    angemeldet_bleiben: bool = False

    @field_validator("email")
    @classmethod
    def kennung_pruefen(cls, wert: str) -> str:
        bereinigt = wert.strip().lower()
        vorne, trenner, hinten = bereinigt.partition("@")
        if not (trenner and vorne and hinten):
            raise ValueError("Bitte die vollständige E-Mail-Adresse eingeben.")
        return bereinigt


class PasswortDaten(BaseModel):
    altes_passwort: str = Field(min_length=1, max_length=200)
    neues_passwort: str = Field(min_length=1, max_length=200)


class AngemeldeterNutzer(BaseModel):
    """Was die Oberfläche über den angemeldeten Nutzer wissen muss."""

    id: int
    name: str
    email: str
    rollen: list[str]
    rechte: dict[str, str]
    muss_passwort_wechseln: bool
    csrf_token: str
    sitzung_laeuft_ab: datetime


class Abmeldung(BaseModel):
    abgemeldet: bool = True


def _als_antwort(zugriff_nutzer, sitzung) -> AngemeldeterNutzer:
    return AngemeldeterNutzer(
        id=zugriff_nutzer.id,
        name=zugriff_nutzer.name,
        email=zugriff_nutzer.email,
        rollen=[rolle.name for rolle in zugriff_nutzer.rollen],
        rechte=zugriff_nutzer.berechtigungsschluessel(),
        muss_passwort_wechseln=zugriff_nutzer.muss_passwort_wechseln,
        csrf_token=sitzung.csrf_token,
        sitzung_laeuft_ab=sitzung.laeuft_ab,
    )


ANMELDUNG_FEHLGESCHLAGEN = "E-Mail-Adresse oder Passwort stimmt nicht."
ANMELDUNG_NAECHSTER_SCHRITT = (
    "Bitte prüfen Sie die Schreibweise. Nach mehreren Fehlversuchen wird die Kennung "
    "zeitweise gesperrt."
)


class AnmeldungFehlgeschlagen(FachFehler):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "anmeldung_fehlgeschlagen"

    def __init__(self) -> None:
        super().__init__(ANMELDUNG_FEHLGESCHLAGEN, ANMELDUNG_NAECHSTER_SCHRITT)


@router.post(
    "/anmelden",
    operation_id="anmelden",
    summary="Mit E-Mail und Passwort anmelden",
    response_model=AngemeldeterNutzer,
    responses={
        401: {"description": "E-Mail oder Passwort stimmt nicht"},
        429: {"description": "Kennung ist nach mehreren Fehlversuchen zeitweise gesperrt"},
    },
)
def anmelden(
    daten: AnmeldeDaten,
    anfrage: Request,
    antwort: Response,
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> AngemeldeterNutzer:
    kennung = str(daten.email).strip().lower()
    absender = anfrage.client.host if anfrage.client else None

    zustand = sperre.zustand(
        db, kennung, absender, werte.anmeldung.max_fehlversuche, werte.anmeldung.sperre_minuten
    )
    if zustand.gesperrt:
        # Auch bei richtigem Passwort: die Sperre wäre sonst eine Auskunft darüber, welches
        # Passwort stimmt.
        audit.eintragen(
            db,
            "anmeldung.gesperrt",
            nutzer=kennung,
            ip=absender,
            neu={"fehlversuche": zustand.fehlversuche},
        )
        db.commit()
        log.warning("Anmeldung gesperrt: %s von %s", kennung, absender)
        raise ZuVieleVersuche(zustand.meldung(), zustand.naechster_schritt())

    nutzer = nutzer_aus_kennung(db, kennung)
    if nutzer is None or not nutzer.aktiv:
        # Auch ohne Nutzer einen Vergleich durchführen, damit die Antwortzeit nichts verrät.
        _blind_pruefen(daten.passwort)
        audit.eintragen(db, sperre.AKTION_FEHLVERSUCH, nutzer=kennung, ip=absender)
        db.commit()
        raise AnmeldungFehlgeschlagen()

    if not pw.passt(daten.passwort, nutzer.pw_hash):
        audit.eintragen(db, sperre.AKTION_FEHLVERSUCH, nutzer=kennung, ip=absender)
        db.commit()
        raise AnmeldungFehlgeschlagen()

    sitzung, token = sitzungen.anlegen(
        db,
        nutzer,
        werte.sitzung,
        angemeldet_bleiben=daten.angemeldet_bleiben,
        ip=absender,
        browser=anfrage.headers.get("user-agent"),
    )
    nutzer.letzte_anmeldung = jetzt_utc()
    audit.eintragen(
        db,
        sperre.AKTION_ERFOLG,
        nutzer=nutzer,
        ip=absender,
        neu={"angemeldet_bleiben": daten.angemeldet_bleiben},
    )
    db.commit()

    antwort.set_cookie(
        value=token, **sitzungen.cookie_einstellungen(werte.sitzung, daten.angemeldet_bleiben)
    )
    log.info("Anmeldung: %s", nutzer.email)
    return _als_antwort(nutzer, sitzung)


@router.post(
    "/abmelden",
    operation_id="abmelden",
    summary="Aktuelle Sitzung beenden",
    response_model=Abmeldung,
)
def abmelden(
    anfrage: Request,
    antwort: Response,
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> Abmeldung:
    """Abmelden.

    Ohne Berechtigungsprüfung und ohne CSRF-Token: Abmelden ist immer erlaubt und darf auch mit
    einer bereits ungültigen Sitzung nicht fehlschlagen – sonst bleibt ein Cookie im Browser, das
    niemand mehr loswird.
    """
    token = anfrage.cookies.get(sitzungen.COOKIE_NAME, "")
    sitzung = sitzungen.finden(db, token)
    if sitzung is not None:
        sitzungen.beenden(sitzung)
        audit.eintragen(
            db,
            "anmeldung.abmeldung",
            nutzer=sitzung.nutzer,
            ip=anfrage.client.host if anfrage.client else None,
        )
        db.commit()
    antwort.delete_cookie(
        sitzungen.COOKIE_NAME, path="/", secure=werte.sitzung.cookie_secure, httponly=True
    )
    return Abmeldung()


@router.get(
    "/ich",
    operation_id="angemeldeten_nutzer_abrufen",
    summary="Angemeldeten Nutzer samt Berechtigungen abrufen",
    response_model=AngemeldeterNutzer,
    responses={401: {"description": "Nicht angemeldet oder Sitzung abgelaufen"}},
)
def ich(zugriff: Zugriff = Depends(aktueller_zugriff)) -> AngemeldeterNutzer:
    """Der erste Aufruf der Oberfläche nach dem Laden.

    Absichtlich ohne Passwortwechselpflicht: die Oberfläche muss erfahren, dass ein Wechsel
    aussteht, um zur Passwortmaske führen zu können.
    """
    return _als_antwort(zugriff.nutzer, zugriff.sitzung)


@router.post(
    "/passwort-aendern",
    operation_id="passwort_aendern",
    summary="Eigenes Passwort ändern",
    response_model=AngemeldeterNutzer,
    responses={
        401: {"description": "Nicht angemeldet"},
        403: {"description": "Das alte Passwort stimmt nicht"},
        422: {"description": "Das neue Passwort erfüllt die Anforderungen nicht"},
    },
)
def passwort_aendern(
    daten: PasswortDaten,
    anfrage: Request,
    zugriff: Zugriff = Depends(aktueller_zugriff),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> AngemeldeterNutzer:
    """Passwort ändern.

    Beendet alle anderen Sitzungen des Nutzers: wer das alte Passwort kannte, soll nicht über eine
    offene Sitzung weiterarbeiten können. Die aufrufende Sitzung bleibt bestehen.
    """
    nutzer = zugriff.nutzer
    absender = anfrage.client.host if anfrage.client else None

    if not pw.passt(daten.altes_passwort, nutzer.pw_hash):
        # Als Fehlversuch zählen: sonst wäre diese Route ein Weg, Passwörter durchzuprobieren.
        audit.eintragen(db, sperre.AKTION_FEHLVERSUCH, nutzer=nutzer.email, ip=absender)
        db.commit()
        raise FachFehler(
            "Das bisherige Passwort stimmt nicht.",
            "Bitte erneut versuchen. Wenn Sie es nicht mehr wissen, kann die Geschäftsführung "
            "es zurücksetzen.",
            code="altes_passwort_falsch",
            status_code=status.HTTP_403_FORBIDDEN,
            felder={"altes_passwort": "Stimmt nicht."},
        )

    pw.pruefe_laenge(daten.neues_passwort, werte.anmeldung.passwort_mindestlaenge)
    if daten.neues_passwort == daten.altes_passwort:
        raise FachFehler(
            "Das neue Passwort ist mit dem bisherigen identisch.",
            "Bitte ein anderes Passwort wählen.",
            code="passwort_unveraendert",
            status_code=422,
            felder={"neues_passwort": "Muss sich vom bisherigen unterscheiden."},
        )

    nutzer.pw_hash = pw.hashen(daten.neues_passwort)
    nutzer.muss_passwort_wechseln = False
    beendete = sitzungen.alle_beenden(db, nutzer.id, ausser=zugriff.sitzung.id)
    audit.eintragen(
        db,
        "passwort.geaendert",
        nutzer=nutzer,
        tabelle="users",
        datensatz_id=nutzer.id,
        ip=absender,
        neu={"andere_sitzungen_beendet": beendete},
    )
    db.commit()
    log.info("Passwort geändert: %s (%d andere Sitzungen beendet)", nutzer.email, beendete)
    return _als_antwort(nutzer, zugriff.sitzung)


@router.get(
    "/csrf",
    operation_id="csrf_token_abrufen",
    summary="Sicherheitsschlüssel der Sitzung abrufen",
    response_model=dict[str, str],
    responses={401: {"description": "Nicht angemeldet"}},
)
def csrf_token(zugriff: Zugriff = Depends(aktueller_zugriff)) -> dict[str, str]:
    """Token nachladen, falls die Oberfläche es verloren hat (nach einem Neuladen der Seite)."""
    if zugriff.sitzung is None:
        raise NichtAngemeldet()
    return {"csrf_token": zugriff.sitzung.csrf_token}
