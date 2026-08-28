"""DATEV-Kostenträgerauswertung einlesen (PLAN §8, §6.5).

Die Kanzlei legt monatlich drei Exporte in ``02_DATEV`` ab. Dieser Import nimmt den ersten:
die **Kostenträgerauswertung mit Einzelbuchungen**. Der Schlüssel ist KOST2 – dort steht die
Projektnummer, dieselbe wie im Leitstand (PLAN §3, deshalb ist sie rein numerisch und höchstens
achtstellig). Summen- und Saldenliste sowie die offenen Posten folgen in Phase 5.

Drei Festlegungen, die den Import ausmachen:

* **Nur Kosten.** Eine Kostenträgerauswertung führt auch Erlöse. Übernommen wird, was in den
  konfigurierten Kontenbereichen liegt (``[datev.kostentraeger] kostenkonten``); alles andere
  steht mit Begründung in der Vorschau. Ein Erlös, der als Kosten gebucht wird, dreht die Marge
  ins Gegenteil – das darf nicht stillschweigend passieren.
* **Verdichtet auf Konto und Monat.** In ``ist_kosten`` entsteht je Projekt, Monat und Konto
  **eine** Zeile. Die Einzelbuchungen stehen im Importprotokoll und sind dort nachzulesen; die
  Auswertungstabelle bleibt so klein und je Lauf reproduzierbar. ``ist_kosten`` trägt kein
  Belegfeld, eine Zeile je Buchung wäre also ohnehin nicht wiederauffindbar.
* **Jeder Lauf ersetzt seinen Monat** (PLAN §8). Vor dem Einfügen wird der Monat gelöscht, in
  derselben Schreibtransaktion. Ein nachgelieferter oder korrigierter Monat ist der Normalfall,
  kein Sonderfall – anders als bei der einmaligen Migration gibt es hier keinen Erstlauf-Riegel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fehler import FachFehler
from app.geld import euro_nach_cent
from app.importe import csv_leser
from app.importe.befunde import Befund
from app.konfiguration import KostentraegerEinstellungen
from app.modelle import IstKosten, Projekt

QUELLE = "datev"

# Ohne diese Felder ergibt die Datei keinen Kostenträgerimport.
PFLICHTSPALTEN: tuple[str, ...] = ("kostentraeger", "konto", "betrag")

# Dateiname nach PLAN §2: 'kostentraeger_2026-07.csv'.
_DATEINAME_MONAT = re.compile(r"(\d{4})[-_](\d{2})")

# Soll heißt Kosten, Haben heißt Minderung. Ohne Kennzeichen entscheidet das Vorzeichen.
_SOLL = {"s", "soll"}
_HABEN = {"h", "haben"}


class DatevFehler(FachFehler):
    code = "datev_fehler"


class MonatUnbekannt(DatevFehler):
    code = "datev_monat_unbekannt"

    def __init__(self, pfad: Path) -> None:
        super().__init__(
            f"Aus dem Dateinamen '{pfad.name}' lässt sich kein Monat lesen.",
            "Die Datei nach dem Muster 'kostentraeger_JJJJ-MM.csv' benennen (PLAN §2) – der "
            "Monat entscheidet, welcher Zeitraum beim Import ersetzt wird.",
        )


@dataclass
class Buchung:
    """Eine Einzelbuchung auf einen Kostenträger. Betrag positiv heißt Kosten."""

    zeile: int
    projekt_nr: int
    konto: str
    kontobezeichnung: str
    betrag_cent: int
    datum: date | None = None
    beleg: str = ""
    buchungstext: str = ""

    @property
    def referenz(self) -> str:
        """Wie die Zeile in ``ist_kosten`` heißt: Konto mit Bezeichnung."""
        return f"{self.konto} {self.kontobezeichnung}".strip()


@dataclass
class Kostentraegerdatei:
    pfad: Path
    monat: str
    buchungen: list[Buchung] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)
    # Zeilen, die bewusst draußen bleiben (Erlöskonten, fremde Kostenträger). Kein Befund,
    # sondern eine Auskunft: in der Vorschau steht, was nicht übernommen wurde und warum.
    nicht_uebernommen: list[dict[str, object]] = field(default_factory=list)

    @property
    def summe_cent(self) -> int:
        return sum(b.betrag_cent for b in self.buchungen)

    def je_projekt(self) -> dict[int, int]:
        summen: dict[int, int] = {}
        for buchung in self.buchungen:
            summen[buchung.projekt_nr] = summen.get(buchung.projekt_nr, 0) + buchung.betrag_cent
        return summen

    def je_konto(self) -> dict[str, int]:
        summen: dict[str, int] = {}
        for buchung in self.buchungen:
            summen[buchung.referenz] = summen.get(buchung.referenz, 0) + buchung.betrag_cent
        return summen

    def kontrollsummen(self) -> dict[str, object]:
        return {
            "datei": self.pfad.name,
            "monat": self.monat,
            "buchungen": len(self.buchungen),
            "summe_cent": self.summe_cent,
            "projekte": len(self.je_projekt()),
            "konten": len(self.je_konto()),
            "nicht_uebernommen": len(self.nicht_uebernommen),
        }


def monat_aus_dateiname(pfad: Path) -> str | None:
    """``'2026-07'`` aus ``kostentraeger_2026-07.csv``."""
    treffer = _DATEINAME_MONAT.search(pfad.stem)
    if treffer is None:
        return None
    jahr, monat = treffer.groups()
    if not 1 <= int(monat) <= 12:
        return None
    return f"{jahr}-{monat}"


def kostentraeger_lesen(
    pfad: Path, einstellungen: KostentraegerEinstellungen, *, monat: str | None = None
) -> Kostentraegerdatei:
    """Liest eine Kostenträgerauswertung. Schreibt nichts."""
    zeitraum = monat or monat_aus_dateiname(pfad)
    if zeitraum is None:
        raise MonatUnbekannt(pfad)

    datei = csv_leser.lesen(pfad, einstellungen.spalten, pflicht=PFLICHTSPALTEN)
    ergebnis = Kostentraegerdatei(pfad=pfad, monat=zeitraum)
    jahr = int(zeitraum[:4])

    for zeile in datei.zeilen:
        buchung = _zeile_deuten(zeile, einstellungen, ergebnis, jahr=jahr)
        if buchung is not None:
            ergebnis.buchungen.append(buchung)
    _monat_gegenpruefen(ergebnis)
    return ergebnis


def _zeile_deuten(
    zeile: csv_leser.Zeile,
    einstellungen: KostentraegerEinstellungen,
    ergebnis: Kostentraegerdatei,
    *,
    jahr: int,
) -> Buchung | None:
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

    def uebergehen(grund: str) -> None:
        ergebnis.nicht_uebernommen.append(
            {
                "zeile": zeile.nummer,
                "kostentraeger": zeile.wert("kostentraeger"),
                "konto": zeile.wert("konto"),
                "betrag": zeile.wert("betrag"),
                "grund": grund,
            }
        )

    kostentraeger = zeile.wert("kostentraeger").strip()
    if not kostentraeger:
        # Buchungen ohne Kostenträger sind der Regelfall in einer Gesamtauswertung – sie gehören
        # zum Gemeinkostenblock und nicht auf ein Projekt.
        uebergehen("ohne Kostenträger (KOST2)")
        return None
    if not kostentraeger.isdigit():
        befund("kostentraeger", "Kostenträger ist keine Projektnummer – Zeile nicht übernommen")
        return None

    konto = zeile.wert("konto").strip()
    if not einstellungen.ist_kostenkonto(konto):
        uebergehen(f"Konto {konto or '(leer)'} liegt außerhalb der Kostenkonten")
        return None

    betrag = csv_leser.deutsche_zahl(zeile.wert("betrag"))
    if betrag is None:
        befund("betrag", "Kein lesbarer Betrag – Zeile nicht übernommen")
        return None

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

    return Buchung(
        zeile=zeile.nummer,
        projekt_nr=int(kostentraeger),
        konto=konto,
        kontobezeichnung=zeile.wert("kontobezeichnung"),
        betrag_cent=euro_nach_cent(betrag),
        datum=csv_leser.deutsches_datum(zeile.wert("datum"), jahr=jahr),
        beleg=zeile.wert("beleg"),
        buchungstext=zeile.wert("buchungstext"),
    )


def _monat_gegenpruefen(ergebnis: Kostentraegerdatei) -> None:
    """Buchungsdaten gegen den Monat aus dem Dateinamen halten.

    Der Dateiname entscheidet, welcher Zeitraum ersetzt wird. Trägt die Datei Buchungen aus
    einem anderen Monat, wäre der Import für beide Monate falsch – einmal zu viel, einmal zu
    wenig. Deshalb ein Befund je fremdem Monat, mit der Anzahl.
    """
    fremd: dict[str, int] = {}
    for buchung in ergebnis.buchungen:
        if buchung.datum is None:
            continue
        gefunden = f"{buchung.datum:%Y-%m}"
        if gefunden != ergebnis.monat:
            fremd[gefunden] = fremd.get(gefunden, 0) + 1
    for gefunden, anzahl in sorted(fremd.items()):
        ergebnis.befunde.append(
            Befund(
                datei=ergebnis.pfad.name,
                zeile=0,
                spalte="datum",
                wert=gefunden,
                meldung=f"{anzahl} Buchungen tragen das Belegdatum {gefunden}, die Datei ist "
                f"aber als {ergebnis.monat} benannt. Sie werden dem Monat des Dateinamens "
                "zugeordnet – bitte prüfen, ob es die richtige Datei ist",
            )
        )


# ---------------------------------------------------------------------------
# Übernehmen
# ---------------------------------------------------------------------------


@dataclass
class Uebernahmeergebnis:
    monat: str
    importlauf_id: int | None = None
    geloescht: int = 0
    zeilen: int = 0
    projekte: int = 0
    summe_cent: int = 0
    unbekannte_projekte: list[dict[str, object]] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)


def uebernehmen(sitzung: Session, datei: Kostentraegerdatei) -> Uebernahmeergebnis:
    """Kostenträgerbuchungen als Ist-Kosten schreiben.

    Muss in einer Schreibtransaktion laufen (``schreib_transaktion``). Der Monat wird zuerst
    geleert und dann neu gefüllt – siehe Modulkopf.
    """
    from app.importe import laeufe

    ergebnis = Uebernahmeergebnis(monat=datei.monat, befunde=list(datei.befunde))
    lauf = laeufe.lauf_beginnen(sitzung, quelle=QUELLE, datei=datei.pfad.name, zeitraum=datei.monat)
    ergebnis.geloescht = laeufe.zeitraum_leeren(sitzung, quelle=QUELLE, monat=datei.monat)

    projekte = dict(
        sitzung.execute(
            select(Projekt.projekt_nr, Projekt.id).where(
                Projekt.projekt_nr.in_(datei.je_projekt().keys())
            )
        ).all()
    )

    # Verdichtung auf Projekt und Konto: eine Zeile je Kombination (siehe Modulkopf).
    summen: dict[tuple[int, str], int] = {}
    for buchung in datei.buchungen:
        projekt_id = projekte.get(buchung.projekt_nr)
        if projekt_id is None:
            continue
        schluessel = (projekt_id, buchung.referenz)
        summen[schluessel] = summen.get(schluessel, 0) + buchung.betrag_cent

    for (projekt_id, referenz), betrag in sorted(summen.items()):
        sitzung.add(
            IstKosten(
                projekt_id=projekt_id,
                quelle=QUELLE,
                monat=datei.monat,
                betrag=betrag,
                referenz=referenz,
                importlauf_id=lauf.id,
            )
        )
    sitzung.flush()

    ergebnis.zeilen = len(summen)
    ergebnis.projekte = len({projekt_id for projekt_id, _ in summen})
    ergebnis.summe_cent = sum(summen.values())
    ergebnis.unbekannte_projekte = _unbekannte_melden(datei, projekte, ergebnis)

    laeufe.lauf_abschliessen(
        sitzung,
        lauf,
        befunde=ergebnis.befunde,
        kontrollsummen=datei.kontrollsummen(),
        unvollstaendig=bool(ergebnis.unbekannte_projekte),
        weiteres={
            "geschrieben": {
                "zeilen": ergebnis.zeilen,
                "projekte": ergebnis.projekte,
                "summe_cent": ergebnis.summe_cent,
                "ersetzte_zeilen": ergebnis.geloescht,
            },
            "unbekannte_projekte": ergebnis.unbekannte_projekte,
            "nicht_uebernommen": datei.nicht_uebernommen,
            "einzelbuchungen": [
                {
                    "zeile": b.zeile,
                    "projekt_nr": b.projekt_nr,
                    "konto": b.konto,
                    "betrag_cent": b.betrag_cent,
                    "datum": b.datum.isoformat() if b.datum else None,
                    "beleg": b.beleg,
                    "buchungstext": b.buchungstext,
                }
                for b in datei.buchungen
            ],
        },
    )
    ergebnis.importlauf_id = lauf.id
    return ergebnis


def _unbekannte_melden(
    datei: Kostentraegerdatei, projekte: dict[int, int], ergebnis: Uebernahmeergebnis
) -> list[dict[str, object]]:
    """Kostenträger ohne Projekt im Leitstand.

    Kein Grund abzubrechen, aber auch nichts zum Übersehen: dahinter steckt entweder ein
    Tippfehler in der Buchhaltung oder ein Projekt, das im Leitstand fehlt. Beides muss jemand
    ansehen, und beides würde die Nachkalkulation der übrigen Projekte nicht verfälschen.
    """
    offen: list[dict[str, object]] = []
    for projekt_nr, betrag in sorted(datei.je_projekt().items()):
        if projekt_nr in projekte:
            continue
        offen.append({"projekt_nr": projekt_nr, "betrag_cent": betrag})
        ergebnis.befunde.append(
            Befund(
                datei=datei.pfad.name,
                zeile=0,
                spalte="kostentraeger",
                wert=str(projekt_nr),
                meldung=f"Kein Projekt mit der Nummer {projekt_nr} im Leitstand – die Kosten "
                "dieses Kostenträgers bleiben unberücksichtigt",
            )
        )
    return offen
