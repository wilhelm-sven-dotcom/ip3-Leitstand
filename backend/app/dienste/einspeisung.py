"""Vergütungs-Controlling der eigenen Bestandsanlagen (PLAN §7 Phase 7).

Die eine Frage: **kommt für den eingespeisten Strom das an, was ankommen müsste?**

Der Leitstand rechnet die Erwartung aus den eigenen Stammdaten – Menge mal Satz – und stellt
sie der Abrechnung des Netzbetreibers gegenüber. Weicht beides ab, hat das genau drei Gründe,
und alle drei kosten Geld:

* der hinterlegte Satz stimmt nicht (falsch abgeschrieben, oder er hat sich geändert),
* die abgerechnete Menge stimmt nicht (Zählerablesung, Zeitraumabgrenzung),
* es fehlt eine Zahlung, die abgerechnet wurde.

**Das ist eine Kontrollrechnung, keine Buchung.** Verbindlich ist die Abrechnung des
Netzbetreibers; der Leitstand rechnet nach und sagt, wo es auseinanderläuft. Er bucht nichts,
stellt nichts fest und ersetzt keine Steuererklärung (PLAN §12).

**Die zwei Vergütungsarten rechnen verschieden** (Entscheidung 51):

* ``einspeisung`` – der Netzbetreiber zahlt den EEG-Satz je kWh. Erwartung = Menge mal Satz.
* ``direktvermarktung`` – Spotmarkterlös und Marktprämie erreichen zusammen den **anzulegenden
  Wert**. Der ist deshalb der richtige Bezugspunkt, auch wenn ihn kein einzelner Zahler
  überweist. Abgezogen wird das Entgelt des Direktvermarkters, sonst läge die Erwartung
  systematisch zu hoch. Wer in der Abrechnung nur die Marktprämie stehen hat, sieht hier eine
  Abweichung, die keine ist – deshalb sagt die Ansicht dazu, worauf sich die Erwartung bezieht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelle.einspeisung import EigeneAnlage, EinspeiseAbrechnung
from app.zeit import heute_ortszeit, monate_rueckwaerts


def erwartung_cent(anlage: EigeneAnlage, kwh: Decimal | float | None) -> int | None:
    """Erwartete Gutschrift für eine Menge, kaufmännisch gerundet auf ganze Cent.

    ``None`` heißt: nicht berechenbar, weil der Satz fehlt. Das ist etwas anderes als 0,00 €
    und wird auch anders angezeigt – eine Null würde als „nichts zu erwarten" gelesen.
    """
    if kwh is None or anlage.verguetung_ct_kwh is None:
        return None
    satz = Decimal(str(anlage.verguetung_ct_kwh))
    if anlage.verguetungsart == "direktvermarktung" and anlage.vermarkter_entgelt_ct_kwh:
        satz -= Decimal(str(anlage.vermarkter_entgelt_ct_kwh))
    # ct/kWh mal kWh ergibt Cent – die Einheit passt ohne Umrechnung (CLAUDE.md Regel 3).
    return int((Decimal(str(kwh)) * satz).quantize(Decimal("1")))


@dataclass
class Monatszeile:
    """Ein Abrechnungsmonat einer Anlage: erwartet, abgerechnet, bezahlt."""

    monat: str
    kwh: Decimal
    erwartet_cent: int | None
    abgerechnet_cent: int
    bezahlt_am: date | None
    quelle_datei: str | None = None

    @property
    def abweichung_cent(self) -> int | None:
        if self.erwartet_cent is None:
            return None
        return self.abgerechnet_cent - self.erwartet_cent

    @property
    def abweichung_promille(self) -> int | None:
        """Abweichung bezogen auf die Erwartung. ``None``, wenn nichts zu erwarten war."""
        if self.erwartet_cent is None or self.erwartet_cent == 0:
            return None
        return round(self.abweichung_cent * 1000 / self.erwartet_cent)

    @property
    def offen(self) -> bool:
        return self.bezahlt_am is None and self.abgerechnet_cent != 0


@dataclass
class Anlagenbild:
    """Eine Anlage mit ihren Monaten und dem, was daran auffällt."""

    anlage_id: int
    bezeichnung: str
    verguetungsart: str
    verguetung_ct_kwh: Decimal | None
    monate: list[Monatszeile] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    @property
    def kwh_gesamt(self) -> Decimal:
        return sum((zeile.kwh for zeile in self.monate), Decimal(0))

    @property
    def erwartet_cent(self) -> int:
        return sum(z.erwartet_cent or 0 for z in self.monate)

    @property
    def abgerechnet_cent(self) -> int:
        return sum(z.abgerechnet_cent for z in self.monate)

    @property
    def offen_cent(self) -> int:
        return sum(z.abgerechnet_cent for z in self.monate if z.offen)


@dataclass
class Bild:
    """Alle Anlagen eines Zeitraums samt Summen."""

    von: str
    bis: str
    anlagen: list[Anlagenbild] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    @property
    def erwartet_cent(self) -> int:
        return sum(a.erwartet_cent for a in self.anlagen)

    @property
    def abgerechnet_cent(self) -> int:
        return sum(a.abgerechnet_cent for a in self.anlagen)

    @property
    def offen_cent(self) -> int:
        return sum(a.offen_cent for a in self.anlagen)


def bild(
    sitzung: Session,
    *,
    monate: int = 12,
    toleranz_promille: int = 20,
    zahlungsziel_tage: int = 45,
    bis: str | None = None,
    heute: date | None = None,
    nur_aktive: bool = True,
) -> Bild:
    """Soll-Ist-Bild über die letzten ``monate`` Abrechnungsmonate."""
    stichtag = heute or heute_ortszeit()
    letzter = bis or f"{stichtag:%Y-%m}"
    fenster = monate_rueckwaerts(letzter, monate)
    erster = fenster[0]

    abfrage = select(EigeneAnlage).order_by(EigeneAnlage.bezeichnung)
    if nur_aktive:
        abfrage = abfrage.where(EigeneAnlage.aktiv.is_(True))
    anlagen = list(sitzung.execute(abfrage).scalars())

    ergebnis = Bild(von=erster, bis=letzter)
    if not anlagen:
        ergebnis.hinweise.append(
            "Es ist keine eigene Anlage erfasst. Ohne sie lässt sich keine Abrechnung zuordnen."
        )
        return ergebnis

    abrechnungen = list(
        sitzung.execute(
            select(EinspeiseAbrechnung).where(
                EinspeiseAbrechnung.anlage_id.in_([a.id for a in anlagen]),
                EinspeiseAbrechnung.monat >= erster,
                EinspeiseAbrechnung.monat <= letzter,
            )
        ).scalars()
    )
    je_anlage: dict[int, dict[str, EinspeiseAbrechnung]] = {}
    for eintrag in abrechnungen:
        je_anlage.setdefault(eintrag.anlage_id, {})[eintrag.monat] = eintrag

    ohne_satz: list[str] = []
    for anlage in anlagen:
        teil = Anlagenbild(
            anlage_id=anlage.id,
            bezeichnung=anlage.bezeichnung,
            verguetungsart=anlage.verguetungsart,
            verguetung_ct_kwh=(
                Decimal(str(anlage.verguetung_ct_kwh))
                if anlage.verguetung_ct_kwh is not None
                else None
            ),
        )
        vorhanden = je_anlage.get(anlage.id, {})
        for monat in fenster:
            eintrag = vorhanden.get(monat)
            if eintrag is None:
                continue
            teil.monate.append(
                Monatszeile(
                    monat=monat,
                    kwh=Decimal(str(eintrag.kwh)),
                    erwartet_cent=erwartung_cent(anlage, eintrag.kwh),
                    abgerechnet_cent=eintrag.betrag_cent,
                    bezahlt_am=eintrag.bezahlt_am,
                    quelle_datei=eintrag.quelle_datei,
                )
            )

        teil.hinweise = _hinweise(
            anlage, teil, fenster, stichtag, toleranz_promille, zahlungsziel_tage
        )
        if anlage.verguetung_ct_kwh is None:
            ohne_satz.append(anlage.bezeichnung)
        ergebnis.anlagen.append(teil)

    if ohne_satz:
        ergebnis.hinweise.append(
            "Ohne Vergütungssatz gibt es keine Erwartung, nur die Abrechnung: "
            + ", ".join(ohne_satz)
            + "."
        )
    return ergebnis


def _hinweise(
    anlage: EigeneAnlage,
    teil: Anlagenbild,
    fenster: list[str],
    heute: date,
    toleranz_promille: int,
    zahlungsziel_tage: int,
) -> list[str]:
    """Was an dieser Anlage auffällt – in Sätzen, nicht als Fehlercode."""
    hinweise: list[str] = []

    # Fehlende Monate: erst ab der Inbetriebnahme und erst, wenn der Monat vorbei ist. Ein
    # laufender Monat ist nicht abgerechnet, sondern noch nicht dran.
    letzter_geschlossener = f"{(heute.replace(day=1) - timedelta(days=1)):%Y-%m}"
    beginn = f"{anlage.inbetriebnahme:%Y-%m}" if anlage.inbetriebnahme else fenster[0]
    erwartete_monate = [m for m in fenster if beginn <= m <= letzter_geschlossener]
    gefunden = {zeile.monat for zeile in teil.monate}
    fehlend = [m for m in erwartete_monate if m not in gefunden]
    if fehlend:
        hinweise.append(
            f"Für {_monatswort(len(fehlend))} liegt keine Abrechnung vor: "
            + ", ".join(_monat_text(m) for m in fehlend[:6])
            + ("…" if len(fehlend) > 6 else "")
            + "."
        )

    auffaellig = [
        zeile
        for zeile in teil.monate
        if zeile.abweichung_promille is not None
        and abs(zeile.abweichung_promille) > toleranz_promille
    ]
    if auffaellig:
        hinweise.append(
            f"{_monatswort(len(auffaellig))} weichen um mehr als "
            f"{toleranz_promille / 10:.0f} % von der Erwartung ab: "
            + ", ".join(_monat_text(z.monat) for z in auffaellig[:6])
            + ("…" if len(auffaellig) > 6 else "")
            + "."
        )

    grenze = heute - timedelta(days=zahlungsziel_tage)
    ueberfaellig = [
        zeile for zeile in teil.monate if zeile.offen and _monatsende(zeile.monat) < grenze
    ]
    if ueberfaellig:
        hinweise.append(
            f"{_monatswort(len(ueberfaellig))} sind abgerechnet, aber seit mehr als "
            f"{zahlungsziel_tage} Tagen nicht als bezahlt vermerkt."
        )
    return hinweise


def _monatswort(anzahl: int) -> str:
    """„1 Monat", „3 Monate" – Zahl und Wort im gleichen Numerus."""
    return "1 Monat" if anzahl == 1 else f"{anzahl} Monate"


def _monat_text(monat: str) -> str:
    """``'2026-07'`` als ``'07/2026'`` – so steht es auf der Abrechnung."""
    jahr, _, teil = monat.partition("-")
    return f"{teil}/{jahr}"


def _monatsende(monat: str) -> date:
    jahr, teil = int(monat[:4]), int(monat[5:7])
    if teil == 12:
        return date(jahr, 12, 31)
    return date(jahr, teil + 1, 1) - timedelta(days=1)
