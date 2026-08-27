"""Rechnungen, Rechnungspositionen und Nummernkreise (PLAN §5, §10).

Die Regeln aus PLAN §6.4 (GoBD) prägen dieses Modul:

* Die Rechnungsnummer wird **erst bei der Festschreibung** vergeben, nicht im Entwurf. Sonst
  reißen verworfene Entwürfe Lücken in einen Kreis, der lückenlos sein muss.
* Mit der Festschreibung werden Nummer, Zeitstempel und ein SHA-256-Hash über die Belegdaten
  gesetzt. Danach ist der Beleg unveränderbar – abgesichert durch Datenbank-Trigger, nicht nur
  durch Anwendungslogik.
* Korrekturen laufen über einen eigenen Beleg: Vollstorno als ``storno``, Teilkorrektur als
  ``gutschrift``, jeweils mit Verweis in ``storno_ref``.

Der Kundenstamm wird beim Festschreiben als ``kunde_snapshot`` mitgeschrieben. Eine spätere
Adressänderung beim Kunden darf einen bereits ausgestellten Beleg nicht verändern.

Der **Absetzungsblock** einer Schlussrechnung (PLAN §6.1, § 14 Abs. 5 UStG) steht als eigene
Tabelle ``rechnung_absetzung`` und wird beim Erzeugen des Belegs gefüllt – nicht beim Anzeigen
abgeleitet. Sonst würde ein später entstehender Abschlag eine bereits festgeschriebene
Schlussrechnung rückwirkend verändern, und die Rechnung auf dem Papier passte nicht mehr zu der
in der Datenbank.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

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
from app.modelle.projekte import UST_KENNZEICHEN
from app.modelle.pruefungen import in_werten, nicht_negativ

if TYPE_CHECKING:
    from app.modelle.projekte import Projekt, Zahlungsplanposition
    from app.modelle.stammdaten import Firma, Kunde

BELEGARTEN = ("ab", "abschlag", "schluss", "service", "gutschrift", "storno")
BELEG_STATUS = ("entwurf", "festgeschrieben", "storniert")

# Nummernkreise (PLAN §3). Die Rechnungskreise sind lückenlos fortlaufend; AB-Nummern laufen
# ebenfalls fortlaufend, unterliegen aber keiner Lückenlosigkeitspflicht.
KREIS_RECHNUNG = "RE"
KREIS_SERVICERECHNUNG = "SR"
KREIS_AUFTRAGSBESTAETIGUNG = "AB"
KREIS_KUNDE = "KD"
KREIS_PROJEKT = "PR"
KREIS_SERVICEAUFTRAG = "SA"

# Welcher Kreis zu welcher Belegart gehört. Storno und Gutschrift stehen nicht in der Tabelle:
# sie erben den Kreis des Belegs, den sie korrigieren – ein Storno einer Servicerechnung bleibt
# im SR-Kreis, sonst liefe die Korrektur in einem anderen Nummernkreis als das Original.
KREIS_JE_ART: dict[str, str] = {
    "ab": KREIS_AUFTRAGSBESTAETIGUNG,
    "abschlag": KREIS_RECHNUNG,
    "schluss": KREIS_RECHNUNG,
    "service": KREIS_SERVICERECHNUNG,
}

# Belegarten mit Negativbeträgen (PLAN §6.4, §6.14).
KORREKTURARTEN = ("storno", "gutschrift")


class Rechnung(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "rechnungen"
    __table_args__ = (
        # Je Firma ist jede Rechnungsnummer einmalig. NULL-Werte (Entwürfe) schließt SQLite von
        # der Prüfung aus, deshalb dürfen mehrere Entwürfe gleichzeitig ohne Nummer bestehen.
        UniqueConstraint("firma_id", "rechnung_nr", name="uq_rechnungen_firma_id_rechnung_nr"),
        in_werten("art", BELEGARTEN),
        in_werten("status", BELEG_STATUS),
        in_werten("ust_kz", UST_KENNZEICHEN),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL bis zur Festschreibung, dann z. B. 'RE-2026-0087' (PLAN §3).
    rechnung_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmen.id"), nullable=False, index=True)
    art: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    projekt_id: Mapped[int | None] = mapped_column(
        ForeignKey("projekte.id"), nullable=True, index=True
    )
    # Der Empfänger steht am Beleg selbst, nicht nur am Projekt: eine Servicerechnung kann ohne
    # Projekt entstehen (PLAN §10), und ohne diesen Verweis hätte sie keinen Adressaten.
    kunde_id: Mapped[int] = mapped_column(ForeignKey("kunden.id"), nullable=False, index=True)
    # Steuerkennzeichen des Belegs (PLAN §6.2). Vorbelegt aus dem Projekt, danach am Beleg
    # eingefroren: ändert jemand später das Kennzeichen am Projekt, bleibt der Beleg richtig.
    ust_kz: Mapped[str] = mapped_column(Kurztext, nullable=False, default="19")
    # Wievielter Abschlag des Projekts – steht auf dem Beleg („3. Abschlagsrechnung"). Gespeichert
    # statt gezählt, damit ein späterer Storno die Beschriftung alter Belege nicht verschiebt.
    abschlag_nr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Kundenstand zum Zeitpunkt der Ausstellung – der Beleg bleibt gültig, auch wenn sich die
    # Adresse später ändert (§ 14 UStG verlangt die Angaben zum Ausstellungszeitpunkt).
    kunde_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    datum: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    leistungszeitraum: Mapped[str | None] = mapped_column(Text, nullable=True)
    faellig_am: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    betreff: Mapped[str | None] = mapped_column(Text, nullable=True)
    anschreiben: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    schlusstext: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    # Gesamtleistung des Belegs.
    netto: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    ust: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    brutto: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    # Aufteilung je Steuersatz zum Zeitpunkt der Festschreibung, als Liste von
    # ``{"satz": 190, "netto": …, "ust": …}``. Gespeichert, damit PDF, XML und Hash denselben
    # Stand zeigen, ohne dass irgendwo nachgerechnet wird (PLAN §6.11).
    ust_details: Mapped[list[dict[str, int]] | None] = mapped_column(JSON, nullable=True)
    # Absetzung der bereits berechneten Abschläge (§ 14 Abs. 5 UStG, PLAN §6.1). Bei allen
    # anderen Belegarten null.
    absetzung_netto: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    absetzung_ust: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    # Was der Kunde zu zahlen hat: Brutto minus Absetzung. Bei einer Schlussrechnung ist das der
    # Restbetrag, sonst der Bruttobetrag.
    zahlbetrag: Mapped[int] = mapped_column(Cent, nullable=False, default=0)

    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="entwurf", index=True)
    # Verweis auf den Beleg, der storniert oder korrigiert wird.
    storno_ref: Mapped[int | None] = mapped_column(
        ForeignKey("rechnungen.id"), nullable=True, index=True
    )
    pdf_pfad: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    xml_pfad: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    # SHA-256 über die Belegdaten, gesetzt bei der Festschreibung (PLAN §6.4).
    hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    festgeschrieben_am: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    erstellt_von: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    # Kennzeichnet Belege aus dem Altbestand (PLAN §8, AR-Altbestand).
    quelle_migration: Mapped[str | None] = mapped_column(Text, nullable=True)

    firma: Mapped[Firma] = relationship()
    kunde: Mapped[Kunde] = relationship()
    projekt: Mapped[Projekt | None] = relationship(back_populates="rechnungen")
    positionen: Mapped[list[Rechnungsposition]] = relationship(
        back_populates="rechnung", cascade="all, delete-orphan", order_by="Rechnungsposition.pos"
    )
    absetzungen: Mapped[list[Absetzung]] = relationship(
        back_populates="rechnung",
        cascade="all, delete-orphan",
        order_by="Absetzung.pos",
        foreign_keys="Absetzung.rechnung_id",
    )
    zahlungsplan_positionen: Mapped[list[Zahlungsplanposition]] = relationship(
        back_populates="rechnung"
    )
    storniert_beleg: Mapped[Rechnung | None] = relationship(remote_side=[id])

    @property
    def ist_festgeschrieben(self) -> bool:
        return self.status == "festgeschrieben"

    @property
    def ist_aenderbar(self) -> bool:
        return self.status == "entwurf"

    def __repr__(self) -> str:
        return f"<Rechnung {self.rechnung_nr or 'Entwurf'} {self.art}>"


class Rechnungsposition(OptimistischMixin, ZeitstempelMixin, Base):
    """Eine Position eines Belegs. Der Steuersatz steht je Position (PLAN §6.2).

    ``ust_satz`` ist der Satz in Promille (190 für 19 %, 0 für 0 % nach § 12 Abs. 3 UStG). Promille
    statt Prozent, damit auch Sätze mit Nachkommastelle ohne Gleitkomma darstellbar bleiben.
    """

    __tablename__ = "rechnungspos"
    __table_args__ = (
        UniqueConstraint("rechnung_id", "pos", name="uq_rechnungspos_rechnung_id_pos"),
        nicht_negativ("ust_satz"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rechnung_id: Mapped[int] = mapped_column(
        ForeignKey("rechnungen.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pos: Mapped[int] = mapped_column(Integer, nullable=False)
    bezeichnung: Mapped[str] = mapped_column(Langtext, nullable=False)
    menge: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    einheit: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    ep_netto: Mapped[int] = mapped_column(Cent, nullable=False)
    ust_satz: Mapped[int] = mapped_column(Integer, nullable=False, default=190)
    # Verknüpfung zur Zahlungsplanposition, wenn die Position einen Abschlag berechnet.
    zahlungsplan_id: Mapped[int | None] = mapped_column(
        ForeignKey("zahlungsplan.id"), nullable=True, index=True
    )

    rechnung: Mapped[Rechnung] = relationship(back_populates="positionen")

    def __repr__(self) -> str:
        return f"<Rechnungsposition {self.rechnung_id}/{self.pos}>"


class Absetzung(ZeitstempelMixin, Base):
    """Eine abgesetzte Abschlagsrechnung im Absetzungsblock einer Schlussrechnung.

    § 14 Abs. 5 UStG verlangt, dass die Schlussrechnung jede vorher berechnete Abschlagszahlung
    **einzeln** mit Netto und darauf entfallender Umsatzsteuer absetzt. Fehlt das, ist der
    Steuerausweis unrichtig (§ 14c UStG) – deshalb erzeugt der Leitstand keine Schlussrechnung
    ohne diesen Block (PLAN §6.1).

    Nummer, Datum und Beträge stehen hier **als Kopie**, nicht als Verweis. Der Beleg muss auch
    dann noch zeigen, was auf dem Papier stand, wenn der Abschlag später storniert wird.
    """

    __tablename__ = "rechnung_absetzung"
    __table_args__ = (
        UniqueConstraint("rechnung_id", "abschlag_id", name="uq_rechnung_absetzung_beleg"),
        nicht_negativ("ust_satz"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rechnung_id: Mapped[int] = mapped_column(
        ForeignKey("rechnungen.id", ondelete="CASCADE"), nullable=False, index=True
    )
    abschlag_id: Mapped[int] = mapped_column(
        ForeignKey("rechnungen.id"), nullable=False, index=True
    )
    pos: Mapped[int] = mapped_column(Integer, nullable=False)
    rechnung_nr: Mapped[str] = mapped_column(Kurztext, nullable=False)
    datum: Mapped[date] = mapped_column(Date, nullable=False)
    netto: Mapped[int] = mapped_column(Cent, nullable=False)
    ust_satz: Mapped[int] = mapped_column(Integer, nullable=False)
    ust: Mapped[int] = mapped_column(Cent, nullable=False)

    rechnung: Mapped[Rechnung] = relationship(
        back_populates="absetzungen", foreign_keys=[rechnung_id]
    )
    abschlag: Mapped[Rechnung] = relationship(foreign_keys=[abschlag_id])

    @property
    def brutto(self) -> int:
        return self.netto + self.ust

    def __repr__(self) -> str:
        return f"<Absetzung {self.rechnung_nr}: {self.netto}>"


class Nummernkreis(ZeitstempelMixin, Base):
    """Zähler für lückenlose Nummern je Firma, Kreis und Jahr (PLAN §3).

    Die Vergabe läuft in einer Schreibtransaktion (siehe ``app.dienste.nummernkreise``), damit
    zwei gleichzeitige Festschreibungen nicht dieselbe Nummer bekommen. Kein Optimistic Locking:
    diese Tabelle wird nie von Hand bearbeitet, sondern nur vom Vergabedienst fortgeschrieben.
    """

    __tablename__ = "nummernkreise"
    __table_args__ = (
        UniqueConstraint("firma_id", "kreis", "jahr", name="uq_nummernkreise_firma_id_kreis_jahr"),
        nicht_negativ("letzter_wert"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmen.id"), nullable=False, index=True)
    kreis: Mapped[str] = mapped_column(Kurztext, nullable=False)
    # 0 für Kreise ohne Jahresbezug (Kunden-, Projektnummern laufen jahresübergreifend weiter).
    jahr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    letzter_wert: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Nummernkreis {self.kreis}/{self.jahr}: {self.letzter_wert}>"
