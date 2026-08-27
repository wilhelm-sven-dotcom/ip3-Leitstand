"""Umsatz, Forecast und Auftragsbestand (PLAN §7 Phase 2).

Die Seite, auf der aus 280 Zahlungsplanpositionen eine Aussage wird: was ist abgerechnet, was
steht noch aus, und was ist vom Auftragsbestand offen. Gerechnet wird in
``app/dienste/auswertung.py`` – hier steht nur, wer fragen darf, welche Filter es gibt und wie die
Antwort aussieht.

**Die Berechtigung ist die Beträge.** ``umsatz.lesen`` heißt „Umsatz, Forecast und
Auftragsbestand ansehen"; wer sie hat, sieht hier Geld. Eine zusätzliche Prüfung auf
``projekte.werte_lesen`` gibt es deshalb nicht – wohl aber den Sichtbarkeits-Scope: wer nur eigene
Projekte sehen darf, bekommt auch nur deren Summen (PLAN §4).

**Der Ist ist in Phase 2 unvollständig, und das steht in der Antwort.** Die Auftragsliste führte
nur die offenen Positionen; bereits bezahlte Rechnungen aus 2026 stehen dort nicht und fehlen
darum im Ist. Solange Altpositionen im Ist stecken, liefert die Antwort einen Hinweis, den die
Oberfläche über dem Diagramm zeigt (Entscheidung Svens, docs/OFFENE-PUNKTE.md). Ab Phase 3 füllt
sich der Ist aus echten Belegen.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.dienste import auswertung
from app.modelle import Projekt, Zahlungsplanposition
from app.modelle.projekte import ANLAGENARTEN, PROJEKT_STATUS
from app.sicherheit.abhaengigkeiten import Zugriff, benoetigt, db_sitzung, scope_filter
from app.zeit import heute_ortszeit

router = APIRouter(prefix="/api/umsatz", tags=["Umsatz"])

LESEN = {
    401: {"description": "Nicht angemeldet"},
    403: {"description": "Berechtigung umsatz.lesen fehlt"},
}

# Erlaubte Werte der Filterleiste. Als Literal statt als freier Text: ein Tippfehler ergibt dann
# eine Meldung und nicht eine stillschweigend leere Auswertung, die wie „kein Umsatz" aussieht.
ANLAGENART_FILTER = ("alle", *ANLAGENARTEN)
STATUS_FILTER = ("alle", *PROJEKT_STATUS)

HINWEIS_ALTBESTAND = (
    "Der Ist enthält die Belege des Leitstands und die aus der Auftragsliste als „gestellt“ "
    "übernommenen Altpositionen. Rechnungen, die vor der Einführung des Leitstands bereits "
    "bezahlt waren, stehen in der Auftragsliste nicht und fehlen deshalb hier. Der Abgleich mit "
    "der Buchhaltung kommt mit dem DATEV-Import in Phase 4."
)


class MonatAntwort(BaseModel):
    monat: str
    ist_netto: int
    plan_netto: int
    summe_netto: int
    ist_anzahl: int
    plan_anzahl: int


class UnterminiertAntwort(BaseModel):
    """Positionen ohne Planmonat – auch gestellte (PLAN §7 Phase 2)."""

    ist_netto: int
    plan_netto: int
    summe_netto: int
    ist_anzahl: int
    plan_anzahl: int
    anzahl: int


class MonateAntwort(BaseModel):
    jahr: int
    monate: list[MonatAntwort]
    ist_netto: int
    plan_netto: int
    unterminiert: UnterminiertAntwort
    # Für die Filterleiste: was in den Daten vorkommt.
    jahre: list[int] = Field(default_factory=list)
    projektleiter: list[str] = Field(default_factory=list)
    # Sätze, die die Oberfläche über dem Diagramm zeigt.
    hinweise: list[str] = Field(default_factory=list)


class ProjektbestandAntwort(BaseModel):
    projekt_nr: int
    bezeichnung: str | None = None
    kunde: str
    status: str
    pl_name: str | None = None
    ab_wert_netto: int | None = None
    nachtraege_netto: int
    soll_netto: int | None = None
    fakturiert_netto: int
    rest_netto: int | None = None
    zahlungsplan_offen_netto: int


class AuftragsbestandAntwort(BaseModel):
    bestand_netto: int
    zahlungsplan_offen_netto: int
    # Bestand minus offener Zahlungsplan: bei Altprojekten der Teil, den die Auftragsliste nicht
    # als Abschlag führte. Erklärt, warum Kachel und Diagramm nicht dieselbe Zahl zeigen.
    nicht_verplant_netto: int
    projekte: list[ProjektbestandAntwort] = Field(default_factory=list)
    # Projekte ohne Auftragswert tragen nichts zum Bestand bei – das gehört gesagt, nicht
    # verschwiegen.
    ohne_auftragswert: list[ProjektbestandAntwort] = Field(default_factory=list)
    # Mehr abgerechnet als beauftragt: der Auftragswert stimmt vermutlich nicht.
    zu_pruefen: list[ProjektbestandAntwort] = Field(default_factory=list)
    projektleiter: list[str] = Field(default_factory=list)


def _sichtbare_projekte(
    zugriff: Zugriff,
    *,
    projektleiter: str = "alle",
    anlagenart: str = "alle",
    status: str = "alle",
) -> Select:
    """Projektauswahl, auf die sich alle Zahlen einer Antwort beziehen.

    Der Scope kommt zuerst: ``scope_filter`` schränkt auf die eigenen Projekte ein, wenn der
    Nutzer nur die sehen darf. Danach die Filter der Leiste – dieselben wie in der Projektliste,
    damit die Bedienung nicht je Seite anders ist.
    """
    abfrage = scope_filter(select(Projekt), zugriff, "projekte.lesen", Projekt.pl_user_id)
    if projektleiter != "alle":
        abfrage = abfrage.where(Projekt.pl_name == projektleiter)
    if anlagenart != "alle":
        abfrage = abfrage.where(Projekt.anlagenart == anlagenart)
    if status != "alle":
        abfrage = abfrage.where(Projekt.status == status)
    return abfrage


def _projektleiter(db: Session, sichtbar: Select) -> list[str]:
    """Namen aus den Daten, nicht fest verdrahtet."""
    zeilen = db.execute(
        sichtbar.with_only_columns(Projekt.pl_name).where(Projekt.pl_name.is_not(None)).distinct()
    ).all()
    return sorted({zeile[0] for zeile in zeilen if zeile[0]})


def _hat_altbestand_im_ist(db: Session, sichtbar: Select) -> bool:
    """Ob im Ist übernommene Altpositionen stecken – dann gilt der Hinweis oben."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Zahlungsplanposition)
            .join(Projekt, Projekt.id == Zahlungsplanposition.projekt_id)
            .where(
                Projekt.id.in_(sichtbar.with_only_columns(Projekt.id)),
                Zahlungsplanposition.migriert_gestellt.is_(True),
            )
        )
        or 0
    ) > 0


