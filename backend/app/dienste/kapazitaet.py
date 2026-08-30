"""Kapazitätsplanung je Kalenderwoche (PLAN §7 Phase 7).

Die Frage ist einfach und die Antwort selten: **Reicht die Mannschaft für das, was terminiert
ist?** Der Dienst stellt den Sollstunden aus der Kalkulation die Wochenstunden der Mitarbeiter
gegenüber, Woche für Woche.

Vier Festlegungen tragen die Zahlen:

* **Verteilt wird über die geplanten Montagewochen**, nicht gleichmäßig über die Projektlaufzeit.
  Ein Projekt bindet Mannschaft, wenn montiert wird – nicht während es auf den Netzbetreiber
  wartet. Welche Meilensteine als Montage gelten, steht in der ``config.toml``.
* **Was keine geplante Woche hat, verschwindet nicht.** Die Stunden stehen als ``ohne_termin``
  daneben. Sie sind der wichtigste Teil der Auskunft: unverplante Arbeit ist der Grund, warum
  eine Woche später überraschend voll ist.
* **Erledigte Meilensteine binden nichts mehr.** Was montiert ist, ist montiert.
* **Urlaub und Krankheit sind nicht abgebildet.** Die Wochenstunden sind die Regelarbeitszeit.
  Eine Abwesenheitsplanung gehört nicht in ein Werkzeug, das ausdrücklich keine
  Personalverwaltung ist (PLAN §12) – die Ansicht sagt das dazu, damit niemand die Zahl für
  eine Zusage hält.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.dienste.suche import AUFGELOEST
from app.modelle import (
    Meilenstein,
    Mitarbeiter,
    Projekt,
    SollKalkulation,
    Stunden,
)
from app.zeit import heute_ortszeit, woche_lesen, woche_schluessel, wochen_ab, wochenbeginn

# Zwei Nachkommastellen wie in der Datenbank; Stunden sind keine Cent-Beträge, aber gerundet
# werden sie trotzdem an einer Stelle und nicht in jeder Anzeige neu.
GENAU = Decimal("0.01")


def _runden(wert: Decimal) -> Decimal:
    return wert.quantize(GENAU, rounding=ROUND_HALF_UP)


@dataclass
class Projektanteil:
    """Was ein Projekt in einer Woche belegt."""

    projekt_nr: int
    bezeichnung: str | None
    stunden: Decimal
    # Über wie viele Wochen die Sollstunden verteilt wurden – erklärt die Zahl.
    wochen: int


@dataclass
class Wochenlast:
    """Eine Kalenderwoche mit Bedarf und Kapazität."""

    jahr: int
    woche: int
    schluessel: str
    beginn: date
    bedarf: Decimal = Decimal(0)
    kapazitaet: Decimal = Decimal(0)
    projekte: list[Projektanteil] = field(default_factory=list)

    @property
    def auslastung_promille(self) -> int | None:
        """Bedarf zu Kapazität in Promille. ``None`` ohne Mannschaft – dann sagt die Zahl nichts."""
        if self.kapazitaet <= 0:
            return None
        return int((self.bedarf / self.kapazitaet * 1000).to_integral_value(ROUND_HALF_UP))

    @property
    def rest(self) -> Decimal:
        """Freie Stunden; negativ bedeutet Überbuchung."""
        return _runden(self.kapazitaet - self.bedarf)


@dataclass
class OhneTermin:
    """Ein Projekt mit Sollstunden, aber ohne geplante Montagewoche."""

    projekt_nr: int
    bezeichnung: str | None
    stunden: Decimal
    status: str


@dataclass
class Kapazitaetsbild:
    """Das Ergebnis: Wochen, Unverplantes und was daran unsicher ist."""

    wochen: list[Wochenlast]
    ohne_termin: list[OhneTermin] = field(default_factory=list)
    ohne_sollwert: list[int] = field(default_factory=list)
    unlesbare_wochen: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)

    @property
    def bedarf_gesamt(self) -> Decimal:
        return _runden(sum((w.bedarf for w in self.wochen), Decimal(0)))

    @property
    def kapazitaet_gesamt(self) -> Decimal:
        return _runden(sum((w.kapazitaet for w in self.wochen), Decimal(0)))

    @property
    def stunden_ohne_termin(self) -> Decimal:
        return _runden(sum((o.stunden for o in self.ohne_termin), Decimal(0)))


def wochenkapazitaet(sitzung: Session, jahr: int, woche: int) -> Decimal:
    """Summe der Wochenstunden aller Mitarbeiter, die in dieser Woche im Haus sind."""
    beginn = wochenbeginn(jahr, woche)
    ende = beginn + timedelta(days=6)
    abfrage = select(Mitarbeiter).where(
        Mitarbeiter.aktiv.is_(True),
        (Mitarbeiter.von.is_(None)) | (Mitarbeiter.von <= ende),
        (Mitarbeiter.bis.is_(None)) | (Mitarbeiter.bis >= beginn),
    )
    return _runden(
        sum((Decimal(str(m.wochenstunden)) for m in sitzung.scalars(abfrage)), Decimal(0))
    )


def _montagewochen(
    sitzung: Session, projekt_id: int, typen: list[str]
) -> tuple[list[tuple[int, int]], list[str]]:
    """Geplante Montagewochen eines Projekts, dazu die Angaben, die sich nicht lesen ließen.

    Erledigte Meilensteine bleiben draußen: was montiert ist, bindet keine Mannschaft mehr.
    """
    zeilen = sitzung.execute(
        select(Meilenstein.geplant_kw).where(
            Meilenstein.projekt_id == projekt_id,
            Meilenstein.typ.in_(typen),
            Meilenstein.geplant_kw.is_not(None),
            Meilenstein.erledigt_am.is_(None),
        )
    ).all()

    wochen: list[tuple[int, int]] = []
    unlesbar: list[str] = []
    for (roh,) in zeilen:
        gelesen = woche_lesen(roh)
        if gelesen is None:
            unlesbar.append(roh)
        elif gelesen not in wochen:
            wochen.append(gelesen)
    return sorted(wochen), unlesbar


def bild(
    sitzung: Session,
    sichtbar: Select,
    *,
    wochen_voraus: int,
    montage_meilensteine: list[str],
    status_mit_bedarf: list[str],
    ab: date | None = None,
) -> Kapazitaetsbild:
    """Kapazitätsbild über die nächsten Wochen.

    ``sichtbar`` ist die bereits nach Sichtbarkeit gefilterte Projektabfrage (PLAN §4) – wer nur
    eigene Projekte sieht, bekommt eine Kapazitätssicht über eigene Projekte. Das ist dann auch
    die ehrliche Auskunft, selbst wenn sie die Mannschaft der ganzen Firma dagegenstellt.
    """
    start = ab or heute_ortszeit()
    fenster = wochen_ab(start, wochen_voraus)
    tabelle = {
        (jahr, woche): Wochenlast(
            jahr=jahr,
            woche=woche,
            schluessel=woche_schluessel(jahr, woche),
            beginn=wochenbeginn(jahr, woche),
            kapazitaet=wochenkapazitaet(sitzung, jahr, woche),
        )
        for jahr, woche in fenster
    }
    ergebnis = Kapazitaetsbild(wochen=[tabelle[w] for w in fenster])

    projekte = sitzung.scalars(
        sichtbar.where(Projekt.status.in_(status_mit_bedarf)).order_by(Projekt.projekt_nr)
    ).all()

    for projekt in projekte:
        soll = sitzung.get(SollKalkulation, projekt.id)
        stunden_soll = (
            Decimal(str(soll.stunden_soll))
            if soll is not None and soll.stunden_soll is not None
            else None
        )
        wochen, unlesbar = _montagewochen(sitzung, projekt.id, montage_meilensteine)
        ergebnis.unlesbare_wochen.extend(f"{projekt.projekt_nr}: „{roh}“" for roh in unlesbar)

        if stunden_soll is None or stunden_soll <= 0:
            # Ohne Sollwert lässt sich nichts verteilen. Das Projekt gehört trotzdem genannt:
            # es bindet Mannschaft, die hier nirgends auftaucht.
            if wochen:
                ergebnis.ohne_sollwert.append(projekt.projekt_nr)
            continue

        if not wochen:
            ergebnis.ohne_termin.append(
                OhneTermin(
                    projekt_nr=projekt.projekt_nr,
                    bezeichnung=projekt.bezeichnung,
                    stunden=_runden(stunden_soll),
                    status=projekt.status,
                )
            )
            continue

        # Gleichmäßig über die geplanten Wochen. Eine feinere Verteilung wäre eine Erfindung:
        # das Kalkulationsblatt kennt nur eine Summe, keinen Verlauf.
        je_woche = _runden(stunden_soll / len(wochen))
        for schluessel in wochen:
            last = tabelle.get(schluessel)
            if last is None:
                # Außerhalb des Fensters – gewollt: eine Montage in acht Monaten sagt heute
                # nichts über die Auslastung der nächsten Wochen.
                continue
            last.bedarf = _runden(last.bedarf + je_woche)
            last.projekte.append(
                Projektanteil(
                    projekt_nr=projekt.projekt_nr,
                    bezeichnung=projekt.bezeichnung,
                    stunden=je_woche,
                    wochen=len(wochen),
                )
            )

    ergebnis.hinweise = _hinweise(sitzung, ergebnis)
    return ergebnis


def _hinweise(sitzung: Session, ergebnis: Kapazitaetsbild) -> list[str]:
    """Was die Zahlen relativiert – in der Reihenfolge, in der es wehtut."""
    hinweise: list[str] = []

    if all(w.kapazitaet <= 0 for w in ergebnis.wochen):
        hinweise.append(
            "Es sind keine Mitarbeiter mit Wochenstunden erfasst. Ohne sie gibt es keine "
            "Auslastung, nur den Bedarf. Nächster Schritt: unter „Kapazität“ die Mannschaft "
            "eintragen."
        )

    if ergebnis.ohne_termin:
        hinweise.append(
            f"{len(ergebnis.ohne_termin)} Projekte mit zusammen "
            f"{ergebnis.stunden_ohne_termin} Sollstunden haben keine geplante Montagewoche. "
            "Sie fehlen in jeder Woche unten – die Auslastung ist damit zu günstig. Nächster "
            "Schritt: im Projekt die Montagetermine als Kalenderwoche eintragen."
        )

    if ergebnis.ohne_sollwert:
        nummern = ", ".join(str(nr) for nr in ergebnis.ohne_sollwert[:5])
        weitere = (
            f" und {len(ergebnis.ohne_sollwert) - 5} weitere"
            if len(ergebnis.ohne_sollwert) > 5
            else ""
        )
        hinweise.append(
            f"Für {nummern}{weitere} gibt es keine Sollstunden aus der Kalkulation. Die "
            "Montagewochen stehen, die Stunden fehlen. Nächster Schritt: das Kalkulationsblatt "
            "in 03_Kalkulation ablegen und den Lauf „Kalkulationsblätter“ starten."
        )

    if ergebnis.unlesbare_wochen:
        hinweise.append(
            "Diese Terminangaben ließen sich nicht als Kalenderwoche lesen und wurden "
            "übergangen: " + ", ".join(ergebnis.unlesbare_wochen[:8]) + ". Erwartet wird "
            "„KW/JJ“, zum Beispiel 29/26."
        )

    fremde = namen_ohne_mitarbeiter(sitzung)
    if fremde:
        hinweise.append(
            "In TimeTac buchen Namen, die hier nicht als Mitarbeiter stehen: "
            + ", ".join(fremde[:8])
            + ". Ihre Stunden zählen in der Nachkalkulation, aber nicht in der Kapazität."
        )

    return hinweise


def _vergleichbar(name: str) -> str:
    """Name auf eine Form bringen, die Schreibvarianten überbrückt.

    Groß- und Kleinschreibung, Umlaute und ß: TimeTac liefert „Bäumler" oder „Baeumler", je
    nachdem wer den Datensatz angelegt hat. Dieselben Regeln nutzt die Kundensuche
    (``app/dienste/suche.py``). Weiter geht die Nachsicht nicht – ein anderer Name ist ein
    anderer Mensch, und genau darauf soll der Hinweis aufmerksam machen.
    """
    ergebnis = name.strip().casefold()
    for zeichen, ersatz in AUFGELOEST:
        ergebnis = ergebnis.replace(zeichen, ersatz)
    return ergebnis


def namen_ohne_mitarbeiter(sitzung: Session) -> list[str]:
    """Wer in TimeTac bucht, aber keinen Mitarbeiterdatensatz hat.

    Der Vergleich läuft über den Namen, weil es keine gemeinsame Kennung gibt. Ohne diesen
    Hinweis wäre ein Tippfehler unsichtbar: die Stunden zählen dann in der Nachkalkulation und
    die Person fehlt in der Kapazität, ohne dass irgendwo etwas fehlt aussieht.
    """
    gebucht = {
        name.strip()
        for (name,) in sitzung.execute(select(Stunden.mitarbeiter).distinct()).all()
        if name and name.strip()
    }
    bekannt = {
        _vergleichbar(name) for (name,) in sitzung.execute(select(Mitarbeiter.name)).all() if name
    }
    return sorted(name for name in gebucht if _vergleichbar(name) not in bekannt)
