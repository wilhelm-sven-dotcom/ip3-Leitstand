"""Anlagenregister-Automatik und Gewährleistung (PLAN §6.9, §7 Phase 6).

Wechselt ein Projekt auf ``abgeschlossen``, entsteht daraus eine Anlage: der Bezugspunkt für
Service, Wartung und Gewährleistung. Die Stammdaten kommen aus dem Projekt, die Termine aus den
Meilensteinen.

Drei Festlegungen tragen das:

* **Die Gewährleistungsfrist hängt an der Vertragsart.** VOB/B sind vier Jahre, BGB fünf
  (§ 634a Abs. 1 Nr. 2 BGB, § 13 Abs. 4 VOB/B). Vorbelegt wird nach Kundentyp – gegenüber
  Verbrauchern gilt ohnehin BGB, weil VOB/B dort selten wirksam vereinbart wird –, beim
  Abschluss ist die Wahl aber änderbar (Entscheidung 32). Die Vorbelegung steht in der
  ``config.toml``, nicht im Code.
* **Gerechnet wird ab Abnahme**, nicht ab Inbetriebnahme oder Rechnungsdatum: die Frist beginnt
  mit der Abnahme (§ 634a Abs. 2 BGB). Fehlt das Abnahmedatum, entsteht die Anlage trotzdem –
  ohne Gewährleistungsfrist und mit einem Hinweis, denn ein erfundenes Datum wäre schlimmer als
  eine fehlende Überwachung.
* **Eine zweite Anlage entsteht nie.** Ein Projekt, das erneut auf ``abgeschlossen`` wechselt,
  aktualisiert die vorhandene Anlage, statt eine Dublette anzulegen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelle import Anlage, Frist, Meilenstein, Projekt

# Vertragsarten und ihre Gewährleistungsdauer in Jahren.
VERTRAGSARTEN: dict[str, int] = {"vob": 4, "bgb": 5}

# Wie lange vor Ablauf die Frist auf der Startseite erscheint: drei Monate (PLAN §6.9).
GEWAEHRLEISTUNG_VORLAUF_TAGE = 90

FRIST_GEWAEHRLEISTUNG = "gewaehrleistung"


def vertragsart_vorbelegen(kundentyp: str | None, vorbelegung: dict[str, str]) -> str:
    """Vertragsart nach Kundentyp, aus der Konfiguration (Entscheidung 32).

    Gegenüber Verbrauchern (``b2c``) gilt BGB: VOB/B wird dort nur wirksam, wenn sie im Ganzen
    vereinbart ist, und das ist im Privatkundengeschäft die Ausnahme.
    """
    gewaehlt = vorbelegung.get(kundentyp or "", "")
    return gewaehlt if gewaehlt in VERTRAGSARTEN else "bgb"


def gewaehrleistung_ende(abnahme: date | None, vertragsart: str) -> date | None:
    """Ende der Gewährleistung: Abnahme plus vier (VOB) oder fünf Jahre (BGB).

    ``None`` ohne Abnahmedatum – lieber keine Frist als eine erfundene.
    """
    if abnahme is None:
        return None
    jahre = VERTRAGSARTEN.get(vertragsart, VERTRAGSARTEN["bgb"])
    try:
        return abnahme.replace(year=abnahme.year + jahre)
    except ValueError:
        # 29. Februar: das Zieljahr hat keinen. Der 1. März ist der nächste Tag, an dem die
        # Frist sicher abgelaufen ist – einen Tag zu spät zu erinnern wäre der teurere Fehler.
        return date(abnahme.year + jahre, 3, 1)


def meilenstein_datum(sitzung: Session, projekt_id: int, typ: str) -> date | None:
    """Erledigungsdatum eines Meilensteins, oder ``None``.

    ``erledigt_am`` und nicht ``erledigt``: die Teamliste kennt nur Kreuze, und ein Kreuz ohne
    Datum sagt nicht, wann. Für eine Frist zählt aber genau das Wann.
    """
    return sitzung.scalar(
        select(Meilenstein.erledigt_am).where(
            Meilenstein.projekt_id == projekt_id,
            Meilenstein.typ == typ,
            Meilenstein.erledigt_am.is_not(None),
        )
    )


@dataclass
class Anlagenergebnis:
    """Was beim Abschluss eines Projekts entstanden ist."""

    anlage: Anlage
    neu: bool
    vertragsart: str
    hinweise: list[str] = field(default_factory=list)


def aus_projekt(
    sitzung: Session,
    projekt: Projekt,
    *,
    vertragsart: str,
    vorlauf_tage: int = GEWAEHRLEISTUNG_VORLAUF_TAGE,
) -> Anlagenergebnis:
    """Anlage zum Projekt anlegen oder aktualisieren und die Gewährleistungsfrist setzen.

    Muss in einer Schreibtransaktion laufen. Wird beim Wechsel auf ``abgeschlossen`` gerufen
    (PLAN §6.9); ein zweiter Aufruf aktualisiert, statt eine Dublette anzulegen.
    """
    if vertragsart not in VERTRAGSARTEN:
        vertragsart = "bgb"

    abnahme = meilenstein_datum(sitzung, projekt.id, "abnahme")
    inbetriebnahme = meilenstein_datum(sitzung, projekt.id, "inbetriebnahme")
    ende = gewaehrleistung_ende(abnahme, vertragsart)

    anlage = sitzung.scalar(select(Anlage).where(Anlage.projekt_id_ursprung == projekt.id))
    neu = anlage is None
    if anlage is None:
        anlage = Anlage(projekt_id_ursprung=projekt.id, kunde_id=projekt.kunde_id)
        sitzung.add(anlage)

    anlage.kunde_id = projekt.kunde_id
    anlage.standort = projekt.standort
    anlage.pv_kwp = projekt.pv_kwp
    anlage.speicher_kwh = projekt.speicher_kwh
    anlage.inbetriebnahme = inbetriebnahme
    anlage.abnahme_datum = abnahme
    anlage.gewaehrleistung_ende = ende
    sitzung.flush()

    ergebnis = Anlagenergebnis(anlage=anlage, neu=neu, vertragsart=vertragsart)

    if ende is None:
        ergebnis.hinweise.append(
            "Für dieses Projekt ist kein Abnahmedatum erfasst. Die Anlage ist angelegt, die "
            "Gewährleistungsfrist bleibt offen – sie beginnt mit der Abnahme (§ 634a BGB). "
            "Nächster Schritt: den Meilenstein „Abnahme“ mit Datum nachtragen."
        )
    else:
        frist_setzen(
            sitzung,
            bezug="anlage",
            bezug_id=anlage.id,
            typ=FRIST_GEWAEHRLEISTUNG,
            bezeichnung=(
                f"Gewährleistung endet ({'VOB, 4' if vertragsart == 'vob' else 'BGB, 5'} Jahre "
                f"ab Abnahme {abnahme:%d.%m.%Y})"
            ),
            faellig_am=ende,
            vorlauf_tage=vorlauf_tage,
        )

    if inbetriebnahme is None:
        ergebnis.hinweise.append(
            "Kein Inbetriebnahmedatum erfasst. Ohne es lässt sich die Frist zur "
            "MaStR-Registrierung nicht überwachen."
        )
    return ergebnis


def frist_setzen(
    sitzung: Session,
    *,
    bezug: str,
    bezug_id: int,
    typ: str,
    bezeichnung: str,
    faellig_am: date,
    vorlauf_tage: int,
) -> tuple[Frist, bool]:
    """Frist anlegen oder die vorhandene desselben Typs aktualisieren.

    Je Bezug und Typ genau eine Frist: verschiebt sich das Abnahmedatum, soll das
    Gewährleistungsende mitwandern und nicht als zweite Zeile daneben stehen. Eine bereits
    erledigte Frist wird nicht wieder aufgemacht – wer sie abgehakt hat, hat es getan.

    Zurück kommt die Frist und ob sie **neu** ist. Der nächtliche Lauf meldet sonst jede Nacht
    „2 Fristen gesetzt", obwohl er nur bestätigt hat, was schon dastand.
    """
    vorhanden = sitzung.scalar(
        select(Frist).where(
            Frist.bezug == bezug,
            Frist.bezug_id == bezug_id,
            Frist.typ == typ,
            Frist.erledigt_am.is_(None),
        )
    )
    neu = vorhanden is None
    if vorhanden is None:
        vorhanden = Frist(bezug=bezug, bezug_id=bezug_id, typ=typ)
        sitzung.add(vorhanden)

    vorhanden.bezeichnung = bezeichnung
    vorhanden.faellig_am = faellig_am
    vorhanden.vorlauf_tage = vorlauf_tage
    sitzung.flush()
    return vorhanden, neu


def ohne_wartungsvertrag(sitzung: Session) -> list[Anlage]:
    """Anlagen ohne Wartungsvertrag, die jüngste zuerst (PLAN §7 Phase 6).

    Die Liste, aus der Servicegeschäft entsteht: jede Anlage hier ist ein Kunde, der noch keinen
    Wartungsvertrag hat.
    """
    return list(
        sitzung.scalars(
            select(Anlage)
            .where(Anlage.wartungsvertrag.is_(False))
            .order_by(Anlage.inbetriebnahme.desc().nullslast(), Anlage.id.desc())
        )
    )
