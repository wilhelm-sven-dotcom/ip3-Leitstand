"""Summen- und Saldenliste einlesen (PLAN §8, Phase 5).

Die zweite der drei Kanzlei-Lieferungen. Sie trägt den Fixkostenblock des Firmen-Cockpits:
je Konto ein Monatswert, über ``konten_mapping`` einem Kostenblock zugeordnet.

Drei Dinge entscheiden hier über richtige Zahlen:

* **Periode statt Kumulativ.** Eine SuSa führt meist beides: den Saldo seit Jahresbeginn und die
  Bewegung des Monats. Für einen Monatsausweis zählt die Bewegung. Führt die Datei nur den
  kumulierten Saldo, wird er genommen – und das Protokoll sagt es, weil die Zahlen sonst ab
  Februar zu hoch aussähen, ohne dass es jemand merkt.
* **Aufwand ist positiv.** In der Buchhaltung steht Aufwand im Soll. Der Leitstand rechnet
  Kosten als positive Beträge, damit der Fixkostenblock nicht mit Vorzeichen jongliert.
* **Ohne Zuordnung kein Block.** Ein Konto, für das keine Zuordnung greift, wird eingelesen und
  bleibt blocklos. Es erscheint in der Pflegeliste und geht nicht in die Fixkosten ein – ein
  sichtbar fehlender Betrag ist besser als ein still falsch einsortierter.

Wie jeder Import ersetzt auch dieser seinen Zeitraum (PLAN §8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.dienste import konten
from app.fehler import FachFehler
from app.geld import euro_nach_cent
from app.importe import csv_leser
from app.importe.befunde import Befund
from app.konfiguration import SusaEinstellungen
from app.modelle import DatevSaldo

QUELLE = "susa"

PFLICHTSPALTEN: tuple[str, ...] = ("konto", "saldo")

# Dateiname nach PLAN §2: 'susa_2026-07.csv'.
_DATEINAME_MONAT = re.compile(r"(\d{4})[-_](\d{2})")

_SOLL = {"s", "soll"}
_HABEN = {"h", "haben"}


class SusaFehler(FachFehler):
    code = "susa_fehler"


class MonatUnbekannt(SusaFehler):
    code = "susa_monat_unbekannt"

    def __init__(self, pfad: Path) -> None:
        super().__init__(
            f"Aus dem Dateinamen '{pfad.name}' lässt sich kein Monat lesen.",
            "Die Datei nach dem Muster 'susa_JJJJ-MM.csv' benennen (PLAN §2) – der Monat "
            "entscheidet, welcher Zeitraum beim Import ersetzt wird.",
        )


@dataclass
class Kontozeile:
    zeile: int
    konto: str
    bezeichnung: str
    betrag_cent: int
    block: str | None = None


@dataclass
class Susadatei:
    pfad: Path
    monat: str
    zeilen: list[Kontozeile] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)
    # True, wenn nur der kumulierte Saldo zur Verfügung stand (siehe Modulkopf).
    kumuliert_gelesen: bool = False

    @property
    def summe_cent(self) -> int:
        return sum(z.betrag_cent for z in self.zeilen)

    def je_block(self) -> dict[str, int]:
        summen: dict[str, int] = {}
        for zeile in self.zeilen:
            schluessel = zeile.block or "(ohne Zuordnung)"
            summen[schluessel] = summen.get(schluessel, 0) + zeile.betrag_cent
        return summen

    def ohne_block(self) -> list[Kontozeile]:
        return [z for z in self.zeilen if z.block is None]

    def kontrollsummen(self) -> dict[str, object]:
        return {
            "datei": self.pfad.name,
            "monat": self.monat,
            "konten": len(self.zeilen),
            "summe_cent": self.summe_cent,
            "ohne_zuordnung": len(self.ohne_block()),
            "kumuliert_gelesen": self.kumuliert_gelesen,
        }


def monat_aus_dateiname(pfad: Path) -> str | None:
    """``'2026-07'`` aus ``susa_2026-07.csv``."""
    treffer = _DATEINAME_MONAT.search(pfad.stem)
    if treffer is None:
        return None
    jahr, monat = treffer.groups()
    if not 1 <= int(monat) <= 12:
        return None
    return f"{jahr}-{monat}"


def susa_lesen(
    pfad: Path,
    einstellungen: SusaEinstellungen,
    bereiche: list[konten.Bereich],
    *,
    monat: str | None = None,
) -> Susadatei:
    """Liest eine Summen- und Saldenliste. Schreibt nichts."""
    zeitraum = monat or monat_aus_dateiname(pfad)
    if zeitraum is None:
        raise MonatUnbekannt(pfad)

    datei = csv_leser.lesen(pfad, einstellungen.spalten, pflicht=PFLICHTSPALTEN)
    ergebnis = Susadatei(pfad=pfad, monat=zeitraum)
    hat_monatssaldo = datei.hat("monatssaldo")

    if einstellungen.monatssaldo_bevorzugen and not hat_monatssaldo:
        ergebnis.kumuliert_gelesen = True
        ergebnis.befunde.append(
            Befund(
                datei=pfad.name,
                zeile=1,
                spalte="monatssaldo",
                wert="",
                meldung=(
                    "Die Datei führt keine Monatsbewegung, gerechnet wird mit dem Saldo. Ist der "
                    "kumuliert (Saldo seit Jahresbeginn), sind die Fixkosten ab Februar zu hoch – "
                    "dann bei der Kanzlei eine Auswertung je Periode anfordern"
                ),
            )
        )

    for zeile in datei.zeilen:
        eintrag = _zeile_deuten(zeile, ergebnis, bereiche, monatssaldo=hat_monatssaldo)
        if eintrag is not None:
            ergebnis.zeilen.append(eintrag)
    return ergebnis


def _zeile_deuten(
    zeile: csv_leser.Zeile,
    ergebnis: Susadatei,
    bereiche: list[konten.Bereich],
    *,
    monatssaldo: bool,
) -> Kontozeile | None:
    def befund(spalte: str, meldung: str) -> None:
        ergebnis.befunde.append(
            Befund(
                datei=ergebnis.pfad.name,
                zeile=zeile.nummer,
                spalte=spalte,
                wert=zeile.wert(spalte),
                meldung=meldung,
            )
        )

    konto = zeile.wert("konto").strip()
    if not konto:
        # Summenzeilen einer SuSa haben kein Konto. Sie zu überspringen ist richtig, sie zu
        # melden wäre Lärm: in jeder Datei stehen mehrere davon.
        return None
    if konten.konto_als_zahl(konto) is None:
        befund("konto", "Konto ist keine Nummer – Zeile nicht übernommen")
        return None

    spalte = "monatssaldo" if monatssaldo else "saldo"
    betrag = csv_leser.deutsche_zahl(zeile.wert(spalte))
    if betrag is None:
        befund(spalte, "Kein lesbarer Betrag – Zeile nicht übernommen")
        return None

    # Aufwand steht im Soll und wird positiv gerechnet (siehe Modulkopf).
    kennzeichen = zeile.wert("soll_haben").strip().casefold()
    if kennzeichen in _HABEN:
        betrag = -abs(betrag)
    elif kennzeichen in _SOLL:
        betrag = abs(betrag)
    elif kennzeichen:
        befund(
            "soll_haben",
            f"Unbekanntes Soll/Haben-Kennzeichen '{kennzeichen}' – gerechnet wird mit dem "
            "Vorzeichen des Betrags",
        )

    return Kontozeile(
        zeile=zeile.nummer,
        konto=konto,
        bezeichnung=zeile.wert("bezeichnung"),
        betrag_cent=euro_nach_cent(betrag),
        block=konten.block_fuer(konto, bereiche),
    )


@dataclass
class Uebernahmeergebnis:
    monat: str
    importlauf_id: int | None = None
    geloescht: int = 0
    zeilen: int = 0
    summe_cent: int = 0
    ohne_zuordnung: list[dict[str, object]] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)


def uebernehmen(sitzung: Session, datei: Susadatei) -> Uebernahmeergebnis:
    """Salden schreiben. Muss in einer Schreibtransaktion laufen.

    Der Monat wird zuerst geleert und dann neu gefüllt (PLAN §8).
    """
    from app.importe import laeufe

    ergebnis = Uebernahmeergebnis(monat=datei.monat, befunde=list(datei.befunde))
    lauf = laeufe.lauf_beginnen(sitzung, quelle=QUELLE, datei=datei.pfad.name, zeitraum=datei.monat)
    ergebnis.geloescht = laeufe.salden_leeren(sitzung, monat=datei.monat)

    # Ein Konto kann in der Datei mehrfach vorkommen (mehrere Kostenstellen). Die Tabelle führt
    # es je Monat einmal, also hier verdichten – sonst schlägt die Eindeutigkeit zu.
    summen: dict[str, Kontozeile] = {}
    for zeile in datei.zeilen:
        vorhanden = summen.get(zeile.konto)
        if vorhanden is None:
            summen[zeile.konto] = Kontozeile(**vars(zeile))
        else:
            vorhanden.betrag_cent += zeile.betrag_cent

    for konto, zeile in sorted(summen.items()):
        sitzung.add(
            DatevSaldo(
                monat=datei.monat,
                konto=konto,
                bezeichnung=zeile.bezeichnung or None,
                saldo=zeile.betrag_cent,
                block=zeile.block,
                importlauf_id=lauf.id,
            )
        )
    sitzung.flush()

    ergebnis.zeilen = len(summen)
    ergebnis.summe_cent = sum(z.betrag_cent for z in summen.values())
    ergebnis.ohne_zuordnung = [
        {"konto": z.konto, "bezeichnung": z.bezeichnung, "betrag_cent": z.betrag_cent}
        for z in sorted(summen.values(), key=lambda z: -abs(z.betrag_cent))
        if z.block is None
    ]

    laeufe.lauf_abschliessen(
        sitzung,
        lauf,
        befunde=ergebnis.befunde,
        kontrollsummen=datei.kontrollsummen(),
        # Nicht zugeordnete Konten machen den Lauf unvollständig: sie fehlen im Fixkostenblock,
        # und die Überdeckung sieht dadurch besser aus, als sie ist.
        unvollstaendig=bool(ergebnis.ohne_zuordnung),
        weiteres={
            "geschrieben": {
                "konten": ergebnis.zeilen,
                "summe_cent": ergebnis.summe_cent,
                "ersetzte_zeilen": ergebnis.geloescht,
            },
            "je_block": datei.je_block(),
            "ohne_zuordnung": ergebnis.ohne_zuordnung,
        },
    )
    ergebnis.importlauf_id = lauf.id
    return ergebnis
