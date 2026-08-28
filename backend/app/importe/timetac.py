"""TimeTac-Stunden: Verrechnungssätze, Projektzuordnung und Übernahme (PLAN §6.6, §8).

Hier steht die Fachlogik, unabhängig davon, woher die Buchungen kommen: aus der Schnittstelle
(:mod:`app.importe.timetac_api`) oder aus dem CSV-Berichtsexport als Rückfallebene. Beide Wege
münden in :func:`uebernehmen` – die Quelle darf an der Rechnung nichts ändern.

Drei Festlegungen:

* **Der Satz wird beim Import eingefroren** (``stunden.satz``). Eine spätere Satzänderung in der
  config verändert abgeschlossene Monate nicht; sonst würde die Nachkalkulation eines längst
  fertigen Projekts sich rückwirkend bewegen.
* **Ein Name ohne Zuordnung rechnet mit dem Standardsatz** und erscheint als Pflegehinweis. Die
  Stunde wegzulassen wäre schlimmer: sie fehlte im Ist, und die Marge sähe besser aus.
* **Die Projektzuordnung trifft nur exakt.** Eine unscharfe Zuordnung hat in der Migration
  beinahe 550.000 € auf das falsche Projekt gebucht (``app/migration/zuordnung.py``); hier gilt
  dieselbe Vorsicht. Was sich nicht sicher zuordnen lässt, wird zum Befund.

Geschrieben wird **beides**: ``stunden`` als Detail je Mitarbeiter und je Projekt und Monat eine
Zeile in ``ist_kosten`` mit ``quelle='timetac'``. Die Nachkalkulation summiert ausschließlich
``ist_kosten`` – wer beide Tabellen addiert, zählt die Eigenleistung doppelt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.geld import kaufmaennisch_runden
from app.importe.befunde import Befund
from app.konfiguration import StundensaetzeEinstellungen
from app.migration.vokabular import vergleichsform
from app.modelle import IstKosten, Projekt, Stunden

QUELLE = "timetac"

# So heißt die Zeile in ist_kosten. Fest, weil sie zugleich der Eindeutigkeitsschlüssel je
# Projekt und Monat ist (Migration 0007).
REFERENZ = "Arbeitsstunden (TimeTac)"

# Projektnummer im TimeTac-Projektnamen: führende Nummer ('26001 Mustermann') oder in eckigen
# Klammern ('Mustermann [26001]') – beides kommt in gewachsenen Projektlisten vor.
_FUEHRENDE_NUMMER = re.compile(r"^\s*(\d{4,8})(?!\d)")
_NUMMER_IN_KLAMMERN = re.compile(r"[\[(](\d{4,8})[\])]")

SEKUNDEN_JE_STUNDE = 3600


@dataclass
class Zeitbuchung:
    """Eine Zeitbuchung, wie sie aus API oder CSV kommt – noch ohne Projekt und ohne Satz."""

    herkunft: str
    zeile: int
    projekt_text: str
    mitarbeiter: str
    datum: date
    stunden: Decimal
    projekt_nr: int | None = None
    aufgabe: str = ""

    @property
    def monat(self) -> str:
        return f"{self.datum:%Y-%m}"


@dataclass
class Stundenlieferung:
    """Alles, was ein Lauf gelesen hat, vor dem Schreiben."""

    herkunft: str
    monate: list[str]
    buchungen: list[Zeitbuchung] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)

    @property
    def summe_stunden(self) -> Decimal:
        return sum((b.stunden for b in self.buchungen), Decimal(0))

    def kontrollsummen(self) -> dict[str, object]:
        return {
            "herkunft": self.herkunft,
            "monate": self.monate,
            "buchungen": len(self.buchungen),
            "stunden": str(self.summe_stunden),
            "mitarbeiter": len({b.mitarbeiter for b in self.buchungen}),
            "projekte": len({b.projekt_text for b in self.buchungen}),
        }


def projektnummer_aus_text(text: str) -> int | None:
    """Projektnummer aus einem TimeTac-Projektnamen. ``None``, wenn keine sicher darin steht."""
    for muster in (_FUEHRENDE_NUMMER, _NUMMER_IN_KLAMMERN):
        treffer = muster.search(text)
        if treffer is not None:
            return int(treffer.group(1))
    return None


def projekte_zuordnen(sitzung: Session, lieferung: Stundenlieferung) -> dict[int, int]:
    """Setzt ``projekt_nr`` auf den Buchungen und liefert ``{projekt_nr: projekt_id}``.

    Zuerst über die Nummer im Projektnamen. Steht dort keine, wird der Name gegen Kundenname und
    Standort der laufenden Projekte gehalten – **nur ein einziger exakter Treffer** auf der
    Vergleichsform zählt. Alles andere ergibt einen Befund; eine geratene Zuordnung bucht Stunden
    auf ein fremdes Projekt und fällt niemandem auf.
    """
    from app.modelle import Kunde

    kandidaten = sitzung.execute(
        select(Projekt.id, Projekt.projekt_nr, Kunde.name, Projekt.standort).join(
            Kunde, Kunde.id == Projekt.kunde_id
        )
    ).all()
    nach_nummer = {nummer: kennung for kennung, nummer, _name, _ort in kandidaten}

    nach_text: dict[str, set[int]] = {}
    for _kennung, nummer, name, standort in kandidaten:
        for teil in (name, standort, f"{name} {standort or ''}"):
            if teil and teil.strip():
                nach_text.setdefault(vergleichsform(teil), set()).add(nummer)

    gefunden: dict[int, int] = {}
    unauffindbar: set[str] = set()
    for buchung in lieferung.buchungen:
        nummer = projektnummer_aus_text(buchung.projekt_text)
        if nummer is None:
            treffer = nach_text.get(vergleichsform(buchung.projekt_text), set())
            nummer = next(iter(treffer)) if len(treffer) == 1 else None
        if nummer is None or nummer not in nach_nummer:
            if buchung.projekt_text not in unauffindbar:
                unauffindbar.add(buchung.projekt_text)
                lieferung.befunde.append(
                    Befund(
                        datei=lieferung.herkunft,
                        zeile=buchung.zeile,
                        spalte="projekt",
                        wert=buchung.projekt_text,
                        meldung="Kein Projekt im Leitstand zuzuordnen – die Stunden dieses "
                        "TimeTac-Projekts bleiben unberücksichtigt. Die Projektnummer in den "
                        "TimeTac-Projektnamen aufnehmen, dann findet sie der Leitstand von "
                        "selbst",
                    )
                )
            continue
        buchung.projekt_nr = nummer
        gefunden[nummer] = nach_nummer[nummer]
    return gefunden


@dataclass
class Uebernahmeergebnis:
    monate: list[str]
    importlauf_id: int | None = None
    stundenzeilen: int = 0
    kostenzeilen: int = 0
    geloescht: int = 0
    summe_stunden: Decimal = Decimal(0)
    summe_cent: int = 0
    ohne_satz: list[str] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)


def uebernehmen(
    sitzung: Session,
    lieferung: Stundenlieferung,
    saetze: StundensaetzeEinstellungen,
) -> Uebernahmeergebnis:
    """Zeitbuchungen als Stunden und als Ist-Kosten schreiben.

    Muss in einer Schreibtransaktion laufen. Jeder gelieferte Monat wird zuerst geleert und dann
    neu gefüllt (PLAN §8) – beide Tabellen zusammen, sonst passen Detail und Summe nicht mehr
    zueinander.
    """
    from app.importe import laeufe

    ergebnis = Uebernahmeergebnis(monate=list(lieferung.monate), befunde=list(lieferung.befunde))
    lauf = laeufe.lauf_beginnen(
        sitzung,
        quelle=QUELLE,
        datei=lieferung.herkunft,
        zeitraum=", ".join(lieferung.monate),
    )
    projekte = projekte_zuordnen(sitzung, lieferung)
    ergebnis.befunde = list(lieferung.befunde)

    for monat in lieferung.monate:
        sitzung.execute(delete(Stunden).where(Stunden.quelle == QUELLE, Stunden.monat == monat))
        ergebnis.geloescht += laeufe.zeitraum_leeren(sitzung, quelle=QUELLE, monat=monat)

    ohne_satz: set[str] = set()
    je_projekt_monat: dict[tuple[int, str], int] = {}
    for buchung in lieferung.buchungen:
        if buchung.projekt_nr is None or buchung.monat not in lieferung.monate:
            continue
        projekt_id = projekte[buchung.projekt_nr]
        satz, gruppe = saetze.satz_fuer(buchung.mitarbeiter)
        if gruppe is None:
            ohne_satz.add(buchung.mitarbeiter)
        betrag = kaufmaennisch_runden(buchung.stunden * satz)

        sitzung.add(
            Stunden(
                projekt_id=projekt_id,
                monat=buchung.monat,
                mitarbeiter=buchung.mitarbeiter,
                stunden=buchung.stunden,
                satz=satz,
                quelle=QUELLE,
                importlauf_id=lauf.id,
            )
        )
        ergebnis.stundenzeilen += 1
        ergebnis.summe_stunden += buchung.stunden
        schluessel = (projekt_id, buchung.monat)
        je_projekt_monat[schluessel] = je_projekt_monat.get(schluessel, 0) + betrag

    for (projekt_id, monat), betrag in sorted(je_projekt_monat.items()):
        sitzung.add(
            IstKosten(
                projekt_id=projekt_id,
                quelle=QUELLE,
                monat=monat,
                betrag=betrag,
                referenz=REFERENZ,
                importlauf_id=lauf.id,
            )
        )
    sitzung.flush()

    ergebnis.kostenzeilen = len(je_projekt_monat)
    ergebnis.summe_cent = sum(je_projekt_monat.values())
    ergebnis.ohne_satz = sorted(ohne_satz)
    for name in ergebnis.ohne_satz:
        ergebnis.befunde.append(
            Befund(
                datei=lieferung.herkunft,
                zeile=0,
                spalte="mitarbeiter",
                wert=name,
                meldung=f"Für '{name}' ist keine Satzgruppe hinterlegt – gerechnet wurde mit dem "
                "Standardsatz. In der config.toml unter [stundensaetze.mitarbeiter] eintragen",
                schwere="hinweis",
            )
        )

    laeufe.lauf_abschliessen(
        sitzung,
        lauf,
        befunde=ergebnis.befunde,
        kontrollsummen=lieferung.kontrollsummen(),
        weiteres={
            "geschrieben": {
                "stundenzeilen": ergebnis.stundenzeilen,
                "kostenzeilen": ergebnis.kostenzeilen,
                "stunden": str(ergebnis.summe_stunden),
                "summe_cent": ergebnis.summe_cent,
                "ersetzte_zeilen": ergebnis.geloescht,
            },
            "ohne_satzgruppe": ergebnis.ohne_satz,
        },
    )
    ergebnis.importlauf_id = lauf.id
    return ergebnis


# ---------------------------------------------------------------------------
# Rückfallebene: CSV-Berichtsexport
# ---------------------------------------------------------------------------

# Ohne diese Spalten ergibt der Bericht keine Zeitbuchung.
CSV_PFLICHTSPALTEN: tuple[str, ...] = ("projekt", "mitarbeiter", "datum", "dauer")

# 'Dauer' kommt im TimeTac-Bericht als Dezimalstunde (7,5) oder als Uhrzeit (07:30) vor.
_DAUER_ALS_UHRZEIT = re.compile(r"^(\d{1,3}):([0-5]\d)(?::([0-5]\d))?$")

MINUTEN_JE_STUNDE = 60


def dauer_deuten(inhalt: str) -> Decimal | None:
    """Dauer als Dezimalstunden – aus ``7,5`` ebenso wie aus ``07:30``.

    Die beiden Formen sehen einander ähnlich genug, um verwechselt zu werden: ``7:30`` sind
    siebeneinhalb Stunden, ``7,30`` sind sieben Stunden und achtzehn Minuten. Ein Doppelpunkt
    entscheidet, kein Ratespiel.
    """
    from app.importe.csv_leser import deutsche_zahl

    roh = inhalt.strip().removesuffix("h").strip()
    if not roh:
        return None
    treffer = _DAUER_ALS_UHRZEIT.match(roh)
    if treffer is not None:
        stunden, minuten, sekunden = treffer.groups()
        gesamt = (
            Decimal(stunden)
            + Decimal(minuten) / MINUTEN_JE_STUNDE
            + Decimal(sekunden or 0) / SEKUNDEN_JE_STUNDE
        )
        return gesamt.quantize(Decimal("0.01"))
    zahl = deutsche_zahl(roh)
    return None if zahl is None else zahl.quantize(Decimal("0.01"))


def bericht_lesen(pfad, einstellungen, *, monate: list[str] | None = None) -> Stundenlieferung:
    """Liest einen TimeTac-Berichtsexport (CSV). Schreibt nichts.

    Die Rückfallebene aus PLAN §8, die auch nach der Freischaltung ihren Zweck hat: sie trägt
    bei einem Ausfall der Schnittstelle und lädt Monate nach, die die API nicht mehr hergibt.
    Das Ergebnis hat dieselbe Form wie das der Schnittstelle, damit :func:`uebernehmen` beide
    Wege ohne Unterschied bedient.

    ``monate`` schränkt ein, welche Monate ersetzt werden. Ohne Angabe sind es die Monate, die
    tatsächlich in der Datei vorkommen – ein Bericht bringt seinen Zeitraum selbst mit.
    """
    from app.importe import csv_leser

    datei = csv_leser.lesen(pfad, einstellungen.spalten, pflicht=CSV_PFLICHTSPALTEN)
    lieferung = Stundenlieferung(herkunft=pfad.name, monate=list(monate or []))

    for zeile in datei.zeilen:
        buchung = _csv_zeile_deuten(zeile, pfad.name, lieferung)
        if buchung is not None:
            lieferung.buchungen.append(buchung)

    if not lieferung.monate:
        lieferung.monate = sorted({b.monat for b in lieferung.buchungen})
    return lieferung


def _csv_zeile_deuten(zeile, dateiname: str, lieferung: Stundenlieferung) -> Zeitbuchung | None:
    from app.importe import csv_leser

    def befund(spalte: str, meldung: str) -> None:
        lieferung.befunde.append(
            Befund(
                datei=dateiname,
                zeile=zeile.nummer,
                spalte=spalte,
                wert=zeile.wert(spalte),
                meldung=meldung,
            )
        )

    projekt = zeile.wert("projekt")
    if not projekt:
        befund("projekt", "Zeile ohne Projekt – nicht übernommen")
        return None

    mitarbeiter = zeile.wert("mitarbeiter")
    if not mitarbeiter:
        befund("mitarbeiter", "Zeile ohne Mitarbeiter – nicht übernommen")
        return None

    tag = csv_leser.deutsches_datum(zeile.wert("datum"))
    if tag is None:
        befund("datum", "Kein lesbares Datum – Zeile nicht übernommen")
        return None

    stunden = dauer_deuten(zeile.wert("dauer"))
    if stunden is None:
        befund("dauer", "Keine lesbare Dauer – Zeile nicht übernommen")
        return None
    if stunden <= 0:
        return None

    return Zeitbuchung(
        herkunft=dateiname,
        zeile=zeile.nummer,
        projekt_text=projekt,
        mitarbeiter=mitarbeiter,
        datum=tag,
        stunden=stunden,
        aufgabe=zeile.wert("aufgabe"),
    )
