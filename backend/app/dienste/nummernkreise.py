"""Nummernvergabe (PLAN §3).

Rechnungsnummern müssen je Kreis **lückenlos und fortlaufend** sein (PLAN §6.4, GoBD). Daraus
folgen zwei Dinge, die man leicht falsch macht:

1. **Die Vergabe gehört in dieselbe Transaktion wie die Festschreibung.** Wird die Nummer vorher
   geholt und der Beleg danach doch nicht festgeschrieben, fehlt sie – und eine fehlende Nummer
   muss gegenüber dem Prüfer erklärt werden. Deshalb nimmt :func:`naechste_nummer` eine bestehende
   Sitzung und vergibt innerhalb der laufenden Schreibtransaktion.

2. **Zwei gleichzeitige Vergaben dürfen nicht dieselbe Nummer bekommen.** Die Schreibtransaktion
   beginnt mit ``BEGIN IMMEDIATE`` (siehe ``app.datenbank``), sodass der zweite Schreiber wartet
   statt zu lesen und danach zu überschreiben. Der Test dazu lässt mehrere Threads gleichzeitig
   Nummern ziehen.

Die Kreise selbst stehen in ``app.modelle.fakturierung``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fehler import FachFehler
from app.modelle.fakturierung import Nummernkreis
from app.zeit import heute_ortszeit

# Kreise ohne Jahresbezug: Kunden- und Projektnummern laufen jahresübergreifend weiter.
# (Die Projektnummer trägt das Jahr in der Nummer selbst, siehe unten.)
OHNE_JAHR = frozenset({"KD"})

# Startwerte je Kreis (PLAN §3): Kundennummern beginnen bei 10001.
STARTWERTE: dict[str, int] = {"KD": 10000}


class NummernkreisFehler(FachFehler):
    code = "nummernkreis"
    status_code = 500


def _jahr_fuer(kreis: str, jahr: int | None) -> int:
    if kreis in OHNE_JAHR:
        return 0
    return jahr if jahr is not None else heute_ortszeit().year


def naechster_wert(sitzung: Session, firma_id: int, kreis: str, jahr: int | None = None) -> int:
    """Nächsten Zählwert eines Kreises vergeben und fortschreiben.

    Muss innerhalb einer laufenden Schreibtransaktion aufgerufen werden. Der Aufrufer schreibt in
    derselben Transaktion den Beleg – so entsteht keine Lücke, wenn etwas dazwischen scheitert.
    """
    schluessel_jahr = _jahr_fuer(kreis, jahr)
    eintrag = sitzung.scalar(
        select(Nummernkreis).where(
            Nummernkreis.firma_id == firma_id,
            Nummernkreis.kreis == kreis,
            Nummernkreis.jahr == schluessel_jahr,
        )
    )
    if eintrag is None:
        eintrag = Nummernkreis(
            firma_id=firma_id,
            kreis=kreis,
            jahr=schluessel_jahr,
            letzter_wert=STARTWERTE.get(kreis, 0),
        )
        sitzung.add(eintrag)
        sitzung.flush()

    eintrag.letzter_wert += 1
    sitzung.flush()
    return eintrag.letzter_wert


def naechste_nummer(
    sitzung: Session, firma_id: int, kreis: str, jahr: int | None = None, stellen: int = 4
) -> str:
    """Formatierte Belegnummer, z. B. ``RE-2026-0087`` (PLAN §3)."""
    schluessel_jahr = _jahr_fuer(kreis, jahr)
    wert = naechster_wert(sitzung, firma_id, kreis, jahr)
    if kreis in OHNE_JAHR:
        return str(wert)
    return f"{kreis}-{schluessel_jahr}-{wert:0{stellen}d}"


def naechste_projektnummer(
    sitzung: Session, firma_id: int, jahr: int | None = None, service: bool = False
) -> int:
    """Projektnummer nach dem Schema ``JJNNN``, Serviceaufträge als ``9JJNN`` (PLAN §3).

    Rein numerisch und höchstens achtstellig, damit die Nummer als DATEV-Kostenträger (KOST2)
    verwendbar ist. Für Serviceaufträge trägt sie eine führende 9, damit sich beides im KOST-Feld
    unterscheiden lässt.

    Bestandsprojekte bekommen bei der Migration Nummern nach ihrem Auftragsjahr; der Zähler wird
    dabei je Jahr fortgeschrieben, sodass anschließend keine Nummer doppelt vergeben wird.
    """
    verwendetes_jahr = jahr if jahr is not None else heute_ortszeit().year
    jahr_zweistellig = verwendetes_jahr % 100
    kreis = "SA" if service else "PR"
    laufend = naechster_wert(sitzung, firma_id, kreis, verwendetes_jahr)

    if service:
        # 9JJNN: zwei Stellen für die laufende Nummer, also 99 Serviceaufträge je Jahr.
        if laufend > 99:
            raise NummernkreisFehler(
                f"Für {verwendetes_jahr} sind alle Serviceauftragsnummern vergeben "
                f"(Schema 9JJNN erlaubt 99 Aufträge je Jahr).",
                "Das Nummernschema muss erweitert werden. Bitte Sven informieren.",
            )
        return 900000 + jahr_zweistellig * 100 + laufend

    # JJNNN: drei Stellen, also 999 Projekte je Jahr.
    if laufend > 999:
        raise NummernkreisFehler(
            f"Für {verwendetes_jahr} sind alle Projektnummern vergeben "
            f"(Schema JJNNN erlaubt 999 Projekte je Jahr).",
            "Das Nummernschema muss erweitert werden. Bitte Sven informieren.",
        )
    return jahr_zweistellig * 1000 + laufend


def stand(sitzung: Session, firma_id: int, kreis: str, jahr: int | None = None) -> int:
    """Aktueller Zählerstand, ohne ihn fortzuschreiben (für Anzeige und Prüfung)."""
    eintrag = sitzung.scalar(
        select(Nummernkreis).where(
            Nummernkreis.firma_id == firma_id,
            Nummernkreis.kreis == kreis,
            Nummernkreis.jahr == _jahr_fuer(kreis, jahr),
        )
    )
    if eintrag is None:
        return STARTWERTE.get(kreis, 0)
    return eintrag.letzter_wert


def zaehler_mindestens(
    sitzung: Session, firma_id: int, kreis: str, wert: int, jahr: int | None = None
) -> None:
    """Zähler auf mindestens ``wert`` setzen.

    Für die Migration: nachdem Bestandsprojekte ihre Nummern nach Auftragsjahr erhalten haben,
    muss der Zähler darüber liegen, sonst vergibt der Leitstand eine bereits benutzte Nummer.
    Verringert wird der Zähler nie.
    """
    schluessel_jahr = _jahr_fuer(kreis, jahr)
    eintrag = sitzung.scalar(
        select(Nummernkreis).where(
            Nummernkreis.firma_id == firma_id,
            Nummernkreis.kreis == kreis,
            Nummernkreis.jahr == schluessel_jahr,
        )
    )
    if eintrag is None:
        sitzung.add(
            Nummernkreis(firma_id=firma_id, kreis=kreis, jahr=schluessel_jahr, letzter_wert=wert)
        )
    elif eintrag.letzter_wert < wert:
        eintrag.letzter_wert = wert
    sitzung.flush()