@router.get(
    "/monate",
    response_model=MonateAntwort,
    summary="Umsatz je Monat als Ist und Plan",
    operation_id="umsatzMonate",
    responses=LESEN,
)
def monate(
    zugriff: Zugriff = Depends(benoetigt("umsatz.lesen")),
    db: Session = Depends(db_sitzung),
    jahr: int | None = Query(None, ge=2000, le=2100, description="Standard: laufendes Jahr"),
    projektleiter: str = Query("alle"),
    anlagenart: Literal[ANLAGENART_FILTER] = Query("alle"),  # type: ignore[valid-type]
    status: Literal[STATUS_FILTER] = Query("alle"),  # type: ignore[valid-type]
) -> MonateAntwort:
    """Jahresverlauf mit zwölf Monaten – auch die leeren.

    Ein Jahr ohne Positionen ist kein Fehler, sondern eine Auskunft: zwölf Nullen und die
    unterminierten Positionen, die an keinem Jahr hängen.
    """
    gewaehltes_jahr = jahr if jahr is not None else heute_ortszeit().year
    sichtbar = _sichtbare_projekte(
        zugriff, projektleiter=projektleiter, anlagenart=anlagenart, status=status
    )
    verlauf = auswertung.jahresverlauf(db, sichtbar, gewaehltes_jahr)

    hinweise: list[str] = []
    if _hat_altbestand_im_ist(db, sichtbar):
        hinweise.append(HINWEIS_ALTBESTAND)

    return MonateAntwort(
        jahr=verlauf.jahr,
        monate=[
            MonatAntwort(
                monat=m.monat,
                ist_netto=m.ist_cent,
                plan_netto=m.plan_cent,
                summe_netto=m.summe_cent,
                ist_anzahl=m.ist_anzahl,
                plan_anzahl=m.plan_anzahl,
            )
            for m in verlauf.monate
        ],
        ist_netto=verlauf.ist_cent,
        plan_netto=verlauf.plan_cent,
        unterminiert=UnterminiertAntwort(
            ist_netto=verlauf.unterminiert.ist_cent,
            plan_netto=verlauf.unterminiert.plan_cent,
            summe_netto=verlauf.unterminiert.summe_cent,
            ist_anzahl=verlauf.unterminiert.ist_anzahl,
            plan_anzahl=verlauf.unterminiert.plan_anzahl,
            anzahl=verlauf.unterminiert.anzahl,
        ),
        jahre=auswertung.jahre_mit_daten(db, sichtbar),
        projektleiter=_projektleiter(db, sichtbar),
        hinweise=hinweise,
    )


