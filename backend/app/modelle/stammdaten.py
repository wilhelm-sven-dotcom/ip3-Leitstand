"""Firmen, Kunden, Ansprechpartner (PLAN §5).

Die Firmen-Dimension steckt von Anfang an im Schema, auch wenn V1 nur mit ip³ arbeitet: Projekte
und Rechnungen tragen eine ``firma_id``, Nummernkreise laufen je Firma. Damit kann später eine
zweite Firma fakturieren, ohne dass das Schema angefasst werden muss (PLAN §12).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.modelle.basis import Base, Kurztext, Langtext, OptimistischMixin, Text, ZeitstempelMixin
from app.modelle.pruefungen import in_werten, in_werten_oder_leer

if TYPE_CHECKING:
    from app.modelle.projekte import Projekt


class Firma(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "firmen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kuerzel: Mapped[str] = mapped_column(Kurztext, nullable=False, unique=True)
    firmierung: Mapped[str] = mapped_column(Text, nullable=False)
    anschrift: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    ust_id: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    st_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    hrb: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Firma {self.kuerzel}>"


class Kunde(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "kunden"
    __table_args__ = (
        in_werten("typ", ("b2b", "b2c")),
        in_werten("status", ("aktiv", "inaktiv")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Fortlaufend ab 10001, Vergabe über die Tabelle nummernkreise (PLAN §3).
    kunden_nr: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    zusatz: Mapped[str | None] = mapped_column(Text, nullable=True)
    strasse: Mapped[str | None] = mapped_column(Text, nullable=True)
    plz: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ort: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    ust_id: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    typ: Mapped[str] = mapped_column(Kurztext, nullable=False, default="b2c")
    # NULL bedeutet: Standard aus der Konfiguration verwenden.
    zahlungsziel_tage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    telefon: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="aktiv", index=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    ansprechpartner: Mapped[list[Ansprechpartner]] = relationship(
        back_populates="kunde", cascade="all, delete-orphan"
    )
    projekte: Mapped[list[Projekt]] = relationship(back_populates="kunde")

    def __repr__(self) -> str:
        return f"<Kunde {self.kunden_nr} {self.name}>"


class Ansprechpartner(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "ansprechpartner"
    __table_args__ = (
        in_werten_oder_leer("funktion", ("technik", "kaufmaennisch", "sonstig")),
        UniqueConstraint("kunde_id", "name", name="uq_ansprechpartner_kunde_id_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kunde_id: Mapped[int] = mapped_column(
        ForeignKey("kunden.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    funktion: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    telefon: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    kunde: Mapped[Kunde] = relationship(back_populates="ansprechpartner")

    def __repr__(self) -> str:
        return f"<Ansprechpartner {self.name}>"
