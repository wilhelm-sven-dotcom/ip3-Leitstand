"""Festschreibung eines Belegs: Nummer, Hash, Sperre, Ablage (PLAN §6.4, §10).

Die Festschreibung ist der eine unumkehrbare Schritt des ganzen Hauses. Danach ist der Beleg
unveränderbar – abgesichert durch Datenbank-Trigger, nicht nur durch diesen Code – und eine
Korrektur kostet einen eigenen Stornobeleg. Entsprechend genau ist die Reihenfolge:

1. **Vollständigkeit prüfen.** Alles Fehlende auf einmal, nicht der Reihe nach: nach der
   Festschreibung ist jede Nachbesserung ein Storno.
2. **Nummer ziehen**, in derselben Schreibtransaktion. Scheitert danach irgendetwas, rollt die
   Nummer mit zurück – eine fehlende Rechnungsnummer müsste sonst gegenüber dem Prüfer erklärt
   werden (PLAN §6.4). Der Jahresbezug kommt aus dem **Belegdatum**, nicht aus dem heutigen Tag:
   ein Beleg vom 31.12. gehört in den Kreis des alten Jahres, auch wenn er am 2.1. entsteht.
3. **Summen und Steueraufteilung schreiben**, damit das Papier und die Datenbank dieselben Zahlen
   zeigen.
4. **PDF und XML in den Speicher rendern.** Vor dem Statuswechsel: ein Renderfehler soll die
   Nummer noch zurückrollen können.
5. **Hash und Status in einem Zug.** Der Trigger
   ``trg_rechnungen_festgeschrieben_update`` verbietet jedes weitere UPDATE an einem
   festgeschriebenen Beleg – die Ablagepfade müssen also im selben Schreibvorgang stehen wie der
   Status, sonst ließen sie sich nachträglich nie eintragen.
6. **Dateien schreiben, nach dem Commit.** Scheitert das, ist der Beleg gültig und die Ablage
   fehlt. Das ist kein Widerspruch: der Hash deckt die Belegdaten ab, nicht die PDF-Bytes, und
   :func:`ablage_wiederholen` rendert aus den gespeicherten Daten dasselbe Dokument noch einmal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dienste.belegarten import BelegFehler, kreis_fuer, summen_setzen
from app.dienste.belege import (
    beleg_hash,
    fehlende_pflichtangaben,
    kunde_snapshot,
    summen_berechnen,
)
from app.dienste.nummernkreise import naechste_nummer
from app.fehler import FachFehler
from app.modelle import Rechnung, Zahlungsplanposition
from app.protokoll import logger
from app.zeit import jetzt_utc

log = logger(__name__)


class UnvollstaendigerBeleg(FachFehler):
    code = "beleg_unvollstaendig"
    status_code = 409


class AblageFehler(FachFehler):
    """Der Beleg ist festgeschrieben, die Datei konnte aber nicht abgelegt werden."""

    code = "beleg_ablage"
    status_code = 500


@dataclass
class Belegdateien:
    """Gerenderte Dokumente eines Belegs, noch im Speicher."""

    pdf_name: str
    pdf_bytes: bytes
    xml_name: str | None = None
    xml_bytes: bytes | None = None


@dataclass
class Ablagepfade:
    pdf_pfad: str | None = None
    xml_pfad: str | None = None


class Belegablage(Protocol):
    """Erzeugt die Dokumente eines Belegs und legt sie im Rechnungsordner ab.

    Getrennt in Rendern und Schreiben, weil das eine vor dem Commit passieren muss und das
    andere danach. Die Umsetzung steht in :mod:`app.belege`; hier steht nur, was gebraucht wird –
    so bleibt die Festschreibung ohne PDF-Werkzeug testbar.
    """

    def pfade(self, dateien: Belegdateien) -> Ablagepfade:
        """Wohin die Dateien kommen, ohne sie zu schreiben."""
        ...

    def rendern(self, beleg: Rechnung) -> Belegdateien: ...

    def schreiben(self, dateien: Belegdateien) -> Ablagepfade: ...


@dataclass
class Ergebnis:
    """Was die Festschreibung hinterlässt."""

    beleg: Rechnung
    dateien: Belegdateien | None = None
    ablage_offen: str | None = None
    freigegebene_positionen: list[int] = field(default_factory=list)
    berechnete_positionen: list[int] = field(default_factory=list)


def _positionen_zum_sperren(db: Session, beleg: Rechnung) -> list[Zahlungsplanposition]:
    """Welche Zahlungsplanpositionen dieser Beleg berechnet (PLAN §5).

    * **Abschlag**: genau die Positionen, auf die seine Rechnungspositionen zeigen.
    * **Schlussrechnung**: alle noch offenen Positionen des Projekts. Sie stellt die
      Gesamtleistung in Rechnung und setzt die Abschläge ab – danach ist am Projekt nichts mehr
      offen, und eine im Forecast stehengelassene Position wäre eine Erwartung, die niemand mehr
      erfüllt.
    * **Auftragsbestätigung**: keine. Eine AB ist keine Rechnung (PLAN §10); den Zahlungsplan zu
      sperren, weil eine Bestätigung gedruckt wurde, wäre falsch.
    """
    if beleg.art == "abschlag":
        ids = [p.zahlungsplan_id for p in beleg.positionen if p.zahlungsplan_id is not None]
        if not ids:
            return []
        return list(
            db.scalars(select(Zahlungsplanposition).where(Zahlungsplanposition.id.in_(ids)))
        )
    if beleg.art == "schluss" and beleg.projekt_id is not None:
        return list(
            db.scalars(
                select(Zahlungsplanposition).where(
                    Zahlungsplanposition.projekt_id == beleg.projekt_id,
                    Zahlungsplanposition.rechnung_id.is_(None),
                    Zahlungsplanposition.migriert_gestellt.is_not(True),
                )
            )
        )
    return []


def _absetzungen_fuer_hash(beleg: Rechnung) -> list[dict[str, object]]:
    return [
        {
            "rechnung_nr": eintrag.rechnung_nr,
            "datum": eintrag.datum.isoformat(),
            "netto": eintrag.netto,
            "ust_satz": eintrag.ust_satz,
            "ust": eintrag.ust,
        }
        for eintrag in sorted(beleg.absetzungen, key=lambda e: e.pos)
    ]


def festschreiben(
    db: Session,
    beleg: Rechnung,
    *,
    ablage: Belegablage | None = None,
    ausfuehrender: str | None = None,
) -> Ergebnis:
    """Beleg festschreiben. Muss innerhalb einer laufenden Schreibtransaktion aufgerufen werden.

    Der Aufrufer öffnet die Transaktion (``schreib_transaktion``), damit Nummernvergabe und Beleg
    gemeinsam stehen oder gemeinsam fallen. Die Dateien schreibt :func:`dateien_ablegen` **nach**
    dem Commit.
    """
    if beleg.status == "festgeschrieben":
        raise BelegFehler(
            f"Beleg {beleg.rechnung_nr} ist bereits festgeschrieben.",
            "Für eine Korrektur einen Storno oder eine Gutschrift erzeugen.",
        )
    if beleg.status == "storniert":
        raise BelegFehler(
            "Ein stornierter Beleg lässt sich nicht festschreiben.",
            "Den Beleg neu ausstellen.",
        )

    positionen = list(beleg.positionen)

    # 1. Vollständigkeit – alles auf einmal.
    if beleg.kunde is not None:
        beleg.kunde_snapshot = kunde_snapshot(beleg.kunde)
    fehlt = fehlende_pflichtangaben(beleg, positionen)
    if fehlt:
        raise UnvollstaendigerBeleg(
            "Dem Beleg fehlen Angaben, die eine Rechnung nach § 14 UStG tragen muss: "
            + ", ".join(fehlt)
            + ".",
            "Die genannten Angaben ergänzen und erneut festschreiben. Nach der Festschreibung "
            "wäre eine Korrektur nur noch über einen Stornobeleg möglich.",
            felder={"fehlend": ", ".join(fehlt)},
        )

    original = db.get(Rechnung, beleg.storno_ref) if beleg.storno_ref else None

    # 2. Nummer ziehen. Vor jedem Schreiben am Beleg selbst: die Vergabe löst ein flush aus,
    #    und der Beleg soll dabei noch als Entwurf in der Datenbank stehen.
    kreis = kreis_fuer(beleg, original)
    nummer = naechste_nummer(db, beleg.firma_id, kreis, jahr=beleg.datum.year)

    # 3. Summen und Steueraufteilung.
    summen = summen_berechnen(
        positionen,
        absetzung_netto=sum(e.netto for e in beleg.absetzungen),
        absetzung_ust=sum(e.ust for e in beleg.absetzungen),
    )
    beleg.rechnung_nr = nummer
    summen_setzen(beleg)
    db.flush()

    # 4. Dokumente rendern, solange noch alles zurückrollbar ist.
    dateien = ablage.rendern(beleg) if ablage is not None else None
    pfade = ablage.pfade(dateien) if (ablage is not None and dateien is not None) else Ablagepfade()

    # 5. Hash, Pfade, Zeitstempel und Status in einem Zug – danach sperrt der Trigger.
    beleg.hash = beleg_hash(beleg, positionen, summen, _absetzungen_fuer_hash(beleg))
    beleg.pdf_pfad = pfade.pdf_pfad
    beleg.xml_pfad = pfade.xml_pfad
    beleg.festgeschrieben_am = jetzt_utc()
    beleg.status = "festgeschrieben"

    berechnet: list[int] = []
    for position in _positionen_zum_sperren(db, beleg):
        position.rechnung_id = beleg.id
        berechnet.append(position.id)

    freigegeben: list[int] = []
    if beleg.art == "storno" and original is not None:
        freigegeben = _storno_wirksam_machen(db, beleg, original)

    db.flush()
    log.info(
        "Beleg festgeschrieben",
        extra={
            "rechnung_nr": nummer,
            "art": beleg.art,
            "zahlbetrag": beleg.zahlbetrag,
            "nutzer": ausfuehrender,
        },
    )
    return Ergebnis(
        beleg=beleg,
        dateien=dateien,
        berechnete_positionen=berechnet,
        freigegebene_positionen=freigegeben,
    )


def _storno_wirksam_machen(db: Session, storno: Rechnung, original: Rechnung) -> list[int]:
    """Ursprungsbeleg auf ``storniert`` setzen und seine Zahlungsplanpositionen freigeben.

    Der Trigger ``trg_rechnungen_storno_nur_status`` lässt genau diesen einen Weg offen: Status
    und ``storno_ref``, sonst nichts. Und ``trg_zahlungsplan_berechnet_update`` lässt das
    Zurücksetzen von ``rechnung_id`` auf NULL zu – das ist die Freigabe, damit die Position neu
    berechnet werden kann (PLAN §5).
    """
    freigegeben: list[int] = []
    for position in db.scalars(
        select(Zahlungsplanposition).where(Zahlungsplanposition.rechnung_id == original.id)
    ):
        position.rechnung_id = None
        freigegeben.append(position.id)
    db.flush()

    original.status = "storniert"
    original.storno_ref = storno.id
    db.flush()
    return freigegeben


def dateien_ablegen(ablage: Belegablage | None, ergebnis: Ergebnis) -> Ergebnis:
    """Dokumente nach dem Commit in den Rechnungsordner schreiben.

    Scheitert das, bleibt der Beleg gültig – die Nummer ist vergeben, der Hash steht. Der Aufrufer
    bekommt in ``ablage_offen`` eine Meldung, die auf dem Bildschirm stehen darf, und kann die
    Ablage später wiederholen.
    """
    if ablage is None or ergebnis.dateien is None:
        return ergebnis
    try:
        ablage.schreiben(ergebnis.dateien)
    except OSError as fehler:
        log.error(
            "Ablage des Belegs fehlgeschlagen",
            extra={"rechnung_nr": ergebnis.beleg.rechnung_nr, "fehler": str(fehler)},
        )
        ergebnis.ablage_offen = (
            f"Der Beleg {ergebnis.beleg.rechnung_nr} ist festgeschrieben, das PDF konnte aber "
            f"nicht im Rechnungsordner abgelegt werden ({fehler.strerror or fehler})."
        )
    return ergebnis


def ablage_wiederholen(db: Session, beleg: Rechnung, ablage: Belegablage) -> Ablagepfade:
    """Dokumente eines festgeschriebenen Belegs erneut erzeugen und ablegen.

    Zulässig, weil der Hash die Belegdaten abdeckt und nicht die PDF-Bytes: aus denselben Daten
    entsteht dasselbe Dokument. Geändert wird dabei nichts am Beleg – die Pfade stehen schon
    darin, sie werden nur wieder mit einer Datei belegt.
    """
    if beleg.status == "entwurf":
        raise BelegFehler(
            "Ein Entwurf hat noch keine Ablage.",
            "Den Beleg erst festschreiben; dabei entsteht das PDF.",
        )
    dateien = ablage.rendern(beleg)
    try:
        return ablage.schreiben(dateien)
    except OSError as fehler:
        raise AblageFehler(
            f"Das PDF zu {beleg.rechnung_nr} konnte nicht abgelegt werden "
            f"({fehler.strerror or fehler}).",
            "Prüfen, ob der Rechnungsordner erreichbar ist und das Dienstkonto dort schreiben "
            "darf. Der Beleg selbst bleibt gültig; die Ablage lässt sich danach erneut anstoßen.",
        ) from fehler
