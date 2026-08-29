"""Zahlungsstatus der Ausgangsrechnungen (PLAN §6.7, §6.13).

Die eine Regel, aus der alles folgt: **gestellt ist nicht bezahlt.** Der Leitstand kennt keine
Kontoauszüge. Was bezahlt ist, sagt ausschließlich der OPOS-Import – und zwar durch Abwesenheit:
eine beglichene Rechnung steht in der Liste des Stichtags nicht mehr drin.

Daraus folgt die Auswertung je festgeschriebener Rechnung, immer gegen den **jüngsten**
Stichtag:

* Rechnung steht mit Restbetrag in der Liste → ``offen``, nach Fälligkeit ``ueberfaellig``
* Rechnung steht mit einem Rest innerhalb der Skonto-Toleranz drin → ``bezahlt_mit_abzug``
  (PLAN §6.13; sonst stünde ein Kunde mit 2 % Skonto dauerhaft als überfällig da)
* Rechnung fehlt in der Liste, ist aber älter als der Stichtag → ``bezahlt``
* Rechnung ist jünger als der Stichtag → ``ohne_stand``; die Liste kann sie noch nicht kennen
* Es gibt gar keinen OPOS-Import → ``ohne_stand`` für alle, mit Hinweis

``ohne_stand`` ist wichtig genug für einen eigenen Wert: eine Rechnung von gestern als
„bezahlt" auszuweisen, nur weil eine Liste von vorgestern sie nicht führt, wäre die Sorte
Fehler, die niemand nachrechnet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.modelle import Opos, Projekt, Rechnung

# Belegarten, die eine Forderung begründen. Auftragsbestätigungen sind keine Rechnung, Stornos
# und Gutschriften mindern und stehen nicht als eigene Forderung im OPOS.
FORDERUNG = ("abschlag", "schluss", "service")

OFFEN = "offen"
UEBERFAELLIG = "ueberfaellig"
BEZAHLT = "bezahlt"
BEZAHLT_MIT_ABZUG = "bezahlt_mit_abzug"
OHNE_STAND = "ohne_stand"


@dataclass
class Zahlungslage:
    """Status einer einzelnen Rechnung zum jüngsten OPOS-Stichtag."""

    rechnung_nr: str
    kunde: str
    datum: date
    faellig_am: date | None
    zahlbetrag_cent: int
    offen_cent: int
    status: str

    @property
    def bezahlt_cent(self) -> int:
        return self.zahlbetrag_cent - self.offen_cent


@dataclass
class Uebersicht:
    """Zahlungslage aller festgeschriebenen Rechnungen zu einem Stichtag."""

    stichtag: date | None
    posten: list[Zahlungslage]
    hinweise: list[str]

    def _summe(self, *status: str) -> int:
        return sum(p.offen_cent for p in self.posten if p.status in status)

    @property
    def offen_cent(self) -> int:
        return self._summe(OFFEN, UEBERFAELLIG)

    @property
    def ueberfaellig_cent(self) -> int:
        return self._summe(UEBERFAELLIG)

    @property
    def bezahlt_cent(self) -> int:
        return sum(
            p.zahlbetrag_cent for p in self.posten if p.status in (BEZAHLT, BEZAHLT_MIT_ABZUG)
        )

    def je_status(self) -> dict[str, int]:
        zaehler: dict[str, int] = {}
        for posten in self.posten:
            zaehler[posten.status] = zaehler.get(posten.status, 0) + 1
        return zaehler


def kundenname(rechnung: Rechnung) -> str:
    """Empfänger aus dem Kundensnapshot des Belegs.

    Aus dem Snapshot und nicht aus dem Kundenstamm: der Beleg trägt den Stand der Ausstellung,
    und genau der gehört in eine Liste offener Forderungen.
    """
    snapshot = rechnung.kunde_snapshot or {}
    return str(snapshot.get("name") or "")


def letzter_stichtag(sitzung: Session) -> date | None:
    """Jüngster OPOS-Stand, oder ``None`` wenn noch nie importiert wurde."""
    return sitzung.scalar(select(func.max(Opos.stand_datum)))


def toleranz_cent(zahlbetrag_cent: int, prozent: float) -> int:
    """Bis zu welchem Restbetrag eine Rechnung als bezahlt gilt (PLAN §6.13).

    Aufgerundet, damit genau der volle Skontosatz noch als bezahlt durchgeht und nicht an einem
    Cent Rundung scheitert.
    """
    promille = round(prozent * 100)  # 3,0 % -> 300 Hundertstelprozent
    return -(-abs(zahlbetrag_cent) * promille // 10_000)


def status_bestimmen(
    *,
    rechnungsdatum: date,
    faellig_am: date | None,
    zahlbetrag_cent: int,
    offen_cent: int | None,
    stichtag: date | None,
    skonto_prozent: float,
) -> str:
    """Status einer Rechnung. ``offen_cent=None`` heißt: steht nicht in der OPOS-Liste."""
    if stichtag is None or rechnungsdatum > stichtag:
        # Kein Stand, oder ein Stand, der jünger als die Rechnung nicht sein kann.
        return OHNE_STAND
    if offen_cent is None:
        return BEZAHLT
    if offen_cent <= 0:
        return BEZAHLT
    if offen_cent <= toleranz_cent(zahlbetrag_cent, skonto_prozent):
        return BEZAHLT_MIT_ABZUG
    if faellig_am is not None and faellig_am < stichtag:
        return UEBERFAELLIG
    return OFFEN


def uebersicht(
    sitzung: Session,
    sichtbare_projekte: Select | None = None,
    *,
    skonto_prozent: float,
    stichtag: date | None = None,
) -> Uebersicht:
    """Zahlungslage aller festgeschriebenen Forderungen.

    ``sichtbare_projekte`` schränkt auf Projekte ein, die der Nutzer sehen darf; Belege ohne
    Projekt (Servicerechnungen) bleiben dabei sichtbar, weil sie an keinem Projekt hängen.
    """
    stand = stichtag or letzter_stichtag(sitzung)
    hinweise: list[str] = []
    if stand is None:
        hinweise.append(
            "Es liegt noch kein OPOS-Import vor. Der Zahlungsstatus kommt ausschließlich von "
            "dort (PLAN §6.7) – bis dahin ist zu jeder Rechnung nur bekannt, dass sie gestellt "
            "wurde."
        )

    abfrage = select(Rechnung).where(
        Rechnung.status == "festgeschrieben",
        Rechnung.art.in_(FORDERUNG),
        Rechnung.rechnung_nr.is_not(None),
    )
    if sichtbare_projekte is not None:
        # Belege ohne Projekt (Servicerechnungen) bleiben sichtbar – sie hängen an keinem
        # Projekt und würden von einem reinen IN-Filter sonst verschwinden.
        erlaubte_ids = sitzung.scalars(sichtbare_projekte.with_only_columns(Projekt.id)).all()
        abfrage = abfrage.where(
            (Rechnung.projekt_id.is_(None)) | (Rechnung.projekt_id.in_(erlaubte_ids))
        )

    offene: dict[str, int] = {}
    if stand is not None:
        offene = dict(
            sitzung.execute(
                select(Opos.rechnung_nr, Opos.offen_betrag).where(Opos.stand_datum == stand)
            ).all()
        )

    posten: list[Zahlungslage] = []
    for rechnung in sitzung.scalars(abfrage):
        nummer = rechnung.rechnung_nr or ""
        offen = offene.get(nummer)
        status = status_bestimmen(
            rechnungsdatum=rechnung.datum,
            faellig_am=rechnung.faellig_am,
            zahlbetrag_cent=rechnung.zahlbetrag,
            offen_cent=offen,
            stichtag=stand,
            skonto_prozent=skonto_prozent,
        )
        posten.append(
            Zahlungslage(
                rechnung_nr=nummer,
                kunde=kundenname(rechnung),
                datum=rechnung.datum,
                faellig_am=rechnung.faellig_am,
                zahlbetrag_cent=rechnung.zahlbetrag,
                offen_cent=offen if offen is not None else 0,
                status=status,
            )
        )

    posten.sort(key=lambda p: (p.faellig_am or p.datum, p.rechnung_nr))
    ergebnis = Uebersicht(stichtag=stand, posten=posten, hinweise=hinweise)

    unbekannt = sorted(set(offene) - {p.rechnung_nr for p in posten})
    if unbekannt:
        hinweise.append(
            f"{len(unbekannt)} offene Posten gehören zu Rechnungen, die der Leitstand nicht "
            "kennt (Belege aus der Zeit vor der Einführung). Sie zählen nicht in die "
            "Zahlungslage."
        )
    return ergebnis


def eingang_je_monat(sitzung: Session, *, jahr: int, skonto_prozent: float) -> dict[str, int]:
    """Bezahlte Beträge je Monat des Rechnungsdatums – die Liquiditätssicht des Cockpits.

    Bewusst dem **Rechnungsmonat** zugeordnet und nicht dem Zahltag: der Zahltag steht in der
    OPOS-Liste nicht, sie kennt nur „am Stichtag noch offen". Der Umschalter im Cockpit fragt
    deshalb „wie viel vom Umsatz dieses Monats ist eingegangen", nicht „wie viel Geld kam in
    diesem Monat herein". Die Beschriftung sagt es ausdrücklich.
    """
    lage = uebersicht(sitzung, skonto_prozent=skonto_prozent)
    je_monat: dict[str, int] = {}
    for posten in lage.posten:
        if posten.status not in (BEZAHLT, BEZAHLT_MIT_ABZUG):
            continue
        if posten.datum.year != jahr:
            continue
        schluessel = f"{posten.datum:%Y-%m}"
        je_monat[schluessel] = je_monat.get(schluessel, 0) + posten.zahlbetrag_cent
    return je_monat
