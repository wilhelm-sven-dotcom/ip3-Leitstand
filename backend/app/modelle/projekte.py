"""Projekte, Zahlungsplan, Nachträge, Meilensteine (PLAN §5).

Die Projektnummer ist der durchgängige Schlüssel des ganzen Hauses: Datenbank,
DATEV-Kostenträger (KOST2), TimeTac-Projekt, Kalkulationsblatt-Dateiname und Rechnungsreferenz
verwenden dieselbe Nummer (PLAN §3). Sie ist rein numerisch, höchstens achtstellig, Schema
``JJNNN`` – Serviceaufträge tragen eine führende 9 (``9JJNN``), damit sie im KOST-Feld
unterscheidbar bleiben.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modelle.basis import (
    Base,
    Cent,
    Kurztext,
    Langtext,
    OptimistischMixin,
    Text,
    ZeitstempelMixin,
)
from app.modelle.pruefungen import in_werten, monat_check, nicht_negativ

if TYPE_CHECKING:
    from app.modelle.anlagen import Anlage
    from app.modelle.fakturierung import Rechnung
    from app.modelle.stammdaten import Firma, Kunde
    from app.modelle.system import User

PROJEKT_STATUS = ("angebot", "beauftragt", "in_bau", "abgeschlossen", "storniert")
UST_KENNZEICHEN = ("19", "0", "13b", "gemischt")
GEWERKE = ("pv", "speicher", "ls", "service", "nachtrag")

# Die Typen der Meilensteine folgen der Teamliste (PLAN §9, Spalten T–AA und AM–AT). Sie liefern
# die Auslöser für Abschlagsvorschläge, Fristen und die Anlagenregister-Automatik (PLAN §6.8, §6.9).
MEILENSTEIN_TYPEN = (
    "uebergabetermin",
    "freigabe_planung",
    "plan_erstellt",
    "anmeldung_nb",
    "mastr",
    "lieferung",
    "montage",
    "fertigmeldung",
    "zaehler",
    "abnahme",
    "inbetriebnahme",
)


class Projekt(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "projekte"
    __table_args__ = (
        in_werten("typ", ("projekt", "service")),
        in_werten("status", PROJEKT_STATUS),
        in_werten("ust_kz", UST_KENNZEICHEN),
        # Projektnummer rein numerisch, höchstens 8 Stellen (DATEV-KOST-tauglich, PLAN §3).
        nicht_negativ("projekt_nr"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_nr: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmen.id"), nullable=False, index=True)
    typ: Mapped[str] = mapped_column(Kurztext, nullable=False, default="projekt", index=True)
    kunde_id: Mapped[int] = mapped_column(ForeignKey("kunden.id"), nullable=False, index=True)
    standort: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Anlagendaten. Leistungen als Dezimalzahl, nicht als Geldbetrag – hier ist Gleitkomma
    # unschädlich, weil damit nicht gerechnet wird, was zu Cent-Differenzen führen könnte.
    pv_kwp: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    wr_typ: Mapped[str | None] = mapped_column(Text, nullable=True)
    speicher_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    ladestation: Mapped[str | None] = mapped_column(Text, nullable=True)

    auftrag_vom: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    ab_wert_netto: Mapped[int | None] = mapped_column(Cent, nullable=True)

    # Grundlage für den Sichtbarkeits-Scope 'eigene' (PLAN §4). Nach der Migration wird die
    # Verknüpfung zu den Nutzerkonten von Hand gesetzt, bis dahin trägt pl_name den Klartext.
    pl_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    pl_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    vertriebsweg: Mapped[str | None] = mapped_column(Text, nullable=True)
    ust_kz: Mapped[str] = mapped_column(Kurztext, nullable=False, default="19")
    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="beauftragt", index=True)
    anlage_id: Mapped[int | None] = mapped_column(
        ForeignKey("anlagen.id"), nullable=True, index=True
    )
    quelle_migration: Mapped[str | None] = mapped_column(Text, nullable=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    firma: Mapped[Firma] = relationship()
    kunde: Mapped[Kunde] = relationship(back_populates="projekte")
    projektleiter: Mapped[User | None] = relationship(foreign_keys=[pl_user_id])
    anlage: Mapped[Anlage | None] = relationship(foreign_keys=[anlage_id])
    zahlungsplan: Mapped[list[Zahlungsplanposition]] = relationship(
        back_populates="projekt",
        cascade="all, delete-orphan",
        order_by="Zahlungsplanposition.pos_nr",
    )
    nachtraege: Mapped[list[Nachtrag]] = relationship(
        back_populates="projekt", cascade="all, delete-orphan"
    )
    meilensteine: Mapped[list[Meilenstein]] = relationship(
        back_populates="projekt", cascade="all, delete-orphan"
    )
    rechnungen: Mapped[list[Rechnung]] = relationship(back_populates="projekt")

    def __repr__(self) -> str:
        return f"<Projekt {self.projekt_nr}>"


class Zahlungsplanposition(OptimistischMixin, ZeitstempelMixin, Base):
    """Eine geplante Rechnung: Abschlag, Schlussrechnung oder Einmalbetrag.

    Ist ``rechnung_id`` gesetzt, ist die Position berechnet und gesperrt – Änderungen laufen nur
    über den Storno des Belegs (PLAN §5, Datenbank-Trigger).
    """

    __tablename__ = "zahlungsplan"
    __table_args__ = (
        UniqueConstraint("projekt_id", "pos_nr", name="uq_zahlungsplan_projekt_id_pos_nr"),
        in_werten("gewerk", GEWERKE),
        in_werten("art", ("abschlag", "schluss", "einmal")),
        monat_check("plan_monat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pos_nr: Mapped[int] = mapped_column(Integer, nullable=False)
    bezeichnung: Mapped[str] = mapped_column(Text, nullable=False)
    gewerk: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    art: Mapped[str] = mapped_column(Kurztext, nullable=False)
    betrag_netto: Mapped[int] = mapped_column(Cent, nullable=False)
    # Monat, in dem die Rechnung erwartet wird. NULL heißt „unterminiert" und wird im Forecast
    # gesondert ausgewiesen (PLAN §7, Phase 2).
    plan_monat: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    # Auslöser für den Rechnungsvorschlag auf der Startseite (PLAN §6.8), z. B. 'lieferung'.
    trigger_status: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    rechnung_id: Mapped[int | None] = mapped_column(
        ForeignKey("rechnungen.id"), nullable=True, index=True
    )

    projekt: Mapped[Projekt] = relationship(back_populates="zahlungsplan")
    rechnung: Mapped[Rechnung | None] = relationship(back_populates="zahlungsplan_positionen")

    def __repr__(self) -> str:
        return f"<Zahlungsplanposition {self.projekt_id}/{self.pos_nr}>"


class Nachtrag(OptimistischMixin, ZeitstempelMixin, Base):
    """Nachtrag zum Auftrag. Beauftragte Nachträge erhöhen den Soll-Wert des Zahlungsplans."""

    __tablename__ = "nachtraege"
    __table_args__ = (in_werten("status", ("angeboten", "beauftragt", "berechnet")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bezeichnung: Mapped[str] = mapped_column(Text, nullable=False)
    betrag_netto: Mapped[int] = mapped_column(Cent, nullable=False)
    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="angeboten", index=True)
    datum: Mapped[date | None] = mapped_column(Date, nullable=True)

    projekt: Mapped[Projekt] = relationship(back_populates="nachtraege")

    def __repr__(self) -> str:
        return f"<Nachtrag {self.bezeichnung}>"


class Meilenstein(OptimistischMixin, ZeitstempelMixin, Base):
    """Termin und Status eines Projektschritts.

    ``geplant_kw`` trägt die Kalenderwoche aus der Teamliste, ``erledigt_am`` das tatsächliche
    Datum. Je Projekt gibt es jeden Typ genau einmal (UNIQUE, PLAN §5).
    """

    __tablename__ = "meilensteine"
    __table_args__ = (
        UniqueConstraint("projekt_id", "typ", name="uq_meilensteine_projekt_id_typ"),
        in_werten("typ", MEILENSTEIN_TYPEN),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    typ: Mapped[str] = mapped_column(Kurztext, nullable=False)
    # Kalenderwoche als Text, weil die Altdaten Formen wie '34' und 'KW 34/25' enthalten.
    geplant_kw: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    erledigt_am: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    projekt: Mapped[Projekt] = relationship(back_populates="meilensteine")

    @property
    def erledigt(self) -> bool:
        return self.erledigt_am is not None

    def __repr__(self) -> str:
        return f"<Meilenstein {self.typ} Projekt {self.projekt_id}>"


class Dokument(OptimistischMixin, ZeitstempelMixin, Base):
    """Verweis auf ein Dokument im Projektordner (PLAN §5).

    Der Leitstand speichert nur den Pfad und ob die Datei vorhanden ist; die Dateien selbst
    bleiben im OneDrive. Ab Phase 7 prüft ein Scan die Vollständigkeit.
    """

    __tablename__ = "dokumente"
    __table_args__ = (
        in_werten(
            "typ", ("ab", "abnahme", "anlagendoku", "konformitaet", "messkonzept", "sonstig")
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False, index=True
    )
    typ: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    pfad: Mapped[str] = mapped_column(Langtext, nullable=False)
    vorhanden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    geprueft_am: Mapped[date | None] = mapped_column(Date, nullable=True)

    projekt: Mapped[Projekt] = relationship()

    def __repr__(self) -> str:
        return f"<Dokument {self.typ} Projekt {self.projekt_id}>"
