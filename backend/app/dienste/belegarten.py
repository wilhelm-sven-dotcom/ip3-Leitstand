"""Belege erzeugen: AB, Abschlag, Schlussrechnung, Servicerechnung, Storno, Gutschrift.

Hier entsteht aus einem Projekt, einer Zahlungsplanposition oder freien Angaben ein **Entwurf**.
Nummer, Hash und Sperre kommen erst mit :mod:`app.dienste.festschreibung`; bis dahin ist alles
änderbar – das ist der Sinn eines Entwurfs.

Zwei Regeln prägen dieses Modul:

* **Die Schlussrechnung hat keinen Weg am Absetzungsblock vorbei** (PLAN §6.1). § 14 Abs. 5 UStG
  verlangt, dass jede vorher berechnete Abschlagszahlung einzeln mit Netto und darauf
  entfallender Umsatzsteuer abgesetzt wird; fehlt das, ist der Steuerausweis unrichtig
  (§ 14c UStG). :func:`schlussrechnung` baut den Block deshalb immer – es gibt keinen Schalter,
  ihn wegzulassen.
* **Altprojekte bekommen keine Schlussrechnung** (Entscheidung 16, docs/OFFENE-PUNKTE.md). Zu
  den aus der Auftragsliste übernommenen, als „gestellt" gekennzeichneten Positionen kennt der
  Leitstand nur das Netto – keine Rechnungsnummer, kein Datum, keinen Steuersatz. Ein
  Absetzungsblock daraus wäre unvollständig und damit falsch. Abschlagsrechnungen bleiben auf
  denselben Projekten erlaubt: ein Abschlag braucht keinen Absetzungsblock.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dienste.auswertung import NACHTRAG_ZAEHLT
from app.dienste.belege import faelligkeit, kunde_snapshot, summen_berechnen
from app.fehler import FachFehler, NichtGefunden
from app.geld import formatiere_euro
from app.modelle import (
    Absetzung,
    Kunde,
    Nachtrag,
    Projekt,
    Rechnung,
    Rechnungsposition,
    Zahlungsplanposition,
)
from app.modelle.fakturierung import KORREKTURARTEN, KREIS_JE_ART
from app.zeit import heute_ortszeit

# Steuersatz je Kennzeichen in Promille (PLAN §6.2). 'gemischt' hat bewusst keinen Eintrag:
# dort muss der Satz je Position gesetzt werden, ein Default wäre eine stille Annahme.
SATZ_JE_KENNZEICHEN: dict[str, int] = {"19": 190, "0": 0, "13b": 0}

# Belegarten, die im Absetzungsblock einer Schlussrechnung erscheinen.
ABZUSETZENDE_ART = "abschlag"


class BelegFehler(FachFehler):
    code = "beleg"
    status_code = 409


def steuersatz(ust_kz: str) -> int:
    """Vorbelegter Steuersatz eines Belegs. Bei ``gemischt`` bleibt es beim Regelsatz je Position.

    Für ``gemischt`` gibt es keinen richtigen Default – die Vorbelegung ist deshalb der
    Regelsatz, und :func:`app.dienste.belege.fehlende_pflichtangaben` verlangt beim
    Festschreiben, dass jede Position ausdrücklich einen Satz trägt.
    """
    return SATZ_JE_KENNZEICHEN.get(ust_kz, 190)


def kreis_fuer(beleg: Rechnung, original: Rechnung | None = None) -> str:
    """Nummernkreis eines Belegs (PLAN §3).

    Storno und Gutschrift erben den Kreis des Belegs, den sie korrigieren – sonst liefe die
    Korrektur einer Servicerechnung im Rechnungskreis der Projekte.
    """
    if beleg.art in KORREKTURARTEN:
        if original is None:
            raise BelegFehler(
                "Zu diesem Korrekturbeleg fehlt der Beleg, den er korrigiert.",
                "Den Storno oder die Gutschrift neu aus dem Ursprungsbeleg erzeugen.",
            )
        return kreis_fuer(original)
    return KREIS_JE_ART[beleg.art]


def altabschlaege(db: Session, projekt_id: int) -> list[Zahlungsplanposition]:
    """Positionen des Altbestands, zu denen es keinen Beleg im Leitstand gibt."""
    return list(
        db.scalars(
            select(Zahlungsplanposition)
            .where(
                Zahlungsplanposition.projekt_id == projekt_id,
                Zahlungsplanposition.migriert_gestellt.is_(True),
            )
            .order_by(Zahlungsplanposition.pos_nr)
        )
    )


def festgeschriebene_abschlaege(db: Session, projekt_id: int) -> list[Rechnung]:
    """Alle festgeschriebenen, nicht stornierten Abschläge eines Projekts, älteste zuerst."""
    return list(
        db.scalars(
            select(Rechnung)
            .where(
                Rechnung.projekt_id == projekt_id,
                Rechnung.art == ABZUSETZENDE_ART,
                Rechnung.status == "festgeschrieben",
            )
            .order_by(Rechnung.rechnung_nr)
        )
    )


def _projekt_holen(db: Session, projekt_id: int) -> Projekt:
    projekt = db.get(Projekt, projekt_id)
    if projekt is None:
        raise NichtGefunden("Das Projekt wurde nicht gefunden.", "Die Projektliste öffnen.")
    if projekt.status == "storniert":
        raise BelegFehler(
            f"Projekt {projekt.projekt_nr} ist storniert; dazu entsteht kein Beleg.",
            "Wenn das Projekt doch abgerechnet wird: zuerst den Status zurücksetzen.",
        )
    return projekt


def _kunde_holen(db: Session, kunde_id: int) -> Kunde:
    kunde = db.get(Kunde, kunde_id)
    if kunde is None:
        raise NichtGefunden("Der Kunde wurde nicht gefunden.", "Die Kundenliste öffnen.")
    return kunde


def _entwurf(
    projekt: Projekt | None,
    kunde: Kunde,
    art: str,
    datum: date,
    firma_id: int,
    ust_kz: str,
    betreff: str | None = None,
    leistungszeitraum: str | None = None,
    erstellt_von: str | None = None,
) -> Rechnung:
    """Belegkopf mit allem, was ohne Positionen feststeht."""
    return Rechnung(
        firma_id=firma_id,
        art=art,
        projekt_id=projekt.id if projekt else None,
        kunde_id=kunde.id,
        kunde_snapshot=kunde_snapshot(kunde),
        ust_kz=ust_kz,
        datum=datum,
        faellig_am=faelligkeit(datum, kunde),
        betreff=betreff,
        leistungszeitraum=leistungszeitraum,
        status="entwurf",
        erstellt_von=erstellt_von,
    )


def summen_setzen(beleg: Rechnung) -> None:
    """Summen des Belegs aus seinen Positionen und dem Absetzungsblock neu berechnen.

    Wird nach jeder Änderung an Positionen aufgerufen, damit die Liste und die Vorschau nicht
    veraltete Beträge zeigen. Beim Festschreiben läuft dieselbe Rechnung noch einmal – dort ist
    sie verbindlich.
    """
    absetzung_netto = sum(eintrag.netto for eintrag in beleg.absetzungen)
    absetzung_ust = sum(eintrag.ust for eintrag in beleg.absetzungen)
    summen = summen_berechnen(list(beleg.positionen), absetzung_netto, absetzung_ust)
    beleg.netto = summen.netto
    beleg.ust = summen.ust
    beleg.brutto = summen.brutto
    beleg.ust_details = summen.ust_details()
    beleg.absetzung_netto = summen.absetzung_netto
    beleg.absetzung_ust = summen.absetzung_ust
    beleg.zahlbetrag = summen.zahlbetrag


# ---------------------------------------------------------------------------------------------
# Auftragsbestätigung
# ---------------------------------------------------------------------------------------------


def ab_aus_projekt(
    db: Session, projekt_id: int, datum: date | None = None, erstellt_von: str | None = None
) -> Rechnung:
    """Auftragsbestätigung aus Projekt und Zahlungsplan (PLAN §7 Phase 3).

    Die AB ist keine Rechnung: sie bestätigt den Auftrag und listet die vereinbarten Zahlungen.
    Sie läuft im eigenen Kreis ``AB`` und unterliegt keiner Lückenlosigkeitspflicht (PLAN §10),
    bekommt aber dieselbe Festschreibung – auch eine AB soll nach dem Versand unverändert sein.
    """
    projekt = _projekt_holen(db, projekt_id)
    kunde = _kunde_holen(db, projekt.kunde_id)
    belegdatum = datum or heute_ortszeit()

    beleg = _entwurf(
        projekt,
        kunde,
        art="ab",
        datum=belegdatum,
        firma_id=projekt.firma_id,
        ust_kz=projekt.ust_kz,
        betreff=f"Auftragsbestätigung Projekt {projekt.projekt_nr}",
        erstellt_von=erstellt_von,
    )
    satz = steuersatz(projekt.ust_kz)
    positionen = list(
        db.scalars(
            select(Zahlungsplanposition)
            .where(Zahlungsplanposition.projekt_id == projekt.id)
            .order_by(Zahlungsplanposition.pos_nr)
        )
    )
    if not positionen and projekt.ab_wert_netto:
        # Ohne Zahlungsplan steht wenigstens der Auftragswert auf der Bestätigung – sonst wäre
        # es eine Bestätigung ohne Betrag.
        beleg.positionen.append(
            Rechnungsposition(
                pos=1,
                bezeichnung=f"Leistungen laut Angebot, Projekt {projekt.projekt_nr}",
                menge=1,
                ep_netto=projekt.ab_wert_netto,
                ust_satz=satz,
            )
        )
    for nummer, position in enumerate(positionen, start=1):
        beleg.positionen.append(
            Rechnungsposition(
                pos=nummer,
                bezeichnung=position.bezeichnung,
                menge=1,
                ep_netto=position.betrag_netto,
                ust_satz=satz,
                zahlungsplan_id=position.id,
            )
        )
    summen_setzen(beleg)
    return beleg


# ---------------------------------------------------------------------------------------------
# Abschlagsrechnung
# ---------------------------------------------------------------------------------------------


def abschlag_aus_position(
    db: Session,
    position_id: int,
    datum: date | None = None,
    leistungszeitraum: str | None = None,
    erstellt_von: str | None = None,
) -> Rechnung:
    """Abschlagsrechnung aus einer Zahlungsplanposition (PLAN §7 Phase 3).

    Die Verknüpfung zur Position entsteht erst beim Festschreiben: eine Position, die an einem
    Entwurf hinge, wäre gesperrt, obwohl noch gar keine Rechnung existiert.
    """
    position = db.get(Zahlungsplanposition, position_id)
    if position is None:
        raise NichtGefunden(
            "Die Zahlungsplanposition wurde nicht gefunden.",
            "Den Zahlungsplan des Projekts öffnen.",
        )
    if position.rechnung_id is not None:
        raise BelegFehler(
            f"Position {position.pos_nr} „{position.bezeichnung}“ ist bereits berechnet.",
            "Wenn die Rechnung falsch war: zuerst den Beleg stornieren, dann ist die Position "
            "wieder frei.",
        )
    if position.migriert_gestellt:
        raise BelegFehler(
            f"Position {position.pos_nr} „{position.bezeichnung}“ wurde vor der Einführung des "
            "Leitstands bereits gestellt.",
            "Wenn das nicht stimmt: das Kennzeichen „gestellt“ am Zahlungsplan zurücknehmen, "
            "dann lässt sich der Abschlag erzeugen.",
        )

    projekt = _projekt_holen(db, position.projekt_id)
    kunde = _kunde_holen(db, projekt.kunde_id)
    belegdatum = datum or heute_ortszeit()
    nummer = len(festgeschriebene_abschlaege(db, projekt.id)) + 1

    beleg = _entwurf(
        projekt,
        kunde,
        art="abschlag",
        datum=belegdatum,
        firma_id=projekt.firma_id,
        ust_kz=projekt.ust_kz,
        betreff=f"{nummer}. Abschlagsrechnung",
        leistungszeitraum=leistungszeitraum,
        erstellt_von=erstellt_von,
    )
    beleg.abschlag_nr = nummer
    beleg.positionen.append(
        Rechnungsposition(
            pos=1,
            bezeichnung=position.bezeichnung,
            menge=1,
            ep_netto=position.betrag_netto,
            ust_satz=steuersatz(projekt.ust_kz),
            zahlungsplan_id=position.id,
        )
    )
    summen_setzen(beleg)
    return beleg


# ---------------------------------------------------------------------------------------------
# Schlussrechnung
# ---------------------------------------------------------------------------------------------


def schlussrechnung(
    db: Session,
    projekt_id: int,
    datum: date | None = None,
    leistungszeitraum: str | None = None,
    erstellt_von: str | None = None,
) -> Rechnung:
    """Schlussrechnung mit Absetzungsblock nach § 14 Abs. 5 UStG (PLAN §6.1).

    Die Gesamtleistung wird aus Auftragswert und beauftragten Nachträgen vorbelegt – nicht aus
    dem Zahlungsplan. Der Zahlungsplan ist die Zerlegung in Abschläge, nicht der Leistungsumfang;
    bei den migrierten Projekten führt er ohnehin nur die offenen Positionen. Alles daran ist
    danach änderbar, solange der Beleg ein Entwurf ist.

    Abgesetzt werden alle festgeschriebenen, nicht stornierten Abschläge des Projekts, jeder mit
    Nummer, Datum, Netto und darauf entfallender Umsatzsteuer.
    """
    projekt = _projekt_holen(db, projekt_id)

    alt = altabschlaege(db, projekt.id)
    if alt:
        betraege = ", ".join(f"Pos. {p.pos_nr} {formatiere_euro(p.betrag_netto)}" for p in alt[:5])
        weitere = f" und {len(alt) - 5} weitere" if len(alt) > 5 else ""
        raise BelegFehler(
            f"Projekt {projekt.projekt_nr} hat {len(alt)} Abschläge, die vor der Einführung des "
            f"Leitstands gestellt wurden ({betraege}{weitere}). Zu ihnen sind Rechnungsnummer, "
            "Datum und Steuersatz nicht bekannt.",
            "Eine Schlussrechnung muss alle vorher berechneten Abschläge einzeln absetzen "
            "(§ 14 Abs. 5 UStG). Solange diese Angaben fehlen, wird sie außerhalb des Leitstands "
            "geschrieben – wie bisher. Abschlagsrechnungen sind für dieses Projekt weiter "
            "möglich.",
            code="altabschlaege_ohne_beleg",
        )

    kunde = _kunde_holen(db, projekt.kunde_id)
    belegdatum = datum or heute_ortszeit()
    satz = steuersatz(projekt.ust_kz)

    beleg = _entwurf(
        projekt,
        kunde,
        art="schluss",
        datum=belegdatum,
        firma_id=projekt.firma_id,
        ust_kz=projekt.ust_kz,
        betreff="Schlussrechnung",
        leistungszeitraum=leistungszeitraum,
        erstellt_von=erstellt_von,
    )

    laufend = 1
    if projekt.ab_wert_netto:
        beleg.positionen.append(
            Rechnungsposition(
                pos=laufend,
                bezeichnung=(
                    f"Errichtung der Anlage laut Auftrag, Projekt {projekt.projekt_nr}"
                    if projekt.auftrag_vom is None
                    else f"Errichtung der Anlage laut Auftrag vom "
                    f"{projekt.auftrag_vom.strftime('%d.%m.%Y')}"
                ),
                menge=1,
                ep_netto=projekt.ab_wert_netto,
                ust_satz=satz,
            )
        )
        laufend += 1
    for nachtrag in db.scalars(
        select(Nachtrag)
        .where(Nachtrag.projekt_id == projekt.id, Nachtrag.status.in_(NACHTRAG_ZAEHLT))
        .order_by(Nachtrag.id)
    ):
        beleg.positionen.append(
            Rechnungsposition(
                pos=laufend,
                bezeichnung=f"Nachtrag: {nachtrag.bezeichnung}",
                menge=1,
                ep_netto=nachtrag.betrag_netto,
                ust_satz=satz,
            )
        )
        laufend += 1

    absetzungsblock_aufbauen(db, beleg, projekt.id)
    summen_setzen(beleg)
    return beleg


def absetzungsblock_aufbauen(db: Session, beleg: Rechnung, projekt_id: int) -> None:
    """Alle festgeschriebenen Abschläge des Projekts in den Absetzungsblock übernehmen.

    Die Steueraufteilung wird aus ``ust_details`` des Abschlags gelesen, nicht neu gerechnet: der
    abgesetzte Betrag muss der sein, der auf dem Abschlag stand. Fehlt die Aufteilung – etwa bei
    einem sehr alten Beleg –, wird ersatzweise die Belegsumme mit dem Kennzeichensatz angesetzt
    und das im Protokoll vermerkt.
    """
    beleg.absetzungen.clear()
    pos = 1
    for abschlag in festgeschriebene_abschlaege(db, projekt_id):
        aufteilung = abschlag.ust_details or [
            {"satz": steuersatz(abschlag.ust_kz), "netto": abschlag.netto, "ust": abschlag.ust}
        ]
        for anteil in aufteilung:
            beleg.absetzungen.append(
                Absetzung(
                    abschlag_id=abschlag.id,
                    pos=pos,
                    rechnung_nr=abschlag.rechnung_nr or "",
                    datum=abschlag.datum,
                    netto=int(anteil["netto"]),
                    ust_satz=int(anteil["satz"]),
                    ust=int(anteil["ust"]),
                )
            )
            pos += 1


# ---------------------------------------------------------------------------------------------
# Servicerechnung
# ---------------------------------------------------------------------------------------------


def servicerechnung(
    db: Session,
    kunde_id: int,
    firma_id: int,
    projekt_id: int | None = None,
    datum: date | None = None,
    leistungszeitraum: str | None = None,
    ust_kz: str = "19",
    erstellt_von: str | None = None,
) -> Rechnung:
    """Servicerechnung mit freien Positionen (PLAN §7 Phase 3).

    Läuft im eigenen Kreis ``SR``. Ein Projektbezug ist möglich (Serviceauftrag mit eigener
    Nummer ``9JJNN``), aber nicht nötig – eine Servicerechnung kann auch ohne Auftrag entstehen.
    """
    kunde = _kunde_holen(db, kunde_id)
    projekt = _projekt_holen(db, projekt_id) if projekt_id is not None else None
    beleg = _entwurf(
        projekt,
        kunde,
        art="service",
        datum=datum or heute_ortszeit(),
        firma_id=firma_id,
        ust_kz=projekt.ust_kz if projekt is not None else ust_kz,
        betreff="Servicerechnung",
        leistungszeitraum=leistungszeitraum,
        erstellt_von=erstellt_von,
    )
    summen_setzen(beleg)
    return beleg


# ---------------------------------------------------------------------------------------------
# Storno und Gutschrift
# ---------------------------------------------------------------------------------------------


def _korrekturbeleg(
    original: Rechnung, art: str, datum: date | None, erstellt_von: str | None
) -> Rechnung:
    beleg = Rechnung(
        firma_id=original.firma_id,
        art=art,
        projekt_id=original.projekt_id,
        kunde_id=original.kunde_id,
        kunde_snapshot=original.kunde_snapshot,
        ust_kz=original.ust_kz,
        datum=datum or heute_ortszeit(),
        faellig_am=datum or heute_ortszeit(),
        leistungszeitraum=original.leistungszeitraum,
        status="entwurf",
        storno_ref=original.id,
        erstellt_von=erstellt_von,
    )
    return beleg


def storno(
    db: Session,
    original_id: int,
    datum: date | None = None,
    grund: str | None = None,
    erstellt_von: str | None = None,
) -> Rechnung:
    """Vollstorno eines festgeschriebenen Belegs (PLAN §6.4).

    Der Storno ist ein **eigener Beleg** mit eigener Nummer und Negativbeträgen. Der Ursprung
    bleibt unverändert stehen und wechselt beim Festschreiben des Stornos auf ``storniert`` –
    die Rechnungsnummern müssen lückenlos bleiben, ein Löschen gäbe es nicht.
    """
    original = db.get(Rechnung, original_id)
    if original is None:
        raise NichtGefunden("Der Beleg wurde nicht gefunden.", "Die Belegliste öffnen.")
    if original.status != "festgeschrieben":
        raise BelegFehler(
            "Nur ein festgeschriebener Beleg lässt sich stornieren.",
            "Ein Entwurf wird einfach verworfen – dafür braucht es keinen Storno."
            if original.status == "entwurf"
            else "Dieser Beleg ist bereits storniert.",
        )

    beleg = _korrekturbeleg(original, "storno", datum, erstellt_von)
    beleg.betreff = f"Stornorechnung zu {original.rechnung_nr}"
    beleg.anschreiben = (
        f"Hiermit stornieren wir unsere Rechnung {original.rechnung_nr} vom "
        f"{original.datum.strftime('%d.%m.%Y')} vollständig."
        + (f" Grund: {grund}" if grund else "")
    )
    for position in original.positionen:
        beleg.positionen.append(
            Rechnungsposition(
                pos=position.pos,
                bezeichnung=position.bezeichnung,
                menge=position.menge,
                einheit=position.einheit,
                ep_netto=-position.ep_netto,
                ust_satz=position.ust_satz,
            )
        )
    # Ein Storno hebt den Beleg als Ganzes auf; ein Absetzungsblock des Originals wird dabei
    # nicht gespiegelt. Er ist Teil des Originals und verschwindet mit ihm aus dem Umsatz.
    summen_setzen(beleg)
    return beleg


def gutschrift(
    db: Session,
    original_id: int,
    datum: date | None = None,
    grund: str | None = None,
    erstellt_von: str | None = None,
) -> Rechnung:
    """Teilkorrektur als eigener Beleg mit Negativbeträgen (PLAN §6.14).

    Anders als der Storno lässt die Gutschrift den Ursprungsbeleg gültig: sie korrigiert einen
    Teil. Die Positionen werden leer angelegt und von Hand gefüllt – welcher Teil zu korrigieren
    ist, weiß nur der Mensch.
    """
    original = db.get(Rechnung, original_id)
    if original is None:
        raise NichtGefunden("Der Beleg wurde nicht gefunden.", "Die Belegliste öffnen.")
    if original.status != "festgeschrieben":
        raise BelegFehler(
            "Eine Gutschrift bezieht sich auf einen festgeschriebenen Beleg.",
            "Solange der Beleg ein Entwurf ist, wird er einfach geändert.",
        )
    beleg = _korrekturbeleg(original, "gutschrift", datum, erstellt_von)
    beleg.betreff = f"Gutschrift zu {original.rechnung_nr}"
    beleg.anschreiben = (
        f"Zu unserer Rechnung {original.rechnung_nr} vom "
        f"{original.datum.strftime('%d.%m.%Y')} schreiben wir Ihnen gut:"
        + (f" {grund}" if grund else "")
    )
    summen_setzen(beleg)
    return beleg


def offene_vorschlaege(
    db: Session, projekt_ids: list[int] | None = None
) -> list[dict[str, object]]:
    """Abschlagsvorschläge nach PLAN §6.8.

    Eine Zahlungsplanposition mit gesetztem ``trigger_status`` wird zum Vorschlag, sobald der
    zugehörige Meilenstein des Projekts erledigt ist. **Nur Vorschlag** – erzeugt wird der Beleg
    erst auf Knopfdruck, nie automatisch.
    """
    from app.modelle import Meilenstein

    abfrage = (
        select(Zahlungsplanposition, Projekt, Meilenstein)
        .join(Projekt, Projekt.id == Zahlungsplanposition.projekt_id)
        .join(
            Meilenstein,
            (Meilenstein.projekt_id == Projekt.id)
            & (Meilenstein.typ == Zahlungsplanposition.trigger_status),
        )
        .where(
            Zahlungsplanposition.trigger_status.is_not(None),
            Zahlungsplanposition.rechnung_id.is_(None),
            Zahlungsplanposition.migriert_gestellt.is_not(True),
            Meilenstein.erledigt.is_(True),
            Projekt.status.in_(("beauftragt", "in_bau", "abgeschlossen")),
        )
        .order_by(Projekt.projekt_nr, Zahlungsplanposition.pos_nr)
    )
    if projekt_ids is not None:
        abfrage = abfrage.where(Projekt.id.in_(projekt_ids))

    return [
        {
            "position_id": position.id,
            "projekt_id": projekt.id,
            "projekt_nr": projekt.projekt_nr,
            "projekt_name": projekt.bezeichnung,
            "pos_nr": position.pos_nr,
            "bezeichnung": position.bezeichnung,
            "betrag_netto": position.betrag_netto,
            "ausloeser": position.trigger_status,
            "erledigt_am": meilenstein.erledigt_am,
        }
        for position, projekt, meilenstein in db.execute(abfrage).all()
    ]
