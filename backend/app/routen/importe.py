"""Vorschau und Übernahme der wiederkehrenden Importe (PLAN §8).

Drei Quellen, ein Ablauf: **Vorschau ansehen, dann übernehmen.** Die Vorschau liest die Dateien
und schreibt nichts; sie liefert Kontrollsummen, die Befunde und eine Kennung über den Inhalt.
Die Übernahme schickt diese Kennung zurück. Stimmt sie nicht mehr, hat sich die Datei
zwischenzeitlich geändert, und der Lauf wird mit einer Meldung abgewiesen statt etwas anderes zu
schreiben als das, was auf dem Schirm stand. Dasselbe Verfahren wie bei der Migration
(``app/routen/migration.py``), aus demselben Grund.

Die Vorschau wird **nicht zwischengespeichert**, sondern neu gerechnet. Ein Zwischenspeicher wäre
ein zweiter Zustand, der veralten kann; die Dateien sind klein genug, um sie zweimal zu lesen.

Berechtigung durchgängig ``importe.ausfuehren`` – dieselbe wie bei der Migration; die Rollen
``admin`` und ``buchhaltung`` haben sie (PLAN §4).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.datenbank import schreib_transaktion
from app.fehler import Konflikt
from app.importe import datev as datev_import
from app.importe import kalkulationsblatt as kalkulation_import
from app.importe import timetac as timetac_import
from app.importe.befunde import Befund, als_liste
from app.konfiguration import Einstellungen
from app.modelle import Importlauf
from app.protokoll import logger
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, konfiguration

log = logger(__name__)

router = APIRouter(prefix="/api/importe", tags=["Importe"])

RECHTE = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung importe.ausfuehren fehlt"},
}
UEBERNEHMEN = {
    **RECHTE,
    409: {"description": "Datei zwischenzeitlich geändert oder Ordner nicht eingerichtet"},
}

Quelle = Literal["datev", "kalkulation"]


class BefundAntwort(BaseModel):
    datei: str
    zeile: int
    spalte: str
    wert: str
    meldung: str
    schwere: str


class VorschauAntwort(BaseModel):
    quelle: str
    kennung: str
    dateien: list[str]
    zeitraum: str | None
    kontrollsummen: dict
    befunde: list[BefundAntwort]
    hinweise: list[str]


class UebernahmeAnfrage(BaseModel):
    kennung: str


class UebernahmeAntwort(BaseModel):
    quelle: str
    importlauf_id: int | None
    zeitraum: str | None
    meldung: str
    ergebnis: dict


class LaufAntwort(BaseModel):
    id: int
    quelle: str
    datei: str | None
    zeitraum: str | None
    gestartet: str
    beendet: str | None
    status: str
    ergebnis: dict | None


def _befunde(befunde: list[Befund]) -> list[BefundAntwort]:
    return [BefundAntwort(**eintrag) for eintrag in als_liste(befunde)]


def _kennung(teile: list[str]) -> str:
    """Kurze Kennung über den Inhalt.

    Bewusst über die gelesenen Werte und nicht über die Datei als Ganzes: ein erneutes Speichern
    ohne inhaltliche Änderung darf die Kennung nicht ändern, eine geänderte Zeile schon.
    """
    return hashlib.sha256("\n".join(teile).encode("utf-8")).hexdigest()[:16]


def _ordner(pfad: Path | None, name: str, eintrag: str) -> Path:
    if pfad is None:
        raise Konflikt(
            f"Es ist kein Ordner für {name} eingerichtet.",
            f"In der config.toml unter [pfade] den Eintrag {eintrag} auf den OneDrive-Ordner "
            "setzen und den Leitstand neu starten.",
            code=f"{eintrag}_pfad_fehlt",
        )
    return pfad


# ---------------------------------------------------------------------------
# DATEV-Kostenträger
# ---------------------------------------------------------------------------


def _datev_datei(werte: Einstellungen, monat: str | None) -> Path:
    ordner = _ordner(werte.pfade.datev, "die DATEV-Exporte", "datev")
    if not ordner.is_dir():
        raise Konflikt(
            f"Der DATEV-Ordner ist nicht erreichbar: {ordner}",
            "Prüfen, ob OneDrive den Ordner synchronisiert hat und ob der Pfad in der "
            "config.toml stimmt.",
            code="datev_pfad_fehlt",
        )
    dateien = sorted(
        (p for p in ordner.glob("kostentraeger*.csv") if datev_import.monat_aus_dateiname(p)),
        key=lambda p: datev_import.monat_aus_dateiname(p) or "",
    )
    if monat:
        dateien = [p for p in dateien if datev_import.monat_aus_dateiname(p) == monat]
    if not dateien:
        raise Konflikt(
            f"Im Ordner {ordner.name} liegt keine Kostenträgerdatei"
            + (f" für {monat}." if monat else "."),
            "Die Kanzlei liefert sie monatlich als 'kostentraeger_JJJJ-MM.csv' (PLAN §8). "
            "Prüfen, ob die Datei angekommen und richtig benannt ist.",
            code="datev_datei_fehlt",
        )
    # Der jüngste Monat zuerst: den will man nach dem Monatsabschluss einlesen.
    return dateien[-1]


def _datev_lesen(werte: Einstellungen, monat: str | None) -> datev_import.Kostentraegerdatei:
    pfad = _datev_datei(werte, monat)
    return datev_import.kostentraeger_lesen(pfad, werte.datev.kostentraeger)


@router.get(
    "/datev/vorschau",
    response_model=VorschauAntwort,
    summary="DATEV-Kostenträger ansehen, ohne zu schreiben",
    operation_id="importDatevVorschau",
    responses={**RECHTE, 409: {"description": "Ordner oder Datei fehlt"}},
)
def datev_vorschau(
    monat: str | None = Query(None, description="Monat 'JJJJ-MM'; ohne Angabe der jüngste"),
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    werte: Einstellungen = Depends(konfiguration),
) -> VorschauAntwort:
    datei = _datev_lesen(werte, monat)
    hinweise = []
    if datei.nicht_uebernommen:
        hinweise.append(
            f"{len(datei.nicht_uebernommen)} Zeilen bleiben draußen – Erlöskonten und Buchungen "
            "ohne Kostenträger. Die Kontenbereiche stehen in der config.toml unter "
            "[datev.kostentraeger]."
        )
    return VorschauAntwort(
        quelle="datev",
        kennung=_kennung(
            [f"{b.zeile}|{b.projekt_nr}|{b.konto}|{b.betrag_cent}" for b in datei.buchungen]
        ),
        dateien=[datei.pfad.name],
        zeitraum=datei.monat,
        kontrollsummen=datei.kontrollsummen(),
        befunde=_befunde(datei.befunde),
        hinweise=hinweise,
    )


@router.post(
    "/datev/uebernehmen",
    response_model=UebernahmeAntwort,
    summary="DATEV-Kostenträger übernehmen (ersetzt den Monat)",
    operation_id="importDatevUebernehmen",
    responses=UEBERNEHMEN,
)
def datev_uebernehmen(
    eingabe: UebernahmeAnfrage,
    monat: str | None = Query(None),
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> UebernahmeAntwort:
    datei = _datev_lesen(werte, monat)
    kennung = _kennung(
        [f"{b.zeile}|{b.projekt_nr}|{b.konto}|{b.betrag_cent}" for b in datei.buchungen]
    )
    _kennung_pruefen(eingabe.kennung, kennung, datei.pfad.name)

    audit.eintragen(
        db,
        "import.datev",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        neu={"datei": datei.pfad.name, "monat": datei.monat, "buchungen": len(datei.buchungen)},
    )
    with schreib_transaktion(db):
        ergebnis = datev_import.uebernehmen(db, datei)

    log.info(
        "DATEV-Import: %s, Monat %s, %d Zeilen, %d Cent",
        datei.pfad.name,
        datei.monat,
        ergebnis.zeilen,
        ergebnis.summe_cent,
    )
    return UebernahmeAntwort(
        quelle="datev",
        importlauf_id=ergebnis.importlauf_id,
        zeitraum=ergebnis.monat,
        meldung=(
            f"{ergebnis.zeilen} Kostenzeilen für {ergebnis.projekte} Projekte übernommen "
            f"({ergebnis.monat}). {ergebnis.geloescht} Zeilen des Monats wurden ersetzt."
        ),
        ergebnis={
            "zeilen": ergebnis.zeilen,
            "projekte": ergebnis.projekte,
            "summe_cent": ergebnis.summe_cent,
            "ersetzt": ergebnis.geloescht,
            "unbekannte_projekte": ergebnis.unbekannte_projekte,
            "befunde": als_liste(ergebnis.befunde),
        },
    )


# ---------------------------------------------------------------------------
# Kalkulationsblätter
# ---------------------------------------------------------------------------


def _kalkulation_lesen(
    werte: Einstellungen,
) -> tuple[list[kalkulation_import.Kalkulationsblatt], list[Befund]]:
    ordner = _ordner(werte.pfade.kalkulation, "die Kalkulationsblätter", "kalkulation")
    dateien, befunde = kalkulation_import.ordner_scannen(ordner)
    blaetter: list[kalkulation_import.Kalkulationsblatt] = []
    for eintrag in dateien:
        try:
            blaetter.append(kalkulation_import.blatt_lesen(eintrag.pfad))
        except kalkulation_import.KalkulationsblattFehler as fehler:
            # Eine kaputte Datei darf den Lauf über die anderen nicht verhindern.
            befunde.append(
                Befund(
                    datei=eintrag.pfad.name,
                    zeile=0,
                    spalte="datei",
                    wert=str(eintrag.projekt_nr),
                    meldung=f"{fehler.meldung} {fehler.naechster_schritt}",
                )
            )
    return blaetter, befunde


def _kalkulation_kennung(blaetter: list[kalkulation_import.Kalkulationsblatt]) -> str:
    return _kennung(
        [
            f"{b.datei.name}|{b.projekt_nr}|{b.material_soll_cent}|{b.dl_soll_cent}|"
            f"{b.marge_soll_promille}|{len(b.positionen)}"
            for b in blaetter
        ]
    )


@router.get(
    "/kalkulation/vorschau",
    response_model=VorschauAntwort,
    summary="Kalkulationsblätter ansehen, ohne zu schreiben",
    operation_id="importKalkulationVorschau",
    responses={**RECHTE, 409: {"description": "Ordner fehlt"}},
)
def kalkulation_vorschau(
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    werte: Einstellungen = Depends(konfiguration),
) -> VorschauAntwort:
    blaetter, befunde = _kalkulation_lesen(werte)
    alle_befunde = befunde + [b for blatt in blaetter for b in blatt.befunde]
    return VorschauAntwort(
        quelle="kalkulation",
        kennung=_kalkulation_kennung(blaetter),
        dateien=[b.datei.name for b in blaetter],
        zeitraum=None,
        kontrollsummen={
            "blaetter": len(blaetter),
            "projekte": len({b.projekt_nr for b in blaetter if b.projekt_nr}),
            "positionen": sum(len(b.positionen) for b in blaetter),
            "lagerpositionen": sum(len(b.lagerpositionen) for b in blaetter),
            "soll_gesamt_cent": sum(b.soll_gesamt_cent or 0 for b in blaetter),
        },
        befunde=_befunde(alle_befunde),
        hinweise=[],
    )


@router.post(
    "/kalkulation/uebernehmen",
    response_model=UebernahmeAntwort,
    summary="Sollwerte aus den Kalkulationsblättern übernehmen",
    operation_id="importKalkulationUebernehmen",
    responses=UEBERNEHMEN,
)
def kalkulation_uebernehmen(
    eingabe: UebernahmeAnfrage,
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> UebernahmeAntwort:
    blaetter, befunde = _kalkulation_lesen(werte)
    _kennung_pruefen(eingabe.kennung, _kalkulation_kennung(blaetter), "die Kalkulationsblätter")

    audit.eintragen(
        db,
        "import.kalkulation",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        neu={"blaetter": len(blaetter)},
    )
    from app.importe import laeufe

    with schreib_transaktion(db):
        lauf = laeufe.lauf_beginnen(
            db,
            quelle="kalkulation",
            datei=", ".join(b.datei.name for b in blaetter) or "keine Datei",
        )
        uebernommen = 0
        positionen = 0
        alle_befunde = list(befunde)
        for blatt in blaetter:
            ergebnis = kalkulation_import.uebernehmen(db, blatt)
            uebernommen += 1 if ergebnis.soll_geschrieben else 0
            positionen += ergebnis.positionen_neu + ergebnis.positionen_geaendert
            alle_befunde.extend(ergebnis.befunde)
        laeufe.lauf_abschliessen(
            db,
            lauf,
            befunde=alle_befunde,
            kontrollsummen={"blaetter": len(blaetter), "uebernommen": uebernommen},
            unvollstaendig=uebernommen < len(blaetter),
            weiteres={"positionen": positionen},
        )
        lauf_id = lauf.id

    log.info("Kalkulationsblätter: %d von %d übernommen", uebernommen, len(blaetter))
    return UebernahmeAntwort(
        quelle="kalkulation",
        importlauf_id=lauf_id,
        zeitraum=None,
        meldung=(
            f"{uebernommen} von {len(blaetter)} Kalkulationsblättern übernommen, "
            f"{positionen} Stücklistenpositionen."
        ),
        ergebnis={
            "blaetter": len(blaetter),
            "uebernommen": uebernommen,
            "positionen": positionen,
            "befunde": als_liste(alle_befunde),
        },
    )


# ---------------------------------------------------------------------------
# TimeTac
# ---------------------------------------------------------------------------


@router.post(
    "/timetac/holen",
    response_model=UebernahmeAntwort,
    summary="Stunden aus TimeTac holen und übernehmen",
    operation_id="importTimetacHolen",
    responses={**RECHTE, 409: {"description": "TimeTac nicht erreichbar oder nicht eingerichtet"}},
)
def timetac_holen(
    monat: str | None = Query(None, description="Monat 'JJJJ-MM'; ohne Angabe die letzten zwei"),
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
    werte: Einstellungen = Depends(konfiguration),
) -> UebernahmeAntwort:
    """Ohne Vorschau: die Schnittstelle liefert keine Datei, die man vorher ansehen könnte.

    Der Lauf ist gefahrlos wiederholbar – er ersetzt seinen Zeitraum (PLAN §8). Ein Netzfehler
    schreibt nichts und lässt die vorhandenen Stunden stehen.
    """
    from app.importe.timetac_api import TimeTacClient, abholen, monate_bestimmen

    client = TimeTacClient(
        werte.timetac,
        client_id=werte.timetac_client_id,
        client_secret=werte.timetac_client_secret,
        konto=werte.timetac_konto,
    )
    monate = [monat] if monat else monate_bestimmen(werte.timetac)
    lieferung = abholen(client, monate)

    audit.eintragen(
        db,
        "import.timetac",
        nutzer=zugriff.nutzer,
        ip=zugriff.ip,
        neu={"monate": monate, "buchungen": len(lieferung.buchungen)},
    )
    with schreib_transaktion(db):
        ergebnis = timetac_import.uebernehmen(db, lieferung, werte.stundensaetze)

    log.info(
        "TimeTac-Import: %s, %d Stundenzeilen, %d Cent",
        ", ".join(monate),
        ergebnis.stundenzeilen,
        ergebnis.summe_cent,
    )
    return UebernahmeAntwort(
        quelle="timetac",
        importlauf_id=ergebnis.importlauf_id,
        zeitraum=", ".join(ergebnis.monate),
        meldung=(
            f"{ergebnis.stundenzeilen} Stundenzeilen für {ergebnis.kostenzeilen} Projekte "
            f"übernommen ({ergebnis.summe_stunden} Stunden)."
        ),
        ergebnis={
            "stundenzeilen": ergebnis.stundenzeilen,
            "kostenzeilen": ergebnis.kostenzeilen,
            "stunden": str(ergebnis.summe_stunden),
            "summe_cent": ergebnis.summe_cent,
            "ohne_satzgruppe": ergebnis.ohne_satz,
            "befunde": als_liste(ergebnis.befunde),
        },
    )


# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------


@router.get(
    "/laeufe",
    response_model=list[LaufAntwort],
    summary="Importprotokolle",
    operation_id="importLaeufe",
    responses=RECHTE,
)
def laeufe_lesen(
    quelle: str | None = None,
    anzahl: int = Query(20, ge=1, le=200),
    zugriff: Zugriff = Depends(benoetigt("importe.ausfuehren")),
    db: Session = Depends(db_sitzung),
) -> list[LaufAntwort]:
    abfrage = select(Importlauf).order_by(Importlauf.id.desc()).limit(anzahl)
    if quelle:
        abfrage = abfrage.where(Importlauf.quelle == quelle)
    return [
        LaufAntwort(
            id=lauf.id,
            quelle=lauf.quelle,
            datei=lauf.datei,
            zeitraum=lauf.zeitraum,
            gestartet=lauf.gestartet.isoformat(),
            beendet=lauf.beendet.isoformat() if lauf.beendet else None,
            status=lauf.status,
            ergebnis=lauf.ergebnis,
        )
        for lauf in db.scalars(abfrage)
    ]


def _kennung_pruefen(gesendet: str, erwartet: str, was: str) -> None:
    if gesendet != erwartet:
        raise Konflikt(
            f"{was} hat sich geändert, seit die Vorschau erstellt wurde.",
            "Die Vorschau neu laden und das Ergebnis noch einmal ansehen, bevor übernommen "
            "wird – sonst wird etwas anderes geschrieben als das, was auf dem Schirm stand.",
            code="import_datei_geaendert",
        )
