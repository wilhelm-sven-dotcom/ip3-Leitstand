"""Firmen-Cockpit: Monatsansicht, Kennzahlen und Zahlungslage (PLAN §7 Phase 5, §4).

Gerechnet wird in ``app/dienste/cockpit.py`` und ``app/dienste/zahlungsstatus.py`` – hier steht
nur, wer fragen darf und wie die Antwort aussieht.

``cockpit.lesen`` ist wie ``nachkalkulation.lesen`` von der Projektsicht getrennt (PLAN §4):
Finanzsichtbarkeit ist eine eigene Entscheidung. Der Sichtbarkeits-Scope wirkt zusätzlich, auch
wenn er im Cockpit selten greift – wer nur eigene Projekte sieht, bekommt eine Firmensicht, die
nur seine Projekte enthält, und das ist dann auch die ehrliche Auskunft.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.dienste import cockpit as dienst
from app.dienste import konten as kontendienst
from app.dienste import zahlungsstatus as zahlungsdienst
from app.fehler import FachFehler
from app.konfiguration import Einstellungen
from app.modelle import Projekt
from app.sicherheit.abhaengigkeiten import (
    Zugriff,
    benoetigt,
    db_sitzung,
    konfiguration,
    scope_filter,
)

router = APIRouter(prefix="/api/cockpit", tags=["Firmen-Cockpit"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung cockpit.lesen fehlt"},
}

_MONAT = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

UMSATZBASIS = ("gestellt", "bezahlt")


class MonatAntwort(BaseModel):
    monat: str
    umsatz_netto: int
    variable_kosten: int
    deckungsbeitrag: int
    fixkosten: int
    fixkosten_herkunft: str
    deckung: int
    db_promille: int | None
    fixkostendeckung_promille: int | None


class ReichweiteAntwort(BaseModel):
    bestand_netto: int
    durchschnittsumsatz: int
    umsatzmonate: float | None
    deckungsbeitrag: int | None
    fixkostenmonate: float | None


class KennzahlenAntwort(BaseModel):
    marge_promille: int | None
    marge_monate: int
    break_even_netto: int | None
    reichweite: ReichweiteAntwort


class CockpitAntwort(BaseModel):
    jahr: int
    monat: str
    umsatzbasis: str
    monate: list[MonatAntwort]
    fixkosten_je_block: dict[str, int]
    fixkosten_herkunft: str
    kumuliert: int
    kennzahlen: KennzahlenAntwort
    hinweise: list[str]
    verfuegbare_monate: list[str]
    # Ausdrücklich in der Antwort, damit die Oberfläche es nicht vergessen kann (PLAN §7).
    steuerungssicht: str = (
        "Steuerungssicht der Geschäftsführung, keine handelsrechtliche BWA: hier stehen "
        "Auftragswerte, kalkulatorische Sätze und Planzahlen neben Buchhaltungswerten."
    )


class OffenesKontoAntwort(BaseModel):
    konto: str
    bezeichnung: str | None
    summe: int
    monate: int


class ZahlungslageAntwort(BaseModel):
    rechnung_nr: str
    kunde: str
    datum: date
    faellig_am: date | None
    zahlbetrag: int
    offen: int
    status: str


class ZahlungenAntwort(BaseModel):
    stichtag: date | None
    offen: int
    ueberfaellig: int
    bezahlt: int
    je_status: dict[str, int]
    posten: list[ZahlungslageAntwort]
    hinweise: list[str]


def _sichtbar(zugriff: Zugriff) -> Select:
    return scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)


def _monat_pruefen(monat: str | None) -> str:
    """Monat aus der Anfrage, sonst der laufende. Ein unsinniger Wert wird abgewiesen."""
    if monat is None:
        return f"{date.today():%Y-%m}"
    if not _MONAT.match(monat):
        raise FachFehler(
            f"'{monat}' ist kein Monat.",
            "Erwartet wird das Format JJJJ-MM, zum Beispiel 2026-07.",
            code="monat_ungueltig",
        )
    return monat


@router.get(
    "",
    response_model=CockpitAntwort,
    summary="Monatsansicht des Firmen-Cockpits",
    operation_id="cockpitMonat",
    responses=LESEN,
)
def monatsansicht(
    monat: str | None = Query(None, description="Monat 'JJJJ-MM' (Standard: laufender Monat)"),
    basis: Literal[UMSATZBASIS] = "gestellt",  # type: ignore[valid-type]
    zugriff: Zugriff = Depends(benoetigt("cockpit.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> CockpitAntwort:
    """Umsatz, Deckungsbeitrag, Fixkosten und Über-/Unterdeckung für einen Monat.

    ``basis=bezahlt`` schaltet auf die Liquiditätssicht: statt der gestellten Rechnungen zählt,
    was laut OPOS beglichen ist (PLAN §6.7).
    """
    gewaehlt = _monat_pruefen(monat)
    sichtbar = _sichtbar(zugriff)

    ergebnis = dienst.monatsansicht(
        db,
        sichtbar,
        monat=gewaehlt,
        skonto_prozent=werte.fakturierung.skonto_toleranz_prozent,
        basis=basis,
    )
    reichweite = ergebnis.kennzahlen.reichweite

    return CockpitAntwort(
        jahr=ergebnis.jahr,
        monat=ergebnis.monat,
        umsatzbasis=ergebnis.umsatzbasis,
        monate=[
            MonatAntwort(
                monat=m.monat,
                umsatz_netto=m.umsatz_cent,
                variable_kosten=m.variable_kosten_cent,
                deckungsbeitrag=m.deckungsbeitrag_cent,
                fixkosten=m.fixkosten_cent,
                fixkosten_herkunft=m.fixkosten_herkunft,
                deckung=m.deckung_cent,
                db_promille=m.db_promille,
                fixkostendeckung_promille=m.fixkostendeckung_promille,
            )
            for m in ergebnis.monate
        ],
        fixkosten_je_block=ergebnis.fixkosten.je_block,
        fixkosten_herkunft=ergebnis.fixkosten.herkunft,
        kumuliert=ergebnis.kumuliert_cent,
        kennzahlen=KennzahlenAntwort(
            marge_promille=ergebnis.kennzahlen.marge_promille,
            marge_monate=ergebnis.kennzahlen.marge_monate,
            break_even_netto=ergebnis.kennzahlen.break_even_cent,
            reichweite=ReichweiteAntwort(
                bestand_netto=reichweite.bestand_cent,
                durchschnittsumsatz=reichweite.durchschnittsumsatz_cent,
                umsatzmonate=reichweite.umsatzmonate,
                deckungsbeitrag=reichweite.deckungsbeitrag_cent,
                fixkostenmonate=reichweite.fixkostenmonate,
            ),
        ),
        hinweise=ergebnis.hinweise,
        verfuegbare_monate=dienst.monate_mit_daten(db, sichtbar),
    )


@router.get(
    "/konten-offen",
    response_model=list[OffenesKontoAntwort],
    summary="Konten ohne Zuordnung zu einem Kostenblock",
    operation_id="cockpitOffeneKonten",
    responses=LESEN,
)
def offene_konten(
    jahr: int | None = Query(None, description="Nur Salden dieses Jahres"),
    zugriff: Zugriff = Depends(benoetigt("cockpit.lesen")),
    db: Session = Depends(db_sitzung),
) -> list[OffenesKontoAntwort]:
    """Die Pflegeliste zum Fixkostenblock, das größte Konto zuerst.

    Jedes Konto hier fehlt in den Fixkosten – die Überdeckung sieht dadurch besser aus, als sie
    ist.
    """
    return [
        OffenesKontoAntwort(
            konto=eintrag.konto,
            bezeichnung=eintrag.bezeichnung,
            summe=eintrag.summe_cent,
            monate=eintrag.monate,
        )
        for eintrag in kontendienst.unzugeordnete(db, jahr=jahr)
    ]


@router.get(
    "/zahlungen",
    response_model=ZahlungenAntwort,
    summary="Zahlungslage der festgeschriebenen Rechnungen",
    operation_id="cockpitZahlungen",
    responses=LESEN,
)
def zahlungen(
    zugriff: Zugriff = Depends(benoetigt("cockpit.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> ZahlungenAntwort:
    """Offen, überfällig und bezahlt zum jüngsten OPOS-Stichtag (PLAN §6.7).

    Ohne OPOS-Import steht zu jeder Rechnung nur fest, dass sie gestellt wurde – der Leitstand
    behauptet dann nichts über Zahlungen.
    """
    lage = zahlungsdienst.uebersicht(
        db,
        _sichtbar(zugriff),
        skonto_prozent=werte.fakturierung.skonto_toleranz_prozent,
    )
    return ZahlungenAntwort(
        stichtag=lage.stichtag,
        offen=lage.offen_cent,
        ueberfaellig=lage.ueberfaellig_cent,
        bezahlt=lage.bezahlt_cent,
        je_status=lage.je_status(),
        posten=[
            ZahlungslageAntwort(
                rechnung_nr=p.rechnung_nr,
                kunde=p.kunde,
                datum=p.datum,
                faellig_am=p.faellig_am,
                zahlbetrag=p.zahlbetrag_cent,
                offen=p.offen_cent,
                status=p.status,
            )
            for p in lage.posten
        ],
        hinweise=lage.hinweise,
    )
