"""Normalisierung der Freitexte aus den Bestandsdateien (PLAN §9).

Die Auftragsliste führt Kunde und Rechnungsart in einer einzigen Spalte als Freitext, über
Jahre von mehreren Personen gepflegt. Entsprechend gibt es Schreibvarianten: ``3 .Abschlag``
mit Leerzeichen vor dem Punkt, ``Schlussrechnung - PV`` neben ``Schlussrechnung PV``,
``100 %`` neben ``100%``. Dieses Modul bringt sie auf die Werte des Datenmodells und ist die
einzige Stelle, an der geraten wird – überall sonst arbeitet die Migration mit klaren Werten.

Was nicht erkannt wird, verschwindet nicht: der Leser erzeugt einen Befund mit Zeilennummer,
und die Zeile landet in der Zuordnungsmaske.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Reihenfolge zählt: 'Schlussrechnung' muss vor 'Rechnung' geprüft werden, sonst gewinnt das
# kürzere Wort. Ebenso '100 %' vor dem allgemeinen 'Rechnung'.
_ARTEN: tuple[tuple[str, str], ...] = (
    (r"schlussrechnung", "schluss"),
    (r"teilrechnung", "abschlag"),
    (r"abschlag", "abschlag"),
    (r"anzahlung", "abschlag"),
    (r"100\s*%", "einmal"),
    (r"rechnung", "einmal"),
)

# Gewerk aus dem Text. 'ls' ist die Ladestation (Wallbox) nach PLAN §5.
_GEWERKE: tuple[tuple[str, str], ...] = (
    (r"\bpv\b|photovoltaik|\bmodule?\b", "pv"),
    (r"speicher|batterie|\bbess\b", "speicher"),
    (r"wallbox|ladestation|ladepunkt", "ls"),
    (r"service|wartung|st(ö|oe)rung", "service"),
)

# Wörter, die eine Rechnungsart einleiten. Der Kundenname endet davor.
_SCHLAGWORTE = re.compile(
    r"(?:\d\s*\.?\s*)?(?:abschlag|teilrechnung|schlussrechnung|anzahlung|rechnung|100\s*%)",
    re.IGNORECASE,
)

_POSITIONSNUMMER = re.compile(r"(\d)\s*\.\s*(?=\s*(?:abschlag|teilrechnung))", re.IGNORECASE)


@dataclass(frozen=True)
class Rechnungsart:
    """Aufgelöste Rechnungsart einer Zeile der Auftragsliste."""

    art: str | None  # 'abschlag' | 'schluss' | 'einmal'
    nummer: int | None  # 1..5 bei Abschlägen, sonst None
    gewerk: str | None  # 'pv' | 'speicher' | 'ls' | 'service'
    text: str  # Fundstelle im Original, für die Bezeichnung der Position

    @property
    def erkannt(self) -> bool:
        return self.art is not None


def ohne_umlaute(text: str) -> str:
    """Für Vergleiche: Umlaute und ß auflösen, Zeichen zerlegen und zusammenziehen."""
    ersetzt = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ß", "ss")
    )
    zerlegt = unicodedata.normalize("NFKD", ersetzt)
    return "".join(z for z in zerlegt if not unicodedata.combining(z))


def vergleichsform(text: str) -> str:
    """Kleinschreibung ohne Umlaute, Klammerzusätze und Sonderzeichen.

    Grundlage für den Abgleich zwischen den beiden Dateien. Klammerzusätze fallen weg, weil die
    Teamliste dort Hinweise wie '(ip³ Ing.)' führt, die in der Auftragsliste fehlen.
    """
    ohne_klammern = re.sub(r"\(.*?\)", " ", text)
    einfach = ohne_umlaute(ohne_klammern).lower()
    return re.sub(r"[^a-z0-9]+", " ", einfach).strip()


def rechnungsart_lesen(freitext: str) -> tuple[str, Rechnungsart]:
    """Trennt den Kundenteil von der Rechnungsart.

    Rückgabe ist ``(kundenteil, rechnungsart)``. Findet sich kein Schlagwort, ist der ganze Text
    der Kundenteil und ``Rechnungsart.erkannt`` ist ``False`` – das sind in der Auftragsliste die
    Projektsummen ohne Zahlungsplan (PLAN §9).
    """
    text = re.sub(r"\s+", " ", freitext).strip()
    treffer = _SCHLAGWORTE.search(text)
    if treffer is None:
        return text, Rechnungsart(None, None, _gewerk(text), "")

    kundenteil = text[: treffer.start()].strip().rstrip("-–/ ").strip()
    artteil = text[treffer.start() :].strip()
    # Ein Kundenteil, der nur aus Trennzeichen besteht, hilft nicht weiter: dann steht die
    # Rechnungsart am Anfang und der Name fehlt in dieser Zeile.
    return kundenteil, Rechnungsart(_art(artteil), _nummer(artteil), _gewerk(text), artteil)


def _art(artteil: str) -> str | None:
    for muster, wert in _ARTEN:
        if re.search(muster, artteil, re.IGNORECASE):
            return wert
    return None


def _nummer(artteil: str) -> int | None:
    treffer = _POSITIONSNUMMER.search(artteil)
    if treffer:
        return int(treffer.group(1))
    # '1. Abschlag' ohne Leerzeichen vor dem Punkt deckt der Ausdruck oben ab; hier bleibt der
    # Fall 'Abschlag 2' übrig.
    nachgestellt = re.search(r"abschlag\s*(\d)\b", artteil, re.IGNORECASE)
    return int(nachgestellt.group(1)) if nachgestellt else None


def _gewerk(text: str) -> str | None:
    for muster, wert in _GEWERKE:
        if re.search(muster, text, re.IGNORECASE):
            return wert
    return None


def kunde_und_ort(kundenteil: str) -> tuple[str, str | None]:
    """Zerlegt 'Wolfram, Meerbodenreuth' in Name und Ort.

    Getrennt wird am **letzten** Komma: 'Kneidl Corinna und Bernd, Weiden' hat den Ort hinten,
    und Namen mit Komma davor kommen vor. Ohne Komma gibt es keinen Ort – dann steht der ganze
    Text im Namen, was bei Firmen wie 'Ärztehaus Weiden' richtig ist.
    """
    text = re.sub(r"\s+", " ", kundenteil).strip()
    if "," not in text:
        return text, None
    name, _, ort = text.rpartition(",")
    name, ort = name.strip(), ort.strip()
    if not name or not ort:
        return text, None
    return name, ort
