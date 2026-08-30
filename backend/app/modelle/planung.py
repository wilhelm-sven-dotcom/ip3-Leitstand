"""Kapazität und Angebotspipeline (PLAN §5, §7 Phase 7).

Zwei Tabellen, die beide dieselbe Frage von zwei Seiten stellen: **Reicht es?**

* ``Mitarbeiter`` trägt die Wochenstunden, die tatsächlich zur Verfügung stehen. Sie stehen in
  der Datenbank und nicht in der ``config.toml``, weil sie sich häufiger ändern als eine
  Konfiguration und weil sie gepflegt werden sollen, ohne dass jemand auf den Host muss
  (Entscheidung 40).
* ``Angebot`` trägt die Pipeline: was angeboten ist, mit welcher Wahrscheinlichkeit es kommt und
  wann. **Getrennt vom beauftragten Umsatz** – ein gewichtetes Angebot ist kein Auftrag, und
  beides in einer Zahl wäre die gefährlichste Kennzahl des ganzen Werkzeugs.

Die Wahrscheinlichkeit steht wie alle Anteile im Leitstand in **Promille** (600 = 60 %), damit
ohne Gleitkomma gerechnet wird (CLAUDE.md Regel 3 sinngemäß).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
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
from app.modelle.pruefungen import in_werten, in_werten_oder_leer, monat_check, nicht_negativ

ANGEBOT_STATUS = ("offen", "gewonnen", "verloren")

# Satzgruppen wie in [stundensaetze.saetze] der config.toml. Hier als Prüfliste, damit ein
# Tippfehler in der Mitarbeitermaske nicht als eigenes Gewerk in der Kapazität auftaucht.
SATZGRUPPEN = ("monteur", "obermonteur", "elektriker", "planung")


class Mitarbeiter(OptimistischMixin, ZeitstempelMixin, Base):
    """Wer wie viele Stunden je Woche zur Verfügung steht (PLAN §7 Phase 7).

    Der Name muss dem in TimeTac entsprechen – nur dann lassen sich geplante und gebuchte
    Stunden derselben Person zuordnen. Weicht er ab, meldet die Kapazitätsansicht das, statt
    still danebenzuliegen.

    **Urlaub und Krankheit sind nicht abgebildet.** Die Wochenstunden sind die Regelarbeitszeit;
    eine Abwesenheitsplanung wäre ein eigenes Thema und gehört nicht in ein Werkzeug, das
    ausdrücklich keine Personalverwaltung ist (PLAN §12). Die Ansicht sagt das dazu, damit
    niemand die Zahl für eine Zusage hält.
    """

    __tablename__ = "mitarbeiter"
    __table_args__ = (
        UniqueConstraint("name", name="uq_mitarbeiter_name"),
        in_werten_oder_leer("satzgruppe", SATZGRUPPEN),
        nicht_negativ("wochenstunden"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Schreibweise wie in TimeTac, üblicherweise „Nachname, Vorname".
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Satzgruppe aus [stundensaetze.saetze]; hier nur zur Gliederung der Kapazität nach Gewerk.
    # Der Verrechnungssatz selbst bleibt in der config.toml (Phase 4, unverändert).
    satzgruppe: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    wochenstunden: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Eintritt und Austritt begrenzen die Kapazität zeitlich: wer im Mai anfängt, zählt nicht
    # schon im März. NULL heißt „schon immer" bzw. „bis auf Weiteres".
    von: Mapped[date | None] = mapped_column(Date, nullable=True)
    bis: Mapped[date | None] = mapped_column(Date, nullable=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    def __repr__(self) -> str:
        return f"<Mitarbeiter {self.name} {self.wochenstunden} h/Woche>"


class Angebot(OptimistischMixin, ZeitstempelMixin, Base):
    """Ein Angebot in der Pipeline (PLAN §7 Phase 7).

    ``kunde_id`` darf fehlen: ein Angebot geht oft an einen Interessenten, der noch kein Kunde
    im Sinne der Stammdaten ist. Dann trägt ``kunde_name`` den Namen aus dem Angebots-Tool. Wird
    der Auftrag erteilt, entsteht ein Projekt und ``projekt_id`` verweist darauf – ab dann zählt
    der Wert im Auftragsbestand und **nicht mehr** in der Pipeline.
    """

    __tablename__ = "angebote"
    __table_args__ = (
        monat_check("erwarteter_monat"),
        in_werten("status", ANGEBOT_STATUS),
        # Geldbetrag, aber hier ausnahmsweise nicht negativ: ein Angebot über einen Minusbetrag
        # gibt es nicht, und ein Vorzeichenfehler im Import würde die Pipeline kleinrechnen.
        nicht_negativ("summe_netto"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nummer aus dem Angebots-Tool. Eindeutig, wenn vorhanden: sie ist der Schlüssel, an dem ein
    # erneuter Import dieselbe Zeile wiedererkennt, statt eine zweite anzulegen.
    angebot_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True, unique=True)
    kunde_id: Mapped[int | None] = mapped_column(ForeignKey("kunden.id"), nullable=True, index=True)
    kunde_name: Mapped[str] = mapped_column(Text, nullable=False)
    bezeichnung: Mapped[str | None] = mapped_column(Text, nullable=True)
    summe_netto: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    # 0 bis 1000 Promille. Die Grenzen prüft die Eingabe, nicht die Datenbank: eine Bandbreite
    # ist keine Bedingung, an der ein Import scheitern soll.
    wahrscheinlichkeit_promille: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Monat, in dem der Auftrag erwartet wird. NULL heißt „unterminiert" und zählt wie im
    # Forecast des Zahlungsplans nicht in den Monatsverlauf.
    erwarteter_monat: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="offen", index=True)
    datum: Mapped[date | None] = mapped_column(Date, nullable=True)
    projekt_id: Mapped[int | None] = mapped_column(
        ForeignKey("projekte.id"), nullable=True, index=True
    )
    quelle_datei: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    eingelesen_am: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    kunde = relationship("Kunde")
    projekt = relationship("Projekt")

    @property
    def gewichtet_cent(self) -> int:
        """Angebotssumme mal Wahrscheinlichkeit, kaufmännisch gerundet auf ganze Cent."""
        return (self.summe_netto * self.wahrscheinlichkeit_promille + 500) // 1000

    def __repr__(self) -> str:
        return f"<Angebot {self.angebot_nr or self.id} {self.kunde_name}>"
