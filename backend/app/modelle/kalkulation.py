"""Soll-Kalkulation, Stückliste, Ist-Kosten und Stunden (PLAN §5, Phase 4).

Die wichtigste Regel dieses Moduls steht in PLAN §6.5: **keine Doppelbelastung**. Material kommt
entweder über die DATEV-Kostenträger (projektbestellt) oder über die bewertete Stückliste
(Lagerentnahme) ins Projekt-Ist – nie über beide Wege. Gesteuert wird das über
``stueckliste.quelle``: nur Positionen mit ``lager`` werden mit Einkaufspreis bewertet.

Ebenso PLAN §6.6: TimeTac-Stunden mal Verrechnungssatz zählen als kalkulatorische Eigenleistung
ins Projekt-Ist. Auf Firmenebene stehen dagegen die echten Personalkosten aus der Summen- und
Saldenliste im Fixkostenblock; die kalkulatorische Eigenleistung wird dort neutralisiert, sonst
zählt Personal doppelt.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelle.basis import (
    Base,
    Cent,
    Kurztext,
    Langtext,
    OptimistischMixin,
    Text,
    UtcDateTime,
    ZeitstempelMixin,
)
from app.modelle.pruefungen import in_werten, in_werten_oder_leer, monat_check

if TYPE_CHECKING:
    from app.modelle.projekte import Projekt

IST_QUELLEN = ("datev", "stueckliste", "timetac")
STUECKLISTE_QUELLEN = ("projektbestellt", "lager")


class SollKalkulation(OptimistischMixin, ZeitstempelMixin, Base):
    """Sollwerte aus dem Kalkulationsblatt, ein Satz je Projekt (PLAN §8, EXPORT-Tab)."""

    __tablename__ = "soll_kalkulation"

    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), primary_key=True
    )
    material_soll: Mapped[int | None] = mapped_column(Cent, nullable=True)
    dl_soll: Mapped[int | None] = mapped_column(Cent, nullable=True)
    stunden_soll: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Sollmarge in Promille (z. B. 180 für 18 %), damit die Ampel ohne Gleitkomma vergleicht.
    marge_soll: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quelle_datei: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    eingelesen_am: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    projekt: Mapped[Projekt] = relationship()

    def __repr__(self) -> str:
        return f"<SollKalkulation Projekt {self.projekt_id}>"


class Stuecklistenposition(OptimistischMixin, ZeitstempelMixin, Base):
    """Position der Stückliste.

    ``menge_soll`` kommt aus der Kalkulation, ``menge_ist`` wird bei Projektabschluss bestätigt
    (Maske „Mengen-Ist bestätigen"). ``bewertet_betrag`` wird nur für Lagerpositionen gefüllt.
    """

    __tablename__ = "stueckliste"
    __table_args__ = (
        in_werten("quelle", STUECKLISTE_QUELLEN),
        in_werten_oder_leer("gewerk", ("pv", "speicher", "ls")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artikel_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    bezeichnung: Mapped[str] = mapped_column(Text, nullable=False)
    menge_soll: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    menge_ist: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    ek_preis: Mapped[int | None] = mapped_column(Cent, nullable=True)
    quelle: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    gewerk: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    bewertet_betrag: Mapped[int | None] = mapped_column(Cent, nullable=True)

    projekt: Mapped[Projekt] = relationship()

    def __repr__(self) -> str:
        return f"<Stuecklistenposition {self.bezeichnung}>"


class IstKosten(ZeitstempelMixin, Base):
    """Ist-Kosten eines Projekts aus einer der drei Quellen.

    Kein Optimistic Locking: die Zeilen entstehen ausschließlich durch Importe. Jeder Importlauf
    ersetzt seinen Zeitraum, statt anzuhängen (PLAN §8, DATEV).
    """

    __tablename__ = "ist_kosten"
    __table_args__ = (in_werten("quelle", IST_QUELLEN), monat_check("monat"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quelle: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    monat: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    betrag: Mapped[int] = mapped_column(Cent, nullable=False)
    referenz: Mapped[str | None] = mapped_column(Text, nullable=True)
    importlauf_id: Mapped[int | None] = mapped_column(
        ForeignKey("importlaeufe.id"), nullable=True, index=True
    )

    projekt: Mapped[Projekt] = relationship()

    def __repr__(self) -> str:
        return f"<IstKosten {self.quelle} {self.monat} Projekt {self.projekt_id}>"


class Stunden(ZeitstempelMixin, Base):
    """Arbeitsstunden je Projekt und Monat aus TimeTac (PLAN §8).

    ``satz`` ist der Verrechnungssatz in Cent je Stunde aus der Konfiguration, festgehalten zum
    Zeitpunkt des Imports – eine spätere Satzänderung verändert die Nachkalkulation
    abgeschlossener Monate nicht.

    Zweck dieser Daten ist die Kostenrechnung, nicht die Leistungskontrolle (PLAN §13.11).
    """

    __tablename__ = "stunden"
    __table_args__ = (monat_check("monat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    monat: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    mitarbeiter: Mapped[str] = mapped_column(Text, nullable=False)
    stunden: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    satz: Mapped[int] = mapped_column(Cent, nullable=False)
    quelle: Mapped[str] = mapped_column(Kurztext, nullable=False, default="timetac")
    importlauf_id: Mapped[int | None] = mapped_column(
        ForeignKey("importlaeufe.id"), nullable=True, index=True
    )

    projekt: Mapped[Projekt] = relationship()

    def __repr__(self) -> str:
        return f"<Stunden {self.monat} {self.mitarbeiter}: {self.stunden}>"
