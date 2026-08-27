"""Einmalige Übernahme der Bestandsdaten (PLAN §7, Phase 1; PLAN §9).

Drei Schritte, die auch in der Oberfläche drei Schritte bleiben:

1. ``GET /api/migration/stand`` – ist schon migriert worden?
2. ``GET /api/migration/vorschau`` – was steht in den Dateien, was ist zugeordnet, was offen?
3. ``POST /api/migration/uebernehmen`` – die Entscheidungen anwenden und schreiben.

Die Vorschau wird nicht zwischengespeichert: sie entsteht bei jedem Aufruf neu aus den Dateien.
Damit kann sie aber veralten, und die Entscheidungen der Maske verweisen auf **Zeilennummern**
der Teamliste. Ändert jemand die Datei zwischen Vorschau und Übernahme, würden Beträge am
falschen Projekt landen – bei der größten Position wären das 550.000 €. Deshalb trägt die
Vorschau eine Kennung über den Inhalt beider Dateien, und die Übernahme verlangt sie zurück.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.fehler import Konflikt, NichtGefunden
from app.konfiguration import Einstellungen
from app.migration.uebernahme import (
    QUELLE,
    Analyse,
    analysieren,
    uebernehmen,
)
from app.migration.zuordnung import bestaetigen
from app.modelle import Importlauf
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, konfiguration

log = logger(__name__)

router = APIRouter(prefix="/api/migration", tags=["Migration"])

# Alle Routen hier verlangen dieselbe Berechtigung. Die Antworten stehen in der Spezifikation,
# damit der TypeScript-Client die Fehlerfälle typisiert kennt.
RECHTE_ANTWORTEN: dict[int | str, dict[str, str]] = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung importe.ausfuehren fehlt"},
}


class Vorschlag(BaseModel):
    projekt_zeile: int
    kunde: str
    guete: float


class ZuordnungAntwort(BaseModel):
    """Ein Kunde der Auftragsliste mit dem Projekt, zu dem seine Zeilen gehören."""

    kundenteil: str
    zeilen: list[int]
    betrag_netto: int
    art: str
    offen: bool
    projekt_zeile: int | None = None
    vorschlaege: list[Vorschlag] = Field(default_factory=list)


class BefundAntwort(BaseModel):
    datei: str
    zeile: int
    spalte: str
    wert: str
    meldung: str
    schwere: str


class ProjektKandidat(BaseModel):
    """Ein Projekt der Teamliste, wie es in der Maske zur Auswahl steht."""

    zeile: int
    kunde: str
    ort: str | None = None
    auftrag_vom: str | None = None
    ab_wert_netto: int | None = None
    pv_kwp: str | None = None
    pl_name: str | None = None


class VorschauAntwort(BaseModel):
    kennung: str
    kontrollsummen: dict
    zuordnungen: list[ZuordnungAntwort]
    kandidaten: list[ProjektKandidat]
    befunde: list[BefundAntwort]


class StandAntwort(BaseModel):
    """Ob und wann übernommen wurde."""

    migriert: bool
    importlauf_id: int | None = None
    status: str | None = None
    gestartet: datetime | None = None
    beendet: datetime | None = None
    dateien: str | None = None
    ergebnis: dict | None = None


class UebernahmeAnfrage(BaseModel):
    kennung: str
    # Kundenteil auf Zeilennummer der Teamliste; ``None`` heißt „als eigenes Projekt anlegen".
    entscheidungen: dict[str, int | None] = Field(default_factory=dict)
    offene_zulassen: bool = False


class UebernahmeAntwort(BaseModel):
    importlauf_id: int | None
    kunden: int
    projekte: int
    zahlungsplan: int
    zahlungsplan_gestellt: int
    zahlungsplan_summe_netto: int
    meilensteine: int
    projekte_ohne_auftragsjahr: int
    ab_luecken: list[dict]
    gewerk_abgeleitet: list[dict]
    nicht_uebernommen: list[dict]
    meldung: str


def kennung_bilden(analyse: Analyse) -> str:
    """Kurze Kennung über den Inhalt beider Dateien.

    Bewusst über Zeilennummern und Kundennamen, nicht über die Datei als Ganzes: eine
    Formatänderung in Excel darf die Kennung nicht ändern, eine verschobene Zeile schon – nur
    daran hängen die Entscheidungen der Maske.
    """
    teile = [f"{z.zeile}|{z.kundenteil}|{z.betrag_cent}" for z in analyse.auftraege.zeilen] + [
        f"{z.zeile}|{z.kundenteil}" for z in analyse.projekte.zeilen
    ]
    roh = "\n".join(teile).encode("utf-8")
    return hashlib.sha256(roh).hexdigest()[:16]


def _quellordner(werte: Einstellungen) -> Path:
    if werte.pfade.migration is None:
        raise Konflikt(
            "Es ist kein Ordner für die Bestandsdateien eingerichtet.",
            "In der config.toml unter [pfade] den Eintrag migration auf den Ordner mit "
            "'Offene_Auftraege' und 'Teambesprechung' setzen und den Leitstand neu starten.",
            code="migration_pfad_fehlt",
        )
    return werte.pfade.migration


def _stand_lesen(db: Session) -> Importlauf | None:
    return db.scalar(
        select(Importlauf)
        .where(Importlauf.quelle == QUELLE, Importlauf.status.in_(("erfolg", "warnung")))
        .order_by(Importlauf.id)
        .limit(1)
    )


@router.get(
    "/stand",
    response_model=StandAntwort,
    summary="Ob die Bestandsdaten schon übernommen wurden",
    operation_id="migrationStand",
    responses=RECHTE_ANTWORTEN,
)
def stand(
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
) -> StandAntwort:
    lauf = _stand_lesen(db)
    if lauf is None:
        return StandAntwort(migriert=False)
    return StandAntwort(
        migriert=True,
        importlauf_id=lauf.id,
        status=lauf.status,
        gestartet=lauf.gestartet,
        beendet=lauf.beendet,
        dateien=lauf.datei,
        ergebnis=lauf.ergebnis,
    )


@router.get(
    "/vorschau",
    response_model=VorschauAntwort,
    summary="Bestandsdateien lesen und Zuordnung vorschlagen",
    operation_id="migrationVorschau",
    responses={
        **RECHTE_ANTWORTEN,
        409: {"description": "Kein Migrationsordner eingerichtet oder Blatt fehlt"},
    },
)
def vorschau(
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    werte: Einstellungen = Depends(konfiguration),
) -> VorschauAntwort:
    """Liest beide Dateien und schlägt die Zuordnung vor. Schreibt nichts."""
    analyse = analysieren(_quellordner(werte))
    return VorschauAntwort(
        kennung=kennung_bilden(analyse),
        kontrollsummen=analyse.kontrollsummen(),
        zuordnungen=[
            ZuordnungAntwort(
                kundenteil=z.kundenteil,
                zeilen=z.auftrags_zeilen,
                betrag_netto=z.betrag_cent,
                art=z.art.value,
                offen=z.offen,
                projekt_zeile=z.projekt_zeile,
                vorschlaege=[
                    Vorschlag(projekt_zeile=v.projekt_zeile, kunde=v.kunde, guete=v.guete)
                    for v in z.vorschlaege
                ],
            )
            for z in analyse.vorschau.zuordnungen
        ],
        kandidaten=[
            ProjektKandidat(
                zeile=p.zeile,
                kunde=p.kundenteil,
                ort=p.ort,
                auftrag_vom=p.auftrag_vom.isoformat() if p.auftrag_vom else None,
                ab_wert_netto=p.ab_wert_cent,
                pv_kwp=str(p.pv_kwp) if p.pv_kwp is not None else None,
                pl_name=p.pl_name,
            )
            for p in analyse.projekte.zeilen
        ],
        befunde=[
            BefundAntwort(
                datei=b.datei,
                zeile=b.zeile,
                spalte=b.spalte,
                wert=b.wert,
                meldung=b.meldung,
                schwere=b.schwere,
            )
            for b in analyse.befunde
        ],
    )


@router.post(
    "/uebernehmen",
    response_model=UebernahmeAntwort,
    summary="Bestandsdaten übernehmen",
    operation_id="migrationUebernehmen",
    responses={
        **RECHTE_ANTWORTEN,
        409: {
            "description": "Schon übernommen, Dateien geändert oder Zuordnungen offen",
        },
    },
)
def uebernehmen_route(
    anfrage: UebernahmeAnfrage,
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> UebernahmeAntwort:
    """Wendet die Entscheidungen der Maske an und schreibt in einer Transaktion."""
    from app.modelle import Firma

    analyse = analysieren(_quellordner(werte))
    if kennung_bilden(analyse) != anfrage.kennung:
        raise Konflikt(
            "Die Bestandsdateien haben sich geändert, seit die Vorschau erstellt wurde.",
            "Bitte die Vorschau neu laden und die Zuordnungen erneut prüfen – sonst würden "
            "Beträge dem falschen Projekt zugeschrieben.",
            code="migration_dateien_geaendert",
        )

    bestaetigen(analyse.vorschau, anfrage.entscheidungen)

    firma_id = db.scalar(select(Firma.id).order_by(Firma.id).limit(1))
    if firma_id is None:  # pragma: no cover – der Seed legt die Firma immer an
        raise NichtGefunden(
            "In der Datenbank ist keine Firma angelegt.",
            "Der Leitstand ist nicht vollständig eingerichtet. Bitte Sven informieren.",
        )

    audit.eintragen(
        db,
        "migration.uebernommen",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        neu={
            "dateien": f"{analyse.auftraege.datei.name}, {analyse.projekte.datei.name}",
            "entscheidungen": len(anfrage.entscheidungen),
            "offene_zulassen": anfrage.offene_zulassen,
        },
    )
    bericht = uebernehmen(db, analyse, firma_id, offene_zulassen=anfrage.offene_zulassen)
    db.commit()
    log.info(
        "Bestandsdaten übernommen: %d Projekte, %d Zahlungsplanpositionen (Importlauf %s)",
        bericht.projekte,
        bericht.zahlungsplan,
        bericht.importlauf_id,
    )

    return UebernahmeAntwort(
        importlauf_id=bericht.importlauf_id,
        kunden=bericht.kunden,
        projekte=bericht.projekte,
        zahlungsplan=bericht.zahlungsplan,
        zahlungsplan_gestellt=bericht.zahlungsplan_gestellt,
        zahlungsplan_summe_netto=bericht.zahlungsplan_summe_cent,
        meilensteine=bericht.meilensteine,
        projekte_ohne_auftragsjahr=bericht.projekte_ohne_auftragsjahr,
        ab_luecken=bericht.ab_luecken,
        gewerk_abgeleitet=bericht.gewerk_abgeleitet,
        nicht_uebernommen=bericht.nicht_uebernommen,
        meldung=(
            f"{bericht.projekte} Projekte und {bericht.zahlungsplan} Zahlungsplanpositionen "
            "übernommen. Die Kontrollsummen stehen im Importprotokoll."
        ),
    )
