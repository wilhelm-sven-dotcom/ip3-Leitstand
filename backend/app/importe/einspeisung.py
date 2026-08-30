"""Abrechnung des Netzbetreibers für die eigenen Anlagen einlesen (PLAN §7 Phase 7).

**Die echte Abrechnung liegt noch nicht vor.** Wie beim Angebots-Tool stehen deshalb die
Spaltennamen in der ``config.toml`` unter ``[einspeisung.spalten]`` und lassen sich ohne
Codeänderung nachziehen. Gelesen werden ``.xlsx``/``.xlsm`` und ``.csv``.

**Als PDF geht es nicht.** Netzbetreiber verschicken ihre Abrechnungen oft als PDF; daraus
Zahlen zu ziehen ist ratebehaftet, und bei einer Zahl, die gegen einen Zahlungseingang geprüft
werden soll, ist Raten das Gegenteil dessen, was gebraucht wird. Wenn nur ein PDF kommt, sind
die zwei Zahlen je Monat und Anlage von Hand schneller erfasst als jede Erkennung.

Zugeordnet wird über **Zählernummer oder MaStR-Nummer**, in dieser Reihenfolge; hilfsweise über
die Bezeichnung, aber nur bei exakter Übereinstimmung. Eine unscharfe Zuordnung wäre hier
gefährlicher als keine: sie schriebe eine Gutschrift der falschen Anlage gut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fehler import FachFehler
from app.importe.befunde import Befund
from app.importe.csv_leser import (
    CsvDatei,
    aus_zeilen,
    deutsche_zahl,
    deutsches_datum,
    excel_zeilen,
)
from app.importe.csv_leser import lesen as csv_lesen
from app.modelle import EigeneAnlage, EinspeiseAbrechnung
from app.zeit import jetzt_utc, monat_gueltig

# Ohne Monat und Menge ist eine Zeile keine Abrechnung.
PFLICHTFELDER: tuple[str, ...] = ("monat", "kwh")

EXCEL_ENDUNGEN = (".xlsx", ".xlsm")


class AbrechnungsdateiFehlt(FachFehler):
    code = "abrechnungsdatei_fehlt"

    def __init__(self, pfad: Path) -> None:
        super().__init__(
            f"Die Abrechnungsdatei '{pfad}' gibt es nicht.",
            "Bitte den Pfad prüfen. Die Datei wird nur gelesen und nicht verändert.",
        )


@dataclass
class Abrechnungszeile:
    """Eine gelesene Zeile, schon in die Form des Leitstands gebracht."""

    zeile: int
    anlage_id: int
    monat: str
    kwh: Decimal
    betrag_cent: int


@dataclass
class Abrechnungsdatei:
    pfad: Path
    zeilen: list[Abrechnungszeile] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)


@dataclass
class Uebernahme:
    """Was der Import geschrieben hat."""

    neu: int = 0
    aktualisiert: int = 0
    uebersprungen: int = 0
    befunde: list[Befund] = field(default_factory=list)


def datei_lesen(pfad: Path, zuordnung: dict[str, list[str]]) -> CsvDatei:
    """Abrechnungsdatei als Tabelle mit den Feldnamen des Leitstands."""
    if not pfad.exists():
        raise AbrechnungsdateiFehlt(pfad)
    if pfad.suffix.lower() in EXCEL_ENDUNGEN:
        kopf, datenzeilen = excel_zeilen(pfad)
        return aus_zeilen(pfad, kopf, datenzeilen, zuordnung, pflicht=PFLICHTFELDER)
    return csv_lesen(pfad, zuordnung, pflicht=PFLICHTFELDER)


def monat_lesen(inhalt: str) -> str | None:
    """Abrechnungsmonat: ``'2026-07'``, ``'07/2026'``, ``'07.2026'`` oder ein Datum darin."""
    roh = inhalt.strip()
    if not roh:
        return None
    if monat_gueltig(roh):
        return roh
    for trenner in ("/", ".", "-"):
        if trenner in roh:
            teile = [t.strip() for t in roh.split(trenner)]
            if len(teile) == 2 and all(t.isdigit() for t in teile):
                monat, jahr = teile
                if len(monat) == 4:  # '2026-07'
                    monat, jahr = jahr, monat
                if len(jahr) == 2:
                    jahr = f"20{jahr}"
                if len(jahr) == 4 and 1 <= int(monat) <= 12:
                    return f"{jahr}-{int(monat):02d}"
    tag = deutsches_datum(roh)
    return f"{tag:%Y-%m}" if tag else None


class _Zuordnung:
    """Nachschlagewerk Zählernummer / MaStR-Nummer / Bezeichnung → Anlage.

    Getrennte Wörterbücher statt eines gemeinsamen: sonst könnte eine Bezeichnung, die zufällig
    wie eine Zählernummer aussieht, die falsche Anlage treffen.
    """

    def __init__(self, anlagen: list[EigeneAnlage]) -> None:
        self.zaehler = {a.zaehler_nr.strip(): a.id for a in anlagen if a.zaehler_nr}
        self.mastr = {a.mastr_nr.strip(): a.id for a in anlagen if a.mastr_nr}
        self.bezeichnung = {a.bezeichnung.strip().casefold(): a.id for a in anlagen}

    def finden(self, zaehler: str, mastr: str, bezeichnung: str) -> int | None:
        return (
            self.zaehler.get(zaehler.strip())
            or self.mastr.get(mastr.strip())
            or self.bezeichnung.get(bezeichnung.strip().casefold())
        )


def lesen(sitzung: Session, pfad: Path, zuordnung: dict[str, list[str]]) -> Abrechnungsdatei:
    """Abrechnungsdatei einlesen. Unklare Werte werden zu Befunden, nicht zu Ausfällen."""
    tabelle = datei_lesen(pfad, zuordnung)
    ergebnis = Abrechnungsdatei(pfad=pfad)
    anlagen = _Zuordnung(list(sitzung.execute(select(EigeneAnlage)).scalars()))

    for zeile in tabelle.zeilen:
        anlage_id = anlagen.finden(zeile.wert("zaehler"), zeile.wert("mastr"), zeile.wert("anlage"))
        if anlage_id is None:
            kennung = zeile.wert("zaehler") or zeile.wert("mastr") or zeile.wert("anlage") or "—"
            ergebnis.befunde.append(
                Befund(
                    pfad.name,
                    zeile.nummer,
                    "anlage",
                    kennung,
                    "Zu dieser Zeile gibt es keine eigene Anlage im Leitstand. Nächster "
                    "Schritt: die Anlage anlegen und Zählernummer oder MaStR-Nummer eintragen",
                )
            )
            continue

        monat = monat_lesen(zeile.wert("monat"))
        if monat is None:
            ergebnis.befunde.append(
                Befund(
                    pfad.name,
                    zeile.nummer,
                    "monat",
                    zeile.wert("monat"),
                    "Abrechnungsmonat nicht lesbar, Zeile übergangen",
                )
            )
            continue

        kwh = deutsche_zahl(zeile.wert("kwh"))
        if kwh is None:
            ergebnis.befunde.append(
                Befund(
                    pfad.name,
                    zeile.nummer,
                    "kwh",
                    zeile.wert("kwh"),
                    "Einspeisemenge nicht lesbar, Zeile übergangen",
                )
            )
            continue
        if kwh < 0:
            ergebnis.befunde.append(
                Befund(
                    pfad.name,
                    zeile.nummer,
                    "kwh",
                    zeile.wert("kwh"),
                    "Negative Einspeisemenge, als Menge ohne Vorzeichen übernommen",
                )
            )
            kwh = abs(kwh)

        betrag = deutsche_zahl(zeile.wert("betrag"))
        if betrag is None:
            # Der Betrag darf fehlen: manche Abrechnungen führen nur die Menge, und die
            # Erwartung lässt sich auch dann rechnen. Gesagt wird es trotzdem.
            if zeile.wert("betrag").strip():
                ergebnis.befunde.append(
                    Befund(
                        pfad.name,
                        zeile.nummer,
                        "betrag",
                        zeile.wert("betrag"),
                        "Betrag nicht lesbar, als 0,00 € übernommen",
                    )
                )
            betrag = Decimal(0)

        ergebnis.zeilen.append(
            Abrechnungszeile(
                zeile=zeile.nummer,
                anlage_id=anlage_id,
                monat=monat,
                kwh=kwh,
                # Bewusst ohne Vorzeichenprüfung: eine Korrekturabrechnung für einen Vormonat
                # kann negativ sein (CLAUDE.md Regel 3).
                betrag_cent=int((betrag * 100).to_integral_value()),
            )
        )

    if not (tabelle.hat("zaehler") or tabelle.hat("mastr")):
        ergebnis.befunde.append(
            Befund(
                pfad.name,
                0,
                "zaehler",
                "",
                "Die Datei führt weder Zählernummer noch MaStR-Nummer. Zugeordnet wird dann "
                "nur über die Bezeichnung, und die muss genau übereinstimmen",
                schwere="hinweis",
            )
        )
    return ergebnis


def uebernehmen(sitzung: Session, datei: Abrechnungsdatei) -> Uebernahme:
    """Gelesene Abrechnungen schreiben. Muss in einer Schreibtransaktion laufen.

    Je Anlage und Monat gibt es genau eine Zeile: ein zweiter Lauf derselben Datei
    aktualisiert, statt zu verdoppeln – dieselbe Regel wie bei den DATEV-Monatsimporten.
    ``bezahlt_am`` bleibt dabei stehen. Ein erneuter Import darf einen von Hand vermerkten
    Zahlungseingang nicht löschen.
    """
    ergebnis = Uebernahme(befunde=list(datei.befunde))
    jetzt = jetzt_utc()

    for zeile in datei.zeilen:
        vorhanden = sitzung.scalar(
            select(EinspeiseAbrechnung).where(
                EinspeiseAbrechnung.anlage_id == zeile.anlage_id,
                EinspeiseAbrechnung.monat == zeile.monat,
            )
        )
        if vorhanden is None:
            vorhanden = EinspeiseAbrechnung(anlage_id=zeile.anlage_id, monat=zeile.monat)
            sitzung.add(vorhanden)
            ergebnis.neu += 1
        else:
            ergebnis.aktualisiert += 1

        vorhanden.kwh = zeile.kwh
        vorhanden.betrag_cent = zeile.betrag_cent
        vorhanden.quelle_datei = datei.pfad.name
        vorhanden.eingelesen_am = jetzt

    sitzung.flush()
    return ergebnis
