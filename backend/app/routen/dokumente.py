"""Projektordner und ihre Unterlagen (PLAN §7 Phase 7).

Gescannt wird in ``app/dienste/dokumente.py`` – hier steht nur, wer fragen darf.

Die Rechte folgen PLAN §4: der Befund über einen Projektordner ist **Projektsicht, kein
Betrag**. Wer Projekte sehen darf, darf auch sehen, welche Unterlagen dazu abgelegt sind; das
Team baut die Anlagen und legt die Protokolle ab. Ein Scan von Hand ist dagegen ein Lauf über
das Dateisystem und braucht ``importe.ausfuehren`` wie die übrigen Läufe.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app import audit
from app.dienste.dokumente import TYP_TEXT
from app.konfiguration import Einstellungen
from app.modelle import Dokument, Projekt, Projektordner
from app.sicherheit.abhaengigkeiten import (
    Zugriff,
    benoetigt,
    db_sitzung,
    konfiguration,
    scope_filter,
)

router = APIRouter(prefix="/api", tags=["Unterlagen"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung projekte.lesen fehlt"},
}
SCANNEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung importe.ausfuehren fehlt"},
    409: {"description": "Kein Projektordner konfiguriert oder nicht erreichbar"},
}


class UnterlageAntwort(BaseModel):
    typ: str
    # Deutsche Bezeichnung – der Schlüssel gehört nicht auf den Bildschirm.
    bezeichnung: str
    vorhanden: bool
    pflicht: bool
    pfad: str | None = None


class OrdnerAntwort(BaseModel):
    projekt_id: int
    projekt_nr: int
    projekt_bezeichnung: str | None = None
    status: str
    gefunden: bool
    pfad: str | None = None
    dateien: int
    mehrdeutig_mit: str | None = None
    geprueft_am: date | None = None
    unterlagen: list[UnterlageAntwort] = Field(default_factory=list)
    fehlende_pflicht: list[str] = Field(default_factory=list)


class UebersichtAntwort(BaseModel):
    gesamt: int
    ohne_ordner: int
    unvollstaendig: int
    mehrdeutig: int
    nie_geprueft: int
    ordner: list[OrdnerAntwort] = Field(default_factory=list)
    einordnung: str


class ScanAntwort(BaseModel):
    projekte: int
    mit_ordner: int
    ohne_ordner: int
    mehrdeutig: int
    unvollstaendig: int
    verwaist: list[str] = Field(default_factory=list)
    meldung: str


EINORDNUNG = (
    "Der Scan sieht nur Dateinamen. Was auf Papier vorliegt oder unter einem anderen Namen "
    "abgelegt ist, fehlt hier – deshalb ist die Liste ein Hinweis und keine Sperre."
)


def _sichtbar(abfrage: Select, zugriff: Zugriff) -> Select:
    return scope_filter(abfrage, zugriff, "projekte.lesen", Projekt.pl_user_id)


@router.get(
    "/unterlagen",
    response_model=UebersichtAntwort,
    summary="Projektordner und ihre Unterlagen",
    operation_id="unterlagenUebersicht",
    responses=LESEN,
)
def uebersicht(
    nur_unvollstaendig: bool = Query(
        default=False, description="Nur Projekte mit fehlender Pflichtunterlage"
    ),
    status: str | None = Query(default=None, description="Auf einen Projektstatus einschränken"),
    zugriff: Zugriff = Depends(benoetigt("projekte.lesen")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> UebersichtAntwort:
    pflicht = list(werte.dokumente.pflicht)
    abfrage = _sichtbar(select(Projekt), zugriff).order_by(Projekt.projekt_nr.desc())
    if status:
        abfrage = abfrage.where(Projekt.status == status)
    projekte = list(db.execute(abfrage).scalars())

    ordner = {
        eintrag.projekt_id: eintrag for eintrag in db.execute(select(Projektordner)).scalars()
    }
    unterlagen: dict[int, list[Dokument]] = {}
    for zeile in db.execute(select(Dokument)).scalars():
        unterlagen.setdefault(zeile.projekt_id, []).append(zeile)

    zeilen: list[OrdnerAntwort] = []
    for projekt in projekte:
        eintrag = ordner.get(projekt.id)
        eigene = sorted(unterlagen.get(projekt.id, []), key=lambda d: d.typ)
        vorhanden = {d.typ for d in eigene if d.vorhanden}
        # Nie geprüft: dann fehlt nichts, es ist nur nichts bekannt.
        fehlend = (
            [typ for typ in pflicht if typ not in vorhanden]
            if eintrag is not None and eintrag.geprueft_am is not None
            else []
        )
        zeile = OrdnerAntwort(
            projekt_id=projekt.id,
            projekt_nr=projekt.projekt_nr,
            projekt_bezeichnung=projekt.bezeichnung,
            status=projekt.status,
            gefunden=bool(eintrag and eintrag.gefunden),
            pfad=eintrag.pfad if eintrag else None,
            dateien=eintrag.dateien if eintrag else 0,
            mehrdeutig_mit=eintrag.mehrdeutig_mit if eintrag else None,
            geprueft_am=eintrag.geprueft_am if eintrag else None,
            unterlagen=[
                UnterlageAntwort(
                    typ=d.typ,
                    bezeichnung=TYP_TEXT.get(d.typ, d.typ),
                    vorhanden=d.vorhanden,
                    pflicht=d.typ in pflicht,
                    pfad=d.pfad or None,
                )
                for d in eigene
            ],
            fehlende_pflicht=fehlend,
        )
        if nur_unvollstaendig and not fehlend:
            continue
        zeilen.append(zeile)

    return UebersichtAntwort(
        gesamt=len(projekte),
        ohne_ordner=sum(1 for p in projekte if not (ordner.get(p.id) and ordner[p.id].gefunden)),
        unvollstaendig=sum(1 for z in zeilen if z.gefunden and z.fehlende_pflicht),
        mehrdeutig=sum(1 for p in projekte if ordner.get(p.id) and ordner[p.id].mehrdeutig_mit),
        nie_geprueft=sum(
            1 for p in projekte if not (ordner.get(p.id) and ordner[p.id].geprueft_am)
        ),
        ordner=zeilen,
        einordnung=EINORDNUNG,
    )


@router.post(
    "/unterlagen/scannen",
    response_model=ScanAntwort,
    summary="Projektordner jetzt prüfen",
    operation_id="unterlagenScannen",
    responses=SCANNEN,
)
def scannen(
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> ScanAntwort:
    """Den Scan von Hand anstoßen – sonst läuft er nachts.

    Der Lauf ändert nichts an den Ordnern; er stellt nur fest, was darin liegt.
    """
    from pathlib import Path

    from app.dienste.dokumente import OrdnerNichtLesbar
    from app.dienste.dokumente import scannen as scan_ausfuehren
    from app.fehler import Konflikt

    if werte.pfade.projekte is None:
        raise Konflikt(
            "Es ist kein Projektordner eingerichtet.",
            "In der config.toml unter [pfade] 'projekte' auf die Wurzel der Projektordner "
            "setzen – ein Ordner je Projekt mit der Nummer im Namen.",
            code="projektordner_fehlt",
        )
    wurzel = Path(werte.pfade.projekte)
    if not wurzel.is_dir():
        raise Konflikt(
            f"Der Projektordner ist nicht erreichbar: {wurzel}",
            "Prüfen, ob OneDrive den Ordner synchronisiert hat und ob der Pfad in der "
            "config.toml stimmt.",
            code="projektordner_unerreichbar",
        )

    try:
        ergebnis = scan_ausfuehren(db, wurzel, werte.dokumente)
    except OrdnerNichtLesbar as fehler:
        raise Konflikt(
            f"Der Projektordner ist nicht lesbar: {fehler.pfad}",
            "Prüfen, ob das Dienstkonto darauf zugreifen darf.",
            code="projektordner_unlesbar",
        ) from fehler

    audit.eintragen(
        db,
        "unterlagen.gescannt",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        neu={"projekte": ergebnis.projekte, "mit_ordner": ergebnis.mit_ordner},
    )
    db.commit()

    from app.formate import mehrzahl

    meldung = (
        f"{mehrzahl(ergebnis.mit_ordner, 'Projektordner', 'Projektordner')} gelesen, "
        f"{mehrzahl(ergebnis.unvollstaendig, 'Ordner', 'Ordner')} ohne vollständige Pflichtdoku."
    )
    return ScanAntwort(
        projekte=ergebnis.projekte,
        mit_ordner=ergebnis.mit_ordner,
        ohne_ordner=ergebnis.ohne_ordner,
        mehrdeutig=ergebnis.mehrdeutig,
        unvollstaendig=ergebnis.unvollstaendig,
        verwaist=ergebnis.verwaist,
        meldung=meldung,
    )
