"""Projekte, Meilensteine und die Zuordnung der Projektleiter (PLAN §5, §7 Phase 1).

Der Kern dieses Moduls ist die **Finanzsichtbarkeit** aus PLAN §4. Die Rolle ``team`` sieht
Projekte, Termine und Anlagendaten, aber keine Beträge. Umgesetzt ist das nicht durch Ausblenden
in der Oberfläche, sondern dadurch, dass die Antwort die Felder **nicht enthält**: ohne
``projekte.werte_lesen`` fehlen ``ab_wert_netto`` und die Zahlungsplansummen, auch wenn jemand
die Adresse direkt aufruft (CLAUDE.md Regel 2).

Der Sichtbarkeits-Scope ``eigene`` beschränkt zusätzlich auf Projekte, bei denen der Nutzer als
Projektleiter eingetragen ist. Dafür muss ``pl_user_id`` gesetzt sein – nach der Migration steht
dort nichts, weil die Teamliste nur Vornamen führt. Die Zuordnungsmaske am Ende dieses Moduls
schließt diese Lücke: elf Namen, je einer ein Konto, wirksam für alle Projekte des Namens.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.dienste.konflikt import geaenderte_felder, konflikt_uebersetzen, stand_pruefen
from app.dienste.nummernkreise import naechste_projektnummer
from app.dienste.suche import alle_woerter
from app.fehler import Konflikt, NichtGefunden
from app.modelle import Firma, Kunde, Meilenstein, Projekt, User, Zahlungsplanposition
from app.modelle.projekte import ANLAGENARTEN, MEILENSTEIN_TYPEN, PROJEKT_STATUS
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, scope_filter

log = logger(__name__)

router = APIRouter(prefix="/api/projekte", tags=["Projekte"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung projekte.lesen fehlt"},
}
SCHREIBEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung projekte.schreiben fehlt"},
    404: {"description": "Projekt nicht gefunden"},
    409: {"description": "Das Projekt wurde zwischenzeitlich geändert"},
}

SEITE_STANDARD = 25
SEITE_MAX = 200


class ProjektZeile(BaseModel):
    """Projekt in der Liste (design/Projektliste.dc.html)."""

    id: int
    projekt_nr: int
    # Die Liste zeigt die Bezeichnung, und wo keine steht, den Kundennamen.
    bezeichnung: str | None = None
    kunde: str
    kunde_id: int
    standort: str | None = None
    anlagenart: str | None = None
    pv_kwp: float | None = None
    speicher_kwh: float | None = None
    status: str
    pl_name: str | None = None
    auftrag_vom: date | None = None
    # Fehlt ohne projekte.werte_lesen – nicht null, sondern nicht vorhanden.
    ab_wert_netto: int | None = None


class ProjekteSeite(BaseModel):
    eintraege: list[ProjektZeile]
    gesamt: int
    versatz: int
    anzahl: int
    # Für die Filterleiste: was in den Daten tatsächlich vorkommt.
    jahre: list[int] = Field(default_factory=list)
    projektleiter: list[str] = Field(default_factory=list)
    # Auftragswert über die **gesamte** gefilterte Auswahl, nicht nur über die angezeigte Seite –
    # die Kopfzeile des Mockups nennt das Volumen des Jahres. Ohne projekte.werte_lesen fehlt es.
    auftragsvolumen: int | None = None


class MeilensteinAntwort(BaseModel):
    id: int
    typ: str
    geplant_kw: str | None = None
    erledigt: bool | None = None
    erledigt_am: date | None = None
    bemerkung: str | None = None
    stand: datetime


class ZahlungsplanZeile(BaseModel):
    id: int
    pos_nr: int
    bezeichnung: str
    gewerk: str
    art: str
    betrag_netto: int
    plan_monat: str | None = None
    trigger_status: str | None = None
    migriert_gestellt: bool | None = None
    berechnet: bool
    quelle_migration: str | None = None
    stand: datetime
    # Warum die Position nicht bearbeitbar ist – leer, wenn sie es ist. Die Maske zeichnet sie
    # damit von Anfang an als gesperrt, statt den Nutzer beim Speichern auflaufen zu lassen.
    sperrgrund: str | None = None


class NachtragZeile(BaseModel):
    id: int
    bezeichnung: str
    betrag_netto: int
    status: str
    datum: date | None = None
    zaehlt_zum_soll: bool
    stand: datetime


class ProjektAntwort(BaseModel):
    id: int
    projekt_nr: int
    bezeichnung: str | None = None
    kunde: str
    kunde_id: int
    typ: str
    standort: str | None = None
    anlagenart: str | None = None
    pv_kwp: float | None = None
    wr_typ: str | None = None
    speicher_typ: str | None = None
    speicher_kwh: float | None = None
    ladestation: str | None = None
    auftrag_vom: date | None = None
    pl_name: str | None = None
    pl_user_id: int | None = None
    vertriebsweg: str | None = None
    ust_kz: str
    status: str
    quelle_migration: str | None = None
    bemerkung: str | None = None
    stand: datetime
    meilensteine: list[MeilensteinAntwort] = Field(default_factory=list)
    # Beträge nur mit projekte.werte_lesen.
    ab_wert_netto: int | None = None
    zahlungsplan: list[ZahlungsplanZeile] = Field(default_factory=list)
    zahlungsplan_summe: int | None = None
    zahlungsplan_gestellt_summe: int | None = None
    nachtraege: list[NachtragZeile] = Field(default_factory=list)
    # Soll-Ist-Vergleich des Zahlungsplans (PLAN §6.12): Auftragswert plus beauftragte Nachträge
    # gegen die Summe der Positionen. Eine Abweichung ist eine Warnung, keine Sperre.
    soll_netto: int | None = None
    nachtraege_summe: int | None = None
    deckung_differenz: int | None = None
    darf_werte_sehen: bool = False


class ProjektEingabe(BaseModel):
    kunde_id: int
    bezeichnung: str | None = Field(default=None, max_length=200)
    typ: Literal["projekt", "service"] = "projekt"
    standort: str | None = Field(default=None, max_length=200)
    anlagenart: Literal[ANLAGENARTEN] | None = None  # type: ignore[valid-type]
    pv_kwp: float | None = Field(default=None, ge=0, le=100000)
    wr_typ: str | None = Field(default=None, max_length=200)
    speicher_typ: str | None = Field(default=None, max_length=200)
    speicher_kwh: float | None = Field(default=None, ge=0, le=100000)
    ladestation: str | None = Field(default=None, max_length=200)
    auftrag_vom: date | None = None
    ab_wert_netto: int | None = Field(default=None, ge=0)
    pl_name: str | None = Field(default=None, max_length=100)
    pl_user_id: int | None = None
    vertriebsweg: str | None = Field(default=None, max_length=100)
    ust_kz: Literal["19", "0", "13b", "gemischt"] = "19"
    status: Literal[PROJEKT_STATUS] = "beauftragt"  # type: ignore[valid-type]
    bemerkung: str | None = None

    @field_validator(
        "bezeichnung",
        "standort",
        "wr_typ",
        "speicher_typ",
        "ladestation",
        "pl_name",
        "vertriebsweg",
    )
    @classmethod
    def leerraum_kuerzen(cls, wert: str | None) -> str | None:
        if wert is None:
            return None
        return wert.strip() or None


class ProjektAendern(ProjektEingabe):
    stand: datetime


class MeilensteinEingabe(BaseModel):
    typ: Literal[MEILENSTEIN_TYPEN]  # type: ignore[valid-type]
    geplant_kw: str | None = Field(default=None, max_length=20)
    erledigt: bool | None = None
    erledigt_am: date | None = None
    bemerkung: str | None = None


def _kunde_namen(db: Session, kunde_ids: list[int]) -> dict[int, str]:
    if not kunde_ids:
        return {}
    zeilen = db.execute(select(Kunde.id, Kunde.name).where(Kunde.id.in_(kunde_ids))).all()
    return dict(zeilen)  # type: ignore[arg-type]


def _projekt_holen(db: Session, projekt_nr: int, zugriff: Zugriff) -> Projekt:
    """Projekt über die Projektnummer, nicht über die technische ID.

    Die Projektnummer ist der Schlüssel, den alle verwenden – sie steht auf der Rechnung, im
    DATEV-Kostenträger und im Dateinamen des Kalkulationsblatts (PLAN §3). Eine Adresse mit der
    technischen ID wäre für Menschen unbrauchbar.
    """
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
            "Die Projektliste zeigt die vorhandenen Projekte. Wer nur eigene Projekte sehen "
            "darf, findet fremde hier nicht.",
        )
    return projekt


def _zahlungsplan(db: Session, projekt_id: int) -> list[Zahlungsplanposition]:
    return list(
        db.scalars(
            select(Zahlungsplanposition)
            .where(Zahlungsplanposition.projekt_id == projekt_id)
            .order_by(Zahlungsplanposition.pos_nr)
        )
    )


def _als_antwort(db: Session, projekt: Projekt, darf_werte: bool) -> ProjektAntwort:
    namen = _kunde_namen(db, [projekt.kunde_id])
    positionen = _zahlungsplan(db, projekt.id) if darf_werte else []

    antwort = ProjektAntwort(
        id=projekt.id,
        projekt_nr=projekt.projekt_nr,
        bezeichnung=projekt.bezeichnung,
        kunde=namen.get(projekt.kunde_id, "unbekannt"),
        kunde_id=projekt.kunde_id,
        typ=projekt.typ,
        standort=projekt.standort,
        anlagenart=projekt.anlagenart,
        pv_kwp=float(projekt.pv_kwp) if projekt.pv_kwp is not None else None,
        wr_typ=projekt.wr_typ,
        speicher_typ=projekt.speicher_typ,
        speicher_kwh=float(projekt.speicher_kwh) if projekt.speicher_kwh is not None else None,
        ladestation=projekt.ladestation,
        auftrag_vom=projekt.auftrag_vom,
        pl_name=projekt.pl_name,
        pl_user_id=projekt.pl_user_id,
        vertriebsweg=projekt.vertriebsweg,
        ust_kz=projekt.ust_kz,
        status=projekt.status,
        quelle_migration=projekt.quelle_migration,
        bemerkung=projekt.bemerkung,
        stand=projekt.updated_at,
        meilensteine=[
            MeilensteinAntwort(
                id=m.id,
                typ=m.typ,
                geplant_kw=m.geplant_kw,
                erledigt=m.erledigt,
                erledigt_am=m.erledigt_am,
                bemerkung=m.bemerkung,
                stand=m.updated_at,
            )
            for m in sorted(projekt.meilensteine, key=lambda m: MEILENSTEIN_TYPEN.index(m.typ))
        ],
        darf_werte_sehen=darf_werte,
    )

    # Beträge nur mit projekte.werte_lesen – die Felder fehlen sonst ganz (PLAN §4).
    if darf_werte:
        # Die Sperrgründe und die Deckungsrechnung stehen in app/routen/zahlungsplan.py – dort
        # gehören sie fachlich hin, und so gibt es sie nur einmal.
        from app.routen.zahlungsplan import NACHTRAG_ZAEHLT, deckung_berechnen
        from app.routen.zahlungsplan import _sperrgrund as sperrgrund

        antwort.ab_wert_netto = projekt.ab_wert_netto
        antwort.zahlungsplan = [
            ZahlungsplanZeile(
                id=p.id,
                pos_nr=p.pos_nr,
                bezeichnung=p.bezeichnung,
                gewerk=p.gewerk,
                art=p.art,
                betrag_netto=p.betrag_netto,
                plan_monat=p.plan_monat,
                trigger_status=p.trigger_status,
                migriert_gestellt=p.migriert_gestellt,
                berechnet=p.rechnung_id is not None,
                quelle_migration=p.quelle_migration,
                stand=p.updated_at,
                sperrgrund=sperrgrund(p),
            )
            for p in positionen
        ]
        antwort.zahlungsplan_summe = sum(p.betrag_netto for p in positionen)
        antwort.zahlungsplan_gestellt_summe = sum(
            p.betrag_netto for p in positionen if p.migriert_gestellt or p.rechnung_id
        )
        antwort.nachtraege = [
            NachtragZeile(
                id=n.id,
                bezeichnung=n.bezeichnung,
                betrag_netto=n.betrag_netto,
                status=n.status,
                datum=n.datum,
                zaehlt_zum_soll=n.status in NACHTRAG_ZAEHLT,
                stand=n.updated_at,
            )
            for n in sorted(projekt.nachtraege, key=lambda n: n.id)
        ]
        deckung = deckung_berechnen(db, projekt)
        antwort.soll_netto = deckung.soll_netto
        antwort.nachtraege_summe = deckung.nachtraege_netto
        antwort.deckung_differenz = deckung.differenz_netto
    return antwort


def _zustand(projekt: Projekt) -> dict[str, object]:
    return {
        feld: getattr(projekt, feld)
        for feld in (
            "bezeichnung",
            "kunde_id",
            "typ",
            "standort",
            "anlagenart",
            "pv_kwp",
            "wr_typ",
            "speicher_typ",
            "speicher_kwh",
            "ladestation",
            "auftrag_vom",
            "ab_wert_netto",
            "pl_name",
            "pl_user_id",
            "vertriebsweg",
            "ust_kz",
            "status",
            "bemerkung",
        )
    }


@router.get(
    "",
    response_model=ProjekteSeite,
    summary="Projekte filtern und blättern",
    operation_id="projekteListe",
    responses=LESEN,
)
def projekte_liste(
    zugriff: Zugriff = Depends(benoetigt("projekte.lesen")),
    db: Session = Depends(db_sitzung),
    suche: str = Query("", description="Kunde, Ort, Bezeichnung oder Projektnummer"),
    jahr: int | None = Query(None, description="Auftragsjahr aus der Projektnummer"),
    status: str = Query("alle"),
    projektleiter: str = Query("alle"),
    anlagenart: str = Query("alle"),
    versatz: int = Query(0, ge=0),
    anzahl: int = Query(SEITE_STANDARD, ge=1, le=SEITE_MAX),
) -> ProjekteSeite:
    """Projektliste mit den Filtern aus design/Projektliste.dc.html."""
    darf_werte = zugriff.darf("projekte.werte_lesen")

    grund = scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)
    if status != "alle":
        grund = grund.where(Projekt.status == status)
    if projektleiter != "alle":
        grund = grund.where(Projekt.pl_name == projektleiter)
    if anlagenart != "alle":
        grund = grund.where(Projekt.anlagenart == anlagenart)
    if jahr is not None:
        # Die Projektnummer trägt das Jahr in den ersten zwei Stellen (JJNNN, PLAN §3). Über die
        # Nummer statt über auftrag_vom, weil 41 migrierte Projekte kein Auftragsdatum haben –
        # die Nummer haben alle.
        grund = grund.where(
            Projekt.projekt_nr >= (jahr % 100) * 1000,
            Projekt.projekt_nr < (jahr % 100 + 1) * 1000,
        )

    if suche.strip():
        bedingung = alle_woerter(
            suche, Projekt.bezeichnung, Projekt.standort, Projekt.pl_name, Kunde.name
        )
        nach_nummer = Projekt.projekt_nr == int(suche.strip()) if suche.strip().isdigit() else None
        grund = grund.join(Kunde, Kunde.id == Projekt.kunde_id)
        if bedingung is not None and nach_nummer is not None:
            from sqlalchemy import or_

            grund = grund.where(or_(bedingung, nach_nummer))
        elif bedingung is not None:
            grund = grund.where(bedingung)
        elif nach_nummer is not None:
            grund = grund.where(nach_nummer)

    unterabfrage = grund.subquery()
    gesamt = db.scalar(select(func.count()).select_from(unterabfrage)) or 0
    volumen = db.scalar(select(func.sum(unterabfrage.c.ab_wert_netto))) if darf_werte else None
    seite = list(
        db.scalars(grund.order_by(Projekt.projekt_nr.desc()).offset(versatz).limit(anzahl))
    )
    namen = _kunde_namen(db, [p.kunde_id for p in seite])

    # Werte für die Filterleiste aus dem sichtbaren Bestand, nicht fest verdrahtet: ein Jahr, in
    # dem es keine Projekte gibt, gehört nicht in die Auswahl. Die Spalten stehen direkt im
    # SELECT, nicht als select_from über eine Unterabfrage – sonst bezieht sich die Spalte auf
    # die Tabelle statt auf die Unterabfrage, SQLite bildet ein Kreuzprodukt und die
    # Sichtbarkeitsgrenze „eigene" wäre in der Filterleiste wirkungslos.
    sichtbar = scope_filter(
        select(Projekt.projekt_nr, Projekt.pl_name).distinct(),
        zugriff,
        "projekte.lesen",
        Projekt.pl_user_id,
    )
    nummern_und_leiter = db.execute(sichtbar).all()
    jahre = sorted({2000 + nr // 1000 for nr, _ in nummern_und_leiter}, reverse=True)
    leiter = sorted({name for _, name in nummern_und_leiter if name})

    return ProjekteSeite(
        eintraege=[
            ProjektZeile(
                id=p.id,
                projekt_nr=p.projekt_nr,
                bezeichnung=p.bezeichnung,
                kunde=namen.get(p.kunde_id, "unbekannt"),
                kunde_id=p.kunde_id,
                standort=p.standort,
                anlagenart=p.anlagenart,
                pv_kwp=float(p.pv_kwp) if p.pv_kwp is not None else None,
                speicher_kwh=float(p.speicher_kwh) if p.speicher_kwh is not None else None,
                status=p.status,
                pl_name=p.pl_name,
                auftrag_vom=p.auftrag_vom,
                ab_wert_netto=p.ab_wert_netto if darf_werte else None,
            )
            for p in seite
        ],
        gesamt=gesamt,
        versatz=versatz,
        anzahl=anzahl,
        jahre=jahre,
        projektleiter=leiter,
        auftragsvolumen=int(volumen) if volumen is not None else None,
    )


@router.get(
    "/{projekt_nr}",
    response_model=ProjektAntwort,
    summary="Projekt mit Meilensteinen und Zahlungsplan lesen",
    operation_id="projektLesen",
    responses={**LESEN, 404: {"description": "Projekt nicht gefunden"}},
)
def projekt_lesen(
    projekt_nr: int,
    zugriff: Zugriff = Depends(benoetigt("projekte.lesen")),
    db: Session = Depends(db_sitzung),
) -> ProjektAntwort:
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    return _als_antwort(db, projekt, zugriff.darf("projekte.werte_lesen"))


@router.post(
    "",
    response_model=ProjektAntwort,
    status_code=201,
    summary="Projekt anlegen",
    operation_id="projektAnlegen",
    responses=SCHREIBEN,
)
def projekt_anlegen(
    eingabe: ProjektEingabe,
    zugriff: Zugriff = Depends(benoetigt("projekte.schreiben")),
    db: Session = Depends(db_sitzung),
) -> ProjektAntwort:
    """Neues Projekt. Die Projektnummer richtet sich nach dem Auftragsjahr (PLAN §3)."""
    if db.get(Kunde, eingabe.kunde_id) is None:
        raise NichtGefunden(
            "Den angegebenen Kunden gibt es nicht.",
            "Zuerst den Kunden unter Stammdaten anlegen, dann das Projekt.",
        )
    firma_id = db.scalar(select(Firma.id).order_by(Firma.id).limit(1))
    if firma_id is None:  # pragma: no cover – der Seed legt die Firma immer an
        raise NichtGefunden(
            "In der Datenbank ist keine Firma angelegt.",
            "Der Leitstand ist nicht vollständig eingerichtet. Bitte Sven informieren.",
        )

    if not zugriff.darf("projekte.werte_lesen") and eingabe.ab_wert_netto is not None:
        # Wer die Beträge nicht sehen darf, darf sie auch nicht setzen. Ohne diese Prüfung
        # könnte jemand einen Wert eintragen, den er anschließend nicht mehr liest.
        raise Konflikt(
            "Zum Erfassen des Auftragswertes fehlt die Berechtigung.",
            "Das Projekt ohne Auftragswert anlegen; die Buchhaltung trägt ihn nach.",
            code="werte_ohne_berechtigung",
        )

    jahr = eingabe.auftrag_vom.year if eingabe.auftrag_vom else None
    projekt = Projekt(
        projekt_nr=naechste_projektnummer(
            db, firma_id, jahr=jahr, service=eingabe.typ == "service"
        ),
        firma_id=firma_id,
        **eingabe.model_dump(),
    )
    db.add(projekt)
    db.flush()
    audit.eintragen(
        db,
        "projekt.angelegt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="projekte",
        datensatz_id=projekt.id,
        neu={"projekt_nr": projekt.projekt_nr, **_zustand(projekt)},
    )
    db.commit()
    log.info("Projekt %s angelegt", projekt.projekt_nr)
    return _als_antwort(db, projekt, zugriff.darf("projekte.werte_lesen"))


@router.put(
    "/{projekt_nr}",
    response_model=ProjektAntwort,
    summary="Projekt ändern",
    operation_id="projektAendern",
    responses=SCHREIBEN,
)
def projekt_aendern(
    projekt_nr: int,
    eingabe: ProjektAendern,
    zugriff: Zugriff = Depends(benoetigt("projekte.schreiben")),
    db: Session = Depends(db_sitzung),
) -> ProjektAntwort:
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    stand_pruefen(projekt, eingabe.stand, "Das Projekt")

    darf_werte = zugriff.darf("projekte.werte_lesen")
    if not darf_werte and eingabe.ab_wert_netto != projekt.ab_wert_netto:
        raise Konflikt(
            "Zum Ändern des Auftragswertes fehlt die Berechtigung.",
            "Die übrigen Angaben lassen sich speichern; den Auftragswert trägt die Buchhaltung "
            "nach.",
            code="werte_ohne_berechtigung",
        )

    vorher = _zustand(projekt)
    werte = eingabe.model_dump(exclude={"stand"})
    if not darf_werte:
        # Ohne die Berechtigung kommt das Feld nicht in der Antwort vor; ein mitgeschickter Wert
        # wäre also erfunden und darf nichts überschreiben.
        werte.pop("ab_wert_netto", None)
    for feld, wert in werte.items():
        setattr(projekt, feld, wert)
    nachher = _zustand(projekt)

    unterschiede = geaenderte_felder(vorher, nachher)
    if not unterschiede:
        return _als_antwort(db, projekt, darf_werte)

    audit.eintragen(
        db,
        "projekt.geaendert",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        tabelle="projekte",
        datensatz_id=projekt.id,
        alt={f: w["alt"] for f, w in unterschiede.items()},
        neu={
            "projekt_nr": projekt.projekt_nr,
            **{f: w["neu"] for f, w in unterschiede.items()},
        },
    )
    try:
        db.commit()
    except Exception as fehler:
        db.rollback()
        konflikt_uebersetzen(fehler, "Das Projekt")
        raise
    return _als_antwort(db, projekt, darf_werte)


@router.put(
    "/{projekt_nr}/meilensteine",
    response_model=list[MeilensteinAntwort],
    summary="Meilensteine eines Projekts setzen",
    operation_id="meilensteineSetzen",
    responses={
        401: {"description": "Nicht angemeldet"},
        403: {"description": "Berechtigung meilensteine.schreiben fehlt"},
        404: {"description": "Projekt nicht gefunden"},
    },
)
def meilensteine_setzen(
    projekt_nr: int,
    eingaben: list[MeilensteinEingabe],
    zugriff: Zugriff = Depends(benoetigt("meilensteine.schreiben")),
    db: Session = Depends(db_sitzung),
) -> list[MeilensteinAntwort]:
    """Meilensteine als Ganzes setzen.

    Übergeben wird der vollständige Stand, nicht einzelne Änderungen: die Zeitleiste im
    Projektdetail bearbeitet mehrere Schritte in einem Zug, und ein Aufruf je Häkchen würde
    zehn Anfragen und zehn Protokolleinträge für einen Vorgang erzeugen.

    Typen, die nicht mitgeschickt werden, bleiben unverändert – gelöscht wird hier nichts.
    """
    projekt = _projekt_holen(db, projekt_nr, zugriff)
    vorhanden = {m.typ: m for m in projekt.meilensteine}
    aenderungen: dict[str, dict[str, object]] = {}

    for eingabe in eingaben:
        stand = vorhanden.get(eingabe.typ)
        if stand is None:
            stand = Meilenstein(projekt_id=projekt.id, typ=eingabe.typ)
            db.add(stand)
            vorhanden[eingabe.typ] = stand
        vorher = (stand.geplant_kw, stand.erledigt, stand.erledigt_am, stand.bemerkung)
        stand.geplant_kw = eingabe.geplant_kw
        stand.erledigt = eingabe.erledigt
        stand.erledigt_am = eingabe.erledigt_am
        stand.bemerkung = eingabe.bemerkung
        nachher = (stand.geplant_kw, stand.erledigt, stand.erledigt_am, stand.bemerkung)
        if vorher != nachher:
            aenderungen[eingabe.typ] = {
                "alt": {
                    "geplant_kw": vorher[0],
                    "erledigt": vorher[1],
                    "erledigt_am": str(vorher[2]) if vorher[2] else None,
                },
                "neu": {
                    "geplant_kw": nachher[0],
                    "erledigt": nachher[1],
                    "erledigt_am": str(nachher[2]) if nachher[2] else None,
                },
            }

    db.flush()
    if aenderungen:
        audit.eintragen(
            db,
            "meilensteine.geaendert",
            nutzer=zugriff.nutzer,
            ip=zugriff.ip,
            tabelle="meilensteine",
            datensatz_id=projekt.id,
            neu={"projekt_nr": projekt.projekt_nr, "schritte": aenderungen},
        )
    db.commit()
    db.refresh(projekt)
    return _als_antwort(db, projekt, zugriff.darf("projekte.werte_lesen")).meilensteine


# ---------------------------------------------------------------------------
# Projektleiter den Nutzerkonten zuordnen
# ---------------------------------------------------------------------------
#
# Nach der Migration steht in `pl_name` ein Vorname („Stefan", „Günther") und in `pl_user_id`
# nichts. Damit greift der Sichtbarkeits-Scope `eigene` aus PLAN §4 nicht: er vergleicht die
# Nutzer-ID, und die fehlt.
#
# Die naive Lösung wäre ein Auswahlfeld je Projekt – bei 530 Projekten und 11 Namen bleibt das
# liegen. Deshalb eine Maske, die je **Name** entscheidet und die Zuordnung auf alle Projekte
# dieses Namens anwendet. Elf Entscheidungen statt 530.


class ProjektleiterName(BaseModel):
    """Ein Name aus der Teamliste und wie weit er zugeordnet ist."""

    pl_name: str
    anzahl_projekte: int
    # Verknüpfte Konten. Mehr als eines heißt: uneinheitlich zugeordnet, das gehört korrigiert.
    user_ids: list[int] = Field(default_factory=list)
    ohne_konto: int = 0


class Konto(BaseModel):
    id: int
    name: str
    email: str


class ProjektleiterUebersicht(BaseModel):
    namen: list[ProjektleiterName]
    konten: list[Konto]


class ProjektleiterZuordnung(BaseModel):
    """Name auf Konto; ``None`` löst die Zuordnung wieder."""

    zuordnungen: dict[str, int | None]


class ProjektleiterErgebnis(BaseModel):
    geaendert: int
    meldung: str


@router.get(
    "/projektleiter/uebersicht",
    response_model=ProjektleiterUebersicht,
    summary="Projektleiternamen und ihre Zuordnung",
    operation_id="projektleiterUebersicht",
    responses=LESEN,
)
def projektleiter_uebersicht(
    zugriff: Zugriff = Depends(benoetigt("projekte.schreiben")),
    db: Session = Depends(db_sitzung),
) -> ProjektleiterUebersicht:
    zeilen = db.execute(
        select(Projekt.pl_name, Projekt.pl_user_id, func.count(Projekt.id))
        .where(Projekt.pl_name.is_not(None))
        .group_by(Projekt.pl_name, Projekt.pl_user_id)
    ).all()

    je_name: dict[str, ProjektleiterName] = {}
    for name, user_id, anzahl in zeilen:
        eintrag = je_name.setdefault(name, ProjektleiterName(pl_name=name, anzahl_projekte=0))
        eintrag.anzahl_projekte += anzahl
        if user_id is None:
            eintrag.ohne_konto += anzahl
        elif user_id not in eintrag.user_ids:
            eintrag.user_ids.append(user_id)

    konten = [
        Konto(id=u.id, name=u.name, email=u.email)
        for u in db.scalars(select(User).where(User.aktiv.is_(True)).order_by(User.name))
    ]
    return ProjektleiterUebersicht(
        namen=sorted(je_name.values(), key=lambda n: -n.anzahl_projekte), konten=konten
    )


@router.put(
    "/projektleiter/zuordnen",
    response_model=ProjektleiterErgebnis,
    summary="Projektleiternamen Nutzerkonten zuordnen",
    operation_id="projektleiterZuordnen",
    responses=SCHREIBEN,
)
def projektleiter_zuordnen(
    anfrage: ProjektleiterZuordnung,
    zugriff: Zugriff = Depends(benoetigt("projekte.schreiben")),
    db: Session = Depends(db_sitzung),
) -> ProjektleiterErgebnis:
    """Setzt ``pl_user_id`` für alle Projekte eines Namens.

    Der Name bleibt stehen: er ist der Herkunftsnachweis aus der Teamliste. Wäre er
    überschrieben, ließe sich später nicht mehr prüfen, ob die Zuordnung stimmt.
    """
    konten = {u.id: u for u in db.scalars(select(User))}
    unbekannt = [str(k) for k in anfrage.zuordnungen.values() if k is not None and k not in konten]
    if unbekannt:
        raise NichtGefunden(
            "Zu den Nummern " + ", ".join(unbekannt) + " gibt es kein Nutzerkonto.",
            "Bitte die Seite neu laden – vermutlich wurde ein Konto zwischenzeitlich deaktiviert.",
        )

    geaendert = 0
    protokoll: dict[str, object] = {}
    for name, user_id in anfrage.zuordnungen.items():
        projekte = list(db.scalars(select(Projekt).where(Projekt.pl_name == name)))
        if not projekte:
            continue
        betroffen = [p for p in projekte if p.pl_user_id != user_id]
        for projekt in betroffen:
            projekt.pl_user_id = user_id
        if betroffen:
            geaendert += len(betroffen)
            protokoll[name] = {
                "konto": konten[user_id].email if user_id is not None else None,
                "projekte": len(betroffen),
            }

    if protokoll:
        audit.eintragen(
            db,
            "projektleiter.zugeordnet",
            nutzer=zugriff.nutzer,
            ip=zugriff.ip,
            tabelle="projekte",
            neu=protokoll,
        )
    db.commit()
    log.info("Projektleiter zugeordnet: %d Projekte", geaendert)
    return ProjektleiterErgebnis(
        geaendert=geaendert,
        meldung=(
            f"{geaendert} Projekte wurden zugeordnet. Der Sichtbarkeits-Scope „eigene“ wirkt "
            "ab sofort."
            if geaendert
            else "Es gab nichts zu ändern."
        ),
    )
