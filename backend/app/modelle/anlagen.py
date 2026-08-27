"""Anlagenregister und Fristen (PLAN §5, Phase 6).

Wechselt ein Projekt auf ``abgeschlossen``, entsteht daraus ein Anlagen-Datensatz und die
Gewährleistungsfrist wird gesetzt: Abnahmedatum plus vier Jahre (VOB) oder fünf Jahre (BGB). Die
Vertragsart wird beim Abschluss abgefragt – es gibt bewusst keinen stillen Standard (PLAN §6.9,
offener Punkt §13.8).

Der Fristenwächter arbeitet mit ``vorlauf_tage``: eine Frist erscheint auf der Startseite, sobald
sie in diesem Vorlauf liegt. Für die Gewährleistung sind das drei Monate.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelle.basis import Base, Kurztext, Langtext, OptimistischMixin, Text, ZeitstempelMixin
from app.modelle.pruefungen import in_werten
from app.modelle.stammdaten import Kunde

FRIST_TYPEN = ("mastr", "fertigmeldung", "reservierung", "gewaehrleistung", "sonstig")
FRIST_BEZUEGE = ("projekt", "anlage")


class Anlage(OptimistischMixin, ZeitstempelMixin, Base):
    """Eine gebaute Anlage – Bezugspunkt für Service, Wartung und Gewährleistung."""

    __tablename__ = "anlagen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Das Projekt, aus dem die Anlage entstanden ist. Kein Fremdschlüssel-Zwang auf Projekte,
    # weil Anlagen aus dem Altbestand ohne Projekt im Leitstand erfasst werden können.
    projekt_id_ursprung: Mapped[int | None] = mapped_column(
        ForeignKey("projekte.id"), nullable=True, index=True
    )
    kunde_id: Mapped[int] = mapped_column(ForeignKey("kunden.id"), nullable=False, index=True)
    standort: Mapped[str | None] = mapped_column(Text, nullable=True)
    pv_kwp: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    speicher_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    inbetriebnahme: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    abnahme_datum: Mapped[date | None] = mapped_column(Date, nullable=True)
    gewaehrleistung_ende: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    wartungsvertrag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    # Nummer im Marktstammdatenregister (MaStR) der Bundesnetzagentur.
    mastr_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    kunde: Mapped[Kunde] = relationship()

    def __repr__(self) -> str:
        return f"<Anlage {self.id} {self.standort or ''}>"


class Frist(OptimistischMixin, ZeitstempelMixin, Base):
    """Eine überwachte Frist zu einem Projekt oder einer Anlage.

    Der Bezug ist absichtlich zweiteilig (``bezug`` plus ``bezug_id``) statt zweier
    Fremdschlüsselspalten: Fristen kommen später auch zu Verträgen und Angeboten, und dann soll
    keine Migration nötig sein. Die Auflösung des Bezugs übernimmt der Fristendienst.
    """

    __tablename__ = "fristen"
    __table_args__ = (
        in_werten("bezug", FRIST_BEZUEGE),
        in_werten("typ", FRIST_TYPEN),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bezug: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    bezug_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    typ: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    bezeichnung: Mapped[str] = mapped_column(Text, nullable=False)
    faellig_am: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    vorlauf_tage: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    erledigt_am: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    @property
    def erledigt(self) -> bool:
        return self.erledigt_am is not None

    def __repr__(self) -> str:
        return f"<Frist {self.typ} fällig {self.faellig_am}>"
