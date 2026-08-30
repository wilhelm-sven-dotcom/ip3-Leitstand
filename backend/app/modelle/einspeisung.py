"""Eigene Bestandsanlagen und ihre Einspeisevergütung (PLAN §7 Phase 7).

Hier geht es um die Anlagen, die **ip³ selbst betreibt** – nicht um die, die ip³ für Kunden
baut. Die stehen in :mod:`app.modelle.anlagen` und sind etwas anderes: Bezugspunkt für Service,
Wartung und Gewährleistung, immer mit einem Kunden daran. Eine eigene Anlage hat keinen Kunden,
keine Gewährleistung und keinen Wartungsvertrag, dafür einen Vergütungssatz, eine Zählernummer
und einen Netzbetreiber. Zwei Tabellen statt einer Tabelle mit halb leeren Spalten
(Entscheidung 52).

**Die Frage, die beantwortet wird:** kommt für den eingespeisten Strom das an, was ankommen
müsste? Der Leitstand rechnet die Erwartung aus den eigenen Stammdaten und stellt sie der
Abrechnung des Netzbetreibers gegenüber. Weicht beides ab, liegt es an einem falschen Satz,
einem falschen Zählerstand oder einer fehlenden Zahlung – alle drei kosten Geld und fallen
sonst erst beim Jahresabschluss auf.

**Was der Leitstand nicht tut:** er rechnet die Vergütung nicht *fest*. Verbindlich ist die
Abrechnung des Netzbetreibers; die Erwartung ist eine Kontrollrechnung und ausdrücklich keine
Buchung (PLAN §12).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
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
    UtcDateTime,
    ZeitstempelMixin,
)
from app.modelle.pruefungen import in_werten, monat_check, nicht_negativ

# Wie eine Anlage vergütet wird. Sven führt beide Formen nebeneinander (Entscheidung 51),
# deshalb hängt das Kennzeichen an der einzelnen Anlage und nicht an der Konfiguration.
VERGUETUNGSARTEN = ("einspeisung", "direktvermarktung")


class EigeneAnlage(OptimistischMixin, ZeitstempelMixin, Base):
    """Eine Anlage, die ip³ selbst betreibt.

    ``verguetung_ct_kwh`` trägt je nach Art zwei verschiedene Dinge, und das ist der Grund für
    die zwei Kommentarzeilen darunter statt zweier Spalten:

    * bei ``einspeisung`` den **Vergütungssatz** nach EEG, den der Netzbetreiber zahlt;
    * bei ``direktvermarktung`` den **anzulegenden Wert**. Erlös aus Spotmarkt plus Marktprämie
      erreichen zusammen diesen Wert – deshalb ist er der richtige Bezugspunkt für die
      Erwartung, auch wenn er nicht der Betrag ist, den ein einzelner Zahler überweist.

    Das Entgelt des Direktvermarkters wird abgezogen, sonst läge die Erwartung systematisch zu
    hoch. Bei ``einspeisung`` bleibt es leer.
    """

    __tablename__ = "eigene_anlagen"
    __table_args__ = (
        UniqueConstraint("bezeichnung", name="uq_eigene_anlagen_bezeichnung"),
        in_werten("verguetungsart", VERGUETUNGSARTEN),
        nicht_negativ("pv_kwp"),
        nicht_negativ("speicher_kwh"),
        nicht_negativ("verguetung_ct_kwh"),
        nicht_negativ("vermarkter_entgelt_ct_kwh"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bezeichnung: Mapped[str] = mapped_column(Text, nullable=False)
    standort: Mapped[str | None] = mapped_column(Text, nullable=True)
    pv_kwp: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    speicher_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    inbetriebnahme: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    verguetungsart: Mapped[str] = mapped_column(
        Kurztext, nullable=False, default="einspeisung", index=True
    )
    # Vier Nachkommastellen, weil Vergütungssätze in Zehntel- und Hundertstelcent angegeben
    # werden (8,11 ct/kWh) und ein gerundeter Satz über ein Jahr sichtbar danebenliegt.
    verguetung_ct_kwh: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    vermarkter_entgelt_ct_kwh: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    # Schlüssel, über die eine Zeile der Netzbetreiber-Abrechnung ihrer Anlage zugeordnet wird.
    zaehler_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    mastr_nr: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    netzbetreiber: Mapped[str | None] = mapped_column(Text, nullable=True)
    vermarkter: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aus dem Betrieb genommene Anlagen bleiben stehen (CLAUDE.md Regel 5); sie zählen nur
    # nicht mehr in der Erwartung und melden keinen fehlenden Monat mehr.
    aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    def __repr__(self) -> str:
        return f"<EigeneAnlage {self.bezeichnung} {self.verguetungsart}>"


class EinspeiseAbrechnung(OptimistischMixin, ZeitstempelMixin, Base):
    """Eine Abrechnungszeile des Netzbetreibers: was er für einen Monat abgerechnet hat.

    Der Monat ist zusammen mit der Anlage eindeutig. Ein erneuter Import derselben Abrechnung
    aktualisiert die Zeile also, statt eine zweite anzulegen – dieselbe Regel wie bei den
    DATEV-Monatsimporten (PLAN §7 Phase 4).

    ``bezahlt_am`` bleibt von Hand zu setzen. Die Abrechnung sagt, was der Netzbetreiber zahlen
    **will**; ob das Geld angekommen ist, weiß nur der Kontoauszug, und den liest der Leitstand
    nicht (PLAN §2: alle externen Quellen werden ausschließlich gelesen, ein Bankzugang gehört
    nicht dazu).
    """

    __tablename__ = "einspeise_abrechnungen"
    __table_args__ = (
        UniqueConstraint("anlage_id", "monat", name="uq_einspeise_abrechnungen_anlage_monat"),
        monat_check("monat"),
        nicht_negativ("kwh"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anlage_id: Mapped[int] = mapped_column(
        ForeignKey("eigene_anlagen.id", ondelete="CASCADE"), nullable=False, index=True
    )
    monat: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    kwh: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    # Was der Netzbetreiber abrechnet, netto in Cent. Bewusst ohne Vorzeichenprüfung: eine
    # Korrekturabrechnung für einen Vormonat kann negativ sein (CLAUDE.md Regel 3).
    betrag_cent: Mapped[int] = mapped_column(Cent, nullable=False, default=0)
    bezahlt_am: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    quelle_datei: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    eingelesen_am: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    bemerkung: Mapped[str | None] = mapped_column(Langtext, nullable=True)

    anlage: Mapped[EigeneAnlage] = relationship()

    def __repr__(self) -> str:
        return f"<EinspeiseAbrechnung Anlage {self.anlage_id} {self.monat}>"
