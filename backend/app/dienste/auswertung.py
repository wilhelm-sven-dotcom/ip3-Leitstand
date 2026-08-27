"""Umsatz, Forecast und Auftragsbestand (PLAN §6.7, §6.12, §7 Phase 2).

Hier stehen die Rechenregeln **einmal**, damit Route, Kommandozeile und das Firmen-Cockpit aus
Phase 5 dieselbe Wahrheit benutzen. Eine Auswertung, die an zwei Stellen gerechnet wird, ergibt
irgendwann zwei Zahlen, und dann glaubt niemand mehr einer davon.

Die vier Begriffe, um die es geht:

* **Ist** – was abgerechnet ist: Positionen mit gesetzter ``rechnung_id`` (ab Phase 3
  festgeschriebene Belege) oder mit ``migriert_gestellt`` (Altbestand, die Rechnung dazu entstand
  vor der Einführung des Leitstands). PLAN §6.7 trennt das ausdrücklich von *bezahlt* – der
  Zahlungsstatus kommt erst mit dem OPOS-Import in Phase 5.
* **Plan** – was noch aussteht: alle übrigen Positionen, nach ``plan_monat``.
* **Unterminiert** – Positionen ohne ``plan_monat``. Sie dürfen in keiner Monatssäule stehen und
  müssen trotzdem sichtbar sein, sonst fehlen im Bestand 689.698,50 € ohne Hinweis. Auch **im
  Ist** gibt es sie: vier gestellte Altpositionen tragen keinen Monat.
* **Auftragsbestand** – Soll der laufenden Projekte minus dem, was davon schon abgerechnet ist
  (Entscheidung Svens, docs/OFFENE-PUNKTE.md). Nicht die Summe der offenen Positionen: bei den
  Altprojekten führt die Auftragsliste nur die offenen Abschläge, der Rest des Auftrags stünde
  sonst nirgends.

**Was der Ist in Phase 2 nicht ist:** ein vollständiger Jahresumsatz. Die Auftragsliste führte nur
offene Positionen, bereits bezahlte Rechnungen aus 2026 stehen dort nicht. Die Oberfläche sagt das
über dem Diagramm; hier wird nichts geschätzt und nichts hochgerechnet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.modelle import Nachtrag, Projekt, Zahlungsplanposition

# Nachträge, die den Soll-Wert erhöhen (PLAN §6.12). 'angeboten' zählt nicht – ein Angebot ist
# kein Auftrag. 'berechnet' zählt mit, denn was berechnet ist, war beauftragt.
NACHTRAG_ZAEHLT = ("beauftragt", "berechnet")

# Projekte, die zum Auftragsbestand gehören. 'angebot' ist kein Auftrag, 'abgeschlossen' kein
# Bestand mehr, 'storniert' zählt nirgends.
LAUFENDE_STATUS = ("beauftragt", "in_bau")

# Status, die in Umsatz und Forecast überhaupt vorkommen. Stornierte Projekte bleiben draußen:
# ihr Zahlungsplan ist Geschichte, nicht Erwartung.
GEZAEHLTE_STATUS = ("angebot", "beauftragt", "in_bau", "abgeschlossen")

MONATE_IM_JAHR = 12


def ist_bedingung() -> object:
    """SQL-Bedingung für „abgerechnet" – an einer Stelle, weil sie in jeder Summe vorkommt."""
    return or_(
        Zahlungsplanposition.rechnung_id.is_not(None),
        Zahlungsplanposition.migriert_gestellt.is_(True),
    )


@dataclass
class Monatswert:
    """Ein Monat im Jahresverlauf. Beträge in Cent (CLAUDE.md Regel 3)."""

    monat: str  # 'JJJJ-MM'
    ist_cent: int = 0
    plan_cent: int = 0
    ist_anzahl: int = 0
    plan_anzahl: int = 0

    @property
    def summe_cent(self) -> int:
        return self.ist_cent + self.plan_cent


@dataclass
class Unterminiert:
    """Positionen ohne Planmonat, getrennt nach Ist und Plan (PLAN §7 Phase 2)."""

    ist_cent: int = 0
    plan_cent: int = 0
    ist_anzahl: int = 0
    plan_anzahl: int = 0

    @property
    def summe_cent(self) -> int:
        return self.ist_cent + self.plan_cent

    @property
    def anzahl(self) -> int:
        return self.ist_anzahl + self.plan_anzahl


@dataclass
class Jahresverlauf:
    jahr: int
    monate: list[Monatswert]
    unterminiert: Unterminiert

    @property
    def ist_cent(self) -> int:
        return sum(m.ist_cent for m in self.monate)

    @property
    def plan_cent(self) -> int:
        return sum(m.plan_cent for m in self.monate)