def _bestand_zeile(eintrag: auswertung.Projektbestand) -> ProjektbestandAntwort:
    return ProjektbestandAntwort(
        projekt_nr=eintrag.projekt_nr,
        bezeichnung=eintrag.bezeichnung,
        kunde=eintrag.kunde,
        status=eintrag.status,
        pl_name=eintrag.pl_name,
        ab_wert_netto=eintrag.ab_wert_cent,
        nachtraege_netto=eintrag.nachtraege_cent,
        soll_netto=eintrag.soll_cent,
        fakturiert_netto=eintrag.fakturiert_cent,
        rest_netto=eintrag.rest_cent,
        zahlungsplan_offen_netto=eintrag.zahlungsplan_offen_cent,
    )


@router.get(
    "/auftragsbestand",
    response_model=AuftragsbestandAntwort,
    summary="Offener Auftragsbestand gesamt und je Projekt",
    operation_id="umsatzAuftragsbestand",
    responses=LESEN,
)
def auftragsbestand(
    zugriff: Zugriff = Depends(benoetigt("umsatz.lesen")),
    db: Session = Depends(db_sitzung),
    projektleiter: str = Query("alle"),
    anlagenart: Literal[ANLAGENART_FILTER] = Query("alle"),  # type: ignore[valid-type]
) -> AuftragsbestandAntwort:
    """Auftragswert plus beauftragte Nachträge minus dem, was schon abgerechnet ist.

    Nur laufende Projekte (``beauftragt``, ``in_bau``) – ein Angebot ist kein Auftrag, ein
    abgeschlossenes Projekt kein Bestand. Einen Statusfilter gibt es hier deshalb nicht.
    """
    sichtbar = _sichtbare_projekte(zugriff, projektleiter=projektleiter, anlagenart=anlagenart)
    bestand = auswertung.auftragsbestand(db, sichtbar)
    return AuftragsbestandAntwort(
        bestand_netto=bestand.bestand_cent,
        zahlungsplan_offen_netto=bestand.zahlungsplan_offen_cent,
        nicht_verplant_netto=bestand.nicht_verplant_cent,
        projekte=[_bestand_zeile(e) for e in bestand.projekte],
        ohne_auftragswert=[_bestand_zeile(e) for e in bestand.ohne_auftragswert],
        zu_pruefen=[_bestand_zeile(e) for e in bestand.zu_pruefen],
        projektleiter=_projektleiter(db, sichtbar),
    )
