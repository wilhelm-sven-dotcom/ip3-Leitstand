"""Eigene Bestandsanlagen und ihre Vergütung (PLAN §4, §7 Phase 7).

Gerechnet wird in ``app/dienste/einspeisung.py`` – hier steht nur, wer fragen darf und wie die
Antwort aussieht.

**Das Team sieht davon nichts.** Es geht um eigene Erlöse, und Beträge sind in PLAN §4
ausdrücklich von der Projektsicht getrennt. Deshalb gibt es die eigenen Schlüssel
``einspeisung.lesen`` und ``einspeisung.schreiben`` und nicht etwa ``anlagen.*`` mit: dort geht
es um Kundenanlagen und Service, hier um Geld.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.dienste import einspeisung as dienst
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.fehler import Konflikt, NichtGefunden
from app.konfiguration import Einstellungen
from app.modelle import EigeneAnlage, EinspeiseAbrechnung
from app.modelle.einspeisung import VERGUETUNGSARTEN
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, konfiguration
from app.zeit import monat_gueltig

router = APIRouter(prefix="/api", tags=["Einspeisung"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung einspeisung.lesen fehlt"},
}
SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung einspeisung.schreiben fehlt"},
    404: {"description": "Anlage oder Abrechnung nicht gefunden"},
    409: {"description": "Der Datensatz wurde zwischenzeitlich geändert"},
}


# ---------------------------------------------------------------------------
# Schemata
# ---------------------------------------------------------------------------


class AnlageAntwort(BaseModel):
    id: int
    bezeichnung: str
    standort: str | None = None
    pv_kwp: float | None = None
    speicher_kwh: float | None = None
    inbetriebnahme: date | None = None
    verguetungsart: str
    verguetung_ct_kwh: float | None = None
    vermarkter_entgelt_ct_kwh: float | None = None
    zaehler_nr: str | None = None
    mastr_nr: str | None = None
    netzbetreiber: str | None = None
    vermarkter: str | None = None
    aktiv: bool
    bemerkung: str | None = None
    stand: datetime


class AnlageEingabe(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=200)
    standort: str | None = Field(default=None, max_length=200)
    pv_kwp: float | None = Field(default=None, ge=0)
    speicher_kwh: float | None = Field(default=None, ge=0)
    inbetriebnahme: date | None = None
    verguetungsart: str = "einspeisung"
    # In ct/kWh: bei 'einspeisung' der EEG-Satz, bei 'direktvermarktung' der anzulegende Wert.
    verguetung_ct_kwh: float | None = Field(default=None, ge=0, le=1000)
    vermarkter_entgelt_ct_kwh: float | None = Field(default=None, ge=0, le=1000)
    zaehler_nr: str | None = Field(default=None, max_length=50)
    mastr_nr: str | None = Field(default=None, max_length=50)
    netzbetreiber: str | None = Field(default=None, max_length=200)
    vermarkter: str | None = Field(default=None, max_length=200)
    aktiv: bool = True
    bemerkung: str | None = Field(default=None, max_length=1000)
    stand: datetime | None = None

    @field_validator("verguetungsart")
    @classmethod
    def bekannte_art(cls, wert: str) -> str:
        if wert not in VERGUETUNGSARTEN:
            raise ValueError(
                f"'{wert}' ist keine bekannte Vergütungsart. "
                f"Erlaubt sind: {', '.join(VERGUETUNGSARTEN)}."
            )
        return wert


class MonatAntwort(BaseModel):
    monat: str
    kwh: float
    # ``None`` heißt „nicht berechenbar, weil der Satz fehlt" – nicht 0,00 €.
    erwartet_cent: int | None = None
    abgerechnet_cent: int
    abweichung_cent: int | None = None
    abweichung_promille: int | None = None
    bezahlt_am: date | None = None
    offen: bool
    quelle_datei: str | None = None


class AnlagenbildAntwort(BaseModel):
    anlage_id: int
    bezeichnung: str
    verguetungsart: str
    verguetung_ct_kwh: float | None = None
    kwh_gesamt: float
    erwartet_cent: int
    abgerechnet_cent: int
    offen_cent: int
    monate: list[MonatAntwort] = Field(default_factory=list)
    hinweise: list[str] = Field(default_factory=list)


class BildAntwort(BaseModel):
    von: str
    bis: str
    erwartet_cent: int
    abgerechnet_cent: int
    offen_cent: int
    anlagen: list[AnlagenbildAntwort] = Field(default_factory=list)
    hinweise: list[str] = Field(default_factory=list)
    # Was die Zahlen nicht sind – steht über der Ansicht, nicht in einer Fußnote.
    einordnung: str


class AbrechnungEingabe(BaseModel):
    """Eine Abrechnung von Hand erfassen oder ändern."""

    monat: str
    kwh: float = Field(ge=0)
    betrag_cent: int
    bezahlt_am: date | None = None
    bemerkung: str | None = Field(default=None, max_length=1000)
    stand: datetime | None = None

    @field_validator("monat")
    @classmethod
    def monatsformat(cls, wert: str) -> str:
        if not monat_gueltig(wert):
            raise ValueError(f"'{wert}' ist kein Monat im Format JJJJ-MM (Beispiel: 2026-07).")
        return wert


class AbrechnungAntwort(BaseModel):
    id: int
    anlage_id: int
    monat: str
    kwh: float
    betrag_cent: int
    bezahlt_am: date | None = None
    quelle_datei: str | None = None
    eingelesen_am: datetime | None = None
    bemerkung: str | None = None
    stand: datetime


EINORDNUNG = (
    "Kontrollrechnung, keine Buchung. Verbindlich ist die Abrechnung des Netzbetreibers – "
    "der Leitstand rechnet nach, was aus den hinterlegten Sätzen zu erwarten wäre, und zeigt, "
    "wo beides auseinanderläuft."
)


# ---------------------------------------------------------------------------
# Anlagen
# ---------------------------------------------------------------------------


def _als_anlage(anlage: EigeneAnlage) -> AnlageAntwort:
    return AnlageAntwort(
        id=anlage.id,
        bezeichnung=anlage.bezeichnung,
        standort=anlage.standort,
        pv_kwp=float(anlage.pv_kwp) if anlage.pv_kwp is not None else None,
        speicher_kwh=float(anlage.speicher_kwh) if anlage.speicher_kwh is not None else None,
        inbetriebnahme=anlage.inbetriebnahme,
        verguetungsart=anlage.verguetungsart,
        verguetung_ct_kwh=(
            float(anlage.verguetung_ct_kwh) if anlage.verguetung_ct_kwh is not None else None
        ),
        vermarkter_entgelt_ct_kwh=(
            float(anlage.vermarkter_entgelt_ct_kwh)
            if anlage.vermarkter_entgelt_ct_kwh is not None
            else None
        ),
        zaehler_nr=anlage.zaehler_nr,
        mastr_nr=anlage.mastr_nr,
        netzbetreiber=anlage.netzbetreiber,
        vermarkter=anlage.vermarkter,
        aktiv=anlage.aktiv,
        bemerkung=anlage.bemerkung,
        stand=anlage.updated_at,
    )


def _anlage_holen(db: Session, anlage_id: int) -> EigeneAnlage:
    anlage = db.get(EigeneAnlage, anlage_id)
    if anlage is None:
        raise NichtGefunden(
            "Diese eigene Anlage gibt es nicht.",
            "Bitte die Liste neu laden – möglicherweise wurde sie zwischenzeitlich entfernt.",
        )
    return anlage


def _zustand(anlage: EigeneAnlage) -> dict[str, object]:
    """Die Felder, deren Änderung im Protokoll stehen soll."""
    return {
        feld: getattr(anlage, feld)
        for feld in (
            "bezeichnung",
            "standort",
            "inbetriebnahme",
            "verguetungsart",
            "verguetung_ct_kwh",
            "vermarkter_entgelt_ct_kwh",
            "zaehler_nr",
            "mastr_nr",
            "netzbetreiber",
            "vermarkter",
            "aktiv",
        )
    }


def _felder_setzen(anlage: EigeneAnlage, eingabe: AnlageEingabe) -> None:
    anlage.bezeichnung = eingabe.bezeichnung.strip()
    anlage.standort = eingabe.standort
    anlage.pv_kwp = eingabe.pv_kwp
    anlage.speicher_kwh = eingabe.speicher_kwh
    anlage.inbetriebnahme = eingabe.inbetriebnahme
    anlage.verguetungsart = eingabe.verguetungsart
    anlage.verguetung_ct_kwh = eingabe.verguetung_ct_kwh
    anlage.vermarkter_entgelt_ct_kwh = eingabe.vermarkter_entgelt_ct_kwh
    anlage.zaehler_nr = (eingabe.zaehler_nr or "").strip() or None
    anlage.mastr_nr = (eingabe.mastr_nr or "").strip() or None
    anlage.netzbetreiber = eingabe.netzbetreiber
    anlage.vermarkter = eingabe.vermarkter
    anlage.aktiv = eingabe.aktiv
    anlage.bemerkung = eingabe.bemerkung


@router.get(
    "/eigene-anlagen",
    response_model=list[AnlageAntwort],
    summary="Eigene Bestandsanlagen auflisten",
    operation_id="eigeneAnlagenListe",
    responses=LESEN,
)
def anlagen_liste(
    nur_aktive: bool = Query(default=False, description="Stillgelegte Anlagen ausblenden"),
    zugriff: Zugriff = Depends(benoetigt("einspeisung.lesen")),
    db: Session = Depends(db_sitzung),
) -> list[AnlageAntwort]:
    abfrage = select(EigeneAnlage).order_by(EigeneAnlage.bezeichnung)
    if nur_aktive:
        abfrage = abfrage.where(EigeneAnlage.aktiv.is_(True))
    return [_als_anlage(a) for a in db.execute(abfrage).scalars()]


@router.post(
    "/eigene-anlagen",
    response_model=AnlageAntwort,
    status_code=201,
    summary="Eigene Anlage anlegen",
    operation_id="eigeneAnlageAnlegen",
    responses=SCHREIBEN,
)
def anlage_anlegen(
    eingabe: AnlageEingabe,
    zugriff: Zugriff = Depends(benoetigt("einspeisung.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AnlageAntwort:
    name = eingabe.bezeichnung.strip()
    if db.scalar(select(EigeneAnlage).where(EigeneAnlage.bezeichnung == name)):
        raise Konflikt(
            f"Eine eigene Anlage mit der Bezeichnung „{eingabe.bezeichnung}“ gibt es schon.",
            "Bitte eine andere Bezeichnung wählen – sie dient auch der Zuordnung der "
            "Abrechnungen und muss deshalb eindeutig sein.",
            code="anlage_doppelt",
        )
    anlage = EigeneAnlage(bezeichnung=eingabe.bezeichnung.strip())
    _felder_setzen(anlage, eingabe)
    db.add(anlage)
    db.flush()
    audit.eintragen(
        db,
        "eigene_anlage.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="eigene_anlagen",
        datensatz_id=anlage.id,
        neu={"bezeichnung": anlage.bezeichnung, "verguetungsart": anlage.verguetungsart},
    )
    db.commit()
    return _als_anlage(anlage)


@router.put(
    "/eigene-anlagen/{anlage_id}",
    response_model=AnlageAntwort,
    summary="Eigene Anlage ändern",
    operation_id="eigeneAnlageAendern",
    responses=SCHREIBEN,
)
def anlage_aendern(
    anlage_id: int,
    eingabe: AnlageEingabe,
    zugriff: Zugriff = Depends(benoetigt("einspeisung.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AnlageAntwort:
    anlage = _anlage_holen(db, anlage_id)
    stand_pruefen(anlage, eingabe.stand, "Diese Anlage")
    vorher = _zustand(anlage)
    _felder_setzen(anlage, eingabe)
    try:
        db.flush()
    except Exception as fehler:
        konflikt_uebersetzen(fehler, "Diese Anlage")
        raise

    unterschiede = geaenderte_felder(vorher, _zustand(anlage))
    if unterschiede:
        audit.eintragen(
            db,
            "eigene_anlage.geaendert",
            nutzer=zugriff.nutzer,
            ip=zugriff.ip,
            tabelle="eigene_anlagen",
            datensatz_id=anlage.id,
            alt={f: w["alt"] for f, w in unterschiede.items()},
            neu={f: w["neu"] for f, w in unterschiede.items()},
        )
    db.commit()
    return _als_anlage(anlage)


# ---------------------------------------------------------------------------
# Abrechnungen
# ---------------------------------------------------------------------------


def _als_abrechnung(eintrag: EinspeiseAbrechnung) -> AbrechnungAntwort:
    return AbrechnungAntwort(
        id=eintrag.id,
        anlage_id=eintrag.anlage_id,
        monat=eintrag.monat,
        kwh=float(eintrag.kwh),
        betrag_cent=eintrag.betrag_cent,
        bezahlt_am=eintrag.bezahlt_am,
        quelle_datei=eintrag.quelle_datei,
        eingelesen_am=eintrag.eingelesen_am,
        bemerkung=eintrag.bemerkung,
        stand=eintrag.updated_at,
    )


@router.put(
    "/eigene-anlagen/{anlage_id}/abrechnungen",
    response_model=AbrechnungAntwort,
    summary="Abrechnung eines Monats erfassen oder ändern",
    operation_id="einspeiseAbrechnungPflegen",
    responses=SCHREIBEN,
)
def abrechnung_pflegen(
    anlage_id: int,
    eingabe: AbrechnungEingabe,
    zugriff: Zugriff = Depends(benoetigt("einspeisung.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AbrechnungAntwort:
    """Je Anlage und Monat gibt es genau eine Zeile – deshalb PUT und nicht POST.

    Von Hand erfasst oder aus der Abrechnungsdatei eingelesen: derselbe Datensatz. Wer den
    Zahlungseingang vermerkt, ändert nur ``bezahlt_am``; ein späterer Import lässt das stehen.
    """
    anlage = _anlage_holen(db, anlage_id)
    eintrag = db.scalar(
        select(EinspeiseAbrechnung).where(
            EinspeiseAbrechnung.anlage_id == anlage.id,
            EinspeiseAbrechnung.monat == eingabe.monat,
        )
    )
    if eintrag is None:
        eintrag = EinspeiseAbrechnung(anlage_id=anlage.id, monat=eingabe.monat)
        db.add(eintrag)
        aktion = "einspeise_abrechnung.angelegt"
    else:
        stand_pruefen(eintrag, eingabe.stand, "Diese Abrechnung")
        aktion = "einspeise_abrechnung.geaendert"

    eintrag.kwh = Decimal(str(eingabe.kwh))
    eintrag.betrag_cent = eingabe.betrag_cent
    eintrag.bezahlt_am = eingabe.bezahlt_am
    eintrag.bemerkung = eingabe.bemerkung
    db.flush()

    audit.eintragen(
        db,
        aktion,
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="einspeise_abrechnungen",
        datensatz_id=eintrag.id,
        neu={
            "anlage_id": anlage.id,
            "monat": eintrag.monat,
            "kwh": float(eintrag.kwh),
            "betrag_cent": eintrag.betrag_cent,
            "bezahlt_am": eintrag.bezahlt_am.isoformat() if eintrag.bezahlt_am else None,
        },
    )
    db.commit()
    return _als_abrechnung(eintrag)


# ---------------------------------------------------------------------------
# Das Bild
# ---------------------------------------------------------------------------


@router.get(
    "/einspeisung",
    response_model=BildAntwort,
    summary="Erwartete Gutschrift gegen Abrechnung",
    operation_id="einspeisungBild",
    responses=LESEN,
)
def bild(
    monate: int = Query(default=12, ge=1, le=60, description="Wie viele Monate zurück"),
    bis: str | None = Query(default=None, description="Letzter Monat, Format JJJJ-MM"),
    nur_aktive: bool = Query(default=True, description="Stillgelegte Anlagen ausblenden"),
    zugriff: Zugriff = Depends(benoetigt("einspeisung.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> BildAntwort:
    if bis is not None and not monat_gueltig(bis):
        raise Konflikt(
            f"'{bis}' ist kein Monat im Format JJJJ-MM.",
            "Beispiel: 2026-07.",
            code="monat_ungueltig",
        )
    ergebnis = dienst.bild(
        db,
        monate=monate,
        toleranz_promille=werte.einspeisung.toleranz_promille,
        zahlungsziel_tage=werte.einspeisung.zahlungsziel_tage,
        bis=bis,
        nur_aktive=nur_aktive,
    )
    return BildAntwort(
        von=ergebnis.von,
        bis=ergebnis.bis,
        erwartet_cent=ergebnis.erwartet_cent,
        abgerechnet_cent=ergebnis.abgerechnet_cent,
        offen_cent=ergebnis.offen_cent,
        anlagen=[
            AnlagenbildAntwort(
                anlage_id=teil.anlage_id,
                bezeichnung=teil.bezeichnung,
                verguetungsart=teil.verguetungsart,
                verguetung_ct_kwh=(
                    float(teil.verguetung_ct_kwh) if teil.verguetung_ct_kwh is not None else None
                ),
                kwh_gesamt=float(teil.kwh_gesamt),
                erwartet_cent=teil.erwartet_cent,
                abgerechnet_cent=teil.abgerechnet_cent,
                offen_cent=teil.offen_cent,
                monate=[
                    MonatAntwort(
                        monat=zeile.monat,
                        kwh=float(zeile.kwh),
                        erwartet_cent=zeile.erwartet_cent,
                        abgerechnet_cent=zeile.abgerechnet_cent,
                        abweichung_cent=zeile.abweichung_cent,
                        abweichung_promille=zeile.abweichung_promille,
                        bezahlt_am=zeile.bezahlt_am,
                        offen=zeile.offen,
                        quelle_datei=zeile.quelle_datei,
                    )
                    for zeile in teil.monate
                ],
                hinweise=teil.hinweise,
            )
            for teil in ergebnis.anlagen
        ],
        hinweise=ergebnis.hinweise,
        einordnung=EINORDNUNG,
    )
