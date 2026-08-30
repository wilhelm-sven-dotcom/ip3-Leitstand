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

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
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
from app.modelle.pruefungen import (
    in_werten,
    in_werten_oder_leer,
    monat_check,
    nicht_negativ,
)

if TYPE_CHECKING:
    from app.modelle.anlagen import Anlage
    from app.modelle.fakturierung import Rechnung
    from app.modelle.stammdaten import Firma, Kunde
    from app.modelle.system import User

PROJEKT_STATUS = ("angebot", "beauftragt", "in_bau", "abgeschlossen", "storniert")

# Unterlagen, die der Doku-Scan im Projektordner unterscheidet (PLAN §5). Die Liste ist
# zugleich die Prüfliste für [dokumente] in der config.toml – ein Tippfehler dort fiele
# sonst erst auf, wenn eine Pflichtunterlage nie gefunden wird.
DOKUMENT_TYPEN = ("ab", "abnahme", "anlagendoku", "konformitaet", "messkonzept", "sonstig")
UST_KENNZEICHEN = ("19", "0", "13b", "gemischt")

# Anlagenart für Filter und Liste (design/Projektliste.dc.html). Aus PV- und Speicherdaten
# ableitbar bis auf 'freiflaeche' – dass eine Anlage auf einer Freifläche steht, sagt kein
# anderes Feld. Siehe Migration 0005.
ANLAGENARTEN = (
    "aufdach",
    "aufdach_speicher",
    "freiflaeche",
    "speicher",
    "ladestation",
    "sonstig",
)
GEWERKE = ("pv", "speicher", "ls", "service", "nachtrag")

# Die Typen der Meilensteine folgen der Teamliste (PLAN §9). Sie liefern die Auslöser für
# Abschlagsvorschläge, Fristen und die Anlagenregister-Automatik (PLAN §6.8, §6.9).
#
# Der Statusblock (Spalten AM–AT) und der Terminblock (AC–AJ) sind getrennt aufgeführt, weil
# ``UNIQUE(projekt_id, typ)`` gilt: die acht Terminspalten unter den Sammeltypen 'montage' und
# 'lieferung' zusammenzufassen würde beim Import acht Werte auf zwei Zeilen zusammenfallen
# lassen. 'montage', 'lieferung' und 'inbetriebnahme' bleiben als gröbere Typen für Projekte,
# die von Hand gepflegt werden.
MEILENSTEIN_TYPEN = (
    # Statusblock der Teamliste, Spalten AM–AT
    "uebergabetermin",
    "freigabe_planung",
    "plan_erstellt",
    "anmeldung_nb",
    "mastr",
    "fertigmeldung",
    "zaehler",
    "abnahme",
    # Terminblock der Teamliste, Spalten AC–AJ
    "montage_uk",
    "montage_elektro",
    "zaehlerschrank",
    "lieferung_uk",
    "lieferung_wr_pv",
    "lieferung_wr_speicher",
    "lieferung_speicher",
    "lieferung_wallbox",
    # gröbere Typen ohne eigene Quellspalte
    "montage",
    "lieferung",
    "inbetriebnahme",
)


