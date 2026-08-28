"""Stückliste und Mengen-Ist-Bestätigung eines Projekts (PLAN §6.5, §7 Phase 4).

Die Stückliste kommt aus dem Kalkulationsblatt (:mod:`app.importe.kalkulationsblatt`) und wird
hier nicht angelegt, sondern nur um die **gezählte Menge** ergänzt. Deshalb gibt es keine Route
zum Anlegen und keine zum Löschen: was in der Liste steht, entscheidet die Kalkulation.

Zwei Dinge, die die Route von einer gewöhnlichen Bearbeitungsmaske unterscheiden:

* **Bestätigen heißt bewerten.** Mit der Menge wird sofort der Wert der Lagerentnahme gerechnet
  und als Ist-Kosten geschrieben (PLAN §6.5). Ein Zwischenzustand, in dem die Menge steht und der
  Betrag nicht, wäre eine Nachkalkulation, die zu gut aussieht.
* **Nur Lagerpositionen tragen einen Betrag.** Projektbestelltes Material kommt über DATEV; die
  Menge darf trotzdem bestätigt werden, sie ist dann eine Zählung ohne Wertansatz.

Berechtigung: ``projekte.schreiben``. Die Mengenbestätigung ist Projektpflege, keine
Finanzsicht – wer sie ausfüllt, muss deswegen keine Margen sehen dürfen (PLAN §4).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.dienste import stueckliste as dienst
from app.dienste.konflikt import konflikt_uebersetzen, stand_pruefen
from app.fehler import NichtGefunden
from app.modelle import Projekt, Stuecklistenposition
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, scope_filter

log = logger(__name__)

router = APIRouter(prefix="/api/projekte", tags=["Stückliste"])

ANTWORTEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung projekte.schreiben fehlt"},
    404: {"description": "Projekt oder Position nicht gefunden"},
    409: {"description": "Position zwischenzeitlich geändert"},
}


class PositionAntwort(BaseModel):
    id: int
    artikel_nr: str | None
    bezeichnung: str
    menge_soll: Decimal
    menge_ist: Decimal | None
    ek_preis: int | None
    quelle: str
    gewerk: str | None
    bewertet_betrag: int | None
    stand: datetime

    @property
    def bewertbar(self) -> bool:
        return self.quelle == "lager"


class MengeEingabe(BaseModel):
    id: int
    menge_ist: Decimal = Field(ge=0, le=Decimal("999999999"))
    stand: datetime


class MengenBestaetigen(BaseModel):
    positionen: list[MengeEingabe] = Field(min_length=1)


class BewertungAntwort(BaseModel):
    projekt_nr: int
    monat: str
    lagerpositionen: int
    bewertet: int
    ohne_preis: int
    betrag_cent: int
    offene_mengen: bool
    positionen: list[PositionAntwort]
    meldung: str


def _als_antwort(position: Stuecklistenposition) -> PositionAntwort:
    return PositionAntwort(
        id=position.id,
        artikel_nr=position.artikel_nr,
        bezeichnung=position.bezeichnung,
        menge_soll=Decimal(str(position.menge_soll)),
        menge_ist=None if position.menge_ist is None else Decimal(str(position.menge_ist)),
        ek_preis=position.ek_preis,
        quelle=position.quelle,
        gewerk=position.gewerk,
        bewertet_betrag=position.bewertet_betrag,
        stand=position.updated_at,
    )


def _projekt_holen(db: Session, projekt_nr: int, zugriff: Zugriff) -> Projekt:
    projekt = db.scalar(
        scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id).where(
            Projekt.projekt_nr == projekt_nr
        )
    )
    if projekt is None:
        raise NichtGefunden(
            f"Es gibt kein Projekt mit der Nummer {projekt_nr}.",
            "Die Projektnummer prüfen. Möglicherweise ist das Projekt einem anderen "
            "Projektleiter zugeordnet.",
        )
    return projekt


def _positionen(db: Session, projekt: Projekt) -> list[Stuecklistenposition]:
    return list(
        db.scalars(
            select(Stuecklistenposition)
            .where(Stuecklistenposition.projekt_id == projekt.id)
            .order_by(Stuecklistenposition.id)
        )
    )


@router.get(
    "/{projekt_nr}/stueckliste",
    response_model=list[PositionAntwort],
    summary="Stückliste eines Projekts",
    operation_id="stuecklisteLesen",
    responses={401: {"description": "Nicht angemeldet"}, 404: {"description": "Nicht gefunden"}},
)
def stueckliste_lesen(
    projekt_nr: int,
    zugriff: Zugriff = Depends(benoetigt("projekte.lesen")),
    db: Session = Depends(db_sitzung),
) -> list[PositionAntwort]:
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    return [_als_antwort(p) for p in _positionen(db, projekt)]


@router.post(
    "/{projekt_nr}/mengen-ist",
    response_model=BewertungAntwort,
    summary="Mengen-Ist bestätigen und die Lagerpositionen bewerten",
    operation_id="mengenIstBestaetigen",
    responses=ANTWORTEN,
)
def mengen_ist_bestaetigen(
    projekt_nr: int,
    eingabe: MengenBestaetigen,
    zugriff: Zugriff = Depends(benoetigt("projekte.schreiben")),
    db: Session = Depends(db_sitzung),
) -> BewertungAntwort:
    """Gezählte Mengen übernehmen und die Lagerentnahme bewerten (PLAN §6.5).

    Beides in einem Schritt: eine bestätigte Menge ohne Bewertung wäre eine Nachkalkulation, die
    zu gut aussieht. Bewertet werden ausschließlich Positionen mit ``quelle='lager'`` – die
    Doppelbelastungssperre sitzt im Dienst, nicht hier.
    """
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    vorhanden = {p.id: p for p in _positionen(db, projekt)}

    alt: dict[str, object] = {}
    neu: dict[str, object] = {}
    for angabe in eingabe.positionen:
        position = vorhanden.get(angabe.id)
        if position is None:
            raise NichtGefunden(
                f"Zur Position {angabe.id} gibt es in diesem Projekt keinen Eintrag.",
                "Die Stückliste neu laden. Möglicherweise wurde das Kalkulationsblatt "
                "zwischenzeitlich erneut eingelesen.",
            )
        stand_pruefen(position, angabe.stand, "Die Stücklistenposition")
        if position.menge_ist != angabe.menge_ist:
            schluessel = position.artikel_nr or position.bezeichnung
            alt[schluessel] = None if position.menge_ist is None else str(position.menge_ist)
            neu[schluessel] = str(angabe.menge_ist)
        position.menge_ist = angabe.menge_ist

    bewertung = dienst.bewerten(db, projekt)

    audit.eintragen(
        db,
        "stueckliste.mengen_bestaetigt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="stueckliste",
        datensatz_id=projekt.id,
        alt=alt,
        neu={
            "projekt_nr": projekt.projekt_nr,
            "monat": bewertung.monat,
            "bewertet_cent": bewertung.betrag_cent,
            **neu,
        },
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Die Stücklistenposition")
        raise

    log.info(
        "Mengen-Ist bestätigt: Projekt %s, %d Lagerpositionen, %d Cent",
        projekt.projekt_nr,
        bewertung.bewertet,
        bewertung.betrag_cent,
    )
    return _antwort_bauen(db, projekt, bewertung)


def _antwort_bauen(db: Session, projekt: Projekt, bewertung: dienst.Bewertung) -> BewertungAntwort:
    offen = dienst.hat_offene_mengen(db, projekt)
    if bewertung.ohne_preis:
        meldung = (
            f"{bewertung.bewertet} Lagerpositionen bewertet. "
            f"{bewertung.ohne_preis} Positionen haben keinen Einkaufspreis und fehlen damit im "
            "Ist – der Preis gehört ins Kalkulationsblatt."
        )
    elif offen:
        meldung = (
            f"{bewertung.bewertet} Lagerpositionen bewertet. Es stehen noch Mengen aus; "
            "solange gilt für sie die kalkulierte Menge."
        )
    else:
        meldung = f"{bewertung.bewertet} Lagerpositionen bewertet, alle Mengen sind bestätigt."

    return BewertungAntwort(
        projekt_nr=projekt.projekt_nr,
        monat=bewertung.monat,
        lagerpositionen=bewertung.lagerpositionen,
        bewertet=bewertung.bewertet,
        ohne_preis=bewertung.ohne_preis,
        betrag_cent=bewertung.betrag_cent,
        offene_mengen=offen,
        positionen=[_als_antwort(p) for p in _positionen(db, projekt)],
        meldung=meldung,
    )
