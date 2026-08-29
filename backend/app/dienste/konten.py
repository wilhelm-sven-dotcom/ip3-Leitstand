"""Zuordnung von Sachkonten zu Kostenblöcken (PLAN §5, §8).

Die Summen- und Saldenliste bringt Konten, das Cockpit braucht Blöcke. Dazwischen steht
``konten_mapping``: Bereiche von-bis, jeder auf einen Block aus :data:`KOSTENBLOECKE`.

Zwei Festlegungen, die man kennen muss:

* **Der engste Bereich gewinnt.** Trägt die Zuordnung 4000-4999 auf ``sonstiges`` und
  4100-4199 auf ``personal``, dann zählt Konto 4120 als Personal. So lässt sich ein Sonderfall
  eintragen, ohne den umgebenden Bereich zu zerlegen.
* **Ohne Treffer bleibt der Block leer** (``None``). Das ist kein Fehler, sondern ein
  Pflegehinweis: das Konto erscheint in der Nachpflegeliste und geht so lange nicht in den
  Fixkostenblock ein. Lieber ein sichtbar fehlender Betrag als ein still falsch einsortierter.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelle import DatevSaldo, KontenMapping

# 'neutral' ist der Block für alles, was ausdrücklich *nicht* in den Fixkostenblock gehört
# (durchlaufende Posten, Verrechnungskonten). Er wird zugeordnet und trotzdem nicht gerechnet –
# das ist der Unterschied zu einem Konto ohne Zuordnung, das noch niemand angesehen hat.
NICHT_GERECHNET = ("neutral",)


def konto_als_zahl(konto: str) -> int | None:
    """Kontonummer als Zahl, oder ``None``. Führende Nullen und Leerzeichen stören nicht."""
    gestrippt = konto.strip()
    return int(gestrippt) if gestrippt.isdigit() else None


@dataclass(frozen=True)
class Bereich:
    von: int
    bis: int
    block: str

    @property
    def breite(self) -> int:
        return self.bis - self.von


def bereiche_laden(sitzung: Session) -> list[Bereich]:
    """Alle Zuordnungen als Zahlenbereiche, engster zuerst."""
    bereiche: list[Bereich] = []
    for eintrag in sitzung.scalars(select(KontenMapping)):
        von = konto_als_zahl(eintrag.konto_von)
        bis = konto_als_zahl(eintrag.konto_bis)
        if von is None or bis is None:
            # Nicht-numerische Kontenbereiche kommen über die Maske nicht herein; ein per Hand
            # eingetragener Unsinn soll den Import trotzdem nicht anhalten.
            continue
        bereiche.append(Bereich(von=von, bis=bis, block=eintrag.block))
    bereiche.sort(key=lambda b: (b.breite, b.von))
    return bereiche


def block_fuer(konto: str, bereiche: list[Bereich]) -> str | None:
    """Block des Kontos, oder ``None`` wenn keine Zuordnung greift."""
    nummer = konto_als_zahl(konto)
    if nummer is None:
        return None
    for bereich in bereiche:
        if bereich.von <= nummer <= bereich.bis:
            return bereich.block
    return None


def salden_neu_zuordnen(sitzung: Session, *, monat: str | None = None) -> int:
    """Blockzuordnung der Salden neu setzen. Gibt die Anzahl geänderter Zeilen zurück.

    Wird nach jeder Änderung an der Kontenzuordnung gebraucht: ohne sie behielten schon
    eingelesene Monate ihre alte Einordnung, und das Cockpit zeigte für zwei Monate
    unterschiedliche Blöcke bei gleichem Konto.
    """
    bereiche = bereiche_laden(sitzung)
    abfrage = select(DatevSaldo)
    if monat is not None:
        abfrage = abfrage.where(DatevSaldo.monat == monat)

    geaendert = 0
    for saldo in sitzung.scalars(abfrage):
        neu = block_fuer(saldo.konto, bereiche)
        if neu != saldo.block:
            saldo.block = neu
            geaendert += 1
    sitzung.flush()
    return geaendert


@dataclass
class OffenesKonto:
    """Ein Konto aus der SuSa, für das keine Zuordnung greift."""

    konto: str
    bezeichnung: str | None
    summe_cent: int
    monate: int


def unzugeordnete(sitzung: Session, *, jahr: int | None = None) -> list[OffenesKonto]:
    """Konten ohne Blockzuordnung, das größte zuerst.

    Sortiert nach Betrag und nicht nach Kontonummer: wer die Liste abarbeitet, soll mit dem
    Konto anfangen, das im Cockpit am meisten ausmacht.
    """
    abfrage = (
        select(
            DatevSaldo.konto,
            func.max(DatevSaldo.bezeichnung),
            func.sum(DatevSaldo.saldo),
            func.count(),
        )
        .where(DatevSaldo.block.is_(None))
        .group_by(DatevSaldo.konto)
    )
    if jahr is not None:
        abfrage = abfrage.where(DatevSaldo.monat.startswith(f"{jahr}-"))

    offene = [
        OffenesKonto(
            konto=konto,
            bezeichnung=bezeichnung,
            summe_cent=int(summe or 0),
            monate=anzahl,
        )
        for konto, bezeichnung, summe, anzahl in sitzung.execute(abfrage).all()
    ]
    offene.sort(key=lambda k: (-abs(k.summe_cent), k.konto))
    return offene