class Projekt(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "projekte"
    __table_args__ = (
        in_werten("typ", ("projekt", "service")),
        in_werten("status", PROJEKT_STATUS),
        in_werten("ust_kz", UST_KENNZEICHEN),
        in_werten_oder_leer("anlagenart", ANLAGENARTEN),
        # Projektnummer rein numerisch, höchstens 8 Stellen (DATEV-KOST-tauglich, PLAN §3).
        nicht_negativ("projekt_nr"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_nr: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmen.id"), nullable=False, index=True)
    typ: Mapped[str] = mapped_column(Kurztext, nullable=False, default="projekt", index=True)
    kunde_id: Mapped[int] = mapped_column(ForeignKey("kunden.id"), nullable=False, index=True)
    # Projektname aus der Liste (design/Projektliste.dc.html). Für die migrierten Projekte leer –
    # die Bestandsdateien führen keinen; die Anzeige fällt dann auf den Kundennamen zurück.
    bezeichnung: Mapped[str | None] = mapped_column(Text, nullable=True)
    standort: Mapped[str | None] = mapped_column(Text, nullable=True)
    anlagenart: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)

    # Anlagendaten. Leistungen als Dezimalzahl, nicht als Geldbetrag – hier ist Gleitkomma
    # unschädlich, weil damit nicht gerechnet wird, was zu Cent-Differenzen führen könnte.
    pv_kwp: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    wr_typ: Mapped[str | None] = mapped_column(Text, nullable=True)
    speicher_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    # Die Teamliste führt in der Speicherspalte eine Produktbezeichnung ('2x BYD HVM 22.1'),
    # keine reine Zahl. Die Kapazität wird daraus gelesen und steht in speicher_kwh; der Text
    # bleibt hier erhalten, weil er das verbaute Gerät benennt und für Service und
    # Gewährleistung gebraucht wird.
    speicher_typ: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    # Herkunft bei Positionen aus der Migration (PLAN §9): Datei und Zeile, damit ein Betrag
    # später bis in die Quelldatei zurückverfolgbar bleibt.
    quelle_migration: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Positionen des Altbestands, die laut Auftragsliste schon berechnet wurden. Es gibt dazu
    # keinen Beleg im Leitstand – die Rechnungen wurden vor der Einführung gestellt. PLAN §6.7
    # trennt „gestellt" von „bezahlt": das hier ist gestellt, der Zahlungsstatus kommt erst mit
    # dem OPOS-Import. NULL heißt „keine Migrationsposition".
    migriert_gestellt: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)

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

    ``erledigt`` und ``erledigt_am`` sind getrennt, weil die Teamliste nur Kreuze kennt: ein
    ``x`` sagt, dass der Schritt erledigt ist, aber nicht wann. Ein erfundenes Datum wäre eine
    Falschangabe, und ``erledigt_am IS NULL`` als „nicht erledigt" zu lesen würde die
    migrierten Kreuze verschlucken – bei der Abnahme allein über 450 Projekte. Darum:
    ``erledigt`` NULL heißt unbekannt, ``False`` ausdrücklich offen, ``True`` erledigt.
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
    # Kalenderwoche als Text, weil die Altdaten Formen wie '34' und '28/22' enthalten.
    geplant_kw: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    erledigt: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    erledigt_am: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    projekt: Mapped[Projekt] = relationship(back_populates="meilensteine")

    def als_erledigt_vermerken(self, am: date | None = None) -> None:
        """Setzt den Schritt auf erledigt und, falls bekannt, das Datum dazu."""
        self.erledigt = True
        if am is not None:
            self.erledigt_am = am

    def __repr__(self) -> str:
        return f"<Meilenstein {self.typ} Projekt {self.projekt_id}>"


class Dokument(OptimistischMixin, ZeitstempelMixin, Base):
    """Verweis auf ein Dokument im Projektordner (PLAN §5).

    Der Leitstand speichert nur den Pfad und ob die Datei vorhanden ist; die Dateien selbst
    bleiben im OneDrive. Ab Phase 7 prüft ein Scan die Vollständigkeit.
    """

    __tablename__ = "dokumente"
    __table_args__ = (
        # Je Projekt und Typ genau eine Zeile: sie trägt den Befund des Scans, nicht eine
        # Fundstelle. Ohne diese Eindeutigkeit legte jeder nächtliche Lauf neue Zeilen an, und
        # „Anlagendokumentation fehlt" stünde neben „Anlagendokumentation liegt vor".
        Index("uq_dokumente_projekt_typ", "projekt_id", "typ", unique=True),
        in_werten("typ", DOKUMENT_TYPEN),
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


class Projektordner(OptimistischMixin, ZeitstempelMixin, Base):
    """Wo der Ordner eines Projekts liegt und was zuletzt darin gefunden wurde (PLAN §7 Phase 7).

    Der Scan muss zwei Dinge auseinanderhalten, die sich sonst zu einer nichtssagenden Meldung
    vermischen: **kein Ordner gefunden** und **Ordner da, Unterlage fehlt**. Das Erste ist meist
    ein Namensproblem – ein Tippfehler in der Projektnummer, ein Ordner unter „Archiv" –, das
    Zweite eine echte Lücke in der Mappe. Deshalb trägt diese Tabelle den Ordnerbefund je
    Projekt, und :class:`Dokument` den Befund je Unterlage.

    Der Leitstand liest die Ordner ausschließlich (PLAN §2). Er legt nichts an, verschiebt
    nichts und benennt nichts um.
    """

    __tablename__ = "projektordner"
    __table_args__ = (
        # Als eindeutiger Index statt als Constraint: SQLite legt fuer einen Constraint zwar
        # auch einen Index an, meldet ihn aber nicht – und der Regressionstest, der jeden
        # Fremdschluessel auf einen Index prueft, saehe hier keinen.
        Index("uq_projektordner_projekt", "projekt_id", unique=True),
        nicht_negativ("dateien"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projekt_id: Mapped[int] = mapped_column(
        ForeignKey("projekte.id", ondelete="CASCADE"), nullable=False
    )
    # Vollständiger Pfad des gefundenen Ordners. NULL heißt: zu diesem Projekt gab es unter der
    # konfigurierten Wurzel keinen Ordner mit passender Nummer.
    pfad: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    gefunden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # Wie viele Dateien der Ordner enthält, über alle Unterordner. Ein Ordner mit null Dateien
    # ist angelegt, aber leer – auch das ist eine Auskunft.
    dateien: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Mehrdeutigkeit wird nicht stillschweigend aufgelöst: liegen zwei Ordner mit derselben
    # Nummer da, steht hier der zweite Fund, und die Übersicht meldet es.
    mehrdeutig_mit: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    geprueft_am: Mapped[date | None] = mapped_column(Date, nullable=True)

    projekt: Mapped[Projekt] = relationship()

    def __repr__(self) -> str:
        return f"<Projektordner Projekt {self.projekt_id} {'da' if self.gefunden else 'fehlt'}>"
