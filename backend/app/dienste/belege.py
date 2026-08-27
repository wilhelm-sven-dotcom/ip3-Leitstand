"""Rechnen und Beschriften eines Belegs (PLAN §6.1, §6.2, §6.11, §10).

Diese Stelle ist die einzige, die aus Positionen einen Beleg macht. Route, Vorschau, PDF, XML und
Festschreibung fragen hier – niemand rechnet ein zweites Mal, weil zwei Rechenwege irgendwann
zwei verschiedene Ergebnisse liefern und dann niemand mehr weiß, welches auf dem Papier steht.

Vier Regeln, die hier ihren Platz haben:

* **Umsatzsteuer je Steuersatz auf die Nettosumme des Belegs**, nicht je Position aufsummiert
  (PLAN §6.11). Die Rechnung selbst steht in :mod:`app.geld`; hier wird sie auf die Positionen
  eines Belegs angewandt und das Ergebnis als ``ust_details`` festgehalten.
* **0 % ist nicht gleich 0 %.** Ein Beleg mit ``ust_kz='13b'`` weist keine Steuer aus, weil sie
  der Leistungsempfänger schuldet; ein Beleg mit 0 % nach § 12 Abs. 3 UStG weist sie nicht aus,
  weil der Satz null ist. Beides verlangt einen **anderen** Pflichthinweis, und beides steht in
  derselben Spalte ``ust_satz = 0``. Unterschieden wird deshalb über ``Rechnung.ust_kz``.
* **Der Kundenstand wird kopiert, nicht verwiesen** (§ 14 UStG: die Angaben gelten zum
  Ausstellungszeitpunkt). Eine Adressänderung beim Kunden darf einen ausgestellten Beleg nicht
  verändern.
* **Der Hash deckt die Belegdaten ab, nicht die PDF-Bytes.** Damit bleibt ein erneutes Rendern
  möglich (etwa wenn die Ablage im Rechnungsordner scheiterte), ohne dass der Beleg als verändert
  gilt. Was in den Hash eingeht, steht in :func:`beleg_hash` – die Reihenfolge ist fest, sonst
  wäre der Hash nicht reproduzierbar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.formate import prozent
from app.geld import position_netto, steuer_je_satz
from app.konfiguration import FirmaEinstellungen, einstellungen
from app.modelle import Kunde, Rechnung, Rechnungsposition

# Pflichthinweise auf dem Beleg. Die Texte stehen hier und nicht in der Vorlage, weil sie
# steuerlich verlangt sind und nicht zum Layout gehören.
HINWEIS_13B = (
    "Steuerschuldnerschaft des Leistungsempfängers (§ 13b Abs. 2 Nr. 4 UStG). "
    "Die Umsatzsteuer ist von Ihnen als Leistungsempfänger anzumelden und abzuführen."
)
HINWEIS_NULL_PROZENT = (
    "Umsatzsteuer 0 % nach § 12 Abs. 3 UStG (Lieferung und Installation einer "
    "Photovoltaikanlage einschließlich Speicher)."
)
HINWEIS_ABSETZUNG = (
    "Die bereits berechneten Abschlagszahlungen sind mit Netto und darauf entfallender "
    "Umsatzsteuer abgesetzt (§ 14 Abs. 5 UStG)."
)


@dataclass(frozen=True)
class SatzAnteil:
    """Netto und Umsatzsteuer eines Steuersatzes auf dem Beleg."""

    satz: int
    netto: int
    ust: int

    @property
    def prozent_text(self) -> str:
        """Der Satz als deutscher Prozenttext (PLAN §6.10)."""
        return prozent(self.satz)

    def als_json(self) -> dict[str, int]:
        return {"satz": self.satz, "netto": self.netto, "ust": self.ust}


@dataclass
class Summen:
    """Ergebnis der Belegrechnung.

    ``netto``/``ust``/``brutto`` sind die **Gesamtleistung**, ``absetzung_*`` die abgesetzten
    Abschläge und ``zahlbetrag`` der Betrag, den der Kunde zu zahlen hat. Bei allem außer einer
    Schlussrechnung ist die Absetzung null und ``zahlbetrag == brutto``.
    """

    netto: int = 0
    ust: int = 0
    brutto: int = 0
    absetzung_netto: int = 0
    absetzung_ust: int = 0
    je_satz: list[SatzAnteil] = field(default_factory=list)

    @property
    def zahlbetrag(self) -> int:
        return self.brutto - self.absetzung_netto - self.absetzung_ust

    @property
    def absetzung_brutto(self) -> int:
        return self.absetzung_netto + self.absetzung_ust

    def ust_details(self) -> list[dict[str, int]]:
        return [anteil.als_json() for anteil in self.je_satz]


def positionspaare(positionen: list[Rechnungsposition]) -> list[tuple[int, int]]:
    """Positionen als ``(netto_cent, satz_promille)`` für :mod:`app.geld`."""
    return [(position_netto(p.menge, p.ep_netto), p.ust_satz) for p in positionen]


def summen_berechnen(
    positionen: list[Rechnungsposition],
    absetzung_netto: int = 0,
    absetzung_ust: int = 0,
) -> Summen:
    """Netto, Umsatzsteuer je Satz, Brutto und Zahlbetrag eines Belegs (PLAN §6.11).

    Die Steuer wird **einmal je Satz** auf die Nettosumme gerechnet. Positionsweise gerundet
    wichen Positionssumme und Belegsumme um Cent-Beträge voneinander ab, und genau darauf schaut
    eine Prüfung.
    """
    je_satz = steuer_je_satz(positionspaare(positionen))
    anteile = [
        SatzAnteil(satz=satz, netto=netto, ust=ust) for satz, (netto, ust) in je_satz.items()
    ]
    netto = sum(anteil.netto for anteil in anteile)
    ust = sum(anteil.ust for anteil in anteile)
    return Summen(
        netto=netto,
        ust=ust,
        brutto=netto + ust,
        absetzung_netto=absetzung_netto,
        absetzung_ust=absetzung_ust,
        je_satz=anteile,
    )


def steuer_hinweise(
    ust_kz: str, positionen: list[Rechnungsposition], mit_absetzung: bool = False
) -> list[str]:
    """Pflichthinweise, die auf diesem Beleg stehen müssen (PLAN §6.2).

    Bei ``13b`` schuldet der Leistungsempfänger die Steuer – der Beleg weist keine aus und muss
    darauf hinweisen. Sonst gilt eine Position mit 0 % als begünstigte Anlagenlieferung nach
    § 12 Abs. 3 UStG; einen anderen Grund für 0 % kennt der Leitstand nicht, und ein Beleg ohne
    Steuer ohne Begründung ist unvollständig.
    """
    hinweise: list[str] = []
    if ust_kz == "13b":
        hinweise.append(HINWEIS_13B)
    elif any(position.ust_satz == 0 for position in positionen):
        hinweise.append(HINWEIS_NULL_PROZENT)
    if mit_absetzung:
        hinweise.append(HINWEIS_ABSETZUNG)
    return hinweise


def kunde_snapshot(kunde: Kunde) -> dict[str, Any]:
    """Kundenstand für den Beleg festhalten (§ 14 UStG, Angaben zum Ausstellungszeitpunkt)."""
    return {
        "kunden_nr": kunde.kunden_nr,
        "name": kunde.name,
        "zusatz": kunde.zusatz,
        "strasse": kunde.strasse,
        "plz": kunde.plz,
        "ort": kunde.ort,
        "ust_id": kunde.ust_id,
        "typ": kunde.typ,
        "zahlungsziel_tage": kunde.zahlungsziel_tage,
    }


def zahlungsziel(kunde: Kunde | None) -> int:
    """Zahlungsziel in Tagen: das des Kunden, sonst der Wert aus der Konfiguration (PLAN §10)."""
    if kunde is not None and kunde.zahlungsziel_tage is not None:
        return kunde.zahlungsziel_tage
    return einstellungen().fakturierung.zahlungsziel_tage


def faelligkeit(belegdatum: date, kunde: Kunde | None) -> date:
    """Fälligkeitsdatum aus Belegdatum und Zahlungsziel."""
    return belegdatum + timedelta(days=zahlungsziel(kunde))


def anschrift_zeilen(snapshot: dict[str, Any]) -> list[str]:
    """Empfängeranschrift für Beleg und XML, leere Zeilen weggelassen."""
    zeilen = [snapshot.get("name"), snapshot.get("zusatz"), snapshot.get("strasse")]
    ort = " ".join(teil for teil in (snapshot.get("plz"), snapshot.get("ort")) if teil)
    zeilen.append(ort or None)
    return [str(zeile).strip() for zeile in zeilen if zeile and str(zeile).strip()]


def fehlende_pflichtangaben(
    beleg: Rechnung,
    positionen: list[Rechnungsposition],
    firma: FirmaEinstellungen | None = None,
) -> list[str]:
    """Was der Festschreibung noch fehlt (§ 14 UStG, PLAN §6.2, §10).

    Ein Entwurf darf unvollständig sein – das ist der Sinn eines Entwurfs. Beim Festschreiben ist
    es zu spät: der Beleg ist danach unveränderbar und eine Korrektur kostet einen Stornobeleg.
    Deshalb wird hier vollständig geprüft und alles Fehlende auf einmal genannt, nicht der Reihe
    nach.
    """
    fehlt: list[str] = []
    firma = firma if firma is not None else einstellungen().firma
    fehlt.extend(firma.unvollstaendige_pflichtangaben())

    snapshot = beleg.kunde_snapshot or (kunde_snapshot(beleg.kunde) if beleg.kunde else {})
    if not snapshot.get("name"):
        fehlt.append("Name des Empfängers")
    if not snapshot.get("strasse") or not snapshot.get("ort"):
        fehlt.append("Anschrift des Empfängers")
    if not positionen:
        fehlt.append("mindestens eine Position")

    # Der Leistungszeitraum ist Pflicht auf einer Rechnung (§ 14 Abs. 4 Nr. 6 UStG, PLAN §10) –
    # nicht auf einer Auftragsbestätigung. Die AB bestätigt einen Auftrag, sie rechnet nichts ab;
    # sie hier zu blockieren, weil ein Leistungszeitraum fehlt, wäre eine erfundene Anforderung.
    if beleg.art != "ab" and not (beleg.leistungszeitraum or "").strip():
        fehlt.append("Leistungszeitraum")

    # 13b ist nur bei hinterlegter USt-ID des Kunden zulässig (PLAN §6.2): ohne sie ist der
    # Leistungsempfänger nicht als Unternehmer belegt, und der Beleg wäre falsch.
    if beleg.ust_kz == "13b" and not (snapshot.get("ust_id") or "").strip():
        fehlt.append("Umsatzsteuer-Identifikationsnummer des Kunden (für § 13b UStG)")

    # 'gemischt' hat keinen stillen Default (PLAN §6.2). Positionen mit demselben Satz sind bei
    # 'gemischt' zwar erlaubt, ein Beleg *ohne* Positionen wäre aber schon oben gemeldet.
    if beleg.ust_kz != "gemischt":
        erwartet = {"19": 190, "0": 0, "13b": 0}[beleg.ust_kz]
        if any(position.ust_satz != erwartet for position in positionen):
            fehlt.append(
                f"einheitlicher Steuersatz passend zum Kennzeichen „{beleg.ust_kz}“ "
                "(oder Kennzeichen auf „gemischt“ stellen)"
            )
    return fehlt


def beleg_hash(
    beleg: Rechnung,
    positionen: list[Rechnungsposition],
    summen: Summen,
    absetzungen: list[dict[str, Any]] | None = None,
) -> str:
    """SHA-256 über die Belegdaten (PLAN §6.4).

    Die Reihenfolge der Felder ist fest und die Zahlen stehen als ganze Cent darin – so ergibt
    dieselbe Rechnung immer denselben Hash, auch nach einem Neustart oder auf einem anderen
    Rechner. Nicht enthalten sind Ablagepfade und Zeitstempel der Datenbank: sie beschreiben die
    Verwaltung des Belegs, nicht seinen Inhalt.
    """
    daten = {
        "rechnung_nr": beleg.rechnung_nr,
        "art": beleg.art,
        "datum": beleg.datum.isoformat() if beleg.datum else None,
        "leistungszeitraum": beleg.leistungszeitraum,
        "faellig_am": beleg.faellig_am.isoformat() if beleg.faellig_am else None,
        "ust_kz": beleg.ust_kz,
        "kunde": beleg.kunde_snapshot,
        "projekt_id": beleg.projekt_id,
        "netto": summen.netto,
        "ust": summen.ust,
        "brutto": summen.brutto,
        "je_satz": summen.ust_details(),
        "absetzung_netto": summen.absetzung_netto,
        "absetzung_ust": summen.absetzung_ust,
        "zahlbetrag": summen.zahlbetrag,
        "absetzungen": absetzungen or [],
        "positionen": [
            {
                "pos": position.pos,
                "bezeichnung": position.bezeichnung,
                "menge": str(position.menge),
                "einheit": position.einheit,
                "ep_netto": position.ep_netto,
                "ust_satz": position.ust_satz,
                "netto": position_netto(position.menge, position.ep_netto),
            }
            for position in sorted(positionen, key=lambda p: p.pos)
        ],
    }
    text = json.dumps(daten, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
