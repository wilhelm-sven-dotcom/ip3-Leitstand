"""Zahlungsplan und Nachträge eines Projekts (PLAN §5, §6.12, §7 Phase 1).

Der Zahlungsplan ist das Rückgrat der Fakturierung: aus jeder Position entsteht ab Phase 3 eine
Abschlags- oder Schlussrechnung, und ab Phase 2 speist er den Forecast. Entsprechend sind hier
drei Dinge geregelt, die woanders nicht so streng sind:

* **Zwei Sperren, nicht eine.** Eine Position mit ``rechnung_id`` ist berechnet und nur über den
  Storno des Belegs wieder frei (PLAN §5). Eine Position mit ``migriert_gestellt`` gehört zum
  Altbestand: die Rechnung dazu wurde vor der Einführung des Leitstands gestellt, es gibt keinen
  Beleg, den man stornieren könnte. Sie ist deshalb ebenfalls gesperrt – **rücknehmbar**, aber
  nur als eigene, sichtbare Entscheidung (docs/OFFENE-PUNKTE.md Nr. 5). Beide Sperren sitzen
  zusätzlich als Trigger in der Datenbank (Migrationen 0002 und 0005); die Prüfungen hier sind
  dafür da, dass der Nutzer eine Meldung statt eines Datenbankfehlers bekommt.
* **Deckung statt Zwang** (PLAN §6.12). Die Summe der Positionen wird gegen den Auftragswert plus
  beauftragte Nachträge geprüft. Weicht sie ab, ist das eine sichtbare Warnung, keine Sperre:
  bei den migrierten Projekten führt die Auftragsliste nur die offenen Positionen, die Lücke ist
  dort der Normalfall und keine Fehleingabe.
* **Beträge nur mit ``projekte.werte_lesen``.** Wer die Beträge nicht sehen darf, sieht den
  Zahlungsplan gar nicht – auch nicht, um ihn zu ändern.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit

# Die Regel, welche Nachträge zum Soll zählen, steht im Auswertungsdienst: Zahlungsplanmaske,
# Umsatzseite und später das Firmen-Cockpit müssen dieselbe verwenden (PLAN §6.12).
from app.dienste.auswertung import NACHTRAG_ZAEHLT
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.fehler import Konflikt, NichtGefunden
from app.modelle import Nachtrag, Projekt, Zahlungsplanposition
from app.modelle.projekte import GEWERKE, MEILENSTEIN_TYPEN
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, scope_filter

log = logger(__name__)

router = APIRouter(prefix="/api", tags=["Zahlungsplan"])

SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung zahlungsplan.schreiben fehlt"},
    404: {"description": "Projekt oder Position nicht gefunden"},
    409: {"description": "Position gesperrt oder zwischenzeitlich geändert"},
}

NACHTRAG_STATUS = ("angeboten", "beauftragt", "berechnet")


class PositionEingabe(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=500)
    gewerk: Literal[GEWERKE]  # type: ignore[valid-type]
    art: Literal["abschlag", "schluss", "einmal"]
    betrag_netto: int = Field(ge=0)
    # Monat, in dem die Rechnung erwartet wird. Leer heißt „unterminiert" und wird im Forecast
    # gesondert ausgewiesen (PLAN §7 Phase 2), nicht stillschweigend auf heute gelegt.
    plan_monat: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    # Auslöser für den Rechnungsvorschlag auf der Startseite (PLAN §6.8).
    trigger_status: Literal[MEILENSTEIN_TYPEN] | None = None  # type: ignore[valid-type]

    @field_validator("bezeichnung")
    @classmethod
    def leerraum_kuerzen(cls, wert: str) -> str:
        gekuerzt = wert.strip()
        if not gekuerzt:
            raise ValueError("Die Bezeichnung darf nicht leer sein.")
        return gekuerzt


class PositionAendern(PositionEingabe):
    stand: datetime


class PositionAntwort(BaseModel):
    id: int
    projekt_id: int
    pos_nr: int
    bezeichnung: str
    gewerk: str
    art: str
    betrag_netto: int
    plan_monat: str | None = None
    trigger_status: str | None = None
    migriert_gestellt: bool | None = None
    berechnet: bool
    # Der Beleg, der die Position berechnet – damit die Maske direkt dorthin verweisen kann.
    rechnung_id: int | None = None
    quelle_migration: str | None = None
    stand: datetime
    # Warum die Position nicht bearbeitbar ist – leer, wenn sie es ist.
    sperrgrund: str | None = None


class NachtragEingabe(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=500)
    betrag_netto: int
    status: Literal[NACHTRAG_STATUS] = "angeboten"  # type: ignore[valid-type]
    datum: date | None = None

    @field_validator("bezeichnung")
    @classmethod
    def leerraum_kuerzen(cls, wert: str) -> str:
        gekuerzt = wert.strip()
        if not gekuerzt:
            raise ValueError("Die Bezeichnung darf nicht leer sein.")
        return gekuerzt


class NachtragAendern(NachtragEingabe):
    stand: datetime


class NachtragAntwort(BaseModel):
    id: int
    projekt_id: int
    bezeichnung: str
    betrag_netto: int
    status: str
    datum: date | None = None
    # Zählt dieser Nachtrag in den Soll-Wert des Zahlungsplans (PLAN §6.12)?
    zaehlt_zum_soll: bool
    stand: datetime


class Deckung(BaseModel):
    """Soll-Ist-Vergleich des Zahlungsplans (PLAN §6.12)."""

    ab_wert_netto: int | None = None
    nachtraege_netto: int = 0
    soll_netto: int | None = None
    zahlungsplan_netto: int = 0
    # Soll minus Zahlungsplan. Positiv: noch nicht verplant. Negativ: mehr verplant als
    # beauftragt. Ohne Auftragswert bleibt sie leer – dann gibt es nichts zu vergleichen.
    differenz_netto: int | None = None


def _projekt_holen(db: Session, projekt_nr: int, zugriff: Zugriff) -> Projekt:
    abfrage = scope_filter(
        select(Projekt).where(Projekt.projekt_nr == projekt_nr),
        zugriff,
        "projekte.lesen",
        Projekt.pl_user_id,
    )
    projekt = db.scalar(abfrage)
    if projekt is None:
        raise NichtGefunden(
            f"Es gibt kein Projekt mit der Nummer {projekt_nr}.",
            "Die Projektliste zeigt die vorhandenen Projekte.",
        )
    return projekt


def _position_holen(db: Session, position_id: int, zugriff: Zugriff) -> Zahlungsplanposition:
    position = db.get(Zahlungsplanposition, position_id)
    if position is None:
        raise NichtGefunden(
            "Die Zahlungsplanposition gibt es nicht mehr.",
            "Bitte das Projekt neu laden – die Position wurde vermutlich zwischenzeitlich "
            "gelöscht.",
        )
    # Der Sichtbarkeits-Scope hängt am Projekt, nicht an der Position.
    _projekt_holen(db, position.projekt.projekt_nr, zugriff)
    return position


def _nachtrag_holen(db: Session, nachtrag_id: int, zugriff: Zugriff) -> Nachtrag:
    nachtrag = db.get(Nachtrag, nachtrag_id)
    if nachtrag is None:
        raise NichtGefunden(
            "Den Nachtrag gibt es nicht mehr.",
            "Bitte das Projekt neu laden.",
        )
    _projekt_holen(db, nachtrag.projekt.projekt_nr, zugriff)
    return nachtrag


def _sperrgrund(position: Zahlungsplanposition) -> str | None:
    """Warum die Position nicht bearbeitbar ist – als Satz für die Maske.

    Die Maske zeichnet die Position damit von Anfang an als gesperrt, statt den Nutzer erst beim
    Speichern in eine Fehlermeldung laufen zu lassen.
    """
    if position.rechnung_id is not None:
        return (
            "Zu dieser Position ist eine Rechnung festgeschrieben. Änderungen sind nur über den "
            "Storno des Belegs möglich."
        )
    if position.migriert_gestellt:
        return (
            "Diese Position war im Altbestand als „gestellt“ gekennzeichnet. Ihr Betrag zählt "
            "zum Umsatz vergangener Monate."
        )
    return None


def _als_antwort(position: Zahlungsplanposition) -> PositionAntwort:
    return PositionAntwort(
        id=position.id,
        projekt_id=position.projekt_id,
        pos_nr=position.pos_nr,
        bezeichnung=position.bezeichnung,
        gewerk=position.gewerk,
        art=position.art,
        betrag_netto=position.betrag_netto,
        plan_monat=position.plan_monat,
        trigger_status=position.trigger_status,
        migriert_gestellt=position.migriert_gestellt,
        rechnung_id=position.rechnung_id,
        berechnet=position.rechnung_id is not None,
        quelle_migration=position.quelle_migration,
        stand=position.updated_at,
        sperrgrund=_sperrgrund(position),
    )


def _nachtrag_antwort(nachtrag: Nachtrag) -> NachtragAntwort:
    return NachtragAntwort(
        id=nachtrag.id,
        projekt_id=nachtrag.projekt_id,
        bezeichnung=nachtrag.bezeichnung,
        betrag_netto=nachtrag.betrag_netto,
        status=nachtrag.status,
        datum=nachtrag.datum,
        zaehlt_zum_soll=nachtrag.status in NACHTRAG_ZAEHLT,
        stand=nachtrag.updated_at,
    )


def deckung_berechnen(db: Session, projekt: Projekt) -> Deckung:
    """Soll-Ist-Vergleich des Zahlungsplans (PLAN §6.12)."""
    plan = (
        db.scalar(
            select(func.sum(Zahlungsplanposition.betrag_netto)).where(
                Zahlungsplanposition.projekt_id == projekt.id
            )
        )
        or 0
    )
    nachtraege = (
        db.scalar(
            select(func.sum(Nachtrag.betrag_netto)).where(
                Nachtrag.projekt_id == projekt.id, Nachtrag.status.in_(NACHTRAG_ZAEHLT)
            )
        )
        or 0
    )
    soll = None if projekt.ab_wert_netto is None else projekt.ab_wert_netto + int(nachtraege)
    return Deckung(
        ab_wert_netto=projekt.ab_wert_netto,
        nachtraege_netto=int(nachtraege),
        soll_netto=soll,
        zahlungsplan_netto=int(plan),
        differenz_netto=None if soll is None else soll - int(plan),
    )


def _werte_pruefen(zugriff: Zugriff) -> None:
    """Ohne ``projekte.werte_lesen`` gibt es keinen Zahlungsplan – auch nicht zum Ändern.

    Die Rolle mit ``zahlungsplan.schreiben``, aber ohne Werterecht gibt es im Seed nicht; sie
    entsteht, sobald jemand eine eigene Rolle anlegt. Ein Zahlungsplan, den man nicht lesen darf,
    lässt sich nicht sinnvoll bearbeiten: jede Änderung wäre ein Schuss ins Dunkle.
    """
    if not zugriff.darf("projekte.werte_lesen"):
        raise Konflikt(
            "Zum Bearbeiten des Zahlungsplans fehlt die Berechtigung, Beträge zu sehen.",
            "Die Buchhaltung oder die Geschäftsführung kann den Zahlungsplan pflegen.",
            code="werte_ohne_berechtigung",
        )


def _naechste_pos_nr(db: Session, projekt_id: int) -> int:
    hoechste = db.scalar(
        select(func.max(Zahlungsplanposition.pos_nr)).where(
            Zahlungsplanposition.projekt_id == projekt_id
        )
    )
    return (hoechste or 0) + 1


def _zustand(position: Zahlungsplanposition) -> dict[str, object]:
    return {
        feld: getattr(position, feld)
        for feld in (
            "pos_nr",
            "bezeichnung",
            "gewerk",
            "art",
            "betrag_netto",
            "plan_monat",
            "trigger_status",
            "migriert_gestellt",
        )
    }


def _nachtrag_zustand(nachtrag: Nachtrag) -> dict[str, object]:
    return {
        feld: getattr(nachtrag, feld) for feld in ("bezeichnung", "betrag_netto", "status", "datum")
    }


@router.post(
    "/projekte/{projekt_nr}/zahlungsplan",
    response_model=PositionAntwort,
    status_code=201,
    summary="Zahlungsplanposition anlegen",
    operation_id="zahlungsplanAnlegen",
    responses=SCHREIBEN,
)
def position_anlegen(
    projekt_nr: int,
    eingabe: PositionEingabe,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> PositionAntwort:
    _werte_pruefen(zugriff)
    projekt = _projekt_holen(db, projekt_nr, zugriff)

    position = Zahlungsplanposition(
        projekt_id=projekt.id,
        pos_nr=_naechste_pos_nr(db, projekt.id),
        **eingabe.model_dump(),
    )
    db.add(position)
    db.flush()
    audit.eintragen(
        db,
        "zahlungsplan.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="zahlungsplan",
        datensatz_id=position.id,
        neu={"projekt_nr": projekt.projekt_nr, **_zustand(position)},
    )
    db.commit()
    log.info("Zahlungsplanposition %s an Projekt %s angelegt", position.pos_nr, projekt.projekt_nr)
    return _als_antwort(position)


@router.put(
    "/zahlungsplan/{position_id}",
    response_model=PositionAntwort,
    summary="Zahlungsplanposition ändern",
    operation_id="zahlungsplanAendern",
    responses=SCHREIBEN,
)
def position_aendern(
    position_id: int,
    eingabe: PositionAendern,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> PositionAntwort:
    _werte_pruefen(zugriff)
    position = _position_holen(db, position_id, zugriff)
    stand_pruefen(position, eingabe.stand, "Die Zahlungsplanposition")

    grund = _sperrgrund(position)
    if grund:
        raise Konflikt(
            grund,
            "Für eine Korrektur zuerst die Sperre auflösen: Beleg stornieren (ab Phase 3) oder "
            "das Kennzeichen „gestellt“ zurücknehmen.",
            code=(
                "zahlungsplan_berechnet"
                if position.rechnung_id is not None
                else "zahlungsplan_migriert_gestellt"
            ),
        )

    vorher = _zustand(position)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(position, feld, wert)
    unterschiede = geaenderte_felder(vorher, _zustand(position))
    if not unterschiede:
        return _als_antwort(position)

    audit.eintragen(
        db,
        "zahlungsplan.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="zahlungsplan",
        datensatz_id=position.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={
            "projekt_nr": position.projekt.projekt_nr,
            **{f: w["neu"] for f, w in unterschiede.items()},
        },
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Die Zahlungsplanposition")
        raise
    return _als_antwort(position)


@router.put(
    "/zahlungsplan/{position_id}/gestellt-zuruecknehmen",
    response_model=PositionAntwort,
    summary="Kennzeichen „gestellt“ einer migrierten Position zurücknehmen",
    operation_id="zahlungsplanGestelltZuruecknehmen",
    responses=SCHREIBEN,
)
def gestellt_zuruecknehmen(
    position_id: int,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> PositionAntwort:
    """Eigener Weg für eine eigene Entscheidung (docs/OFFENE-PUNKTE.md Nr. 5).

    Der Betrag einer migriert-gestellten Position zählt zum Umsatz eines vergangenen Monats. Ihn
    im Rahmen einer gewöhnlichen Änderung mitzuverschieben würde rückwirkend Umsatz zwischen
    Monaten bewegen, ohne dass es auffällt. Deshalb: erst das Kennzeichen zurücknehmen – ein
    eigener Aufruf, ein eigener Protokolleintrag –, danach ist die Position frei.
    """
    _werte_pruefen(zugriff)
    position = _position_holen(db, position_id, zugriff)

    if position.rechnung_id is not None:
        raise Konflikt(
            "Zu dieser Position ist eine Rechnung festgeschrieben.",
            "Änderungen sind nur über den Storno des Belegs möglich.",
            code="zahlungsplan_berechnet",
        )
    if not position.migriert_gestellt:
        raise Konflikt(
            "Diese Position ist nicht als „gestellt“ gekennzeichnet.",
            "Sie lässt sich unmittelbar bearbeiten.",
            code="zahlungsplan_nicht_gestellt",
        )

    position.migriert_gestellt = None
    audit.eintragen(
        db,
        "zahlungsplan.gestellt_zurueckgenommen",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="zahlungsplan",
        datensatz_id=position.id,
        alt={"migriert_gestellt": True},
        neu={
            "projekt_nr": position.projekt.projekt_nr,
            "pos_nr": position.pos_nr,
            "betrag_netto": position.betrag_netto,
            "plan_monat": position.plan_monat,
            "migriert_gestellt": None,
            "herkunft": position.quelle_migration,
        },
    )
    db.commit()
    log.info(
        "Kennzeichen 'gestellt' zurückgenommen: Projekt %s, Position %s",
        position.projekt.projekt_nr,
        position.pos_nr,
    )
    return _als_antwort(position)


@router.delete(
    "/zahlungsplan/{position_id}",
    status_code=204,
    summary="Zahlungsplanposition löschen",
    operation_id="zahlungsplanLoeschen",
    responses=SCHREIBEN,
)
def position_loeschen(
    position_id: int,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> None:
    """Löschen ist hier erlaubt – solange keine Sperre greift.

    Eine offene Zahlungsplanposition ist eine Planung, kein Beleg: an ihr hängt nichts, und eine
    Planung, die sich nicht korrigieren lässt, wäre in der Maske unbrauchbar. Berechnete und
    migriert-gestellte Positionen sind dagegen Umsatz und bleiben (CLAUDE.md Regel 5).
    """
    _werte_pruefen(zugriff)
    position = _position_holen(db, position_id, zugriff)

    grund = _sperrgrund(position)
    if grund:
        raise Konflikt(
            grund,
            "Für eine Korrektur zuerst die Sperre auflösen: Beleg stornieren (ab Phase 3) oder "
            "das Kennzeichen „gestellt“ zurücknehmen.",
            code=(
                "zahlungsplan_berechnet"
                if position.rechnung_id is not None
                else "zahlungsplan_migriert_gestellt"
            ),
        )

    audit.eintragen(
        db,
        "zahlungsplan.geloescht",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="zahlungsplan",
        datensatz_id=position.id,
        alt={"projekt_nr": position.projekt.projekt_nr, **_zustand(position)},
    )
    db.delete(position)
    db.commit()


@router.post(
    "/projekte/{projekt_nr}/nachtraege",
    response_model=NachtragAntwort,
    status_code=201,
    summary="Nachtrag anlegen",
    operation_id="nachtragAnlegen",
    responses=SCHREIBEN,
)
def nachtrag_anlegen(
    projekt_nr: int,
    eingabe: NachtragEingabe,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> NachtragAntwort:
    _werte_pruefen(zugriff)
    projekt = _projekt_holen(db, projekt_nr, zugriff)

    nachtrag = Nachtrag(projekt_id=projekt.id, **eingabe.model_dump())
    db.add(nachtrag)
    db.flush()
    audit.eintragen(
        db,
        "nachtrag.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="nachtraege",
        datensatz_id=nachtrag.id,
        neu={"projekt_nr": projekt.projekt_nr, **_nachtrag_zustand(nachtrag)},
    )
    db.commit()
    return _nachtrag_antwort(nachtrag)


@router.put(
    "/nachtraege/{nachtrag_id}",
    response_model=NachtragAntwort,
    summary="Nachtrag ändern",
    operation_id="nachtragAendern",
    responses=SCHREIBEN,
)
def nachtrag_aendern(
    nachtrag_id: int,
    eingabe: NachtragAendern,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> NachtragAntwort:
    _werte_pruefen(zugriff)
    nachtrag = _nachtrag_holen(db, nachtrag_id, zugriff)
    stand_pruefen(nachtrag, eingabe.stand, "Der Nachtrag")

    if nachtrag.status == "berechnet" and eingabe.status != "berechnet":
        # Ab Phase 3 hängt am berechneten Nachtrag ein Beleg. Den Status zurückzudrehen würde
        # den Umsatz-Ist verändern, ohne den Beleg anzufassen.
        raise Konflikt(
            "Ein berechneter Nachtrag lässt sich nicht auf „angeboten“ oder „beauftragt“ "
            "zurücksetzen.",
            "Für eine Korrektur die zugehörige Rechnung stornieren (ab Phase 3).",
            code="nachtrag_berechnet",
        )

    vorher = _nachtrag_zustand(nachtrag)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(nachtrag, feld, wert)
    unterschiede = geaenderte_felder(vorher, _nachtrag_zustand(nachtrag))
    if not unterschiede:
        return _nachtrag_antwort(nachtrag)

    audit.eintragen(
        db,
        "nachtrag.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="nachtraege",
        datensatz_id=nachtrag.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={
            "projekt_nr": nachtrag.projekt.projekt_nr,
            **{f: w["neu"] for f, w in unterschiede.items()},
        },
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Der Nachtrag")
        raise
    return _nachtrag_antwort(nachtrag)


@router.delete(
    "/nachtraege/{nachtrag_id}",
    status_code=204,
    summary="Nachtrag löschen",
    operation_id="nachtragLoeschen",
    responses=SCHREIBEN,
)
def nachtrag_loeschen(
    nachtrag_id: int,
    zugriff: Zugriff = Depends(benoetigt("zahlungsplan.schreiben")),
    db: Session = Depends(db_sitzung),
) -> None:
    """Angebotene und beauftragte Nachträge dürfen weg, berechnete nicht."""
    _werte_pruefen(zugriff)
    nachtrag = _nachtrag_holen(db, nachtrag_id, zugriff)

    if nachtrag.status == "berechnet":
        raise Konflikt(
            "Ein berechneter Nachtrag kann nicht gelöscht werden.",
            "Für eine Korrektur die zugehörige Rechnung stornieren (ab Phase 3).",
            code="nachtrag_berechnet",
        )

    audit.eintragen(
        db,
        "nachtrag.geloescht",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="nachtraege",
        datensatz_id=nachtrag.id,
        alt={"projekt_nr": nachtrag.projekt.projekt_nr, **_nachtrag_zustand(nachtrag)},
    )
    db.delete(nachtrag)
    db.commit()
