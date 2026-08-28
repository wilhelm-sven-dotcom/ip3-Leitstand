"""Nachkalkulation je Projekt: Erlös, Soll, Ist und Marge (PLAN §7 Phase 4, §6.5, §6.6).

Die Rechenregeln stehen **einmal**, wie in :mod:`app.dienste.auswertung` für den Umsatz – das
Firmen-Cockpit aus Phase 5 baut auf denselben Zahlen auf. Eine Marge, die an zwei Stellen
gerechnet wird, ergibt irgendwann zwei Zahlen, und dann glaubt niemand mehr einer davon.

**Die vier Größen**

* **Erlös** – Auftragswert plus die Nachträge, die zum Soll zählen (``NACHTRAG_ZAEHLT``,
  PLAN §6.12). Daneben steht der tatsächlich fakturierte Betrag; weichen beide ab, sagt es die
  Ansicht, statt einen davon stillschweigend zu bevorzugen.
* **Soll** – Material und Dienstleistung aus dem Kalkulationsblatt, dazu die Sollstunden.
* **Ist** – ausschließlich aus ``ist_kosten``, aufgegliedert nach den drei Quellen. ``stunden``
  und ``stueckliste`` sind Detailtabellen; wer sie noch einmal addiert, zählt doppelt.
* **Marge** – ``Erlös − Ist`` in Cent, und als Prozentsatz **auf den Erlös** (Entscheidung
  Svens): 18 % heißt, von 100.000 € Auftrag bleiben 18.000 € übrig. Gerechnet wird in Promille,
  damit der Vergleich mit ``soll_kalkulation.marge_soll`` ohne Gleitkomma auskommt.

**Was die Ansicht nicht tut:** schätzen. Fehlt der Auftragswert, gibt es keine Marge. Fehlt das
Kalkulationsblatt, gibt es keinen Soll-Ist-Vergleich und keine Ampel – für die 539 migrierten
Projekte ist das der Regelfall. Eine Null als Sollwert wäre eine Aussage über Daten, die es
nicht gibt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.dienste.auswertung import ist_bedingung, nachtraege_je_projekt
from app.modelle import (
    IstKosten,
    Kunde,
    Projekt,
    SollKalkulation,
    Stuecklistenposition,
    Stunden,
    Zahlungsplanposition,
)

# Promille, weil marge_soll in der Datenbank Promille ist (app/modelle/kalkulation.py).
PROMILLE = 1000

# Ampel gegen die Sollmarge. „knapp" beginnt 5 Prozentpunkte unter dem Soll; der Wert ist in
# [nachkalkulation] konfigurierbar, weil er eine Einschätzung ist und keine Rechengröße.
AMPEL_GELB_PROMILLE = 50

Ampel = Literal["im_soll", "knapp", "unter_soll", "ohne_soll"]

# Projektstatus, für die eine Nachkalkulation überhaupt etwas aussagt. Ein Angebot hat weder
# Ist-Kosten noch einen Auftrag; ein storniertes Projekt ist keine Auswertung wert.
GEZAEHLTE_STATUS = ("beauftragt", "in_bau", "abgeschlossen")


@dataclass
class Hinweis:
    """Ein Grund, warum eine Zahl weniger wert ist, als sie aussieht."""

    code: str
    text: str


@dataclass
class Nachkalkulation:
    """Eine Projektzeile. Alle Beträge in Cent (CLAUDE.md Regel 3)."""

    projekt_nr: int
    bezeichnung: str | None
    kunde: str
    status: str
    pl_name: str | None

    ab_wert_cent: int | None = None
    nachtraege_cent: int = 0
    fakturiert_cent: int = 0

    soll_material_cent: int | None = None
    soll_dl_cent: int | None = None
    soll_stunden: Decimal | None = None
    marge_soll_promille: int | None = None

    ist_datev_cent: int = 0
    ist_stueckliste_cent: int = 0
    ist_timetac_cent: int = 0
    stunden_ist: Decimal = Decimal(0)

    hinweise: list[Hinweis] = field(default_factory=list)
    ampel_gelb_promille: int = AMPEL_GELB_PROMILLE

    # -- Erlös ------------------------------------------------------------

    @property
    def erloes_cent(self) -> int | None:
        """Auftragswert plus zählende Nachträge. ``None`` ohne Auftragswert."""
        if self.ab_wert_cent is None:
            return None
        return self.ab_wert_cent + self.nachtraege_cent

    # -- Soll -------------------------------------------------------------

    @property
    def soll_cent(self) -> int | None:
        if self.soll_material_cent is None and self.soll_dl_cent is None:
            return None
        return (self.soll_material_cent or 0) + (self.soll_dl_cent or 0)

    @property
    def hat_kalkulation(self) -> bool:
        return self.soll_cent is not None or self.marge_soll_promille is not None

    # -- Ist --------------------------------------------------------------

    @property
    def ist_cent(self) -> int:
        return self.ist_datev_cent + self.ist_stueckliste_cent + self.ist_timetac_cent

    @property
    def ist_material_cent(self) -> int:
        """Material aus beiden erlaubten Wegen – nie aus beiden zugleich (PLAN §6.5)."""
        return self.ist_datev_cent + self.ist_stueckliste_cent

    # -- Marge ------------------------------------------------------------

    @property
    def marge_cent(self) -> int | None:
        erloes = self.erloes_cent
        return None if erloes is None else erloes - self.ist_cent

    @property
    def marge_promille(self) -> int | None:
        """Marge auf den Erlös, in Promille (Entscheidung Svens)."""
        erloes = self.erloes_cent
        marge = self.marge_cent
        if erloes is None or marge is None or erloes == 0:
            return None
        return round(marge * PROMILLE / erloes)

    @property
    def abweichung_promille(self) -> int | None:
        """Wie weit die Ist-Marge über oder unter der Sollmarge liegt."""
        if self.marge_promille is None or self.marge_soll_promille is None:
            return None
        return self.marge_promille - self.marge_soll_promille

    @property
    def ampel(self) -> Ampel:
        """Ohne Sollmarge keine Ampel – geraten wird hier nicht."""
        abweichung = self.abweichung_promille
        if abweichung is None:
            return "ohne_soll"
        if abweichung >= 0:
            return "im_soll"
        if abweichung >= -self.ampel_gelb_promille:
            return "knapp"
        return "unter_soll"

    # -- Soll-Ist ---------------------------------------------------------

    @property
    def soll_ist_abweichung_cent(self) -> int | None:
        soll = self.soll_cent
        return None if soll is None else self.ist_cent - soll

    @property
    def stunden_abweichung(self) -> Decimal | None:
        if self.soll_stunden is None:
            return None
        return self.stunden_ist - Decimal(str(self.soll_stunden))

    @property
    def hat_ist(self) -> bool:
        return self.ist_cent != 0 or self.stunden_ist != 0


@dataclass
class Uebersicht:
    """Alle sichtbaren Projekte mit ihren Summen."""

    projekte: list[Nachkalkulation] = field(default_factory=list)

    @property
    def erloes_cent(self) -> int:
        return sum(p.erloes_cent or 0 for p in self.projekte)

    @property
    def ist_cent(self) -> int:
        return sum(p.ist_cent for p in self.projekte)

    @property
    def marge_cent(self) -> int:
        """Nur über Projekte mit Auftragswert – sonst stünde Ist ohne Erlös in der Summe."""
        return sum(p.marge_cent or 0 for p in self.projekte if p.erloes_cent is not None)

    @property
    def marge_promille(self) -> int | None:
        erloes = self.erloes_cent
        return None if erloes == 0 else round(self.marge_cent * PROMILLE / erloes)

    @property
    def ohne_kalkulation(self) -> list[Nachkalkulation]:
        return [p for p in self.projekte if not p.hat_kalkulation]

    @property
    def zu_pruefen(self) -> list[Nachkalkulation]:
        """Projekte mit einem Hinweis, der die Zahl in Frage stellt."""
        return [p for p in self.projekte if p.hinweise]


# ---------------------------------------------------------------------------
# Erheben
# ---------------------------------------------------------------------------


def uebersicht(
    sitzung: Session,
    sichtbare_projekte: Select,
    *,
    ampel_gelb_promille: int = AMPEL_GELB_PROMILLE,
    status: tuple[str, ...] = GEZAEHLTE_STATUS,
) -> Uebersicht:
    """Nachkalkulation aller sichtbaren Projekte.

    ``sichtbare_projekte`` ist eine Abfrage auf ``Projekt`` – üblicherweise mit ``scope_filter``
    eingeschränkt, damit der Sichtbarkeits-Scope ``eigene`` auch hier wirkt.
    """
    projekte = list(sitzung.scalars(sichtbare_projekte.where(Projekt.status.in_(status))))
    if not projekte:
        return Uebersicht()

    ids = [p.id for p in projekte]
    namen = dict(
        sitzung.execute(
            select(Kunde.id, Kunde.name).where(Kunde.id.in_({p.kunde_id for p in projekte}))
        ).all()
    )
    nachtraege = nachtraege_je_projekt(sitzung, ids)
    fakturiert = _fakturiert_je_projekt(sitzung, ids)
    soll = _soll_je_projekt(sitzung, ids)
    ist = _ist_je_projekt(sitzung, ids)
    stunden = _stunden_je_projekt(sitzung, ids)
    stueckliste = _stueckliste_je_projekt(sitzung, ids)

    zeilen = []
    for projekt in projekte:
        sollwerte = soll.get(projekt.id)
        istwerte = ist.get(projekt.id, {})
        zeile = Nachkalkulation(
            projekt_nr=projekt.projekt_nr,
            bezeichnung=projekt.bezeichnung,
            kunde=namen.get(projekt.kunde_id, "unbekannt"),
            status=projekt.status,
            pl_name=projekt.pl_name,
            ab_wert_cent=projekt.ab_wert_netto,
            nachtraege_cent=nachtraege.get(projekt.id, 0),
            fakturiert_cent=fakturiert.get(projekt.id, 0),
            soll_material_cent=sollwerte.material_soll if sollwerte else None,
            soll_dl_cent=sollwerte.dl_soll if sollwerte else None,
            soll_stunden=Decimal(str(sollwerte.stunden_soll))
            if sollwerte and sollwerte.stunden_soll is not None
            else None,
            marge_soll_promille=sollwerte.marge_soll if sollwerte else None,
            ist_datev_cent=istwerte.get("datev", 0),
            ist_stueckliste_cent=istwerte.get("stueckliste", 0),
            ist_timetac_cent=istwerte.get("timetac", 0),
            stunden_ist=stunden.get(projekt.id, Decimal(0)),
            ampel_gelb_promille=ampel_gelb_promille,
        )
        zeile.hinweise = hinweise_sammeln(zeile, stueckliste.get(projekt.id, (0, 0, 0)))
        zeilen.append(zeile)

    # Die schwächste Marge zuerst: dort ist die Nachfrage fällig. Projekte ohne Marge ans Ende,
    # sie sagen nichts aus.
    zeilen.sort(key=lambda z: (z.marge_promille is None, z.marge_promille or 0, z.projekt_nr))
    return Uebersicht(projekte=zeilen)


def fuer_projekt(
    sitzung: Session,
    projekt: Projekt,
    *,
    ampel_gelb_promille: int = AMPEL_GELB_PROMILLE,
) -> Nachkalkulation:
    """Nachkalkulation eines einzelnen Projekts – ohne Statusfilter.

    Auch ein Angebot oder ein storniertes Projekt darf man sich ansehen, wenn man ausdrücklich
    danach fragt; nur in der Übersicht haben sie nichts verloren.
    """
    ergebnis = uebersicht(
        sitzung,
        select(Projekt).where(Projekt.id == projekt.id),
        ampel_gelb_promille=ampel_gelb_promille,
        status=tuple({projekt.status}),
    )
    return ergebnis.projekte[0]


def _fakturiert_je_projekt(sitzung: Session, ids: list[int]) -> dict[int, int]:
    """Was von den Zahlungsplanpositionen abgerechnet ist – dieselbe Bedingung wie im Umsatz."""
    zeilen = sitzung.execute(
        select(Zahlungsplanposition.projekt_id, func.sum(Zahlungsplanposition.betrag_netto))
        .where(Zahlungsplanposition.projekt_id.in_(ids), ist_bedingung())
        .group_by(Zahlungsplanposition.projekt_id)
    ).all()
    return {projekt_id: int(summe or 0) for projekt_id, summe in zeilen}


def _soll_je_projekt(sitzung: Session, ids: list[int]) -> dict[int, SollKalkulation]:
    return {
        eintrag.projekt_id: eintrag
        for eintrag in sitzung.scalars(
            select(SollKalkulation).where(SollKalkulation.projekt_id.in_(ids))
        )
    }


def _ist_je_projekt(sitzung: Session, ids: list[int]) -> dict[int, dict[str, int]]:
    """Ist-Kosten je Projekt und Quelle – die einzige Summenquelle (siehe Modulkopf)."""
    zeilen = sitzung.execute(
        select(IstKosten.projekt_id, IstKosten.quelle, func.sum(IstKosten.betrag))
        .where(IstKosten.projekt_id.in_(ids))
        .group_by(IstKosten.projekt_id, IstKosten.quelle)
    ).all()
    summen: dict[int, dict[str, int]] = {}
    for projekt_id, quelle, betrag in zeilen:
        summen.setdefault(projekt_id, {})[quelle] = int(betrag or 0)
    return summen


def _stunden_je_projekt(sitzung: Session, ids: list[int]) -> dict[int, Decimal]:
    """Nur die Stundenzahl. Ihr Wert steckt in ``ist_kosten`` und wird dort nicht doppelt geholt."""
    zeilen = sitzung.execute(
        select(Stunden.projekt_id, func.sum(Stunden.stunden))
        .where(Stunden.projekt_id.in_(ids))
        .group_by(Stunden.projekt_id)
    ).all()
    return {projekt_id: Decimal(str(summe or 0)) for projekt_id, summe in zeilen}


def _stueckliste_je_projekt(sitzung: Session, ids: list[int]) -> dict[int, tuple[int, int, int]]:
    """``{projekt_id: (Positionen, davon lager, davon ohne bestätigte Menge)}``."""
    from sqlalchemy import case

    zeilen = sitzung.execute(
        select(
            Stuecklistenposition.projekt_id,
            func.count(Stuecklistenposition.id),
            func.sum(case((Stuecklistenposition.quelle == "lager", 1), else_=0)),
            func.sum(
                case(
                    (
                        (Stuecklistenposition.quelle == "lager")
                        & (Stuecklistenposition.menge_ist.is_(None)),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .where(Stuecklistenposition.projekt_id.in_(ids))
        .group_by(Stuecklistenposition.projekt_id)
    ).all()
    return {
        projekt_id: (int(gesamt or 0), int(lager or 0), int(offen or 0))
        for projekt_id, gesamt, lager, offen in zeilen
    }


# ---------------------------------------------------------------------------
# Hinweise
# ---------------------------------------------------------------------------


def hinweise_sammeln(zeile: Nachkalkulation, stueckliste: tuple[int, int, int]) -> list[Hinweis]:
    """Die Gründe, aus denen eine Zahl weniger wert ist, als sie aussieht.

    Darunter die Plausibilitätsprüfung aus PLAN §6.5, in **beiden** Richtungen: Material kann
    doppelt drinstehen oder ganz fehlen, und beides sieht der Zahl niemand an.
    """
    positionen, lager, offene_mengen = stueckliste
    projektbestellt = positionen - lager
    hinweise: list[Hinweis] = []

    if zeile.ab_wert_cent is None:
        hinweise.append(
            Hinweis(
                "ohne_auftragswert",
                "Ohne Auftragswert lässt sich keine Marge rechnen. Der Wert gehört in die "
                "Projektmaske.",
            )
        )

    if not zeile.hat_kalkulation:
        hinweise.append(
            Hinweis(
                "ohne_kalkulation",
                "Für dieses Projekt gibt es kein Kalkulationsblatt. Der Ist steht trotzdem; ein "
                "Soll-Ist-Vergleich und die Ampel fehlen.",
            )
        )

    # PLAN §6.5, Richtung 1: DATEV-Kosten, aber keine einzige projektbestellte Position.
    if zeile.ist_datev_cent > 0 and positionen > 0 and projektbestellt == 0:
        hinweise.append(
            Hinweis(
                "doppelbelastung_verdacht",
                "Das Projekt hat DATEV-Kosten, in der Stückliste steht aber alles auf „lager“. "
                "Entweder ist Material doppelt im Ist, oder die Stückliste ist falsch "
                "gekennzeichnet.",
            )
        )

    # Richtung 2: projektbestellte Positionen, aber keine DATEV-Kosten.
    if projektbestellt > 0 and zeile.ist_datev_cent == 0:
        hinweise.append(
            Hinweis(
                "material_fehlt",
                "In der Stückliste steht projektbestelltes Material, aus DATEV kam dazu noch "
                "nichts. Das Ist ist zu niedrig, solange die Kostenträgerbuchungen fehlen.",
            )
        )

    if offene_mengen:
        hinweise.append(
            Hinweis(
                "mengen_ist_offen",
                f"{offene_mengen} Lagerpositionen sind noch nicht gezählt. Bis dahin ist die "
                "Bewertung mit der kalkulierten Menge gerechnet.",
            )
        )

    return hinweise
