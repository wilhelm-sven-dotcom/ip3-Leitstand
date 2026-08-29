"""Kontenzuordnung und Fixkostenplanung pflegen (PLAN §5, §7 Phase 5).

Die beiden Tabellen, die das Firmen-Cockpit von Hand gefüttert bekommt:

* ``konten_mapping`` ordnet Kontenbereiche den Kostenblöcken zu. Erstbefüllung mit dem
  Steuerberater; danach kommt gelegentlich ein neues Konto dazu.
* ``fixkosten_plan`` trägt die geplanten Fixkosten für Monate, für die noch keine Summen- und
  Saldenliste vorliegt – also die Zukunft.

**Eine Änderung an der Zuordnung wirkt rückwirkend.** Nach jedem Schreiben werden die schon
eingelesenen Salden neu zugeordnet (:func:`app.dienste.konten.salden_neu_zuordnen`). Ohne das
zeigte das Cockpit für zwei Monate verschiedene Blöcke beim selben Konto, je nachdem wann
importiert wurde.

Berechtigung ist ``admin.konfiguration``: das ist eine Einstellung der Firma, keine
Projektarbeit. PLAN §4 führt Fixkosten ausdrücklich unter den Rechten der Geschäftsführung.
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.dienste import konten as kontendienst
from app.dienste.konflikt import stand_pruefen
from app.fehler import FachFehler, NichtGefunden
from app.modelle import FixkostenPlan, KontenMapping
from app.modelle.finanzen import KOSTENBLOECKE
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung

router = APIRouter(prefix="/api/kostenpflege", tags=["Kostenpflege"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung admin.konfiguration fehlt"},
}

SCHREIBEN = {**LESEN, 409: {"description": "Der Datensatz wurde zwischenzeitlich geändert"}}

_MONAT = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class BereichEingabe(BaseModel):
    konto_von: str = Field(min_length=1, max_length=20)
    konto_bis: str = Field(min_length=1, max_length=20)
    block: str

    @field_validator("konto_von", "konto_bis")
    @classmethod
    def nur_zahlen(cls, wert: str) -> str:
        gestrippt = wert.strip()
        if not gestrippt.isdigit():
            raise ValueError("Kontonummern bestehen nur aus Ziffern, z. B. '4100'.")
        return gestrippt

    @field_validator("block")
    @classmethod
    def bekannter_block(cls, wert: str) -> str:
        if wert not in KOSTENBLOECKE:
            raise ValueError(f"Unbekannter Kostenblock. Erlaubt: {', '.join(KOSTENBLOECKE)}.")
        return wert


class BereichAendern(BereichEingabe):
    stand: datetime | None = None


class BereichAntwort(BaseModel):
    id: int
    konto_von: str
    konto_bis: str
    block: str
    stand: datetime | None


class PlanEingabe(BaseModel):
    monat: str
    block: str
    betrag: int = Field(ge=0, description="Geplanter Monatsbetrag in Cent")
    bemerkung: str | None = None

    @field_validator("monat")
    @classmethod
    def monat_pruefen(cls, wert: str) -> str:
        if not _MONAT.match(wert):
            raise ValueError("Erwartet wird das Format JJJJ-MM, zum Beispiel 2026-07.")
        return wert

    @field_validator("block")
    @classmethod
    def bekannter_block(cls, wert: str) -> str:
        if wert not in KOSTENBLOECKE:
            raise ValueError(f"Unbekannter Kostenblock. Erlaubt: {', '.join(KOSTENBLOECKE)}.")
        return wert


class PlanAendern(BaseModel):
    betrag: int = Field(ge=0)
    bemerkung: str | None = None
    stand: datetime | None = None


class PlanAntwort(BaseModel):
    id: int
    monat: str
    block: str
    betrag: int
    bemerkung: str | None
    stand: datetime | None


class UebernahmeErgebnis(BaseModel):
    monat: str
    quelle_monat: str
    uebernommen: int
    uebersprungen: int


def _bereich_antwort(eintrag: KontenMapping) -> BereichAntwort:
    return BereichAntwort(
        id=eintrag.id,
        konto_von=eintrag.konto_von,
        konto_bis=eintrag.konto_bis,
        block=eintrag.block,
        stand=eintrag.updated_at,
    )


def _plan_antwort(eintrag: FixkostenPlan) -> PlanAntwort:
    return PlanAntwort(
        id=eintrag.id,
        monat=eintrag.monat,
        block=eintrag.block,
        betrag=eintrag.betrag,
        bemerkung=eintrag.bemerkung,
        stand=eintrag.updated_at,
    )


def _grenzen_pruefen(eingabe: BereichEingabe) -> None:
    if int(eingabe.konto_von) > int(eingabe.konto_bis):
        raise FachFehler(
            f"Der Bereich {eingabe.konto_von}–{eingabe.konto_bis} ist verkehrt herum.",
            "Die kleinere Kontonummer gehört nach vorn.",
            code="kontenbereich_verkehrt",
        )


def _voriger_monat(monat: str) -> str:
    jahr, nummer = (int(teil) for teil in monat.split("-"))
    return f"{jahr - 1}-12" if nummer == 1 else f"{jahr}-{nummer - 1:02d}"


# ---------------------------------------------------------------------------
# Kontenzuordnung
# ---------------------------------------------------------------------------


@router.get(
    "/konten",
    response_model=list[BereichAntwort],
    summary="Zuordnung der Kontenbereiche zu Kostenblöcken",
    operation_id="kontenBereiche",
    responses=LESEN,
)
def bereiche(
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> list[BereichAntwort]:
    eintraege = db.scalars(
        select(KontenMapping).order_by(KontenMapping.konto_von, KontenMapping.konto_bis)
    )
    return [_bereich_antwort(e) for e in eintraege]


@router.post(
    "/konten",
    response_model=BereichAntwort,
    status_code=status.HTTP_201_CREATED,
    summary="Kontenbereich zuordnen",
    operation_id="kontenBereichAnlegen",
    responses=SCHREIBEN,
)
def bereich_anlegen(
    eingabe: BereichEingabe,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> BereichAntwort:
    """Neuen Bereich anlegen und die vorhandenen Salden neu zuordnen."""
    _grenzen_pruefen(eingabe)
    vorhanden = db.scalar(
        select(KontenMapping).where(
            KontenMapping.konto_von == eingabe.konto_von,
            KontenMapping.konto_bis == eingabe.konto_bis,
        )
    )
    if vorhanden is not None:
        raise FachFehler(
            f"Der Bereich {eingabe.konto_von}–{eingabe.konto_bis} ist bereits zugeordnet "
            f"(Block '{vorhanden.block}').",
            "Den vorhandenen Eintrag ändern statt einen zweiten anzulegen.",
            code="kontenbereich_doppelt",
        )

    eintrag = KontenMapping(**eingabe.model_dump())
    db.add(eintrag)
    db.flush()
    geaendert = kontendienst.salden_neu_zuordnen(db)

    audit.eintragen(
        db,
        "kontenzuordnung.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="konten_mapping",
        datensatz_id=eintrag.id,
        neu={**eingabe.model_dump(), "salden_neu_zugeordnet": geaendert},
    )
    db.commit()
    return _bereich_antwort(eintrag)


@router.put(
    "/konten/{bereich_id}",
    response_model=BereichAntwort,
    summary="Kontenbereich ändern",
    operation_id="kontenBereichAendern",
    responses=SCHREIBEN,
)
def bereich_aendern(
    bereich_id: int,
    eingabe: BereichAendern,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> BereichAntwort:
    eintrag = db.get(KontenMapping, bereich_id)
    if eintrag is None:
        raise NichtGefunden("Diese Kontenzuordnung gibt es nicht.")
    stand_pruefen(eintrag, eingabe.stand, "Die Kontenzuordnung")
    _grenzen_pruefen(eingabe)

    alt = {
        "konto_von": eintrag.konto_von,
        "konto_bis": eintrag.konto_bis,
        "block": eintrag.block,
    }
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(eintrag, feld, wert)
    db.flush()
    geaendert = kontendienst.salden_neu_zuordnen(db)

    audit.eintragen(
        db,
        "kontenzuordnung.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="konten_mapping",
        datensatz_id=eintrag.id,
        alt=alt,
        neu={**eingabe.model_dump(exclude={"stand"}), "salden_neu_zugeordnet": geaendert},
    )
    db.commit()
    return _bereich_antwort(eintrag)


@router.delete(
    "/konten/{bereich_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Kontenzuordnung entfernen",
    operation_id="kontenBereichEntfernen",
    responses=SCHREIBEN,
)
def bereich_entfernen(
    bereich_id: int,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> Response:
    """Zuordnung löschen. Die betroffenen Konten fallen auf „ohne Block" zurück.

    Anders als bei Belegen und Stammdaten ist Löschen hier richtig (CLAUDE.md Regel 5 meint
    Datensätze mit Bezügen): eine Zuordnung ist eine Einstellung, kein Geschäftsvorfall. Die
    Salden bleiben stehen und erscheinen wieder auf der Pflegeliste.
    """
    eintrag = db.get(KontenMapping, bereich_id)
    if eintrag is None:
        raise NichtGefunden("Diese Kontenzuordnung gibt es nicht.")

    alt = {
        "konto_von": eintrag.konto_von,
        "konto_bis": eintrag.konto_bis,
        "block": eintrag.block,
    }
    db.delete(eintrag)
    db.flush()
    geaendert = kontendienst.salden_neu_zuordnen(db)

    audit.eintragen(
        db,
        "kontenzuordnung.entfernt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="konten_mapping",
        datensatz_id=bereich_id,
        alt={**alt, "salden_neu_zugeordnet": geaendert},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Fixkostenplanung
# ---------------------------------------------------------------------------


@router.get(
    "/fixkosten",
    response_model=list[PlanAntwort],
    summary="Geplante Fixkosten",
    operation_id="fixkostenPlan",
    responses=LESEN,
)
def plan(
    monat: str | None = Query(None, description="Nur diesen Monat 'JJJJ-MM'"),
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> list[PlanAntwort]:
    abfrage = select(FixkostenPlan).order_by(FixkostenPlan.monat, FixkostenPlan.block)
    if monat is not None:
        abfrage = abfrage.where(FixkostenPlan.monat == monat)
    return [_plan_antwort(e) for e in db.scalars(abfrage)]


@router.post(
    "/fixkosten",
    response_model=PlanAntwort,
    status_code=status.HTTP_201_CREATED,
    summary="Fixkosten-Planwert anlegen",
    operation_id="fixkostenPlanAnlegen",
    responses=SCHREIBEN,
)
def plan_anlegen(
    eingabe: PlanEingabe,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> PlanAntwort:
    vorhanden = db.scalar(
        select(FixkostenPlan).where(
            FixkostenPlan.monat == eingabe.monat, FixkostenPlan.block == eingabe.block
        )
    )
    if vorhanden is not None:
        raise FachFehler(
            f"Für {eingabe.monat} ist der Block '{eingabe.block}' bereits geplant.",
            "Den vorhandenen Wert ändern statt einen zweiten anzulegen.",
            code="fixkosten_doppelt",
        )

    eintrag = FixkostenPlan(**eingabe.model_dump())
    db.add(eintrag)
    db.flush()

    audit.eintragen(
        db,
        "fixkostenplan.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fixkosten_plan",
        datensatz_id=eintrag.id,
        neu=eingabe.model_dump(),
    )
    db.commit()
    return _plan_antwort(eintrag)


@router.put(
    "/fixkosten/{plan_id}",
    response_model=PlanAntwort,
    summary="Fixkosten-Planwert ändern",
    operation_id="fixkostenPlanAendern",
    responses=SCHREIBEN,
)
def plan_aendern(
    plan_id: int,
    eingabe: PlanAendern,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> PlanAntwort:
    eintrag = db.get(FixkostenPlan, plan_id)
    if eintrag is None:
        raise NichtGefunden("Diesen Planwert gibt es nicht.")
    stand_pruefen(eintrag, eingabe.stand, "Der Planwert")

    alt = {"betrag": eintrag.betrag, "bemerkung": eintrag.bemerkung}
    eintrag.betrag = eingabe.betrag
    eintrag.bemerkung = eingabe.bemerkung
    db.flush()

    audit.eintragen(
        db,
        "fixkostenplan.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fixkosten_plan",
        datensatz_id=eintrag.id,
        alt=alt,
        neu={"betrag": eingabe.betrag, "bemerkung": eingabe.bemerkung},
    )
    db.commit()
    return _plan_antwort(eintrag)


@router.delete(
    "/fixkosten/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Fixkosten-Planwert entfernen",
    operation_id="fixkostenPlanEntfernen",
    responses=SCHREIBEN,
)
def plan_entfernen(
    plan_id: int,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> Response:
    eintrag = db.get(FixkostenPlan, plan_id)
    if eintrag is None:
        raise NichtGefunden("Diesen Planwert gibt es nicht.")

    alt = {"monat": eintrag.monat, "block": eintrag.block, "betrag": eintrag.betrag}
    db.delete(eintrag)

    audit.eintragen(
        db,
        "fixkostenplan.entfernt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fixkosten_plan",
        datensatz_id=plan_id,
        alt=alt,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/fixkosten/{monat}/vormonat-uebernehmen",
    response_model=UebernahmeErgebnis,
    summary="Planwerte aus dem Vormonat übernehmen",
    operation_id="fixkostenPlanVormonat",
    responses=SCHREIBEN,
)
def vormonat_uebernehmen(
    monat: str,
    zugriff: Zugriff = Depends(benoetigt("admin.konfiguration")),
    db: Session = Depends(db_sitzung),
) -> UebernahmeErgebnis:
    """Die Planwerte des Vormonats in diesen Monat kopieren.

    Fixkosten ändern sich selten – ein Jahr von Hand einzutragen wäre zwölfmal dieselbe Arbeit.
    Schon vorhandene Blöcke werden **nicht** überschrieben: wer einen Wert bewusst angepasst
    hat, soll ihn nicht durch einen Klick verlieren.
    """
    if not _MONAT.match(monat):
        raise FachFehler(
            f"'{monat}' ist kein Monat.",
            "Erwartet wird das Format JJJJ-MM, zum Beispiel 2026-07.",
            code="monat_ungueltig",
        )

    quelle = _voriger_monat(monat)
    vorlagen = list(db.scalars(select(FixkostenPlan).where(FixkostenPlan.monat == quelle)))
    if not vorlagen:
        raise FachFehler(
            f"Für {quelle} sind keine Planwerte hinterlegt.",
            "Zuerst den Vormonat planen, oder die Werte für diesen Monat einzeln eintragen.",
            code="vormonat_leer",
        )

    schon_da = set(
        db.scalars(select(FixkostenPlan.block).where(FixkostenPlan.monat == monat)).all()
    )
    uebernommen = 0
    for vorlage in vorlagen:
        if vorlage.block in schon_da:
            continue
        db.add(
            FixkostenPlan(
                monat=monat,
                block=vorlage.block,
                betrag=vorlage.betrag,
                bemerkung=vorlage.bemerkung,
            )
        )
        uebernommen += 1
    db.flush()

    ergebnis = UebernahmeErgebnis(
        monat=monat,
        quelle_monat=quelle,
        uebernommen=uebernommen,
        uebersprungen=len(vorlagen) - uebernommen,
    )
    audit.eintragen(
        db,
        "fixkostenplan.vormonat_uebernommen",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fixkosten_plan",
        neu=ergebnis.model_dump(),
    )
    db.commit()
    return ergebnis
