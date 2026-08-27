"""Fixkosten, DATEV-Salden, Kontenzuordnung und offene Posten (PLAN §5, Phase 5).

Diese Tabellen tragen das Firmen-Cockpit. Sie werden ausschließlich durch Importe und die
Fixkostenpflege gefüllt, deshalb ohne Optimistic Locking – bis auf die Kontenzuordnung und die
Fixkostenplanung, die von Hand bearbeitet werden.

Wichtig für die Auswertung (PLAN §6.7): „gestellt" ist nicht „bezahlt". Der Umsatz-Ist kommt aus
den festgeschriebenen Rechnungen, der Zahlungsstatus ausschließlich aus dem OPOS-Import.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modelle.basis import (
    Base,
    Cent,
    Kurztext,
    Langtext,
    OptimistischMixin,
    Text,
    ZeitstempelMixin,
)
from app.modelle.pruefungen import in_werten, monat_check

# Blöcke des Fixkostenausweises im Cockpit. 'neutral' sammelt Konten, die nicht in den
# Fixkostenblock gehören (z. B. durchlaufende Posten) – sie werden bewusst nicht gerechnet.
KOSTENBLOECKE = (
    "personal",
    "raum",
    "fahrzeuge",
    "versicherung",
    "werbung",
    "zins",
    "sonstiges",
    "neutral",
)


class FixkostenPlan(OptimistischMixin, ZeitstempelMixin, Base):
    """Geplante Fixkosten je Monat und Block.

    Für Zukunftsmonate, in denen noch keine Summen- und Saldenliste vorliegt.
    """

    __tablename__ = "fixkosten_plan"
    __table_args__ = (
        UniqueConstraint("monat", "block", name="uq_fixkosten_plan_monat_block"),
        monat_check("monat"),
        in_werten("block", KOSTENBLOECKE),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monat: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    block: Mapped[str] = mapped_column(Kurztext, nullable=False)
    betrag: Mapped[int] = mapped_column(Cent, nullable=False)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    def __repr__(self) -> str:
        return f"<FixkostenPlan {self.monat} {self.block}>"


class DatevSaldo(ZeitstempelMixin, Base):
    """Zeile der Summen- und Saldenliste. Jeder Importlauf ersetzt seinen Monat."""

    __tablename__ = "datev_salden"
    __table_args__ = (
        UniqueConstraint("monat", "konto", name="uq_datev_salden_monat_konto"),
        monat_check("monat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monat: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    konto: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    bezeichnung: Mapped[str | None] = mapped_column(Text, nullable=True)
    saldo: Mapped[int] = mapped_column(Cent, nullable=False)
    # Zugeordneter Block; NULL bedeutet: Konto ist noch nicht zugeordnet und erscheint als
    # Pflegehinweis (PLAN §8).
    block: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    importlauf_id: Mapped[int | None] = mapped_column(
        ForeignKey("importlaeufe.id"), nullable=True, index=True
    )

    def __repr__(self) -> str:
        return f"<DatevSaldo {self.monat} {self.konto}>"


class KontenMapping(OptimistischMixin, ZeitstempelMixin, Base):
    """Zuordnung von Kontenbereichen zu Kostenblöcken (Erstbefüllung mit dem Steuerberater)."""

    __tablename__ = "konten_mapping"
    __table_args__ = (
        UniqueConstraint("konto_von", "konto_bis", name="uq_konten_mapping_konto_von_konto_bis"),
        in_werten("block", KOSTENBLOECKE),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    konto_von: Mapped[str] = mapped_column(Kurztext, nullable=False)
    konto_bis: Mapped[str] = mapped_column(Kurztext, nullable=False)
    block: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<KontenMapping {self.konto_von}-{self.konto_bis} → {self.block}>"


class Opos(ZeitstempelMixin, Base):
    """Offene Posten der Debitoren aus dem OPOS-Import (PLAN §6.7, §6.13).

    Der Zahlungsstatus kommt ausschließlich von hier. „bezahlt" gilt bei Restbetrag null oder
    innerhalb der Skonto-Toleranz aus der Konfiguration; solche Fälle erscheinen als „bezahlt mit
    Abzug" statt dauerhaft als überfällig.
    """

    __tablename__ = "opos"
    __table_args__ = (
        UniqueConstraint("rechnung_nr", "stand_datum", name="uq_opos_rechnung_nr_stand_datum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rechnung_nr: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    kunde: Mapped[str | None] = mapped_column(Text, nullable=True)
    betrag: Mapped[int] = mapped_column(Cent, nullable=False)
    faellig_am: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    offen_betrag: Mapped[int] = mapped_column(Cent, nullable=False)
    stand_datum: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    importlauf_id: Mapped[int | None] = mapped_column(
        ForeignKey("importlaeufe.id"), nullable=True, index=True
    )

    def __repr__(self) -> str:
        return f"<Opos {self.rechnung_nr} offen {self.offen_betrag}>"
