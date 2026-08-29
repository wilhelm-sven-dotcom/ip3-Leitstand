"""Anlagenregister, Fristen und die Servicehistorie (PLAN §5, §6.9, §7 Phase 6).

Die Anlage ist der Bezugspunkt für alles, was nach dem Bau kommt: Wartung, Störung, Nachrüstung,
Gewährleistung. Sie entsteht in der Regel von selbst, wenn ein Projekt auf ``abgeschlossen``
wechselt (siehe ``app/dienste/anlagen.py``) – von Hand angelegt wird sie nur für den Altbestand,
also für Anlagen, die vor dem Leitstand gebaut wurden.

Drei Festlegungen:

* **Gelesen mit ``anlagen.lesen``, geschrieben mit ``anlagen.schreiben``.** Das Team sieht das
  Register, ändert es aber nicht – dort stehen Zusagen mit Rechtsfolge (Gewährleistungsende,
  MaStR-Nummer), keine Notizen.
* **Keine Anlage wird gelöscht.** An ihr hängen Fristen und Serviceaufträge. Was nicht mehr
  betrieben wird, bekommt eine Bemerkung; die Frist wird erledigt.
* **Fristen werden erledigt, nicht entfernt.** Eine abgehakte Frist ist der Beleg, dass jemand
  hingesehen hat. Verschwände sie, bliebe nur die Erinnerung daran, dass da mal etwas war.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.dienste import fristen as fristendienst
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.dienste.suche import alle_woerter
from app.fehler import FachFehler, NichtGefunden
from app.konfiguration import Einstellungen
from app.modelle import Anlage, Frist, Kunde, Projekt
from app.modelle.anlagen import FRIST_BEZUEGE, FRIST_TYPEN
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, konfiguration

log = logger(__name__)

router = APIRouter(prefix="/api", tags=["Anlagen und Fristen"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung anlagen.lesen fehlt"},
}
SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung anlagen.schreiben fehlt"},
    404: {"description": "Datensatz nicht gefunden"},
    409: {"description": "Der Datensatz wurde zwischenzeitlich geändert"},
}

SEITE_STANDARD = 25
SEITE_MAX = 200

# Für die Startseite: mehr als eine Handvoll Fristen ist kein Widget mehr, sondern eine Liste.
WIDGET_GRENZE = 8


# ---------------------------------------------------------------------------
# Antwort- und Eingabeformen
# ---------------------------------------------------------------------------


class AnlageZeile(BaseModel):
    """Anlage in der Liste."""

    id: int
    kunde_id: int
    kunde: str
    standort: str | None = None
    pv_kwp: float | None = None
    speicher_kwh: float | None = None
    inbetriebnahme: date | None = None
    gewaehrleistung_ende: date | None = None
    wartungsvertrag: bool
    mastr_nr: str | None = None
    projekt_nr: int | None = None
    stand: datetime


class FristAntwort(BaseModel):
    id: int
    typ: str
    bezeichnung: str
    faellig_am: date
    vorlauf_tage: int
    status: str
    tage_bis: int
    bezug: str
    bezug_id: int
    betreff: str
    kunde: str | None = None
    erledigt_am: date | None = None
    stand: datetime | None = None


class ServicezeileAntwort(BaseModel):
    """Serviceauftrag zu einer Anlage – die Historie im Anlagenblatt."""

    projekt_nr: int
    bezeichnung: str | None = None
    status: str
    auftrag_vom: date | None = None


class AnlageAntwort(AnlageZeile):
    abnahme_datum: date | None = None
    bemerkung: str | None = None
    fristen: list[FristAntwort] = Field(default_factory=list)
    servicehistorie: list[ServicezeileAntwort] = Field(default_factory=list)


class AnlagenListe(BaseModel):
    anlagen: list[AnlageZeile]
    gesamt: int
    seite: int
    seiten: int


class AnlageEingabe(BaseModel):
    kunde_id: int
    standort: str | None = Field(default=None, max_length=200)
    pv_kwp: float | None = Field(default=None, ge=0, le=100000)
    speicher_kwh: float | None = Field(default=None, ge=0, le=100000)
    inbetriebnahme: date | None = None
    abnahme_datum: date | None = None
    gewaehrleistung_ende: date | None = None
    wartungsvertrag: bool = False
    mastr_nr: str | None = Field(default=None, max_length=100)
    bemerkung: str | None = None

    @field_validator("standort", "mastr_nr")
    @classmethod
    def leerraum_kuerzen(cls, wert: str | None) -> str | None:
        if wert is None:
            return None
        return wert.strip() or None


class AnlageAendern(AnlageEingabe):
    stand: datetime


class FristEingabe(BaseModel):
    bezug: Literal[FRIST_BEZUEGE]  # type: ignore[valid-type]
    bezug_id: int
    typ: Literal[FRIST_TYPEN]  # type: ignore[valid-type]
    bezeichnung: str = Field(min_length=1, max_length=500)
    faellig_am: date
    vorlauf_tage: int = Field(default=30, ge=0, le=3650)


class FristAendern(BaseModel):
    bezeichnung: str = Field(min_length=1, max_length=500)
    faellig_am: date
    vorlauf_tage: int = Field(default=30, ge=0, le=3650)
    stand: datetime


class FristenListe(BaseModel):
    fristen: list[FristAntwort]
    zaehlung: dict[str, int]


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------


def _zustand(anlage: Anlage) -> dict[str, object]:
    return {
        feld: getattr(anlage, feld)
        for feld in (
            "kunde_id",
            "standort",
            "pv_kwp",
            "speicher_kwh",
            "inbetriebnahme",
            "abnahme_datum",
            "gewaehrleistung_ende",
            "wartungsvertrag",
            "mastr_nr",
            "bemerkung",
        )
    }


def _zeile(anlage: Anlage, kunde: str, projekt_nr: int | None) -> AnlageZeile:
    return AnlageZeile(
        id=anlage.id,
        kunde_id=anlage.kunde_id,
        kunde=kunde,
        standort=anlage.standort,
        pv_kwp=float(anlage.pv_kwp) if anlage.pv_kwp is not None else None,
        speicher_kwh=float(anlage.speicher_kwh) if anlage.speicher_kwh is not None else None,
        inbetriebnahme=anlage.inbetriebnahme,
        gewaehrleistung_ende=anlage.gewaehrleistung_ende,
        wartungsvertrag=anlage.wartungsvertrag,
        mastr_nr=anlage.mastr_nr,
        projekt_nr=projekt_nr,
        stand=anlage.updated_at,
    )


def _als_frist_antwort(zeile: fristendienst.Fristzeile, stand: datetime | None) -> FristAntwort:
    return FristAntwort(
        id=zeile.id,
        typ=zeile.typ,
        bezeichnung=zeile.bezeichnung,
        faellig_am=zeile.faellig_am,
        vorlauf_tage=zeile.vorlauf_tage,
        status=zeile.status,
        tage_bis=zeile.tage_bis,
        bezug=zeile.bezug,
        bezug_id=zeile.bezug_id,
        betreff=zeile.betreff,
        kunde=zeile.kunde,
        erledigt_am=zeile.erledigt_am,
        stand=stand,
    )


def _anlage_holen(db: Session, anlage_id: int) -> Anlage:
    anlage = db.get(Anlage, anlage_id)
    if anlage is None:
        raise NichtGefunden(
            f"Es gibt keine Anlage mit der Nummer {anlage_id}.",
            "Das Anlagenregister zeigt die vorhandenen Anlagen.",
        )
    return anlage


def _frist_holen(db: Session, frist_id: int) -> Frist:
    frist = db.get(Frist, frist_id)
    if frist is None:
        raise NichtGefunden(
            f"Es gibt keine Frist mit der Nummer {frist_id}.",
            "Die Fristenliste zeigt die vorhandenen Fristen.",
        )
    return frist


# ---------------------------------------------------------------------------
# Anlagen
# ---------------------------------------------------------------------------


@router.get(
    "/anlagen",
    response_model=AnlagenListe,
    summary="Anlagenregister",
    operation_id="anlagenListe",
    responses=LESEN,
)
def anlagen_liste(
    suche: str | None = Query(None, description="Standort, Kundenname oder MaStR-Nummer"),
    ohne_wartungsvertrag: bool = Query(
        False, description="Nur Anlagen ohne Wartungsvertrag (die Serviceliste)"
    ),
    kunde_id: int | None = Query(None),
    seite: int = Query(1, ge=1),
    anzahl: int = Query(SEITE_STANDARD, ge=1, le=SEITE_MAX),
    zugriff: Zugriff = Depends(benoetigt("anlagen.lesen")),
    db: Session = Depends(db_sitzung),
) -> AnlagenListe:
    """Das Register, die jüngste Inbetriebnahme zuerst.

    ``ohne_wartungsvertrag=true`` ist die Liste aus PLAN §7: jede Zeile darin ist ein Kunde, dem
    ein Wartungsvertrag angeboten werden kann.
    """
    abfrage = (
        select(Anlage, Kunde.name, Projekt.projekt_nr)
        .join(Kunde, Kunde.id == Anlage.kunde_id)
        .outerjoin(Projekt, Projekt.id == Anlage.projekt_id_ursprung)
    )
    if ohne_wartungsvertrag:
        abfrage = abfrage.where(Anlage.wartungsvertrag.is_(False))
    if kunde_id is not None:
        abfrage = abfrage.where(Anlage.kunde_id == kunde_id)
    if suche:
        bedingung = alle_woerter(suche, Anlage.standort, Kunde.name, Anlage.mastr_nr)
        if bedingung is not None:
            abfrage = abfrage.where(bedingung)

    gesamt = db.scalar(select(func.count()).select_from(abfrage.subquery())) or 0
    zeilen = db.execute(
        abfrage.order_by(Anlage.inbetriebnahme.desc().nullslast(), Anlage.id.desc())
        .offset((seite - 1) * anzahl)
        .limit(anzahl)
    ).all()

    return AnlagenListe(
        anlagen=[_zeile(anlage, kunde, projekt_nr) for anlage, kunde, projekt_nr in zeilen],
        gesamt=gesamt,
        seite=seite,
        seiten=max(1, -(-gesamt // anzahl)),
    )


@router.get(
    "/anlagen/{anlage_id}",
    response_model=AnlageAntwort,
    summary="Anlagenblatt mit Fristen und Servicehistorie",
    operation_id="anlageLesen",
    responses={**LESEN, 404: {"description": "Anlage nicht gefunden"}},
)
def anlage_lesen(
    anlage_id: int,
    zugriff: Zugriff = Depends(benoetigt("anlagen.lesen")),
    db: Session = Depends(db_sitzung),
) -> AnlageAntwort:
    """Stammdaten, offene und erledigte Fristen sowie alle Serviceaufträge zur Anlage."""
    anlage = _anlage_holen(db, anlage_id)
    kunde = db.scalar(select(Kunde.name).where(Kunde.id == anlage.kunde_id)) or "unbekannt"
    projekt_nr = (
        db.scalar(select(Projekt.projekt_nr).where(Projekt.id == anlage.projekt_id_ursprung))
        if anlage.projekt_id_ursprung
        else None
    )

    zeilen = fristendienst.liste(db, mit_erledigten=True)
    staende = {
        f.id: f.updated_at
        for f in db.scalars(
            select(Frist).where(Frist.bezug == "anlage", Frist.bezug_id == anlage_id)
        )
    }
    fristen = [
        _als_frist_antwort(z, staende.get(z.id))
        for z in zeilen
        if z.bezug == "anlage" and z.bezug_id == anlage_id
    ]

    historie = db.execute(
        select(Projekt.projekt_nr, Projekt.bezeichnung, Projekt.status, Projekt.auftrag_vom)
        .where(Projekt.typ == "service", Projekt.anlage_id == anlage_id)
        .order_by(Projekt.auftrag_vom.desc().nullslast(), Projekt.projekt_nr.desc())
    ).all()

    basis = _zeile(anlage, kunde, projekt_nr)
    return AnlageAntwort(
        **basis.model_dump(),
        abnahme_datum=anlage.abnahme_datum,
        bemerkung=anlage.bemerkung,
        fristen=fristen,
        servicehistorie=[
            ServicezeileAntwort(
                projekt_nr=nr, bezeichnung=bezeichnung, status=status, auftrag_vom=auftrag_vom
            )
            for nr, bezeichnung, status, auftrag_vom in historie
        ],
    )


@router.post(
    "/anlagen",
    response_model=AnlageAntwort,
    status_code=201,
    summary="Anlage von Hand anlegen (Altbestand)",
    operation_id="anlageAnlegen",
    responses=SCHREIBEN,
)
def anlage_anlegen(
    eingabe: AnlageEingabe,
    zugriff: Zugriff = Depends(benoetigt("anlagen.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AnlageAntwort:
    """Für Anlagen aus der Zeit vor dem Leitstand.

    Anlagen aus laufenden Projekten entstehen beim Projektabschluss von selbst (PLAN §6.9) –
    diese Maske ist für den Bestand, der nie ein Projekt im Leitstand hatte.
    """
    if db.get(Kunde, eingabe.kunde_id) is None:
        raise NichtGefunden(
            "Den angegebenen Kunden gibt es nicht.",
            "Zuerst den Kunden unter Stammdaten anlegen, dann die Anlage.",
        )
    anlage = Anlage(**eingabe.model_dump())
    db.add(anlage)
    db.flush()
    audit.eintragen(
        db,
        "anlage.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="anlagen",
        datensatz_id=anlage.id,
        neu=_zustand(anlage),
    )
    db.commit()
    log.info("Anlage %s von Hand angelegt", anlage.id)
    return anlage_lesen(anlage.id, zugriff, db)


@router.put(
    "/anlagen/{anlage_id}",
    response_model=AnlageAntwort,
    summary="Anlage ändern",
    operation_id="anlageAendern",
    responses=SCHREIBEN,
)
def anlage_aendern(
    anlage_id: int,
    eingabe: AnlageAendern,
    zugriff: Zugriff = Depends(benoetigt("anlagen.schreiben")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> AnlageAntwort:
    """Stammdaten pflegen – vor allem MaStR-Nummer und Wartungsvertrag.

    Wird die MaStR-Nummer nachgetragen, gilt die Registrierungsfrist als erfüllt: der
    Fristenwächter hakt sie im selben Zug ab, statt bis zur Nacht rot zu bleiben.
    """
    anlage = _anlage_holen(db, anlage_id)
    stand_pruefen(anlage, eingabe.stand, "Die Anlage")

    if db.get(Kunde, eingabe.kunde_id) is None:
        raise NichtGefunden(
            "Den angegebenen Kunden gibt es nicht.",
            "Die Kundenliste zeigt die vorhandenen Kunden.",
        )

    vorher = _zustand(anlage)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(anlage, feld, wert)
    unterschiede = geaenderte_felder(vorher, _zustand(anlage))
    if not unterschiede:
        return anlage_lesen(anlage_id, zugriff, db)

    audit.eintragen(
        db,
        "anlage.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="anlagen",
        datensatz_id=anlage.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={f: w["neu"] for f, w in unterschiede.items()},
    )
    if "mastr_nr" in unterschiede:
        fristendienst.mastr_pflegen(db, tage=werte.fristen.mastr_tage)
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Die Anlage")
        raise
    return anlage_lesen(anlage_id, zugriff, db)


# ---------------------------------------------------------------------------
# Fristen
# ---------------------------------------------------------------------------


@router.get(
    "/fristen",
    response_model=FristenListe,
    summary="Fristen, das Dringendste zuerst",
    operation_id="fristenListe",
    responses=LESEN,
)
def fristen_liste(
    nur_anstehende: bool = Query(
        False, description="Nur überfällige und im Vorlauf liegende Fristen (Startseite)"
    ),
    mit_erledigten: bool = Query(False, description="Erledigte Fristen mit anzeigen"),
    grenze: int | None = Query(None, ge=1, le=SEITE_MAX, description="Höchstens so viele Zeilen"),
    zugriff: Zugriff = Depends(benoetigt("anlagen.lesen")),
    db: Session = Depends(db_sitzung),
) -> FristenListe:
    """Die Fristenliste und – mit ``nur_anstehende`` – das Startseiten-Widget.

    Gezählt wird immer über die ungekürzte Liste: „3 überfällig" darf nicht davon abhängen, wie
    viele Zeilen das Widget anzeigt.
    """
    zeilen = fristendienst.liste(db, nur_anstehende=nur_anstehende, mit_erledigten=mit_erledigten)
    gezaehlt = fristendienst.zaehlung(zeilen)
    if grenze:
        zeilen = zeilen[:grenze]

    staende = {f.id: f.updated_at for f in db.scalars(select(Frist))}
    return FristenListe(
        fristen=[_als_frist_antwort(z, staende.get(z.id)) for z in zeilen],
        zaehlung=gezaehlt,
    )


@router.post(
    "/fristen",
    response_model=FristAntwort,
    status_code=201,
    summary="Frist von Hand anlegen",
    operation_id="fristAnlegen",
    responses=SCHREIBEN,
)
def frist_anlegen(
    eingabe: FristEingabe,
    zugriff: Zugriff = Depends(benoetigt("anlagen.schreiben")),
    db: Session = Depends(db_sitzung),
) -> FristAntwort:
    """Fertigmeldungen, Netzanschluss-Reservierungen und alles andere mit Ablaufdatum.

    Gewährleistung und MaStR-Registrierung entstehen von selbst; hier steht, was der Leitstand
    nicht ausrechnen kann.
    """
    _bezug_pruefen(db, eingabe.bezug, eingabe.bezug_id)
    frist = Frist(**eingabe.model_dump())
    db.add(frist)
    db.flush()
    audit.eintragen(
        db,
        "frist.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fristen",
        datensatz_id=frist.id,
        neu={
            "bezug": frist.bezug,
            "bezug_id": frist.bezug_id,
            "typ": frist.typ,
            "faellig_am": frist.faellig_am,
        },
    )
    db.commit()
    return _eine_frist(db, frist.id)


@router.put(
    "/fristen/{frist_id}",
    response_model=FristAntwort,
    summary="Frist ändern",
    operation_id="fristAendern",
    responses=SCHREIBEN,
)
def frist_aendern(
    frist_id: int,
    eingabe: FristAendern,
    zugriff: Zugriff = Depends(benoetigt("anlagen.schreiben")),
    db: Session = Depends(db_sitzung),
) -> FristAntwort:
    frist = _frist_holen(db, frist_id)
    stand_pruefen(frist, eingabe.stand, "Die Frist")

    vorher = {
        "bezeichnung": frist.bezeichnung,
        "faellig_am": frist.faellig_am,
        "vorlauf_tage": frist.vorlauf_tage,
    }
    frist.bezeichnung = eingabe.bezeichnung
    frist.faellig_am = eingabe.faellig_am
    frist.vorlauf_tage = eingabe.vorlauf_tage
    nachher = {
        "bezeichnung": frist.bezeichnung,
        "faellig_am": frist.faellig_am,
        "vorlauf_tage": frist.vorlauf_tage,
    }

    unterschiede = geaenderte_felder(vorher, nachher)
    if not unterschiede:
        return _eine_frist(db, frist_id)

    audit.eintragen(
        db,
        "frist.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fristen",
        datensatz_id=frist.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={f: w["neu"] for f, w in unterschiede.items()},
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Die Frist")
        raise
    return _eine_frist(db, frist_id)


@router.post(
    "/fristen/{frist_id}/erledigt",
    response_model=FristAntwort,
    summary="Frist abhaken oder wieder öffnen",
    operation_id="fristErledigen",
    responses=SCHREIBEN,
)
def frist_erledigen(
    frist_id: int,
    erledigt: bool = Query(True, description="false öffnet eine versehentlich abgehakte Frist"),
    zugriff: Zugriff = Depends(benoetigt("anlagen.schreiben")),
    db: Session = Depends(db_sitzung),
) -> FristAntwort:
    """Abhaken statt löschen (CLAUDE.md Regel 5).

    Eine erledigte Frist bleibt stehen: sie ist der Beleg, dass jemand hingesehen hat. Der
    nächtliche Lauf rührt sie nicht mehr an.
    """
    frist = _frist_holen(db, frist_id)
    vorher = frist.erledigt_am
    frist.erledigt_am = date.today() if erledigt else None
    if vorher == frist.erledigt_am:
        return _eine_frist(db, frist_id)

    audit.eintragen(
        db,
        "frist.erledigt" if erledigt else "frist.wieder_geoeffnet",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="fristen",
        datensatz_id=frist.id,
        alt={"erledigt_am": vorher},
        neu={"erledigt_am": frist.erledigt_am, "bezeichnung": frist.bezeichnung},
    )
    db.commit()
    return _eine_frist(db, frist_id)


def _bezug_pruefen(db: Session, bezug: str, bezug_id: int) -> None:
    """Eine Frist ohne auffindbaren Bezug wäre eine Erinnerung an nichts."""
    vorhanden = db.get(Anlage, bezug_id) if bezug == "anlage" else db.get(Projekt, bezug_id)
    if vorhanden is None:
        raise NichtGefunden(
            f"Es gibt {'keine Anlage' if bezug == 'anlage' else 'kein Projekt'} mit der "
            f"Nummer {bezug_id}.",
            "Die Frist braucht einen Bezug, sonst weiß später niemand, worum es ging.",
        )


def _eine_frist(db: Session, frist_id: int) -> FristAntwort:
    """Eine Frist mit aufgelöstem Bezug – dieselbe Form wie in der Liste."""
    frist = _frist_holen(db, frist_id)
    zeilen = fristendienst.liste(db, mit_erledigten=True)
    passend = next((z for z in zeilen if z.id == frist_id), None)
    if passend is None:  # pragma: no cover – die Frist wurde gerade gelesen
        raise FachFehler(
            "Die Frist ließ sich nicht mehr lesen.",
            "Bitte die Fristenliste neu laden.",
            code="frist_verschwunden",
        )
    return _als_frist_antwort(passend, frist.updated_at)
