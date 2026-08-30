"""Angebotspipeline: was noch kein Auftrag ist (PLAN §7 Phase 7).

Die Pipeline steht **neben** dem Forecast, nie darin. Ein gewichtetes Angebot ist kein Auftrag;
beides in einer Zahl wäre die gefährlichste Kennzahl des ganzen Werkzeugs – sie sähe aus wie
Umsatz und wäre eine Hoffnung. Deshalb ist das hier ein eigener Dienst mit eigenen Klassen und
nicht ein zusätzliches Feld in ``auswertung.Monatswert``: was nicht zusammen in einer Struktur
steht, kann auch nicht versehentlich zusammen addiert werden.

Drei Festlegungen:

* **Nur offene Angebote zählen.** Ein gewonnenes ist ein Projekt und steht im Auftragsbestand;
  es hier noch einmal zu zeigen, hieße denselben Euro zweimal zu zählen. Ein verlorenes ist weg.
* **Gewichtet und roh stehen nebeneinander.** Die gewichtete Summe ist die Planungsgröße, die
  rohe sagt, wie viel überhaupt im Rennen ist. Nur die gewichtete zu zeigen, verschweigt das
  Risiko; nur die rohe, die Wahrscheinlichkeit.
* **Ohne erwarteten Monat wird nicht geraten.** Solche Angebote stehen als ``unterminiert``
  daneben, wie unterminierte Zahlungsplanpositionen im Forecast (PLAN §7 Phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formate import prozent
from app.geld import formatiere_euro
from app.modelle import Angebot

# Wahrscheinlichkeiten unter dieser Schwelle sind Rauschen: sie blähen die rohe Summe auf und
# tragen zur gewichteten fast nichts bei. Sie zählen trotzdem mit – aber die Ansicht kann sie
# über diese Grenze getrennt ausweisen, statt sie stillschweigend zu unterschlagen.
GERINGE_CHANCE_PROMILLE = 200


@dataclass
class Pipelinemonat:
    """Ein Monat der Pipeline. Beträge in Cent (CLAUDE.md Regel 3)."""

    monat: str
    roh_cent: int = 0
    gewichtet_cent: int = 0
    anzahl: int = 0


@dataclass
class Unterminiert:
    """Angebote ohne erwarteten Auftragsmonat."""

    roh_cent: int = 0
    gewichtet_cent: int = 0
    anzahl: int = 0


@dataclass
class Pipelinebild:
    jahr: int
    monate: list[Pipelinemonat]
    unterminiert: Unterminiert = field(default_factory=Unterminiert)
    hinweise: list[str] = field(default_factory=list)

    @property
    def roh_cent(self) -> int:
        return sum(m.roh_cent for m in self.monate) + self.unterminiert.roh_cent

    @property
    def gewichtet_cent(self) -> int:
        return sum(m.gewichtet_cent for m in self.monate) + self.unterminiert.gewichtet_cent

    @property
    def anzahl(self) -> int:
        return sum(m.anzahl for m in self.monate) + self.unterminiert.anzahl


def gewichten(summe_cent: int, wahrscheinlichkeit_promille: int) -> int:
    """Angebotssumme mal Wahrscheinlichkeit, kaufmännisch gerundet auf ganze Cent."""
    return (summe_cent * wahrscheinlichkeit_promille + 500) // 1000


def jahresverlauf(sitzung: Session, jahr: int) -> Pipelinebild:
    """Offene Angebote eines Jahres, roh und gewichtet, Monat für Monat."""
    monate = [Pipelinemonat(monat=f"{jahr:04d}-{m:02d}") for m in range(1, 13)]
    nach_monat = {m.monat: m for m in monate}
    bild = Pipelinebild(jahr=jahr, monate=monate)

    offen = sitzung.scalars(select(Angebot).where(Angebot.status == "offen")).all()
    for angebot in offen:
        gewichtet = gewichten(angebot.summe_netto, angebot.wahrscheinlichkeit_promille)
        if angebot.erwarteter_monat is None:
            bild.unterminiert.roh_cent += angebot.summe_netto
            bild.unterminiert.gewichtet_cent += gewichtet
            bild.unterminiert.anzahl += 1
            continue
        eintrag = nach_monat.get(angebot.erwarteter_monat)
        if eintrag is None:
            # Ein anderes Jahr – gewollt übergangen, der Jahresverlauf zeigt dieses eine.
            continue
        eintrag.roh_cent += angebot.summe_netto
        eintrag.gewichtet_cent += gewichtet
        eintrag.anzahl += 1

    bild.hinweise = _hinweise(sitzung, bild)
    return bild


def _hinweise(sitzung: Session, bild: Pipelinebild) -> list[str]:
    hinweise: list[str] = []

    if bild.unterminiert.anzahl:
        hinweise.append(
            f"{bild.unterminiert.anzahl} offene Angebote haben keinen erwarteten "
            "Auftragsmonat. Sie zählen in der Gesamtsumme, aber in keinem Monat. Nächster "
            "Schritt: den erwarteten Monat am Angebot nachtragen."
        )

    ohne_projekt = sitzung.scalars(
        select(Angebot).where(Angebot.status == "gewonnen", Angebot.projekt_id.is_(None))
    ).all()
    if ohne_projekt:
        namen = ", ".join(a.angebot_nr or a.kunde_name for a in ohne_projekt[:5])
        hinweise.append(
            f"{len(ohne_projekt)} gewonnene Angebote hängen an keinem Projekt ({namen}). Ihr "
            "Wert steht weder in der Pipeline noch im Auftragsbestand. Nächster Schritt: das "
            "Projekt anlegen und am Angebot verknüpfen."
        )

    gering = sitzung.scalars(
        select(Angebot).where(
            Angebot.status == "offen",
            Angebot.wahrscheinlichkeit_promille < GERINGE_CHANCE_PROMILLE,
        )
    ).all()
    if gering:
        summe = sum(a.summe_netto for a in gering)
        hinweise.append(
            f"{len(gering)} Angebote stehen unter {prozent(GERINGE_CHANCE_PROMILLE)} "
            f"Wahrscheinlichkeit und machen zusammen {formatiere_euro(summe)} der rohen Summe "
            "aus. In der gewichteten Summe tragen sie fast nichts bei – die rohe Summe ist "
            "dadurch deutlich größer, als es der Erwartung entspricht."
        )

    return hinweise


def jahre_mit_angeboten(sitzung: Session) -> list[int]:
    """Jahre, für die überhaupt Angebote vorliegen – für die Jahresauswahl der Ansicht."""
    monate = sitzung.scalars(
        select(Angebot.erwarteter_monat).where(Angebot.erwarteter_monat.is_not(None)).distinct()
    ).all()
    return sorted({int(m[:4]) for m in monate if m})
