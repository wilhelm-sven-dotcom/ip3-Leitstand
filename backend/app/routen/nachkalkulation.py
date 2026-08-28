"""Nachkalkulation: Übersicht und Projektansicht (PLAN §7 Phase 4, §4).

Gerechnet wird in ``app/dienste/nachkalkulation.py`` – hier steht nur, wer fragen darf, welche
Filter es gibt und wie die Antwort aussieht.

**Die Berechtigung ist die Trennlinie.** ``nachkalkulation.lesen`` ist bewusst von der
Projektsicht getrennt (PLAN §4): ein Mitarbeiter darf Projektdaten pflegen, ohne Margen zu sehen.
Die Rolle ``team`` hat das Recht nicht, ``buchhaltung`` ebenfalls nicht – nur ``admin``. Der
Sichtbarkeits-Scope wirkt zusätzlich: wer nur eigene Projekte sieht, bekommt auch nur deren
Margen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.dienste import nachkalkulation as dienst
from app.dienste import stueckliste as stuecklistendienst
from app.fehler import NichtGefunden
from app.konfiguration import Einstellungen
from app.modelle import Projekt, Stuecklistenposition, Stunden
from app.modelle.projekte import PROJEKT_STATUS
from app.sicherheit.abhaengigkeiten import (
    Zugriff,
    benoetigt,
    db_sitzung,
    konfiguration,
    scope_filter,
)

router = APIRouter(prefix="/api/nachkalkulation", tags=["Nachkalkulation"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung nachkalkulation.lesen fehlt"},
}

STATUS_FILTER = ("alle", *PROJEKT_STATUS)
SORTIERUNG = ("marge", "projekt_nr", "erloes", "ist")


class HinweisAntwort(BaseModel):
    code: str
    text: str


class ProjektAntwort(BaseModel):
    projekt_nr: int
    bezeichnung: str | None
    kunde: str
    status: str
    pl_name: str | None

    ab_wert_netto: int | None
    nachtraege_netto: int
    erloes_netto: int | None
    fakturiert_netto: int

    soll_material: int | None
    soll_dl: int | None
    soll_gesamt: int | None
    soll_stunden: Decimal | None
    marge_soll_promille: int | None

    ist_datev: int
    ist_stueckliste: int
    ist_timetac: int
    ist_gesamt: int
    stunden_ist: Decimal

    marge_netto: int | None
    marge_promille: int | None
    abweichung_promille: int | None
    soll_ist_abweichung: int | None
    stunden_abweichung: Decimal | None
    ampel: str
    hinweise: list[HinweisAntwort]


class UebersichtAntwort(BaseModel):
    projekte: list[ProjektAntwort]
    erloes_netto: int
    ist_netto: int
    marge_netto: int
    marge_promille: int | None
    anzahl: int
    ohne_kalkulation: int
    mit_hinweis: int
    ampel_gelb_promille: int


class StundenzeileAntwort(BaseModel):
    monat: str
    mitarbeiter: str
    stunden: Decimal
    satz: int
    betrag: int


class StuecklistenzeileAntwort(BaseModel):
    artikel_nr: str | None
    bezeichnung: str
    menge_soll: Decimal
    menge_ist: Decimal | None
    ek_preis: int | None
    quelle: str
    gewerk: str | None
    bewertet_betrag: int | None


class DetailAntwort(BaseModel):
    projekt: ProjektAntwort
    stunden: list[StundenzeileAntwort]
    stueckliste: list[StuecklistenzeileAntwort]


class OffeneMengeAntwort(BaseModel):
    projekt_nr: int
    bezeichnung: str | None
    kunde: str
    status: str
    positionen: int
    offen: int


def _als_antwort(zeile: dienst.Nachkalkulation) -> ProjektAntwort:
    return ProjektAntwort(
        projekt_nr=zeile.projekt_nr,
        bezeichnung=zeile.bezeichnung,
        kunde=zeile.kunde,
        status=zeile.status,
        pl_name=zeile.pl_name,
        ab_wert_netto=zeile.ab_wert_cent,
        nachtraege_netto=zeile.nachtraege_cent,
        erloes_netto=zeile.erloes_cent,
        fakturiert_netto=zeile.fakturiert_cent,
        soll_material=zeile.soll_material_cent,
        soll_dl=zeile.soll_dl_cent,
        soll_gesamt=zeile.soll_cent,
        soll_stunden=zeile.soll_stunden,
        marge_soll_promille=zeile.marge_soll_promille,
        ist_datev=zeile.ist_datev_cent,
        ist_stueckliste=zeile.ist_stueckliste_cent,
        ist_timetac=zeile.ist_timetac_cent,
        ist_gesamt=zeile.ist_cent,
        stunden_ist=zeile.stunden_ist,
        marge_netto=zeile.marge_cent,
        marge_promille=zeile.marge_promille,
        abweichung_promille=zeile.abweichung_promille,
        soll_ist_abweichung=zeile.soll_ist_abweichung_cent,
        stunden_abweichung=zeile.stunden_abweichung,
        ampel=zeile.ampel,
        hinweise=[HinweisAntwort(code=h.code, text=h.text) for h in zeile.hinweise],
    )


def _sichtbar(zugriff: Zugriff) -> Select:
    return scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)


@router.get(
    "",
    response_model=UebersichtAntwort,
    summary="Nachkalkulation aller Projekte",
    operation_id="nachkalkulationUebersicht",
    responses=LESEN,
)
def uebersicht(
    jahr: int | None = Query(None, description="Auftragsjahr, abgeleitet aus der Projektnummer"),
    status: Literal[STATUS_FILTER] = "alle",  # type: ignore[valid-type]
    projektleiter: str | None = None,
    sortierung: Literal[SORTIERUNG] = "marge",  # type: ignore[valid-type]
    nur_mit_hinweis: bool = False,
    zugriff: Zugriff = Depends(benoetigt("nachkalkulation.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> UebersichtAntwort:
    """Alle Projekte mit Erlös, Soll, Ist und Marge.

    Voreingestellt ist die Sortierung nach der schwächsten Marge: dort ist die Nachfrage fällig.
    """
    abfrage = _sichtbar(zugriff)
    if projektleiter:
        abfrage = abfrage.where(Projekt.pl_name == projektleiter)
    if jahr is not None:
        # Die Projektnummer trägt das Auftragsjahr (PLAN §3, Schema JJNNN).
        abfrage = abfrage.where(
            Projekt.projekt_nr >= (jahr % 100) * 1000,
            Projekt.projekt_nr < ((jahr % 100) + 1) * 1000,
        )

    gefunden = dienst.uebersicht(
        db,
        abfrage,
        ampel_gelb_promille=werte.nachkalkulation.ampel_gelb_promille,
        status=dienst.GEZAEHLTE_STATUS if status == "alle" else (status,),
    )
    zeilen = gefunden.projekte
    if nur_mit_hinweis:
        zeilen = [z for z in zeilen if z.hinweise]
    zeilen = _sortieren(zeilen, sortierung)

    return UebersichtAntwort(
        projekte=[_als_antwort(z) for z in zeilen],
        erloes_netto=gefunden.erloes_cent,
        ist_netto=gefunden.ist_cent,
        marge_netto=gefunden.marge_cent,
        marge_promille=gefunden.marge_promille,
        anzahl=len(gefunden.projekte),
        ohne_kalkulation=len(gefunden.ohne_kalkulation),
        mit_hinweis=len(gefunden.zu_pruefen),
        ampel_gelb_promille=werte.nachkalkulation.ampel_gelb_promille,
    )


def _sortieren(
    zeilen: list[dienst.Nachkalkulation], sortierung: str
) -> list[dienst.Nachkalkulation]:
    """``marge`` ist die Vorbelegung und kommt schon sortiert aus dem Dienst."""
    if sortierung == "projekt_nr":
        return sorted(zeilen, key=lambda z: z.projekt_nr)
    if sortierung == "erloes":
        return sorted(zeilen, key=lambda z: -(z.erloes_cent or 0))
    if sortierung == "ist":
        return sorted(zeilen, key=lambda z: -z.ist_cent)
    return zeilen


@router.get(
    "/mengen-ist-offen",
    response_model=list[OffeneMengeAntwort],
    summary="Projekte mit ungezählten Lagerpositionen",
    operation_id="nachkalkulationOffeneMengen",
    responses=LESEN,
)
def offene_mengen(
    zugriff: Zugriff = Depends(benoetigt("nachkalkulation.lesen")),
    db: Session = Depends(db_sitzung),
) -> list[OffeneMengeAntwort]:
    """Wo die Lagerbewertung noch mit der kalkulierten Menge rechnet (PLAN §6.5)."""
    return [
        OffeneMengeAntwort(
            projekt_nr=e.projekt_nr,
            bezeichnung=e.bezeichnung,
            kunde=e.kunde,
            status=e.status,
            positionen=e.positionen,
            offen=e.offen,
        )
        for e in stuecklistendienst.offene_mengen(db, _sichtbar(zugriff))
    ]


@router.get(
    "/{projekt_nr}",
    response_model=DetailAntwort,
    summary="Nachkalkulation eines Projekts mit Aufgliederung",
    operation_id="nachkalkulationProjekt",
    responses={**LESEN, 404: {"description": "Projekt nicht gefunden"}},
)
def projekt(
    projekt_nr: int,
    zugriff: Zugriff = Depends(benoetigt("nachkalkulation.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> DetailAntwort:
    eintrag = db.scalar(_sichtbar(zugriff).where(Projekt.projekt_nr == projekt_nr))
    if eintrag is None:
        raise NichtGefunden(
            f"Es gibt kein Projekt mit der Nummer {projekt_nr}.",
            "Die Projektnummer prüfen. Möglicherweise ist das Projekt einem anderen "
            "Projektleiter zugeordnet.",
        )

    zeile = dienst.fuer_projekt(
        db, eintrag, ampel_gelb_promille=werte.nachkalkulation.ampel_gelb_promille
    )
    stunden = db.scalars(
        select(Stunden)
        .where(Stunden.projekt_id == eintrag.id)
        .order_by(Stunden.monat, Stunden.mitarbeiter)
    )
    positionen = db.scalars(
        select(Stuecklistenposition)
        .where(Stuecklistenposition.projekt_id == eintrag.id)
        .order_by(Stuecklistenposition.id)
    )

    return DetailAntwort(
        projekt=_als_antwort(zeile),
        stunden=[
            StundenzeileAntwort(
                monat=z.monat,
                mitarbeiter=z.mitarbeiter,
                stunden=Decimal(str(z.stunden)),
                satz=z.satz,
                betrag=round(Decimal(str(z.stunden)) * z.satz),
            )
            for z in stunden
        ],
        stueckliste=[
            StuecklistenzeileAntwort(
                artikel_nr=p.artikel_nr,
                bezeichnung=p.bezeichnung,
                menge_soll=Decimal(str(p.menge_soll)),
                menge_ist=None if p.menge_ist is None else Decimal(str(p.menge_ist)),
                ek_preis=p.ek_preis,
                quelle=p.quelle,
                gewerk=p.gewerk,
                bewertet_betrag=p.bewertet_betrag,
            )
            for p in positionen
        ],
    )
