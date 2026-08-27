"""Geldrechnung in Cent (PLAN §5, §6.10, §6.11).

Alle Beträge sind ganze Cent. Gleitkomma ist für Geld untauglich: 0,1 + 0,2 ergibt dort nicht 0,3,
und aus solchen Resten entstehen Rechnungen, deren Positionssumme nicht zur Belegsumme passt.

Zwei Regeln, die hier ihren einzigen Platz haben:

* **Kaufmännische Rundung** (0,5 wird aufgerundet, bei negativen Beträgen symmetrisch abgerundet).
  Pythons ``round`` rundet zur nächsten geraden Zahl und ist damit für Belege falsch.
* **Umsatzsteuer je Steuersatz auf die Nettosumme des Belegs**, nicht je Position aufsummiert.
  Positionsweise gerundet weichen Summe und Belegsumme um Cent-Beträge ab, und genau darauf
  schaut eine Prüfung.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

# Steuersätze als Prozentwert in ganzen Zehnteln, damit auch 13b (0 %) und künftige Sätze passen.
CENT_JE_EURO = 100


def kaufmaennisch_runden(wert: Decimal | float | int) -> int:
    """Auf ganze Einheiten kaufmännisch runden (0,5 vom Nullpunkt weg)."""
    betrag = Decimal(str(wert))
    return int(betrag.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def euro_nach_cent(betrag: Decimal | float | int | str) -> int:
    """Eurobetrag in Cent umrechnen, kaufmännisch gerundet."""
    return kaufmaennisch_runden(Decimal(str(betrag)) * CENT_JE_EURO)


def cent_nach_euro(cent: int) -> Decimal:
    """Cent als Dezimalzahl in Euro – nur für Anzeige und Export, nicht zum Weiterrechnen."""
    return (Decimal(cent) / CENT_JE_EURO).quantize(Decimal("0.01"))


def formatiere_euro(cent: int, mit_zeichen: bool = True) -> str:
    """Deutsche Schreibweise: ``1.250,00 €`` mit geschütztem Leerzeichen (PLAN §6.10)."""
    vorzeichen = "-" if cent < 0 else ""
    ganze, rest = divmod(abs(cent), CENT_JE_EURO)
    mit_punkten = f"{ganze:,}".replace(",", ".")
    text = f"{vorzeichen}{mit_punkten},{rest:02d}"
    return f"{text} €" if mit_zeichen else text


def ust_betrag(netto_cent: int, satz_promille: int) -> int:
    """Umsatzsteuer auf einen Nettobetrag; ``satz_promille`` ist der Satz in Promille.

    19 % sind 190, 7 % sind 70, 0 % sind 0. Promille statt Prozent, damit auch 8,5 % ohne
    Gleitkomma darstellbar wäre.
    """
    return kaufmaennisch_runden(Decimal(netto_cent) * Decimal(satz_promille) / Decimal(1000))


def steuer_je_satz(positionen: Iterable[tuple[int, int]]) -> dict[int, tuple[int, int]]:
    """Netto- und Steuerbeträge je Steuersatz für einen Beleg.

    ``positionen`` sind Paare ``(netto_cent, satz_promille)``. Rückgabe je Satz:
    ``(netto_summe, steuer_summe)`` – die Steuer wird **einmal** auf die Nettosumme des Satzes
    gerechnet (PLAN §6.11), nicht je Position.
    """
    netto_summen: dict[int, int] = defaultdict(int)
    for netto, satz in positionen:
        netto_summen[satz] += netto
    return {satz: (netto, ust_betrag(netto, satz)) for satz, netto in sorted(netto_summen.items())}


def belegsumme(positionen: Iterable[tuple[int, int]]) -> tuple[int, int, int]:
    """Netto, Umsatzsteuer und Brutto eines Belegs aus ``(netto_cent, satz_promille)``-Paaren."""
    je_satz = steuer_je_satz(positionen)
    netto = sum(netto for netto, _ in je_satz.values())
    steuer = sum(steuer for _, steuer in je_satz.values())
    return netto, steuer, netto + steuer


def position_netto(menge: Decimal | float | int | str, ep_cent: int) -> int:
    """Positionsnetto aus Menge und Einzelpreis in Cent, kaufmännisch gerundet."""
    return kaufmaennisch_runden(Decimal(str(menge)) * Decimal(ep_cent))
