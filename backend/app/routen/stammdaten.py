"""Kunden und Ansprechpartner (PLAN §5, §7 Phase 1).

Die erste Bearbeitungsmaske des Leitstands. Was hier festgelegt wird, gilt danach für Projekte,
Zahlungsplan und Nachträge:

* **Konfliktprüfung bei jedem Speichern.** Die Maske schickt den Stand mit, den sie gelesen hat.
  Weicht er ab, gibt es eine Meldung statt eines stillen Überschreibens – der Fehler, den ein
  Werkzeug für zwei Geschäftsführer und eine Buchhaltungskraft am ehesten macht.
* **Jede Änderung ins Änderungsprotokoll**, und nur die Felder, die sich wirklich geändert
  haben. Ein Protokoll, das bei jedem Speichern den ganzen Datensatz wiederholt, ist nicht
  lesbar (CLAUDE.md Regel 7).
* **Kein Löschen von Kunden.** An ihnen hängen Projekte; sie wechseln auf ``inaktiv``
  (CLAUDE.md Regel 5). Ansprechpartner dürfen weg – an ihnen hängt kein Beleg.
* **Seitenwechsel serverseitig.** 475 Kunden lassen sich nicht in einer Antwort ausliefern und
  im Browser sortieren.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.dienste.nummernkreise import naechster_wert
from app.dienste.suche import alle_woerter
from app.fehler import Konflikt, NichtGefunden
from app.modelle import Ansprechpartner, Firma, Kunde, Projekt
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung

log = logger(__name__)

router = APIRouter(prefix="/api", tags=["Stammdaten"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung kunden.lesen fehlt"},
}
SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung kunden.schreiben fehlt"},
    404: {"description": "Datensatz nicht gefunden"},
    409: {"description": "Der Datensatz wurde zwischenzeitlich geändert"},
}

# Höchstwert je Seite. Ohne Deckel könnte eine Anfrage alle 475 Kunden samt Ansprechpartnern
# ziehen – das ist keine Liste mehr, sondern ein Export.
SEITE_STANDARD = 25
SEITE_MAX = 200


class AnsprechpartnerAntwort(BaseModel):
    id: int
    name: str
    funktion: str | None = None
    telefon: str | None = None
    email: str | None = None
    bemerkung: str | None = None
    stand: datetime


class KundeZeile(BaseModel):
    """Kunde in der Liste – nur, was in der Tabelle steht."""

    id: int
    kunden_nr: int
    name: str
    zusatz: str | None = None
    ort: str | None = None
    typ: str
    status: str
    anzahl_projekte: int


class KundenSeite(BaseModel):
    eintraege: list[KundeZeile]
    gesamt: int
    versatz: int
    anzahl: int


class KundeAntwort(BaseModel):
    id: int
    kunden_nr: int
    name: str
    zusatz: str | None = None
    strasse: str | None = None
    plz: str | None = None
    ort: str | None = None
    ust_id: str | None = None
    typ: str
    zahlungsziel_tage: int | None = None
    email: str | None = None
    telefon: str | None = None
    status: str
    bemerkung: str | None = None
    # Der Stand, gegen den beim Speichern geprüft wird. Die Maske schickt ihn unverändert zurück.
    stand: datetime
    ansprechpartner: list[AnsprechpartnerAntwort] = Field(default_factory=list)
    anzahl_projekte: int = 0


class KundeEingabe(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    zusatz: str | None = Field(default=None, max_length=200)
    strasse: str | None = Field(default=None, max_length=200)
    plz: str | None = Field(default=None, max_length=10)
    ort: str | None = Field(default=None, max_length=200)
    ust_id: str | None = Field(default=None, max_length=50)
    typ: Literal["b2b", "b2c"] = "b2c"
    zahlungsziel_tage: int | None = Field(default=None, ge=0, le=365)
    email: str | None = Field(default=None, max_length=200)
    telefon: str | None = Field(default=None, max_length=50)
    status: Literal["aktiv", "inaktiv"] = "aktiv"
    bemerkung: str | None = None

    @field_validator("zusatz", "strasse", "ort", "ust_id", "email", "telefon", "plz")
    @classmethod
    def leerraum_kuerzen(cls, wert: str | None) -> str | None:
        # Führende und folgende Leerzeichen sind der häufigste Grund, warum derselbe Kunde
        # zweimal in einer Liste steht. In der Teamliste stand der Projektleiter 16-mal
        # verschieden geschrieben, in 11 Fällen nur wegen eines Leerzeichens.
        if wert is None:
            return None
        gekuerzt = wert.strip()
        return gekuerzt or None

    @field_validator("name")
    @classmethod
    def name_pruefen(cls, wert: str) -> str:
        """Der Name ist Pflicht – er darf nicht durch das Kürzen verschwinden.

        Getrennt von :meth:`leerraum_kuerzen`, weil dieses leere Werte zu ``None`` macht. Für ein
        Pflichtfeld wäre das ein Datenbankfehler mit Vorgangsnummer statt einer Meldung am Feld;
        genau das soll nicht passieren (CLAUDE.md Regel 8).
        """
        gekuerzt = wert.strip()
        if not gekuerzt:
            raise ValueError("Der Name darf nicht leer sein.")
        return gekuerzt


class KundeAendern(KundeEingabe):
    """Wie :class:`KundeEingabe`, zusätzlich der gelesene Stand für die Konfliktprüfung."""

    stand: datetime


class AnsprechpartnerEingabe(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    funktion: Literal["technik", "kaufmaennisch", "sonstig"] | None = None
    telefon: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    bemerkung: str | None = None

    @field_validator("telefon", "email")
    @classmethod
    def leerraum_kuerzen(cls, wert: str | None) -> str | None:
        if wert is None:
            return None
        return wert.strip() or None

    @field_validator("name")
    @classmethod
    def name_pruefen(cls, wert: str) -> str:
        gekuerzt = wert.strip()
        if not gekuerzt:
            raise ValueError("Der Name darf nicht leer sein.")
        return gekuerzt


class AnsprechpartnerAendern(AnsprechpartnerEingabe):
    stand: datetime


def _projektzahlen(db: Session, kunden_ids: list[int]) -> dict[int, int]:
    """Projekte je Kunde in einer Abfrage.

    Nicht je Zeile einzeln zählen: bei 25 Zeilen wären das 25 zusätzliche Abfragen, und die
    Liste wird bei jedem Tastendruck im Suchfeld neu geholt.
    """
    if not kunden_ids:
        return {}
    zeilen = db.execute(
        select(Projekt.kunde_id, func.count(Projekt.id))
        .where(Projekt.kunde_id.in_(kunden_ids))
        .group_by(Projekt.kunde_id)
    ).all()
    return dict(zeilen)  # type: ignore[arg-type]


def _kunde_holen(db: Session, kunde_id: int) -> Kunde:
    kunde = db.get(Kunde, kunde_id)
    if kunde is None:
        raise NichtGefunden(
            f"Es gibt keinen Kunden mit der Nummer {kunde_id}.",
            "Die Kundenliste zeigt die vorhandenen Kunden.",
        )
    return kunde


def _als_antwort(db: Session, kunde: Kunde) -> KundeAntwort:
    anzahl = _projektzahlen(db, [kunde.id]).get(kunde.id, 0)
    return KundeAntwort(
        id=kunde.id,
        kunden_nr=kunde.kunden_nr,
        name=kunde.name,
        zusatz=kunde.zusatz,
        strasse=kunde.strasse,
        plz=kunde.plz,
        ort=kunde.ort,
        ust_id=kunde.ust_id,
        typ=kunde.typ,
        zahlungsziel_tage=kunde.zahlungsziel_tage,
        email=kunde.email,
        telefon=kunde.telefon,
        status=kunde.status,
        bemerkung=kunde.bemerkung,
        stand=kunde.updated_at,
        ansprechpartner=[
            AnsprechpartnerAntwort(
                id=a.id,
                name=a.name,
                funktion=a.funktion,
                telefon=a.telefon,
                email=a.email,
                bemerkung=a.bemerkung,
                stand=a.updated_at,
            )
            for a in sorted(kunde.ansprechpartner, key=lambda a: a.name)
        ],
        anzahl_projekte=anzahl,
    )


def _zustand(kunde: Kunde) -> dict[str, object]:
    """Felder für das Änderungsprotokoll."""
    return {
        feld: getattr(kunde, feld)
        for feld in (
            "name",
            "zusatz",
            "strasse",
            "plz",
            "ort",
            "ust_id",
            "typ",
            "zahlungsziel_tage",
            "email",
            "telefon",
            "status",
            "bemerkung",
        )
    }


@router.get(
    "/kunden",
    response_model=KundenSeite,
    summary="Kunden suchen und blättern",
    operation_id="kundenListe",
    responses=LESEN,
)
def kunden_liste(
    zugriff: Zugriff = Depends(benoetigt("kunden.lesen")),
    db: Session = Depends(db_sitzung),
    suche: str = Query("", description="Name, Ort oder Kundennummer; Umlaute beliebig"),
    status: Literal["aktiv", "inaktiv", "alle"] = Query("aktiv"),
    versatz: int = Query(0, ge=0),
    anzahl: int = Query(SEITE_STANDARD, ge=1, le=SEITE_MAX),
) -> KundenSeite:
    """Kundenliste. Standardmäßig nur aktive – inaktive sind Altbestand und stören beim Suchen."""
    abfrage = select(Kunde)
    if status != "alle":
        abfrage = abfrage.where(Kunde.status == status)

    bedingung = alle_woerter(suche, Kunde.name, Kunde.ort, Kunde.zusatz)
    if suche.strip().isdigit():
        # Eine reine Zahl kann die Kundennummer sein – oder Teil eines Namens
        # („Volksfestplatz Weiden 2"). Beides muss finden, deshalb ODER und nicht ENTWEDER:
        # als elif-Zweig wäre die Nummernsuche unerreichbar gewesen, weil die Textsuche bei
        # jeder nicht leeren Eingabe eine Bedingung liefert.
        nach_nummer = Kunde.kunden_nr == int(suche.strip())
        bedingung = or_(bedingung, nach_nummer) if bedingung is not None else nach_nummer
    if bedingung is not None:
        abfrage = abfrage.where(bedingung)

    gesamt = db.scalar(select(func.count()).select_from(abfrage.subquery())) or 0
    seite = list(
        db.scalars(abfrage.order_by(Kunde.name, Kunde.kunden_nr).offset(versatz).limit(anzahl))
    )
    zahlen = _projektzahlen(db, [k.id for k in seite])

    return KundenSeite(
        eintraege=[
            KundeZeile(
                id=k.id,
                kunden_nr=k.kunden_nr,
                name=k.name,
                zusatz=k.zusatz,
                ort=k.ort,
                typ=k.typ,
                status=k.status,
                anzahl_projekte=zahlen.get(k.id, 0),
            )
            for k in seite
        ],
        gesamt=gesamt,
        versatz=versatz,
        anzahl=anzahl,
    )


@router.get(
    "/kunden/{kunde_id}",
    response_model=KundeAntwort,
    summary="Kunden mit Ansprechpartnern lesen",
    operation_id="kundeLesen",
    responses={**LESEN, 404: {"description": "Kunde nicht gefunden"}},
)
def kunde_lesen(
    kunde_id: int,
    zugriff: Zugriff = Depends(benoetigt("kunden.lesen")),
    db: Session = Depends(db_sitzung),
) -> KundeAntwort:
    return _als_antwort(db, _kunde_holen(db, kunde_id))


@router.post(
    "/kunden",
    response_model=KundeAntwort,
    status_code=201,
    summary="Kunden anlegen",
    operation_id="kundeAnlegen",
    responses=SCHREIBEN,
)
def kunde_anlegen(
    eingabe: KundeEingabe,
    zugriff: Zugriff = Depends(benoetigt("kunden.schreiben")),
    db: Session = Depends(db_sitzung),
) -> KundeAntwort:
    """Neuen Kunden anlegen. Die Kundennummer vergibt der Nummernkreis (PLAN §3)."""
    firma_id = db.scalar(select(Firma.id).order_by(Firma.id).limit(1))
    if firma_id is None:  # pragma: no cover – der Seed legt die Firma immer an
        raise NichtGefunden(
            "In der Datenbank ist keine Firma angelegt.",
            "Der Leitstand ist nicht vollständig eingerichtet. Bitte Sven informieren.",
        )

    kunde = Kunde(kunden_nr=naechster_wert(db, firma_id, "KD"), **eingabe.model_dump())
    db.add(kunde)
    db.flush()
    audit.eintragen(
        db,
        "kunde.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="kunden",
        datensatz_id=kunde.id,
        neu=_zustand(kunde),
    )
    db.commit()
    log.info("Kunde %s angelegt: %s", kunde.kunden_nr, kunde.name)
    return _als_antwort(db, kunde)


@router.put(
    "/kunden/{kunde_id}",
    response_model=KundeAntwort,
    summary="Kunden ändern",
    operation_id="kundeAendern",
    responses=SCHREIBEN,
)
def kunde_aendern(
    kunde_id: int,
    eingabe: KundeAendern,
    zugriff: Zugriff = Depends(benoetigt("kunden.schreiben")),
    db: Session = Depends(db_sitzung),
) -> KundeAntwort:
    """Kunden ändern, mit Konfliktprüfung gegen den gelesenen Stand."""
    kunde = _kunde_holen(db, kunde_id)
    stand_pruefen(kunde, eingabe.stand, "Der Kunde")

    vorher = _zustand(kunde)
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(kunde, feld, wert)
    nachher = _zustand(kunde)

    unterschiede = geaenderte_felder(vorher, nachher)
    if not unterschiede:
        # Nichts geändert: kein Protokolleintrag. Ein Protokoll voller Leeränderungen verdeckt
        # die echten.
        return _als_antwort(db, kunde)

    audit.eintragen(
        db,
        "kunde.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="kunden",
        datensatz_id=kunde.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={f: w["neu"] for f, w in unterschiede.items()},
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Der Kunde")
        raise
    return _als_antwort(db, kunde)


@router.get(
    "/kunden/{kunde_id}/ansprechpartner",
    response_model=list[AnsprechpartnerAntwort],
    summary="Ansprechpartner eines Kunden",
    operation_id="ansprechpartnerListe",
    responses={**LESEN, 404: {"description": "Kunde nicht gefunden"}},
)
def ansprechpartner_liste(
    kunde_id: int,
    zugriff: Zugriff = Depends(benoetigt("kunden.lesen")),
    db: Session = Depends(db_sitzung),
) -> list[AnsprechpartnerAntwort]:
    kunde = _kunde_holen(db, kunde_id)
    return _als_antwort(db, kunde).ansprechpartner


@router.post(
    "/kunden/{kunde_id}/ansprechpartner",
    response_model=AnsprechpartnerAntwort,
    status_code=201,
    summary="Ansprechpartner anlegen",
    operation_id="ansprechpartnerAnlegen",
    responses=SCHREIBEN,
)
def ansprechpartner_anlegen(
    kunde_id: int,
    eingabe: AnsprechpartnerEingabe,
    zugriff: Zugriff = Depends(benoetigt("kunden.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AnsprechpartnerAntwort:
    kunde = _kunde_holen(db, kunde_id)
    # UNIQUE(kunde_id, name) fängt Doppelte in der Datenbank ab; hier die verständliche Meldung.
    if any(a.name == eingabe.name for a in kunde.ansprechpartner):
        raise Konflikt(
            f"Bei {kunde.name} gibt es schon einen Ansprechpartner mit dem Namen '{eingabe.name}'.",
            "Den vorhandenen Eintrag bearbeiten, oder den Namen unterscheidbar machen "
            "(zum Beispiel mit Vornamen).",
            code="ansprechpartner_doppelt",
        )

    partner = Ansprechpartner(kunde_id=kunde.id, **eingabe.model_dump())
    db.add(partner)
    db.flush()
    audit.eintragen(
        db,
        "ansprechpartner.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="ansprechpartner",
        datensatz_id=partner.id,
        neu={"kunde": kunde.name, **eingabe.model_dump()},
    )
    db.commit()
    return AnsprechpartnerAntwort(
        id=partner.id,
        name=partner.name,
        funktion=partner.funktion,
        telefon=partner.telefon,
        email=partner.email,
        bemerkung=partner.bemerkung,
        stand=partner.updated_at,
    )


def _partner_holen(db: Session, partner_id: int) -> Ansprechpartner:
    partner = db.get(Ansprechpartner, partner_id)
    if partner is None:
        raise NichtGefunden(
            "Diesen Ansprechpartner gibt es nicht.",
            "Vermutlich hat ihn jemand anderes gelöscht. Bitte die Seite neu laden.",
        )
    return partner


@router.put(
    "/ansprechpartner/{partner_id}",
    response_model=AnsprechpartnerAntwort,
    summary="Ansprechpartner ändern",
    operation_id="ansprechpartnerAendern",
    responses=SCHREIBEN,
)
def ansprechpartner_aendern(
    partner_id: int,
    eingabe: AnsprechpartnerAendern,
    zugriff: Zugriff = Depends(benoetigt("kunden.schreiben")),
    db: Session = Depends(db_sitzung),
) -> AnsprechpartnerAntwort:
    partner = _partner_holen(db, partner_id)
    stand_pruefen(partner, eingabe.stand, "Der Ansprechpartner")

    felder = ("name", "funktion", "telefon", "email", "bemerkung")
    vorher = {f: getattr(partner, f) for f in felder}
    for feld, wert in eingabe.model_dump(exclude={"stand"}).items():
        setattr(partner, feld, wert)
    nachher = {f: getattr(partner, f) for f in felder}

    unterschiede = geaenderte_felder(vorher, nachher)
    if unterschiede:
        audit.eintragen(
            db,
            "ansprechpartner.geaendert",
            nutzer=zugriff.nutzer,
            ip=zugriff.ip,
            tabelle="ansprechpartner",
            datensatz_id=partner.id,
            alt={f: w["alt"] for f, w in unterschiede.items()},
            neu={f: w["neu"] for f, w in unterschiede.items()},
        )
        try:
            db.commit()
        except Exception as fehler:
            db.rollback()
            konflikt_uebersetzen(fehler, "Der Ansprechpartner")
            raise

    return AnsprechpartnerAntwort(
        id=partner.id,
        name=partner.name,
        funktion=partner.funktion,
        telefon=partner.telefon,
        email=partner.email,
        bemerkung=partner.bemerkung,
        stand=partner.updated_at,
    )


@router.delete(
    "/ansprechpartner/{partner_id}",
    status_code=204,
    summary="Ansprechpartner löschen",
    operation_id="ansprechpartnerLoeschen",
    responses=SCHREIBEN,
)
def ansprechpartner_loeschen(
    partner_id: int,
    zugriff: Zugriff = Depends(benoetigt("kunden.schreiben")),
    db: Session = Depends(db_sitzung),
) -> None:
    """Ansprechpartner löschen.

    Die einzige Löschroute im Leitstand. Begründung: an einem Ansprechpartner hängt kein Beleg
    und keine Buchung – er ist eine Kontaktnotiz. Kunden, Projekte und Belege werden dagegen nie
    gelöscht, sondern wechseln den Status (CLAUDE.md Regel 5). Der Name bleibt im
    Änderungsprotokoll, damit nachvollziehbar ist, wer wann entfernt wurde.
    """
    partner = _partner_holen(db, partner_id)
    audit.eintragen(
        db,
        "ansprechpartner.geloescht",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="ansprechpartner",
        datensatz_id=partner.id,
        alt={
            "name": partner.name,
            "funktion": partner.funktion,
            "telefon": partner.telefon,
            "email": partner.email,
        },
    )
    db.delete(partner)
    db.commit()