@dataclass
class Projektbestand:
    """Auftragsbestand eines Projekts."""

    projekt_nr: int
    bezeichnung: str | None
    kunde: str
    status: str
    pl_name: str | None
    ab_wert_cent: int | None
    nachtraege_cent: int
    fakturiert_cent: int
    zahlungsplan_offen_cent: int

    @property
    def soll_cent(self) -> int | None:
        if self.ab_wert_cent is None:
            return None
        return self.ab_wert_cent + self.nachtraege_cent

    @property
    def rest_cent(self) -> int | None:
        """Was vom Auftrag noch abzurechnen ist. ``None`` ohne Auftragswert."""
        soll = self.soll_cent
        return None if soll is None else soll - self.fakturiert_cent


@dataclass
class Auftragsbestand:
    """Bestand über alle laufenden Projekte, mit den beiden Listen zum Nachsehen."""

    projekte: list[Projektbestand] = field(default_factory=list)

    @property
    def bestand_cent(self) -> int:
        return sum(p.rest_cent or 0 for p in self.projekte if p.rest_cent is not None)

    @property
    def zahlungsplan_offen_cent(self) -> int:
        return sum(p.zahlungsplan_offen_cent for p in self.projekte)

    @property
    def nicht_verplant_cent(self) -> int:
        """Bestand minus offener Zahlungsplan.

        Positiv heißt: ein Teil des Auftrags ist noch nicht in Abschläge zerlegt – bei den
        Altprojekten der Regelfall, weil die Auftragsliste nur die offenen Positionen führte.
        Negativ heißt: es ist mehr verplant als beauftragt.
        """
        return self.bestand_cent - self.zahlungsplan_offen_cent

    @property
    def ohne_auftragswert(self) -> list[Projektbestand]:
        """Projekte ohne Auftragswert – sie tragen nichts zum Bestand bei."""
        return [p for p in self.projekte if p.ab_wert_cent is None]

    @property
    def zu_pruefen(self) -> list[Projektbestand]:
        """Mehr abgerechnet als beauftragt: der Auftragswert stimmt vermutlich nicht.

        Nicht auf null geklammert. Eine stillschweigend auf null gesetzte Überdeckung wäre eine
        Aussage über Daten, die niemand geprüft hat.
        """
        return [p for p in self.projekte if p.rest_cent is not None and p.rest_cent < 0]


def _summen_abfrage(sichtbare_projekte: Select, *spalten: Any) -> Select:
    """Abfrage über die Positionen der sichtbaren Projekte, ohne stornierte.

    ``sichtbare_projekte`` ist eine Abfrage auf ``Projekt`` – üblicherweise mit ``scope_filter``
    eingeschränkt, damit der Sichtbarkeits-Scope ``eigene`` auch in den Summen wirkt.

    Die gewünschten Spalten stehen **direkt** im SELECT. Der naheliegende Weg – eine Abfrage auf
    ``Zahlungsplanposition`` bauen und später ``select(spalten).select_from(basis.subquery())``
    darüberlegen – ergibt ein Kreuzprodukt: die Spalten beziehen sich dann auf die Tabelle, nicht
    auf die Unterabfrage. Die Summen kommen dabei vervielfacht heraus, ohne dass etwas
    fehlschlägt. Genau das ist beim Bau passiert (18 Mio. € statt 3 Mio. €).
    """
    return (
        select(*spalten)
        .select_from(Zahlungsplanposition)
        .join(Projekt, Projekt.id == Zahlungsplanposition.projekt_id)
        .where(
            Projekt.id.in_(sichtbare_projekte.with_only_columns(Projekt.id)),
            Projekt.status.in_(GEZAEHLTE_STATUS),
        )
    )


def jahresverlauf(
    db: Session,
    sichtbare_projekte: Select,
    jahr: int,
) -> Jahresverlauf:
    """Umsatz je Monat als Ist und Plan, dazu die unterminierten Positionen.

    Das Jahr wird über ``plan_monat`` gefiltert, nicht über die Projektnummer: hier geht es um
    Monate, nicht um Auftragsjahre. Ein Jahr ohne Daten ergibt zwölf leere Monate und keinen
    Fehler – eine leere Auswertung ist eine Auskunft.

    Ab Phase 3 tritt für festgeschriebene Belege das Belegdatum an die Stelle von ``plan_monat``
    (Monatszuordnung dann über :func:`app.zeit.monat` in Europe/Berlin). Die Aufteilung in Ist und
    Plan steht schon hier, damit dafür kein zweiter Aggregationsweg entsteht.
    """
    ist = ist_bedingung()
    zeilen = db.execute(
        _summen_abfrage(
            sichtbare_projekte,
            Zahlungsplanposition.plan_monat,
            func.sum(case((ist, Zahlungsplanposition.betrag_netto), else_=0)),
            func.sum(case((ist, 0), else_=Zahlungsplanposition.betrag_netto)),
            func.sum(case((ist, 1), else_=0)),
            func.sum(case((ist, 0), else_=1)),
        ).group_by(Zahlungsplanposition.plan_monat)
    ).all()

    # Die zwölf Monate stehen immer alle da, auch die leeren: ein Verlauf mit Lücken ist kein
    # Verlauf, und die Balken sollen im Januar anfangen und im Dezember enden.
    werte = {
        f"{jahr}-{monat:02d}": Monatswert(monat=f"{jahr}-{monat:02d}")
        for monat in range(1, MONATE_IM_JAHR + 1)
    }
    unterminiert = Unterminiert()

    for monat, ist_cent, plan_cent, ist_anzahl, plan_anzahl in zeilen:
        if monat is None:
            unterminiert.ist_cent += int(ist_cent or 0)
            unterminiert.plan_cent += int(plan_cent or 0)
            unterminiert.ist_anzahl += int(ist_anzahl or 0)
            unterminiert.plan_anzahl += int(plan_anzahl or 0)
            continue
        eintrag = werte.get(monat)
        if eintrag is None:
            continue  # anderes Jahr
        eintrag.ist_cent = int(ist_cent or 0)
        eintrag.plan_cent = int(plan_cent or 0)
        eintrag.ist_anzahl = int(ist_anzahl or 0)
        eintrag.plan_anzahl = int(plan_anzahl or 0)

    return Jahresverlauf(
        jahr=jahr,
        monate=[werte[schluessel] for schluessel in sorted(werte)],
        unterminiert=unterminiert,
    )


