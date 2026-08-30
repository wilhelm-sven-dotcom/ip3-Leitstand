"""Belege: Liste, Entwurf, Erzeugung, Festschreibung, Storno (PLAN §7 Phase 3, §10).

Gerechnet und erzeugt wird in ``app/dienste/belege.py``, ``belegarten.py`` und
``festschreibung.py``. Hier steht, wer was darf, wie die Antwort aussieht und wo eine Sperre zu
einer verständlichen Meldung wird.

Vier Berechtigungen, absichtlich getrennt (PLAN §4):

* ``rechnungen.lesen`` – Belege ansehen,
* ``rechnungen.erstellen`` – Entwürfe anlegen und ändern,
* ``rechnungen.festschreiben`` – der unumkehrbare Schritt,
* ``rechnungen.stornieren`` – Storno und Gutschrift.

Die Buchhaltung darf im Seed festschreiben, aber **nicht** stornieren: eine Korrektur an einem
bereits gestellten Beleg ist eine Entscheidung der Geschäftsführung.

Der Sichtbarkeits-Scope wirkt über das Projekt: wer nur eigene Projekte sehen darf, sieht auch nur
deren Belege. Belege ohne Projekt (Servicerechnungen) sieht nur, wer den Scope ``alle`` hat – ein
Beleg ohne Projekt hat keinen Projektleiter, an dem sich „eigene" festmachen ließe.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.datenbank import schreib_transaktion
from app.datenbank_sperren import sperren_uebersetzen
from app.dienste.belegarten import (
    ab_aus_projekt,
    abschlag_aus_position,
    gutschrift,
    offene_vorschlaege,
    schlussrechnung,
    servicerechnung,
    storno,
    summen_setzen,
)
from app.dienste.belege import steuer_hinweise
from app.dienste.dokumente import TYP_TEXT, fehlende_pflicht
from app.dienste.festschreibung import ablage_wiederholen, dateien_ablegen, festschreiben
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.fehler import Konflikt, NichtGefunden
from app.modelle import Kunde, Projekt, Rechnung, Rechnungsposition
from app.modelle.fakturierung import BELEG_STATUS, BELEGARTEN
from app.modelle.projekte import UST_KENNZEICHEN
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, scope_filter
from app.zeit import heute_ortszeit

log = logger(__name__)

router = APIRouter(prefix="/api/rechnungen", tags=["Fakturierung"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung rechnungen.lesen fehlt"},
    404: {"description": "Beleg nicht gefunden"},
}
SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung fehlt"},
    404: {"description": "Beleg, Projekt oder Position nicht gefunden"},
    409: {"description": "Beleg gesperrt, unvollständig oder zwischenzeitlich geändert"},
}

# Filterwerte der Belegliste. Als Literal statt als freier Text: ein Tippfehler ergibt dann eine
# Meldung und nicht eine leere Liste, die wie „keine Belege" aussieht.
ART_FILTER = ("alle", *BELEGARTEN)
STATUS_FILTER = ("alle", *BELEG_STATUS)


# ---------------------------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------------------------


class PositionEingabe(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=1000)
    menge: Decimal = Field(default=Decimal(1), max_digits=12, decimal_places=3)
    einheit: str | None = Field(default=None, max_length=50)
    ep_netto: int
    # Steuersatz in Promille (190 für 19 %, 0 für 0 %). Promille, damit auch 7,5 % ohne
    # Gleitkomma darstellbar bleibt (PLAN §6.2).
    ust_satz: int = Field(default=190, ge=0, le=1000)

    @field_validator("bezeichnung")
    @classmethod
    def leerraum_kuerzen(cls, wert: str) -> str:
        gekuerzt = wert.strip()
        if not gekuerzt:
            raise ValueError("Die Bezeichnung darf nicht leer sein.")
        return gekuerzt


class PositionAntwort(BaseModel):
    id: int
    pos: int
    bezeichnung: str
    menge: Decimal
    einheit: str | None = None
    ep_netto: int
    ust_satz: int
    netto: int
    zahlungsplan_id: int | None = None


class AbsetzungAntwort(BaseModel):
    pos: int
    rechnung_nr: str
    datum: date
    netto: int
    ust_satz: int
    ust: int
    brutto: int


class SatzAntwort(BaseModel):
    satz: int
    netto: int
    ust: int


class KopfEingabe(BaseModel):
    """Was an einem Entwurf von Hand änderbar ist."""

    datum: date
    leistungszeitraum: str | None = Field(default=None, max_length=200)
    faellig_am: date | None = None
    ust_kz: Literal[UST_KENNZEICHEN]  # type: ignore[valid-type]
    betreff: str | None = Field(default=None, max_length=200)
    anschreiben: str | None = Field(default=None, max_length=1000)
    schlusstext: str | None = Field(default=None, max_length=1000)


class KopfAendern(KopfEingabe):
    stand: datetime


class BelegAntwort(BaseModel):
    id: int
    rechnung_nr: str | None = None
    art: str
    status: str
    projekt_id: int | None = None
    projekt_nr: int | None = None
    kunde_id: int
    kunde_name: str
    kunde_snapshot: dict | None = None
    abschlag_nr: int | None = None
    datum: date
    leistungszeitraum: str | None = None
    faellig_am: date | None = None
    ust_kz: str
    betreff: str | None = None
    anschreiben: str | None = None
    schlusstext: str | None = None
    netto: int
    ust: int
    brutto: int
    absetzung_netto: int
    absetzung_ust: int
    zahlbetrag: int
    ust_details: list[SatzAntwort] = Field(default_factory=list)
    steuer_hinweise: list[str] = Field(default_factory=list)
    positionen: list[PositionAntwort] = Field(default_factory=list)
    absetzungen: list[AbsetzungAntwort] = Field(default_factory=list)
    hash: str | None = None
    festgeschrieben_am: datetime | None = None
    pdf_pfad: str | None = None
    xml_pfad: str | None = None
    storno_ref: int | None = None
    storniert_durch_nr: str | None = None
    aenderbar: bool
    stand: datetime
    # Pflichtunterlagen, die im Projektordner fehlen (PLAN §7 Phase 7). Nur bei
    # Schlussrechnungen gefüllt und nur, wenn der Doku-Scan schon einmal gelaufen ist. Die
    # Maske zeigt sie an; gesperrt wird nichts (Entscheidung 50).
    fehlende_unterlagen: list[str] = Field(default_factory=list)


class FestschreibenEingabe(BaseModel):
    """Was beim Festschreiben zusätzlich mitkommen kann.

    Zurzeit genau ein Feld: die Bestätigung, dass eine Schlussrechnung auch ohne die
    Pflichtunterlagen im Projektordner rausgehen soll. Sie wird nur verlangt, wenn tatsächlich
    etwas fehlt, und landet im ``audit_log``.
    """

    unterlagen_bestaetigt: bool = False


class ZeileAntwort(BaseModel):
    """Ein Beleg in der Liste – ohne Positionen, dafür mit dem, wonach gefiltert wird."""

    id: int
    rechnung_nr: str | None = None
    art: str
    status: str
    datum: date
    faellig_am: date | None = None
    projekt_nr: int | None = None
    kunde_name: str
    betreff: str | None = None
    netto: int
    zahlbetrag: int
    aenderbar: bool


class ListeAntwort(BaseModel):
    zeilen: list[ZeileAntwort]
    anzahl: int
    summe_netto: int
    jahre: list[int]


class VorschlagAntwort(BaseModel):
    position_id: int
    projekt_id: int
    projekt_nr: int
    projekt_name: str | None = None
    pos_nr: int
    bezeichnung: str
    betrag_netto: int
    ausloeser: str
    erledigt_am: date | None = None


class ServiceEingabe(BaseModel):
    kunde_id: int
    projekt_nr: int | None = None
    datum: date | None = None
    leistungszeitraum: str | None = Field(default=None, max_length=200)
    ust_kz: Literal[UST_KENNZEICHEN] = "19"  # type: ignore[valid-type]


class ErzeugenEingabe(BaseModel):
    datum: date | None = None
    leistungszeitraum: str | None = Field(default=None, max_length=200)


class KorrekturEingabe(BaseModel):
    datum: date | None = None
    grund: str | None = Field(default=None, max_length=500)


class FestschreibenAntwort(BaseModel):
    beleg: BelegAntwort
    # Leer, wenn alles glatt lief. Sonst der Satz, der auf dem Bildschirm stehen darf: der Beleg
    # ist gültig, nur die Ablage fehlt noch.
    ablage_offen: str | None = None
    freigegebene_positionen: list[int] = Field(default_factory=list)
    berechnete_positionen: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# Sichtbarkeit
# ---------------------------------------------------------------------------------------------


def _sichtbar(abfrage: Select, zugriff: Zugriff) -> Select:
    """Belegabfrage auf die sichtbaren Projekte einschränken (PLAN §4).

    Belege ohne Projekt bleiben nur bei Scope ``alle`` sichtbar: ohne Projekt gibt es keinen
    Projektleiter, an dem sich „eigene" festmachen ließe. Sie zu zeigen wäre eine stille
    Ausweitung des Scopes.
    """
    if not zugriff.nur_eigene("projekte.lesen"):
        return abfrage
    eigene = select(Projekt.id).where(Projekt.pl_user_id == zugriff.nutzer.id)
    return abfrage.where(Rechnung.projekt_id.in_(eigene))


def _beleg_holen(db: Session, beleg_id: int, zugriff: Zugriff) -> Rechnung:
    beleg = db.scalar(_sichtbar(select(Rechnung).where(Rechnung.id == beleg_id), zugriff))
    if beleg is None:
        raise NichtGefunden(
            "Der Beleg wurde nicht gefunden.",
            "Die Belegliste öffnen. Wenn der Beleg zu einem Projekt gehört, das Sie nicht sehen "
            "dürfen, wenden Sie sich an Sven oder Michael.",
        )
    return beleg


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
            f"Projekt {projekt_nr} wurde nicht gefunden.", "Die Projektliste öffnen."
        )
    return projekt


def _entwurf_pruefen(beleg: Rechnung) -> None:
    if beleg.status != "entwurf":
        raise Konflikt(
            f"Beleg {beleg.rechnung_nr} ist festgeschrieben und kann nicht mehr geändert werden.",
            "Für eine Korrektur einen Storno oder eine Gutschrift erzeugen und den Beleg neu "
            "ausstellen. Das verlangen die GoBD.",
            code="beleg_festgeschrieben",
        )


# ---------------------------------------------------------------------------------------------
# Antwortaufbau
# ---------------------------------------------------------------------------------------------


def _als_position(position: Rechnungsposition) -> PositionAntwort:
    from app.geld import position_netto

    return PositionAntwort(
        id=position.id,
        pos=position.pos,
        bezeichnung=position.bezeichnung,
        menge=position.menge,
        einheit=position.einheit,
        ep_netto=position.ep_netto,
        ust_satz=position.ust_satz,
        netto=position_netto(position.menge, position.ep_netto),
        zahlungsplan_id=position.zahlungsplan_id,
    )


def _fehlende_unterlagen(db: Session, beleg: Rechnung) -> list[str]:
    """Welche Pflichtunterlagen dem Projekt dieser Schlussrechnung fehlen.

    Nur für ``schluss``: eine Abschlagsrechnung geht raus, während gebaut wird – dort eine
    Anlagendokumentation zu verlangen wäre unsinnig. Ein festgeschriebener Beleg fragt gar
    nicht mehr, er ist ohnehin unveränderbar.
    """
    if beleg.art != "schluss" or beleg.projekt_id is None or beleg.status != "entwurf":
        return []
    return fehlende_pflicht(db, beleg.projekt_id)


def _als_antwort(beleg: Rechnung, db: Session | None = None) -> BelegAntwort:
    snapshot = beleg.kunde_snapshot or {}
    return BelegAntwort(
        id=beleg.id,
        rechnung_nr=beleg.rechnung_nr,
        art=beleg.art,
        status=beleg.status,
        projekt_id=beleg.projekt_id,
        projekt_nr=beleg.projekt.projekt_nr if beleg.projekt else None,
        kunde_id=beleg.kunde_id,
        kunde_name=snapshot.get("name") or (beleg.kunde.name if beleg.kunde else ""),
        kunde_snapshot=beleg.kunde_snapshot,
        abschlag_nr=beleg.abschlag_nr,
        datum=beleg.datum,
        leistungszeitraum=beleg.leistungszeitraum,
        faellig_am=beleg.faellig_am,
        ust_kz=beleg.ust_kz,
        betreff=beleg.betreff,
        anschreiben=beleg.anschreiben,
        schlusstext=beleg.schlusstext,
        netto=beleg.netto,
        ust=beleg.ust,
        brutto=beleg.brutto,
        absetzung_netto=beleg.absetzung_netto,
        absetzung_ust=beleg.absetzung_ust,
        zahlbetrag=beleg.zahlbetrag,
        ust_details=[SatzAntwort(**anteil) for anteil in (beleg.ust_details or [])],
        steuer_hinweise=steuer_hinweise(
            beleg.ust_kz, list(beleg.positionen), mit_absetzung=bool(beleg.absetzungen)
        ),
        positionen=[_als_position(p) for p in beleg.positionen],
        absetzungen=[
            AbsetzungAntwort(
                pos=eintrag.pos,
                rechnung_nr=eintrag.rechnung_nr,
                datum=eintrag.datum,
                netto=eintrag.netto,
                ust_satz=eintrag.ust_satz,
                ust=eintrag.ust,
                brutto=eintrag.brutto,
            )
            for eintrag in beleg.absetzungen
        ],
        hash=beleg.hash,
        festgeschrieben_am=beleg.festgeschrieben_am,
        pdf_pfad=beleg.pdf_pfad,
        xml_pfad=beleg.xml_pfad,
        storno_ref=beleg.storno_ref,
        storniert_durch_nr=(
            beleg.storniert_beleg.rechnung_nr
            if beleg.status == "storniert" and beleg.storniert_beleg
            else None
        ),
        aenderbar=beleg.ist_aenderbar,
        stand=beleg.updated_at,
        fehlende_unterlagen=_fehlende_unterlagen(db, beleg) if db is not None else [],
    )


def _als_zeile(beleg: Rechnung) -> ZeileAntwort:
    snapshot = beleg.kunde_snapshot or {}
    return ZeileAntwort(
        id=beleg.id,
        rechnung_nr=beleg.rechnung_nr,
        art=beleg.art,
        status=beleg.status,
        datum=beleg.datum,
        faellig_am=beleg.faellig_am,
        projekt_nr=beleg.projekt.projekt_nr if beleg.projekt else None,
        kunde_name=snapshot.get("name") or (beleg.kunde.name if beleg.kunde else ""),
        betreff=beleg.betreff,
        netto=beleg.netto,
        zahlbetrag=beleg.zahlbetrag,
        aenderbar=beleg.ist_aenderbar,
    )


def _zustand(beleg: Rechnung) -> dict[str, object]:
    return {
        feld: getattr(beleg, feld)
        for feld in (
            "datum",
            "leistungszeitraum",
            "faellig_am",
            "ust_kz",
            "betreff",
            "anschreiben",
            "schlusstext",
        )
    }


# ---------------------------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------------------------


@router.get(
    "",
    response_model=ListeAntwort,
    summary="Belege auflisten",
    operation_id="rechnungenListe",
    responses=LESEN,
)
def liste(
    jahr: int | None = Query(default=None, ge=2000, le=2100),
    art: Literal[ART_FILTER] = "alle",  # type: ignore[valid-type]
    status: Literal[STATUS_FILTER] = "alle",  # type: ignore[valid-type]
    projekt_nr: int | None = None,
    kunde_id: int | None = None,
    suche: str | None = Query(default=None, max_length=100),
    zugriff: Zugriff = Depends(benoetigt("rechnungen.lesen")),
    db: Session = Depends(db_sitzung),
) -> ListeAntwort:
    abfrage = _sichtbar(select(Rechnung), zugriff).outerjoin(
        Projekt, Projekt.id == Rechnung.projekt_id
    )
    if jahr is not None:
        abfrage = abfrage.where(
            Rechnung.datum >= date(jahr, 1, 1), Rechnung.datum <= date(jahr, 12, 31)
        )
    if art != "alle":
        abfrage = abfrage.where(Rechnung.art == art)
    if status != "alle":
        abfrage = abfrage.where(Rechnung.status == status)
    if projekt_nr is not None:
        abfrage = abfrage.where(Projekt.projekt_nr == projekt_nr)
    if kunde_id is not None:
        abfrage = abfrage.where(Rechnung.kunde_id == kunde_id)
    if suche:
        muster = f"%{suche.strip()}%"
        abfrage = abfrage.join(Kunde, Kunde.id == Rechnung.kunde_id).where(
            or_(
                Rechnung.rechnung_nr.ilike(muster),
                Rechnung.betreff.ilike(muster),
                Kunde.name.ilike(muster),
            )
        )

    belege = list(
        db.scalars(abfrage.order_by(Rechnung.datum.desc(), Rechnung.id.desc()).distinct()).unique()
    )
    # Die Jahresliste kommt aus den Daten, nicht aus einer festen Spanne: ein Jahr ohne Belege
    # gehört nicht in den Filter. Das aktuelle Jahr steht immer darin, sonst wäre der Filter im
    # Januar leer.
    jahre = {b.datum.year for b in db.scalars(_sichtbar(select(Rechnung), zugriff))}
    jahre.add(heute_ortszeit().year)
    return ListeAntwort(
        zeilen=[_als_zeile(beleg) for beleg in belege],
        anzahl=len(belege),
        summe_netto=sum(beleg.netto for beleg in belege),
        jahre=sorted(jahre, reverse=True),
    )


@router.get(
    "/vorschlaege",
    response_model=list[VorschlagAntwort],
    summary="Abschlagsvorschläge",
    operation_id="rechnungenVorschlaege",
    responses=LESEN,
)
def vorschlaege(
    zugriff: Zugriff = Depends(benoetigt("rechnungen.lesen")),
    db: Session = Depends(db_sitzung),
) -> list[VorschlagAntwort]:
    """Positionen, deren Auslöser erreicht ist (PLAN §6.8). Vorschlag, kein Automatikversand."""
    projekt_ids = None
    if zugriff.nur_eigene("projekte.lesen"):
        projekt_ids = list(
            db.scalars(select(Projekt.id).where(Projekt.pl_user_id == zugriff.nutzer.id))
        )
    return [VorschlagAntwort(**eintrag) for eintrag in offene_vorschlaege(db, projekt_ids)]


@router.get(
    "/{beleg_id}",
    response_model=BelegAntwort,
    summary="Beleg ansehen",
    operation_id="rechnungLesen",
    responses=LESEN,
)
def lesen(
    beleg_id: int,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.lesen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    return _als_antwort(_beleg_holen(db, beleg_id, zugriff), db)


# ---------------------------------------------------------------------------------------------
# Erzeugen
# ---------------------------------------------------------------------------------------------


def _neu_protokollieren(db: Session, zugriff: Zugriff, beleg: Rechnung, aktion: str) -> None:
    audit.eintragen(
        db,
        aktion,
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="rechnungen",
        datensatz_id=beleg.id,
        neu={
            "art": beleg.art,
            "projekt_id": beleg.projekt_id,
            "kunde_id": beleg.kunde_id,
            "netto": beleg.netto,
            "brutto": beleg.brutto,
        },
    )


@router.post(
    "/ab/{projekt_nr}",
    response_model=BelegAntwort,
    status_code=201,
    summary="Auftragsbestätigung erzeugen",
    operation_id="auftragsbestaetigungErzeugen",
    responses=SCHREIBEN,
)
def ab_erzeugen(
    projekt_nr: int,
    eingabe: ErzeugenEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    beleg = ab_aus_projekt(db, projekt.id, eingabe.datum, erstellt_von=zugriff.kennung)
    db.add(beleg)
    db.flush()
    _neu_protokollieren(db, zugriff, beleg, "beleg.ab_erzeugt")
    db.commit()
    log.info("Auftragsbestätigung zu Projekt %s als Entwurf angelegt", projekt_nr)
    return _als_antwort(beleg, db)


@router.post(
    "/aus-zahlungsplan/{position_id}",
    response_model=BelegAntwort,
    status_code=201,
    summary="Abschlagsrechnung aus einer Zahlungsplanposition erzeugen",
    operation_id="abschlagErzeugen",
    responses=SCHREIBEN,
)
def abschlag_erzeugen(
    position_id: int,
    eingabe: ErzeugenEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    from app.modelle import Zahlungsplanposition

    position = db.get(Zahlungsplanposition, position_id)
    if position is None:
        raise NichtGefunden(
            "Die Zahlungsplanposition wurde nicht gefunden.", "Den Zahlungsplan öffnen."
        )
    _projekt_holen(db, position.projekt.projekt_nr, zugriff)

    beleg = abschlag_aus_position(
        db,
        position_id,
        datum=eingabe.datum,
        leistungszeitraum=eingabe.leistungszeitraum,
        erstellt_von=zugriff.kennung,
    )
    db.add(beleg)
    db.flush()
    _neu_protokollieren(db, zugriff, beleg, "beleg.abschlag_erzeugt")
    db.commit()
    return _als_antwort(beleg, db)


@router.post(
    "/schlussrechnung/{projekt_nr}",
    response_model=BelegAntwort,
    status_code=201,
    summary="Schlussrechnung mit Absetzungsblock erzeugen",
    operation_id="schlussrechnungErzeugen",
    responses=SCHREIBEN,
)
def schlussrechnung_erzeugen(
    projekt_nr: int,
    eingabe: ErzeugenEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    beleg = schlussrechnung(
        db,
        projekt.id,
        datum=eingabe.datum,
        leistungszeitraum=eingabe.leistungszeitraum,
        erstellt_von=zugriff.kennung,
    )
    db.add(beleg)
    db.flush()
    _neu_protokollieren(db, zugriff, beleg, "beleg.schlussrechnung_erzeugt")
    db.commit()
    return _als_antwort(beleg, db)


@router.post(
    "/service",
    response_model=BelegAntwort,
    status_code=201,
    summary="Servicerechnung erzeugen",
    operation_id="servicerechnungErzeugen",
    responses=SCHREIBEN,
)
def service_erzeugen(
    eingabe: ServiceEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    from app.modelle import Firma

    projekt = (
        _projekt_holen(db, eingabe.projekt_nr, zugriff) if eingabe.projekt_nr is not None else None
    )
    firma_id = (
        projekt.firma_id if projekt else db.scalar(select(Firma.id).order_by(Firma.id).limit(1))
    )
    beleg = servicerechnung(
        db,
        eingabe.kunde_id,
        firma_id,
        projekt_id=projekt.id if projekt else None,
        datum=eingabe.datum,
        leistungszeitraum=eingabe.leistungszeitraum,
        ust_kz=eingabe.ust_kz,
        erstellt_von=zugriff.kennung,
    )
    db.add(beleg)
    db.flush()
    _neu_protokollieren(db, zugriff, beleg, "beleg.service_erzeugt")
    db.commit()
    return _als_antwort(beleg, db)


# ---------------------------------------------------------------------------------------------
# Entwurf pflegen
# ---------------------------------------------------------------------------------------------


@router.put(
    "/{beleg_id}",
    response_model=BelegAntwort,
    summary="Belegkopf ändern",
    operation_id="rechnungAendern",
    responses=SCHREIBEN,
)
def aendern(
    beleg_id: int,
    eingabe: KopfAendern,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    beleg = _beleg_holen(db, beleg_id, zugriff)
    stand_pruefen(beleg, eingabe.stand, "Der Beleg")
    _entwurf_pruefen(beleg)

    vorher = _zustand(beleg)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(beleg, feld, wert)
    summen_setzen(beleg)
    unterschiede = geaenderte_felder(vorher, _zustand(beleg))
    if not unterschiede:
        return _als_antwort(beleg, db)

    audit.eintragen(
        db,
        "beleg.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="rechnungen",
        datensatz_id=beleg.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={f: w["neu"] for f, w in unterschiede.items()},
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        sperren_uebersetzen(fehler)
        konflikt_uebersetzen(fehler, "Der Beleg")
        raise
    return _als_antwort(beleg, db)


@router.delete(
    "/{beleg_id}",
    status_code=204,
    summary="Entwurf verwerfen",
    operation_id="rechnungVerwerfen",
    responses=SCHREIBEN,
)
def verwerfen(
    beleg_id: int,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> None:
    """Einen Entwurf löschen.

    Zulässig, weil ein Entwurf noch keine Nummer trägt: es entsteht keine Lücke im Nummernkreis
    (PLAN §6.4). Festgeschriebene Belege sind unlöschbar – dafür gibt es den Storno.
    """
    beleg = _beleg_holen(db, beleg_id, zugriff)
    _entwurf_pruefen(beleg)
    audit.eintragen(
        db,
        "beleg.verworfen",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="rechnungen",
        datensatz_id=beleg.id,
        alt={"art": beleg.art, "netto": beleg.netto, "projekt_id": beleg.projekt_id},
    )
    db.delete(beleg)
    db.commit()


def _naechste_pos(beleg: Rechnung) -> int:
    return max((position.pos for position in beleg.positionen), default=0) + 1


@router.post(
    "/{beleg_id}/positionen",
    response_model=BelegAntwort,
    status_code=201,
    summary="Position anfügen",
    operation_id="rechnungPositionAnlegen",
    responses=SCHREIBEN,
)
def position_anlegen(
    beleg_id: int,
    eingabe: PositionEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    beleg = _beleg_holen(db, beleg_id, zugriff)
    _entwurf_pruefen(beleg)
    beleg.positionen.append(Rechnungsposition(pos=_naechste_pos(beleg), **eingabe.model_dump()))
    summen_setzen(beleg)
    db.flush()
    audit.eintragen(
        db,
        "beleg.position_angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="rechnungspos",
        datensatz_id=beleg.positionen[-1].id,
        neu={"rechnung_id": beleg.id, **eingabe.model_dump()},
    )
    db.commit()
    return _als_antwort(beleg, db)


@router.put(
    "/{beleg_id}/positionen/{position_id}",
    response_model=BelegAntwort,
    summary="Position ändern",
    operation_id="rechnungPositionAendern",
    responses=SCHREIBEN,
)
def position_aendern(
    beleg_id: int,
    position_id: int,
    eingabe: PositionEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    beleg = _beleg_holen(db, beleg_id, zugriff)
    _entwurf_pruefen(beleg)
    position = next((p for p in beleg.positionen if p.id == position_id), None)
    if position is None:
        raise NichtGefunden("Die Position gehört nicht zu diesem Beleg.", "Den Beleg neu laden.")
    alt = {
        "bezeichnung": position.bezeichnung,
        "ep_netto": position.ep_netto,
        "ust_satz": position.ust_satz,
    }
    for feld, wert in eingabe.model_dump().items():
        setattr(position, feld, wert)
    summen_setzen(beleg)
    audit.eintragen(
        db,
        "beleg.position_geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="rechnungspos",
        datensatz_id=position.id,
        alt=alt,
        neu=eingabe.model_dump(),
    )
    db.commit()
    return _als_antwort(beleg, db)


@router.delete(
    "/{beleg_id}/positionen/{position_id}",
    response_model=BelegAntwort,
    summary="Position entfernen",
    operation_id="rechnungPositionLoeschen",
    responses=SCHREIBEN,
)
def position_loeschen(
    beleg_id: int,
    position_id: int,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.erstellen")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    beleg = _beleg_holen(db, beleg_id, zugriff)
    _entwurf_pruefen(beleg)
    position = next((p for p in beleg.positionen if p.id == position_id), None)
    if position is None:
        raise NichtGefunden("Die Position gehört nicht zu diesem Beleg.", "Den Beleg neu laden.")
    audit.eintragen(
        db,
        "beleg.position_geloescht",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="rechnungspos",
        datensatz_id=position.id,
        alt={"bezeichnung": position.bezeichnung, "ep_netto": position.ep_netto},
    )
    beleg.positionen.remove(position)
    summen_setzen(beleg)
    db.commit()
    return _als_antwort(beleg, db)


# ---------------------------------------------------------------------------------------------
# Festschreiben, Storno, Gutschrift
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{beleg_id}/vorschau",
    summary="Beleg als PDF ansehen",
    operation_id="rechnungVorschau",
    responses={**LESEN, 200: {"content": {"application/pdf": {}}}},
    response_class=Response,
)
def vorschau(
    beleg_id: int,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.lesen")),
    db: Session = Depends(db_sitzung),
) -> Response:
    """PDF eines Belegs – für den Entwurf die Vorschau, für den festgeschriebenen die Ansicht.

    Immer neu gerendert, nie aus dem Rechnungsordner gelesen: das PDF eines festgeschriebenen
    Belegs entsteht aus den gespeicherten Daten und ist deshalb reproduzierbar, und eine Datei,
    die jemand im OneDrive ersetzt hat, soll hier nicht als Beleg erscheinen.
    """
    from app.belege.pdf import dateiname, pdf_erzeugen

    beleg = _beleg_holen(db, beleg_id, zugriff)
    name = dateiname(beleg)
    return Response(
        content=pdf_erzeugen(beleg),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


@router.post(
    "/{beleg_id}/ablage-wiederholen",
    response_model=BelegAntwort,
    summary="Ablage eines festgeschriebenen Belegs nachholen",
    operation_id="rechnungAblageWiederholen",
    responses=SCHREIBEN,
)
def ablage_nachholen(
    beleg_id: int,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.festschreiben")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    """PDF erneut erzeugen und im Rechnungsordner ablegen.

    Für den Fall, dass die Ablage beim Festschreiben scheiterte (Ordner nicht erreichbar). Am
    Beleg ändert sich dabei nichts: der Hash deckt die Belegdaten ab, nicht die PDF-Bytes.
    """
    from app.belege import ablage_aus_konfiguration

    beleg = _beleg_holen(db, beleg_id, zugriff)
    ablage = ablage_aus_konfiguration()
    if ablage is None:
        raise Konflikt(
            "Es ist kein Rechnungsordner konfiguriert.",
            "In der config.toml unter [pfade] den Eintrag rechnungen auf den Ordner "
            "01_Rechnungen setzen und den Dienst neu starten.",
            code="rechnungsordner_fehlt",
        )
    pfade = ablage_wiederholen(db, beleg, ablage)
    log.info("Ablage zu %s nachgeholt: %s", beleg.rechnung_nr, pfade.pdf_pfad)
    return _als_antwort(beleg, db)


@router.post(
    "/{beleg_id}/festschreiben",
    response_model=FestschreibenAntwort,
    summary="Beleg festschreiben",
    operation_id="rechnungFestschreiben",
    responses=SCHREIBEN,
)
def beleg_festschreiben(
    beleg_id: int,
    eingabe: FestschreibenEingabe | None = None,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.festschreiben")),
    db: Session = Depends(db_sitzung),
) -> FestschreibenAntwort:
    """Der unumkehrbare Schritt: Nummer, Hash, Sperre, Ablage (PLAN §6.4).

    Läuft in einer eigenen Schreibtransaktion (``BEGIN IMMEDIATE``), damit zwei gleichzeitige
    Festschreibungen nicht dieselbe Nummer bekommen. Die Dateien werden erst nach dem Commit
    geschrieben – scheitert das, bleibt der Beleg gültig und die Antwort sagt, was noch fehlt.

    Fehlen Pflichtunterlagen im Projektordner, verlangt der Leitstand eine ausdrückliche
    Bestätigung, bevor er eine Schlussrechnung festschreibt (Entscheidung 50). Er sperrt nicht:
    der Scan sieht nur Dateinamen, und was auf Papier vorliegt, dürfte eine berechtigte
    Rechnung nicht verhindern. Die Bestätigung steht im ``audit_log``.
    """
    from app.belege import ablage_aus_konfiguration

    beleg = _beleg_holen(db, beleg_id, zugriff)
    fehlend = _fehlende_unterlagen(db, beleg)
    bestaetigt = bool(eingabe and eingabe.unterlagen_bestaetigt)
    if fehlend and not bestaetigt:
        raise Konflikt(
            "Im Projektordner fehlen Unterlagen: "
            + ", ".join(TYP_TEXT.get(typ, typ) for typ in fehlend)
            + ".",
            "Die Unterlagen ablegen und den Ordner erneut prüfen lassen – oder das "
            "Festschreiben ausdrücklich bestätigen, wenn sie auf anderem Weg vorliegen.",
            code="unterlagen_fehlen",
        )
    ablage = ablage_aus_konfiguration()
    try:
        with schreib_transaktion(db):
            ergebnis = festschreiben(db, beleg, ablage=ablage, ausfuehrender=zugriff.kennung)
            audit.eintragen(
                db,
                "beleg.festgeschrieben",
                nutzer=zugriff.nutzer,
                ip=zugriff.ip,
                tabelle="rechnungen",
                datensatz_id=beleg.id,
                neu={
                    "rechnung_nr": beleg.rechnung_nr,
                    "art": beleg.art,
                    "netto": beleg.netto,
                    "ust": beleg.ust,
                    "brutto": beleg.brutto,
                    "zahlbetrag": beleg.zahlbetrag,
                    "hash": beleg.hash,
                },
            )
            if fehlend:
                audit.eintragen(
                    db,
                    "beleg.ohne_unterlagen_festgeschrieben",
                    nutzer=zugriff.nutzer,
                    ip=zugriff.ip,
                    tabelle="rechnungen",
                    datensatz_id=beleg.id,
                    neu={"rechnung_nr": beleg.rechnung_nr, "fehlende_unterlagen": fehlend},
                )
    except Exception as fehler:
        sperren_uebersetzen(fehler)
        raise

    ergebnis = dateien_ablegen(ablage, ergebnis)
    return FestschreibenAntwort(
        beleg=_als_antwort(beleg, db),
        ablage_offen=ergebnis.ablage_offen,
        freigegebene_positionen=ergebnis.freigegebene_positionen,
        berechnete_positionen=ergebnis.berechnete_positionen,
    )


@router.post(
    "/{beleg_id}/storno",
    response_model=BelegAntwort,
    status_code=201,
    summary="Stornobeleg erzeugen",
    operation_id="rechnungStorno",
    responses=SCHREIBEN,
)
def storno_erzeugen(
    beleg_id: int,
    eingabe: KorrekturEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.stornieren")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    """Storno als Entwurf. Wirksam wird er erst mit dem Festschreiben (PLAN §6.4)."""
    original = _beleg_holen(db, beleg_id, zugriff)
    beleg = storno(
        db, original.id, datum=eingabe.datum, grund=eingabe.grund, erstellt_von=zugriff.kennung
    )
    db.add(beleg)
    db.flush()
    _neu_protokollieren(db, zugriff, beleg, "beleg.storno_erzeugt")
    db.commit()
    log.info("Storno zu %s als Entwurf angelegt", original.rechnung_nr)
    return _als_antwort(beleg, db)


@router.post(
    "/{beleg_id}/gutschrift",
    response_model=BelegAntwort,
    status_code=201,
    summary="Gutschrift erzeugen",
    operation_id="rechnungGutschrift",
    responses=SCHREIBEN,
)
def gutschrift_erzeugen(
    beleg_id: int,
    eingabe: KorrekturEingabe,
    zugriff: Zugriff = Depends(benoetigt("rechnungen.stornieren")),
    db: Session = Depends(db_sitzung),
) -> BelegAntwort:
    """Teilkorrektur als Entwurf mit leeren Positionen (PLAN §6.14)."""
    original = _beleg_holen(db, beleg_id, zugriff)
    beleg = gutschrift(
        db, original.id, datum=eingabe.datum, grund=eingabe.grund, erstellt_von=zugriff.kennung
    )
    db.add(beleg)
    db.flush()
    _neu_protokollieren(db, zugriff, beleg, "beleg.gutschrift_erzeugt")
    db.commit()
    return _als_antwort(beleg, db)
