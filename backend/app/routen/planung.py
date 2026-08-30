"""Kapazität, Mitarbeiter und Angebotspipeline (PLAN §4, §7 Phase 7).

Gerechnet wird in ``app/dienste/kapazitaet.py`` und ``app/dienste/pipeline.py`` – hier steht
nur, wer fragen darf und wie die Antwort aussieht.

Die Rechte folgen PLAN §4:

* ``kapazitaet.lesen`` hat auch das Team. Die Wochenauslastung zeigt Stunden, keine Beträge; sie
  ist der eigene Terminplan und nicht Teil der Finanzsichtbarkeit.
* ``angebote.lesen`` hat nur die Geschäftsführung. Eine Angebotssumme ist ein Betrag, und
  Beträge sind in PLAN §4 ausdrücklich abgetrennt.
* Gepflegt wird mit ``kapazitaet.schreiben`` und ``angebote.schreiben``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app import audit
from app.dienste import kapazitaet as kapazitaetsdienst
from app.dienste import pipeline as pipelinedienst
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.fehler import FachFehler, Konflikt, NichtGefunden
from app.konfiguration import Einstellungen
from app.modelle import Angebot, Kunde, Mitarbeiter, Projekt
from app.modelle.planung import ANGEBOT_STATUS, SATZGRUPPEN
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import (
    Zugriff,
    benoetigt,
    db_sitzung,
    konfiguration,
    scope_filter,
)
from app.zeit import heute_ortszeit, monat_gueltig

log = logger(__name__)

router = APIRouter(prefix="/api", tags=["Kapazität und Pipeline"])

KAPAZITAET_LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung kapazitaet.lesen fehlt"},
}
KAPAZITAET_SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung kapazitaet.schreiben fehlt"},
    404: {"description": "Mitarbeiter nicht gefunden"},
    409: {"description": "Der Datensatz wurde zwischenzeitlich geändert"},
}
ANGEBOTE_LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung angebote.lesen fehlt"},
}
ANGEBOTE_SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung angebote.schreiben fehlt"},
    404: {"description": "Angebot nicht gefunden"},
    409: {"description": "Das Angebot wurde zwischenzeitlich geändert"},
}


# ---------------------------------------------------------------------------
# Kapazität
# ---------------------------------------------------------------------------


class ProjektanteilAntwort(BaseModel):
    projekt_nr: int
    bezeichnung: str | None = None
    stunden: float
    # Über wie viele Wochen die Sollstunden verteilt wurden – erklärt die Zahl.
    wochen: int


class WochenAntwort(BaseModel):
    schluessel: str
    jahr: int
    woche: int
    beginn: date
    bedarf: float
    kapazitaet: float
    rest: float
    auslastung_promille: int | None
    projekte: list[ProjektanteilAntwort]


class OhneTerminAntwort(BaseModel):
    projekt_nr: int
    bezeichnung: str | None = None
    stunden: float
    status: str


class KapazitaetAntwort(BaseModel):
    wochen: list[WochenAntwort]
    ohne_termin: list[OhneTerminAntwort]
    bedarf_gesamt: float
    kapazitaet_gesamt: float
    stunden_ohne_termin: float
    warnung_ab_promille: int
    hinweise: list[str]
    # Ausdrücklich in der Antwort, damit die Oberfläche es nicht vergessen kann.
    einordnung: str = (
        "Regelarbeitszeit ohne Urlaub und Krankheit: der Leitstand führt keine "
        "Abwesenheitsplanung. Die verfügbaren Stunden sind eine Obergrenze, keine Zusage."
    )


class MitarbeiterAntwort(BaseModel):
    id: int
    name: str
    satzgruppe: str | None = None
    wochenstunden: float
    aktiv: bool
    von: date | None = None
    bis: date | None = None
    bemerkung: str | None = None
    stand: datetime


class MitarbeiterListe(BaseModel):
    mitarbeiter: list[MitarbeiterAntwort]
    # Wer in TimeTac bucht, aber hier fehlt. Ohne diesen Hinweis wäre ein Tippfehler unsichtbar.
    ohne_datensatz: list[str]
    summe_wochenstunden: float


class MitarbeiterEingabe(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    satzgruppe: Literal[SATZGRUPPEN] | None = None  # type: ignore[valid-type]
    wochenstunden: float = Field(default=0, ge=0, le=100)
    aktiv: bool = True
    von: date | None = None
    bis: date | None = None
    bemerkung: str | None = None

    @field_validator("name", "bemerkung")
    @classmethod
    def leerraum_kuerzen(cls, wert: str | None) -> str | None:
        if wert is None:
            return None
        return wert.strip() or None


class MitarbeiterAendern(MitarbeiterEingabe):
    stand: datetime


def _sichtbar(zugriff: Zugriff) -> Select:
    return scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)


@router.get(
    "/kapazitaet",
    response_model=KapazitaetAntwort,
    summary="Auslastung je Kalenderwoche",
    operation_id="kapazitaetLesen",
    responses=KAPAZITAET_LESEN,
)
def kapazitaet_lesen(
    wochen: int | None = Query(
        None, ge=1, le=52, description="Anzahl Wochen (Standard aus der config.toml)"
    ),
    ab: date | None = Query(None, description="Erste Woche; ohne Angabe die laufende"),
    zugriff: Zugriff = Depends(benoetigt("kapazitaet.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> KapazitaetAntwort:
    """Sollstunden der terminierten Projekte gegen die Wochenstunden der Mannschaft."""
    bild = kapazitaetsdienst.bild(
        db,
        _sichtbar(zugriff),
        wochen_voraus=wochen or werte.kapazitaet.wochen_voraus,
        montage_meilensteine=werte.kapazitaet.montage_meilensteine,
        status_mit_bedarf=werte.kapazitaet.status_mit_bedarf,
        ab=ab,
    )
    return KapazitaetAntwort(
        wochen=[
            WochenAntwort(
                schluessel=w.schluessel,
                jahr=w.jahr,
                woche=w.woche,
                beginn=w.beginn,
                bedarf=float(w.bedarf),
                kapazitaet=float(w.kapazitaet),
                rest=float(w.rest),
                auslastung_promille=w.auslastung_promille,
                projekte=[
                    ProjektanteilAntwort(
                        projekt_nr=p.projekt_nr,
                        bezeichnung=p.bezeichnung,
                        stunden=float(p.stunden),
                        wochen=p.wochen,
                    )
                    for p in w.projekte
                ],
            )
            for w in bild.wochen
        ],
        ohne_termin=[
            OhneTerminAntwort(
                projekt_nr=o.projekt_nr,
                bezeichnung=o.bezeichnung,
                stunden=float(o.stunden),
                status=o.status,
            )
            for o in bild.ohne_termin
        ],
        bedarf_gesamt=float(bild.bedarf_gesamt),
        kapazitaet_gesamt=float(bild.kapazitaet_gesamt),
        stunden_ohne_termin=float(bild.stunden_ohne_termin),
        warnung_ab_promille=werte.kapazitaet.warnung_ab_promille,
        hinweise=bild.hinweise,
    )


@router.get(
    "/mitarbeiter",
    response_model=MitarbeiterListe,
    summary="Mannschaft und Wochenstunden",
    operation_id="mitarbeiterListe",
    responses=KAPAZITAET_LESEN,
)
def mitarbeiter_liste(
    zugriff: Zugriff = Depends(benoetigt("kapazitaet.lesen")),
    db: Session = Depends(db_sitzung),
) -> MitarbeiterListe:
    zeilen = list(db.scalars(select(Mitarbeiter).order_by(Mitarbeiter.name)))
    return MitarbeiterListe(
        mitarbeiter=[_mitarbeiter_antwort(m) for m in zeilen],
        ohne_datensatz=kapazitaetsdienst.namen_ohne_mitarbeiter(db),
        summe_wochenstunden=float(sum(float(m.wochenstunden) for m in zeilen if m.aktiv)),
    )


def _mitarbeiter_antwort(eintrag: Mitarbeiter) -> MitarbeiterAntwort:
    return MitarbeiterAntwort(
        id=eintrag.id,
        name=eintrag.name,
        satzgruppe=eintrag.satzgruppe,
        wochenstunden=float(eintrag.wochenstunden),
        aktiv=eintrag.aktiv,
        von=eintrag.von,
        bis=eintrag.bis,
        bemerkung=eintrag.bemerkung,
        stand=eintrag.updated_at,
    )


def _zeitraum_pruefen(von: date | None, bis: date | None) -> None:
    if von and bis and bis < von:
        raise FachFehler(
            "Das Austrittsdatum liegt vor dem Eintritt.",
            "Bitte die beiden Daten tauschen oder eines davon leer lassen.",
            code="zeitraum_verdreht",
        )


@router.post(
    "/mitarbeiter",
    response_model=MitarbeiterAntwort,
    status_code=201,
    summary="Mitarbeiter anlegen",
    operation_id="mitarbeiterAnlegen",
    responses=KAPAZITAET_SCHREIBEN,
)
def mitarbeiter_anlegen(
    eingabe: MitarbeiterEingabe,
    zugriff: Zugriff = Depends(benoetigt("kapazitaet.schreiben")),
    db: Session = Depends(db_sitzung),
) -> MitarbeiterAntwort:
    """Der Name muss dem in TimeTac entsprechen – sonst laufen Stunden und Kapazität auseinander."""
    _zeitraum_pruefen(eingabe.von, eingabe.bis)
    if db.scalar(select(Mitarbeiter).where(Mitarbeiter.name == eingabe.name)):
        raise Konflikt(
            f"„{eingabe.name}“ steht schon in der Liste.",
            "Den vorhandenen Eintrag bearbeiten statt einen zweiten anzulegen.",
            code="mitarbeiter_doppelt",
        )

    eintrag = Mitarbeiter(**eingabe.model_dump())
    db.add(eintrag)
    db.flush()
    audit.eintragen(
        db,
        "mitarbeiter.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="mitarbeiter",
        datensatz_id=eintrag.id,
        neu={"name": eintrag.name, "wochenstunden": float(eintrag.wochenstunden)},
    )
    db.commit()
    return _mitarbeiter_antwort(eintrag)


@router.put(
    "/mitarbeiter/{mitarbeiter_id}",
    response_model=MitarbeiterAntwort,
    summary="Mitarbeiter ändern",
    operation_id="mitarbeiterAendern",
    responses=KAPAZITAET_SCHREIBEN,
)
def mitarbeiter_aendern(
    mitarbeiter_id: int,
    eingabe: MitarbeiterAendern,
    zugriff: Zugriff = Depends(benoetigt("kapazitaet.schreiben")),
    db: Session = Depends(db_sitzung),
) -> MitarbeiterAntwort:
    """Wer geht, wird auf ``aktiv = false`` gesetzt und nicht gelöscht (CLAUDE.md Regel 5)."""
    eintrag = db.get(Mitarbeiter, mitarbeiter_id)
    if eintrag is None:
        raise NichtGefunden(
            f"Es gibt keinen Mitarbeiter mit der Nummer {mitarbeiter_id}.",
            "Die Mitarbeiterliste steht unter „Kapazität“.",
        )
    stand_pruefen(eintrag, eingabe.stand, "Der Mitarbeiter")
    _zeitraum_pruefen(eingabe.von, eingabe.bis)

    doppelt = db.scalar(
        select(Mitarbeiter).where(Mitarbeiter.name == eingabe.name, Mitarbeiter.id != eintrag.id)
    )
    if doppelt is not None:
        raise Konflikt(
            f"„{eingabe.name}“ steht schon in der Liste.",
            "Die beiden Einträge gehören zusammengeführt; einer davon wird deaktiviert.",
            code="mitarbeiter_doppelt",
        )

    vorher = _mitarbeiter_zustand(eintrag)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(eintrag, feld, wert)
    unterschiede = geaenderte_felder(vorher, _mitarbeiter_zustand(eintrag))
    if not unterschiede:
        return _mitarbeiter_antwort(eintrag)

    audit.eintragen(
        db,
        "mitarbeiter.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="mitarbeiter",
        datensatz_id=eintrag.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={f: w["neu"] for f, w in unterschiede.items()},
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Der Mitarbeiter")
        raise
    return _mitarbeiter_antwort(eintrag)


def _mitarbeiter_zustand(eintrag: Mitarbeiter) -> dict[str, object]:
    return {
        feld: getattr(eintrag, feld)
        for feld in ("name", "satzgruppe", "wochenstunden", "aktiv", "von", "bis", "bemerkung")
    }


# ---------------------------------------------------------------------------
# Angebote
# ---------------------------------------------------------------------------


class AngebotAntwort(BaseModel):
    id: int
    angebot_nr: str | None = None
    kunde_id: int | None = None
    kunde_name: str
    bezeichnung: str | None = None
    summe_netto: int
    wahrscheinlichkeit_promille: int
    gewichtet_netto: int
    erwarteter_monat: str | None = None
    status: str
    datum: date | None = None
    projekt_nr: int | None = None
    quelle_datei: str | None = None
    bemerkung: str | None = None
    stand: datetime


class AngebotListe(BaseModel):
    angebote: list[AngebotAntwort]
    gesamt: int
    roh_netto: int
    gewichtet_netto: int


class PipelinemonatAntwort(BaseModel):
    monat: str
    roh_netto: int
    gewichtet_netto: int
    anzahl: int


class PipelineAntwort(BaseModel):
    jahr: int
    monate: list[PipelinemonatAntwort]
    unterminiert_roh: int
    unterminiert_gewichtet: int
    unterminiert_anzahl: int
    roh_netto: int
    gewichtet_netto: int
    anzahl: int
    jahre: list[int]
    hinweise: list[str]
    # Ausdrücklich in der Antwort: die Oberfläche darf das nie weglassen.
    einordnung: str = (
        "Angebote, keine Aufträge. Die gewichtete Summe ist eine Erwartung und gehört nicht "
        "zum Auftragsbestand."
    )


class AngebotEingabe(BaseModel):
    kunde_name: str = Field(min_length=1, max_length=200)
    kunde_id: int | None = None
    angebot_nr: str | None = Field(default=None, max_length=50)
    bezeichnung: str | None = Field(default=None, max_length=200)
    summe_netto: int = Field(default=0, ge=0)
    wahrscheinlichkeit_promille: int = Field(default=500, ge=0, le=1000)
    erwarteter_monat: str | None = None
    status: Literal[ANGEBOT_STATUS] = "offen"  # type: ignore[valid-type]
    datum: date | None = None
    projekt_id: int | None = None
    bemerkung: str | None = None

    @field_validator("kunde_name", "angebot_nr", "bezeichnung", "bemerkung")
    @classmethod
    def leerraum_kuerzen(cls, wert: str | None) -> str | None:
        if wert is None:
            return None
        return wert.strip() or None

    @field_validator("erwarteter_monat")
    @classmethod
    def monat_pruefen(cls, wert: str | None) -> str | None:
        if wert is None or not wert.strip():
            return None
        if not monat_gueltig(wert):
            raise ValueError(f"'{wert}' ist kein Monat im Format JJJJ-MM (Beispiel: 2027-03).")
        return wert


class AngebotAendern(AngebotEingabe):
    stand: datetime


def _angebot_antwort(db: Session, angebot: Angebot) -> AngebotAntwort:
    projekt_nr = (
        db.scalar(select(Projekt.projekt_nr).where(Projekt.id == angebot.projekt_id))
        if angebot.projekt_id
        else None
    )
    return AngebotAntwort(
        id=angebot.id,
        angebot_nr=angebot.angebot_nr,
        kunde_id=angebot.kunde_id,
        kunde_name=angebot.kunde_name,
        bezeichnung=angebot.bezeichnung,
        summe_netto=angebot.summe_netto,
        wahrscheinlichkeit_promille=angebot.wahrscheinlichkeit_promille,
        gewichtet_netto=angebot.gewichtet_cent,
        erwarteter_monat=angebot.erwarteter_monat,
        status=angebot.status,
        datum=angebot.datum,
        projekt_nr=projekt_nr,
        quelle_datei=angebot.quelle_datei,
        bemerkung=angebot.bemerkung,
        stand=angebot.updated_at,
    )


@router.get(
    "/angebote",
    response_model=AngebotListe,
    summary="Angebote der Pipeline",
    operation_id="angeboteListe",
    responses=ANGEBOTE_LESEN,
)
def angebote_liste(
    status: str = Query("offen", description="'offen', 'gewonnen', 'verloren' oder 'alle'"),
    zugriff: Zugriff = Depends(benoetigt("angebote.lesen")),
    db: Session = Depends(db_sitzung),
) -> AngebotListe:
    """Das größte Angebot zuerst – danach sucht man in einer Pipeline."""
    abfrage = select(Angebot)
    if status != "alle":
        if status not in ANGEBOT_STATUS:
            raise FachFehler(
                f"'{status}' ist kein Angebotsstatus.",
                "Erlaubt sind 'offen', 'gewonnen', 'verloren' und 'alle'.",
                code="status_ungueltig",
            )
        abfrage = abfrage.where(Angebot.status == status)

    zeilen = list(db.scalars(abfrage.order_by(Angebot.summe_netto.desc(), Angebot.id)))
    return AngebotListe(
        angebote=[_angebot_antwort(db, a) for a in zeilen],
        gesamt=len(zeilen),
        roh_netto=sum(a.summe_netto for a in zeilen),
        gewichtet_netto=sum(a.gewichtet_cent for a in zeilen),
    )


@router.get(
    "/angebote/pipeline",
    response_model=PipelineAntwort,
    summary="Gewichtete Angebotssumme je Monat",
    operation_id="angebotePipeline",
    responses=ANGEBOTE_LESEN,
)
def pipeline(
    jahr: int | None = Query(None, ge=2000, le=2100),
    zugriff: Zugriff = Depends(benoetigt("angebote.lesen")),
    db: Session = Depends(db_sitzung),
) -> PipelineAntwort:
    """Die Pipeline steht **neben** dem Forecast, nie darin (PLAN §7 Phase 7)."""
    gewaehlt = jahr or pipelinedienst.jahr_mit_angeboten(db, heute_ortszeit().year)
    bild = pipelinedienst.jahresverlauf(db, gewaehlt)
    return PipelineAntwort(
        jahr=bild.jahr,
        monate=[
            PipelinemonatAntwort(
                monat=m.monat,
                roh_netto=m.roh_cent,
                gewichtet_netto=m.gewichtet_cent,
                anzahl=m.anzahl,
            )
            for m in bild.monate
        ],
        unterminiert_roh=bild.unterminiert.roh_cent,
        unterminiert_gewichtet=bild.unterminiert.gewichtet_cent,
        unterminiert_anzahl=bild.unterminiert.anzahl,
        roh_netto=bild.roh_cent,
        gewichtet_netto=bild.gewichtet_cent,
        anzahl=bild.anzahl,
        jahre=pipelinedienst.jahre_mit_angeboten(db) or [gewaehlt],
        hinweise=bild.hinweise,
    )


def _bezuege_pruefen(db: Session, eingabe: AngebotEingabe) -> None:
    if eingabe.kunde_id is not None and db.get(Kunde, eingabe.kunde_id) is None:
        raise NichtGefunden(
            "Den angegebenen Kunden gibt es nicht.",
            "Die Kundenliste zeigt die vorhandenen Kunden. Ein Interessent braucht keinen "
            "Kundendatensatz – dann das Feld leer lassen.",
        )
    if eingabe.projekt_id is not None and db.get(Projekt, eingabe.projekt_id) is None:
        raise NichtGefunden(
            "Das angegebene Projekt gibt es nicht.",
            "Erst das Projekt anlegen, dann das Angebot damit verknüpfen.",
        )


@router.post(
    "/angebote",
    response_model=AngebotAntwort,
    status_code=201,
    summary="Angebot erfassen",
    operation_id="angebotAnlegen",
    responses=ANGEBOTE_SCHREIBEN,
)
def angebot_anlegen(
    eingabe: AngebotEingabe,
    zugriff: Zugriff = Depends(benoetigt("angebote.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AngebotAntwort:
    _bezuege_pruefen(db, eingabe)
    if eingabe.angebot_nr and db.scalar(
        select(Angebot).where(Angebot.angebot_nr == eingabe.angebot_nr)
    ):
        raise Konflikt(
            f"Angebot {eingabe.angebot_nr} gibt es schon.",
            "Das vorhandene Angebot bearbeiten statt ein zweites anzulegen.",
            code="angebot_doppelt",
        )

    angebot = Angebot(**eingabe.model_dump())
    db.add(angebot)
    db.flush()
    audit.eintragen(
        db,
        "angebot.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="angebote",
        datensatz_id=angebot.id,
        neu={
            "angebot_nr": angebot.angebot_nr,
            "kunde_name": angebot.kunde_name,
            "summe_netto": angebot.summe_netto,
        },
    )
    db.commit()
    return _angebot_antwort(db, angebot)


@router.put(
    "/angebote/{angebot_id}",
    response_model=AngebotAntwort,
    summary="Angebot ändern",
    operation_id="angebotAendern",
    responses=ANGEBOTE_SCHREIBEN,
)
def angebot_aendern(
    angebot_id: int,
    eingabe: AngebotAendern,
    zugriff: Zugriff = Depends(benoetigt("angebote.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AngebotAntwort:
    """Ein Angebot wird nicht gelöscht, sondern auf ``verloren`` gesetzt (CLAUDE.md Regel 5).

    Die Trefferquote der Vergangenheit ist die einzige Grundlage, auf der sich künftige
    Wahrscheinlichkeiten begründen lassen – verlorene Angebote wegzuwerfen nähme sie weg.
    """
    angebot = db.get(Angebot, angebot_id)
    if angebot is None:
        raise NichtGefunden(
            f"Es gibt kein Angebot mit der Nummer {angebot_id}.",
            "Die Angebotsliste zeigt die vorhandenen Angebote.",
        )
    stand_pruefen(angebot, eingabe.stand, "Das Angebot")
    _bezuege_pruefen(db, eingabe)

    if eingabe.status == "gewonnen" and eingabe.projekt_id is None:
        raise Konflikt(
            "Ein gewonnenes Angebot braucht ein Projekt.",
            "Sonst steht sein Wert weder in der Pipeline noch im Auftragsbestand. Zuerst das "
            "Projekt anlegen, dann hier verknüpfen.",
            code="gewonnen_ohne_projekt",
        )

    vorher = _angebot_zustand(angebot)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(angebot, feld, wert)
    unterschiede = geaenderte_felder(vorher, _angebot_zustand(angebot))
    if not unterschiede:
        return _angebot_antwort(db, angebot)

    audit.eintragen(
        db,
        "angebot.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="angebote",
        datensatz_id=angebot.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={f: w["neu"] for f, w in unterschiede.items()},
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Das Angebot")
        raise
    return _angebot_antwort(db, angebot)


def _angebot_zustand(angebot: Angebot) -> dict[str, object]:
    return {
        feld: getattr(angebot, feld)
        for feld in (
            "angebot_nr",
            "kunde_id",
            "kunde_name",
            "bezeichnung",
            "summe_netto",
            "wahrscheinlichkeit_promille",
            "erwarteter_monat",
            "status",
            "datum",
            "projekt_id",
            "bemerkung",
        )
    }
