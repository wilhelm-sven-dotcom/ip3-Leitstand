"""Befunde: was ein Import nicht sicher deuten konnte (PLAN §8).

Ein Import bricht nicht mitten in der Datei ab. Jeder Wert, der sich nicht sicher deuten lässt,
wird zu einem :class:`Befund` mit Herkunft, Originalinhalt und Meldung; die Zeile wird
übersprungen oder mit einer Lücke übernommen, und der Lauf geht weiter. Wer abbricht, sieht
nicht, wie viel in Ordnung war – und liest die Datei beim nächsten Versuch von vorn.

Die Befunde stehen anschließend in der Vorschau und im Importprotokoll (``importlaeufe``), und
sie entscheiden über den Laufstatus: ein Lauf, der Zeilen liegen gelassen hat, darf auf der
Startseite nicht wie ein glatter Erfolg aussehen.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# 'warnung' heißt: eine Angabe fehlt oder ist unlesbar, jemand muss nachsehen.
# 'hinweis' heißt: es wurde bewusst anders verfahren, zur Kenntnis.
SCHWEREN = ("warnung", "hinweis")


@dataclass(frozen=True)
class Befund:
    """Ein Wert, den der Leser nicht sicher deuten konnte.

    ``spalte`` trägt bei Tabellendateien den Spaltenbuchstaben, bei Textdateien den Feldnamen
    und bei Schnittstellen den Feldpfad der Antwort – immer das, womit sich die Stelle in der
    Quelle wiederfinden lässt. ``zeile`` ist bei zeilenlosen Quellen 0.
    """

    datei: str
    zeile: int
    spalte: str
    wert: str
    meldung: str
    schwere: str = "warnung"

    def als_text(self) -> str:
        return f"{self.datei} {self.spalte}{self.zeile}: {self.meldung} (Inhalt: {self.wert!r})"


def als_liste(befunde: Iterable[Befund]) -> list[dict[str, object]]:
    """Befunde für das Importprotokoll und die API-Antwort."""
    return [
        {
            "datei": b.datei,
            "zeile": b.zeile,
            "spalte": b.spalte,
            "wert": b.wert,
            "meldung": b.meldung,
            "schwere": b.schwere,
        }
        for b in befunde
    ]


def laufstatus(befunde: Iterable[Befund], *, unvollstaendig: bool = False) -> str:
    """``'warnung'``, wenn etwas nachzusehen ist, sonst ``'erfolg'``.

    ``unvollstaendig`` setzt die aufrufende Stelle, wenn sie Zeilen liegen gelassen hat – das
    ist unabhängig davon, ob dazu ein Befund entstanden ist.
    """
    if unvollstaendig:
        return "warnung"
    if any(b.schwere == "warnung" for b in befunde):
        return "warnung"
    return "erfolg"
