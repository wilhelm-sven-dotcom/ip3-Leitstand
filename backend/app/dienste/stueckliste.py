"""Stückliste bewerten und die Mengen-Ist-Bestätigung (PLAN §6.5, §7 Phase 4).

Die harte Regel gegen die Doppelbelastung steht in :func:`bewerten`: **nur Positionen mit
``quelle='lager'`` bekommen einen ``bewertet_betrag``.** Material, das auf das Projekt bestellt
wurde, kommt über die DATEV-Kostenträger ins Ist; würde es hier zusätzlich mit dem
Einkaufspreis bewertet, stünde es zweimal im Projekt, und die Marge wäre um den vollen
Materialwert zu schlecht. Die Funktion hat keinen Weg daran vorbei (PLAN §6.5).

**Welcher Preis?** Der Einkaufspreis aus der Kalkulation. Das Werkzeug führt keine
Lagerbuchhaltung (PLAN §12), es gibt also keinen gleitenden Durchschnittspreis und keine
Charge – der kalkulierte EK ist der einzige belastbare Wert, den es gibt. Das ist eine bewusste
Vereinfachung und steht so in der Verfahrensdokumentation.

**Welcher Monat?** Der Monat der Bestätigung in Europe/Berlin. Eine Lagerentnahme ist im
Leitstand ein Bewertungsvorgang und keine Buchung mit eigenem Datum.

**Keine Sperre.** Wird die Bestätigung übergangen, trägt das Projekt eine sichtbare Warnung und
steht in :func:`offene_mengen`. Einen Statuswechsel an einer Dateneingabe scheitern zu lassen
treibt die Leute dazu, den Status gar nicht erst zu pflegen.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, case, delete, func, select
from sqlalchemy.orm import Session

from app.geld import kaufmaennisch_runden
from app.modelle import IstKosten, Projekt, Stuecklistenposition
from app.zeit import heute_ortszeit

QUELLE = "stueckliste"

# So heißt die Zeile in ist_kosten – zugleich der Eindeutigkeitsschlüssel je Projekt und Monat
# (Migration 0007).
REFERENZ = "Lagerentnahme (Stückliste)"

# Projektstatus, in denen eine offene Mengenbestätigung überhaupt auffallen soll. Vor dem Bau
# ist sie noch nicht fällig.
ZU_BESTAETIGEN = ("in_bau", "abgeschlossen")


@dataclass
class Bewertung:
    """Ergebnis einer Bewertung, für Antwort und Protokoll."""

    projekt_nr: int
    monat: str
    lagerpositionen: int
    bewertet: int
    ohne_preis: int
    betrag_cent: int = 0

    @property
    def vollstaendig(self) -> bool:
        return self.ohne_preis == 0


def menge_fuer_bewertung(position: Stuecklistenposition) -> Decimal:
    """Die bestätigte Menge, ersatzweise die kalkulierte.

    Ohne Bestätigung mit dem Soll zu rechnen ist die ehrlichere Vorbelegung als eine Null: das
    Material ist verbaut, nur hat es noch niemand gezählt. Dass gezählt wurde, sagt
    :func:`offene_mengen`.
    """
    return Decimal(
        str(position.menge_ist if position.menge_ist is not None else position.menge_soll)
    )


def bewerten(sitzung: Session, projekt: Projekt, *, monat: str | None = None) -> Bewertung:
    """Lagerpositionen bewerten und als Ist-Kosten schreiben.

    Muss in einer Schreibtransaktion laufen. Ersetzt eine frühere Bewertung desselben Monats,
    statt sie zu ergänzen – sonst stünde die Lagerentnahme nach der zweiten Bestätigung doppelt.
    """
    zeitraum = monat or f"{heute_ortszeit():%Y-%m}"
    positionen = list(
        sitzung.scalars(
            select(Stuecklistenposition).where(Stuecklistenposition.projekt_id == projekt.id)
        )
    )
    ergebnis = Bewertung(
        projekt_nr=projekt.projekt_nr,
        monat=zeitraum,
        lagerpositionen=sum(1 for p in positionen if p.quelle == "lager"),
        bewertet=0,
        ohne_preis=0,
    )

    for position in positionen:
        if position.quelle != "lager":
            # Die Doppelbelastungssperre (PLAN §6.5). Ein früher gesetzter Betrag wird
            # zurückgenommen: die Position kann in der Kalkulation von 'lager' auf
            # 'projektbestellt' gewechselt sein, und dann gehört der Betrag dort nicht mehr hin.
            position.bewertet_betrag = None
            continue
        if position.ek_preis is None:
            position.bewertet_betrag = None
            ergebnis.ohne_preis += 1
            continue
        position.bewertet_betrag = kaufmaennisch_runden(
            menge_fuer_bewertung(position) * position.ek_preis
        )
        ergebnis.bewertet += 1
        ergebnis.betrag_cent += position.bewertet_betrag

    _als_ist_kosten_schreiben(sitzung, projekt, ergebnis)
    sitzung.flush()
    return ergebnis


def _als_ist_kosten_schreiben(sitzung: Session, projekt: Projekt, ergebnis: Bewertung) -> None:
    """**Eine** Zeile je Projekt – über alle Monate hinweg.

    Anders als DATEV und TimeTac ist die Lagerbewertung keine periodische Größe, sondern der
    aktuelle Wertansatz: sie sagt, was an Lagermaterial in diesem Projekt steckt. Es gibt davon
    genau einen, nicht eine Reihe je Bestätigung.

    Deshalb wird beim Neubewerten der **ganze** Bestand dieses Projekts gelöscht und nicht nur
    der Monat. Andernfalls stünde nach einer zweiten Bestätigung im Folgemonat die Lagerentnahme
    zweimal im Ist – und eine verdoppelte Zahl sieht in der Nachkalkulation aus wie ein teures
    Projekt, nicht wie ein Fehler. Der Monat der Zeile ist der der letzten Bestätigung; er
    ordnet den Wertansatz zeitlich ein, teilt ihn aber nicht auf.
    """
    sitzung.execute(
        delete(IstKosten).where(
            IstKosten.projekt_id == projekt.id,
            IstKosten.quelle == QUELLE,
        )
    )
    if ergebnis.betrag_cent == 0 and ergebnis.bewertet == 0:
        return
    sitzung.add(
        IstKosten(
            projekt_id=projekt.id,
            quelle=QUELLE,
            monat=ergebnis.monat,
            betrag=ergebnis.betrag_cent,
            referenz=REFERENZ,
        )
    )


@dataclass
class OffeneMenge:
    projekt_nr: int
    bezeichnung: str | None
    kunde: str
    status: str
    positionen: int
    offen: int


def offene_mengen(sitzung: Session, sichtbare_projekte: Select) -> list[OffeneMenge]:
    """Projekte, deren Lagerpositionen noch nicht gezählt sind.

    Grundlage der Warnung am Projekt und der Liste „Mengen-Ist offen". Gezählt werden nur
    Lagerpositionen: bei projektbestelltem Material sagt die DATEV-Buchung, was es gekostet hat,
    die Menge ist dort ohne Belang.
    """
    from app.modelle import Kunde

    zeilen = sitzung.execute(
        select(
            Projekt.projekt_nr,
            Projekt.bezeichnung,
            Kunde.name,
            Projekt.status,
            func.count(Stuecklistenposition.id),
            func.sum(case((Stuecklistenposition.menge_ist.is_(None), 1), else_=0)),
        )
        .select_from(Stuecklistenposition)
        .join(Projekt, Projekt.id == Stuecklistenposition.projekt_id)
        .join(Kunde, Kunde.id == Projekt.kunde_id)
        .where(
            Projekt.id.in_(sichtbare_projekte.with_only_columns(Projekt.id)),
            Projekt.status.in_(ZU_BESTAETIGEN),
            Stuecklistenposition.quelle == "lager",
        )
        .group_by(Projekt.id)
        .order_by(Projekt.projekt_nr)
    ).all()

    return [
        OffeneMenge(
            projekt_nr=nummer,
            bezeichnung=bezeichnung,
            kunde=kunde,
            status=status,
            positionen=int(anzahl or 0),
            offen=int(unbestaetigt or 0),
        )
        for nummer, bezeichnung, kunde, status, anzahl, unbestaetigt in zeilen
        if int(unbestaetigt or 0) > 0
    ]


def hat_offene_mengen(sitzung: Session, projekt: Projekt) -> bool:
    """Ob an diesem Projekt Lagerpositionen ohne bestätigte Menge stehen."""
    offen = sitzung.scalar(
        select(func.count())
        .select_from(Stuecklistenposition)
        .where(
            Stuecklistenposition.projekt_id == projekt.id,
            Stuecklistenposition.quelle == "lager",
            Stuecklistenposition.menge_ist.is_(None),
        )
    )
    return bool(offen)
