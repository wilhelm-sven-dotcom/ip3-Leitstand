"""Offene Posten der Debitoren einlesen (PLAN §8, §6.7, §6.13).

Die dritte Kanzlei-Lieferung und die einzige Quelle für die Frage, ob eine Rechnung bezahlt ist.
PLAN §6.7 ist dabei streng: **gestellt ist nicht bezahlt.** Der Umsatz-Ist kommt aus den
festgeschriebenen Rechnungen, der Zahlungsstatus ausschließlich von hier. Der Leitstand leitet
ihn nie aus dem eigenen Belegbestand ab – er weiß nichts über Kontoauszüge.

Anders als Kostenträger und SuSa ist eine OPOS-Liste **kein Zeitraum, sondern ein Stichtag**:
sie zeigt, was an einem Tag offen war. Deshalb ersetzt ein Lauf den Stichtag und nicht einen
Monat, und der Dateiname trägt ein volles Datum (``opos_2026-07-31.csv``).

Was die Liste *nicht* enthält, ist die Antwort auf „bezahlt": eine beglichene Rechnung steht
irgendwann gar nicht mehr drin. Die Auswertung in :mod:`app.dienste.zahlungsstatus` liest das
deshalb als Abwesenheit – siehe dort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.fehler import FachFehler
from app.geld import euro_nach_cent
from app.importe import csv_leser
from app.importe.befunde import Befund
from app.konfiguration import OposEinstellungen
from app.modelle import Opos

QUELLE = "opos"

PFLICHTSPALTEN: tuple[str, ...] = ("rechnung_nr", "offen_betrag")

# Dateiname nach PLAN §2: 'opos_2026-07-31.csv'. Voller Stichtag, nicht nur der Monat.
_DATEINAME_STICHTAG = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})")


class OposFehler(FachFehler):
    code = "opos_fehler"


class StichtagUnbekannt(OposFehler):
    code = "opos_stichtag_unbekannt"

    def __init__(self, pfad: Path) -> None:
        super().__init__(
            f"Aus dem Dateinamen '{pfad.name}' lässt sich kein Stichtag lesen.",
            "Die Datei nach dem Muster 'opos_JJJJ-MM-TT.csv' benennen (PLAN §2). Eine "
            "OPOS-Liste gilt für einen Tag, nicht für einen Monat – ohne den Tag lässt sich "
            "nicht sagen, welcher Stand ersetzt wird.",
        )


@dataclass
class Posten:
    zeile: int
    rechnung_nr: str
    kunde: str
    betrag_cent: int
    offen_cent: int
    faellig_am: date | None = None


@dataclass
class Oposdatei:
    pfad: Path
    stichtag: date
    posten: list[Posten] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)

    @property
    def offen_cent(self) -> int:
        return sum(p.offen_cent for p in self.posten)

    def ueberfaellig(self) -> list[Posten]:
        return [p for p in self.posten if p.faellig_am is not None and p.faellig_am < self.stichtag]

    def kontrollsummen(self) -> dict[str, object]:
        return {
            "datei": self.pfad.name,
            "stichtag": self.stichtag.isoformat(),
            "posten": len(self.posten),
            "offen_cent": self.offen_cent,
            "ueberfaellig": len(self.ueberfaellig()),
            "ueberfaellig_cent": sum(p.offen_cent for p in self.ueberfaellig()),
        }


def stichtag_aus_dateiname(pfad: Path) -> date | None:
    """``date(2026, 7, 31)`` aus ``opos_2026-07-31.csv``."""
    treffer = _DATEINAME_STICHTAG.search(pfad.stem)
    if treffer is None:
        return None
    jahr, monat, tag = (int(teil) for teil in treffer.groups())
    try:
        return date(jahr, monat, tag)
    except ValueError:
        return None


def opos_lesen(
    pfad: Path, einstellungen: OposEinstellungen, *, stichtag: date | None = None
) -> Oposdatei:
    """Liest eine OPOS-Liste. Schreibt nichts."""
    tag = stichtag or stichtag_aus_dateiname(pfad)
    if tag is None:
        raise StichtagUnbekannt(pfad)

    datei = csv_leser.lesen(pfad, einstellungen.spalten, pflicht=PFLICHTSPALTEN)
    ergebnis = Oposdatei(pfad=pfad, stichtag=tag)

    for zeile in datei.zeilen:
        posten = _zeile_deuten(zeile, ergebnis, jahr=tag.year)
        if posten is not None:
            ergebnis.posten.append(posten)
    return ergebnis


def _zeile_deuten(zeile: csv_leser.Zeile, ergebnis: Oposdatei, *, jahr: int) -> Posten | None:
    def befund(spalte: str, meldung: str) -> None:
        ergebnis.befunde.append(
            Befund(
                datei=ergebnis.pfad.name,
                zeile=zeile.nummer,
                spalte=spalte,
                wert=zeile.wert(spalte),
                meldung=meldung,
            )
        )

    rechnung_nr = zeile.wert("rechnung_nr").strip()
    if not rechnung_nr:
        # Summenzeilen je Debitor haben keine Belegnummer.
        return None

    offen = csv_leser.deutsche_zahl(zeile.wert("offen_betrag"))
    if offen is None:
        befund("offen_betrag", "Kein lesbarer offener Betrag – Zeile nicht übernommen")
        return None

    betrag = csv_leser.deutsche_zahl(zeile.wert("betrag"))
    if betrag is None:
        # Führt die Liste nur den Restbetrag, ist das kein Fehler: für den Zahlungsstatus zählt
        # ohnehin der Rest, und den Rechnungsbetrag kennt der Leitstand aus dem eigenen Beleg.
        betrag = offen

    return Posten(
        zeile=zeile.nummer,
        rechnung_nr=rechnung_nr,
        kunde=zeile.wert("kunde"),
        betrag_cent=euro_nach_cent(betrag),
        offen_cent=euro_nach_cent(offen),
        faellig_am=csv_leser.deutsches_datum(zeile.wert("faellig_am"), jahr=jahr),
    )


@dataclass
class Uebernahmeergebnis:
    stichtag: date
    importlauf_id: int | None = None
    geloescht: int = 0
    posten: int = 0
    offen_cent: int = 0
    unbekannte_rechnungen: list[str] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)


def uebernehmen(sitzung: Session, datei: Oposdatei) -> Uebernahmeergebnis:
    """Offene Posten schreiben. Muss in einer Schreibtransaktion laufen.

    Der Stichtag wird zuerst geleert und dann neu gefüllt – dieselbe Regel wie bei den anderen
    Importen, nur ist der Zeitraum hier ein einzelner Tag.
    """
    from sqlalchemy import select

    from app.importe import laeufe
    from app.modelle import Rechnung

    ergebnis = Uebernahmeergebnis(stichtag=datei.stichtag, befunde=list(datei.befunde))
    lauf = laeufe.lauf_beginnen(
        sitzung,
        quelle=QUELLE,
        datei=datei.pfad.name,
        zeitraum=f"{datei.stichtag:%Y-%m}",
    )
    ergebnis.geloescht = laeufe.opos_leeren(sitzung, stichtag=datei.stichtag)

    # Eine Rechnungsnummer kann in der Liste mehrfach stehen (Teilzahlungen als eigene Zeilen).
    # Die Tabelle führt sie je Stichtag einmal, also verdichten.
    zusammen: dict[str, Posten] = {}
    for posten in datei.posten:
        vorhanden = zusammen.get(posten.rechnung_nr)
        if vorhanden is None:
            zusammen[posten.rechnung_nr] = Posten(**vars(posten))
        else:
            vorhanden.offen_cent += posten.offen_cent
            vorhanden.betrag_cent += posten.betrag_cent

    for nummer, posten in sorted(zusammen.items()):
        sitzung.add(
            Opos(
                rechnung_nr=nummer,
                kunde=posten.kunde or None,
                betrag=posten.betrag_cent,
                faellig_am=posten.faellig_am,
                offen_betrag=posten.offen_cent,
                stand_datum=datei.stichtag,
                importlauf_id=lauf.id,
            )
        )
    sitzung.flush()

    bekannte = set(
        sitzung.scalars(
            select(Rechnung.rechnung_nr).where(Rechnung.rechnung_nr.in_(zusammen.keys()))
        ).all()
    )
    ergebnis.unbekannte_rechnungen = sorted(set(zusammen) - bekannte)

    ergebnis.posten = len(zusammen)
    ergebnis.offen_cent = sum(p.offen_cent for p in zusammen.values())

    laeufe.lauf_abschliessen(
        sitzung,
        lauf,
        befunde=ergebnis.befunde,
        kontrollsummen=datei.kontrollsummen(),
        # Belegnummern ohne Rechnung im Leitstand sind der Regelfall, solange der Altbestand
        # nicht eingelesen ist (PLAN §8, AR-Altbestand) – deshalb keine Warnung, nur ein
        # Protokolleintrag.
        weiteres={
            "geschrieben": {
                "posten": ergebnis.posten,
                "offen_cent": ergebnis.offen_cent,
                "ersetzte_zeilen": ergebnis.geloescht,
            },
            "unbekannte_rechnungen": ergebnis.unbekannte_rechnungen,
        },
    )
    ergebnis.importlauf_id = lauf.id
    return ergebnis