def jahre_mit_daten(db: Session, sichtbare_projekte: Select) -> list[int]:
    """Jahre, in denen Zahlungsplanpositionen liegen – für die Auswahlliste.

    Aus den Daten und nicht fest verdrahtet: ein Jahr ohne Positionen gehört nicht in den Filter.
    """
    zeilen = db.execute(
        _summen_abfrage(sichtbare_projekte, func.substr(Zahlungsplanposition.plan_monat, 1, 4))
        .where(Zahlungsplanposition.plan_monat.is_not(None))
        .distinct()
    ).all()
    return sorted({int(zeile[0]) for zeile in zeilen if zeile[0]}, reverse=True)


def nachtraege_je_projekt(db: Session, projekt_ids: list[int]) -> dict[int, int]:
    """Summe der Nachträge, die zum Soll zählen (PLAN §6.12)."""
    if not projekt_ids:
        return {}
    zeilen = db.execute(
        select(Nachtrag.projekt_id, func.sum(Nachtrag.betrag_netto))
        .where(Nachtrag.projekt_id.in_(projekt_ids), Nachtrag.status.in_(NACHTRAG_ZAEHLT))
        .group_by(Nachtrag.projekt_id)
    ).all()
    return {projekt_id: int(summe or 0) for projekt_id, summe in zeilen}


def auftragsbestand(db: Session, sichtbare_projekte: Select) -> Auftragsbestand:
    """Offener Auftragsbestand je Projekt und in Summe (Entscheidung Svens).

    Bestand = Auftragswert plus beauftragte Nachträge minus dem, was schon abgerechnet ist.
    Gezählt werden nur laufende Projekte: ein Angebot ist kein Auftrag, ein abgeschlossenes
    Projekt kein Bestand.
    """
    ist = ist_bedingung()
    projekte = list(db.scalars(sichtbare_projekte.where(Projekt.status.in_(LAUFENDE_STATUS))))
    if not projekte:
        return Auftragsbestand()

    ids = [p.id for p in projekte]
    nachtraege = nachtraege_je_projekt(db, ids)

    summen = dict.fromkeys(ids, (0, 0))
    zeilen = db.execute(
        select(
            Zahlungsplanposition.projekt_id,
            func.sum(case((ist, Zahlungsplanposition.betrag_netto), else_=0)),
            func.sum(case((ist, 0), else_=Zahlungsplanposition.betrag_netto)),
        )
        .where(Zahlungsplanposition.projekt_id.in_(ids))
        .group_by(Zahlungsplanposition.projekt_id)
    ).all()
    for projekt_id, fakturiert, offen in zeilen:
        summen[projekt_id] = (int(fakturiert or 0), int(offen or 0))

    from app.modelle import Kunde

    namen = dict(
        db.execute(
            select(Kunde.id, Kunde.name).where(Kunde.id.in_([p.kunde_id for p in projekte]))
        ).all()
    )

    eintraege = [
        Projektbestand(
            projekt_nr=p.projekt_nr,
            bezeichnung=p.bezeichnung,
            kunde=namen.get(p.kunde_id, "unbekannt"),
            status=p.status,
            pl_name=p.pl_name,
            ab_wert_cent=p.ab_wert_netto,
            nachtraege_cent=nachtraege.get(p.id, 0),
            fakturiert_cent=summen[p.id][0],
            zahlungsplan_offen_cent=summen[p.id][1],
        )
        for p in projekte
    ]
    # Größter offener Rest zuerst – dort steckt das Geld, um das es geht.
    eintraege.sort(key=lambda e: (e.rest_cent is None, -(e.rest_cent or 0), e.projekt_nr))
    return Auftragsbestand(projekte=eintraege)
