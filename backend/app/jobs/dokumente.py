"""Nächtlicher Doku-Scan der Projektordner (PLAN §7 Phase 7).

Der Lauf zählt, was in den Projektordnern liegt, und schreibt den Befund in die Datenbank. Er
ändert **nichts** an den Ordnern und **nichts** an den Projekten; er stellt nur fest.

Ein unvollständiger Ordner macht den Lauf **nicht** zur Warnung. Das unterscheidet ihn vom
Fristenwächter, und der Unterschied ist beabsichtigt: eine versäumte MaStR-Frist ist ein
Termin, der vorbei ist, eine fehlende Anlagendokumentation dagegen ein Zustand, der bei
laufenden Projekten der Normalfall ist. Ein Systemstatus, der neun Monate im Jahr gelb steht,
sagt nichts mehr. Gewarnt wird nur, wenn der Scan seine Arbeit nicht tun konnte – Wurzel nicht
gesetzt, Ordner nicht erreichbar – oder wenn Ordner mehrdeutig sind.
"""

from __future__ import annotations

from pathlib import Path

from app.datenbank import schreib_sitzung
from app.dienste import dokumente as dienst
from app.formate import mehrzahl
from app.jobs.lauf import LaufErgebnis, protokollierter_lauf
from app.konfiguration import Einstellungen, einstellungen


def doku_scan_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """Projektordner lesen und den Befund festhalten."""
    konfiguration = werte or einstellungen()
    with protokollierter_lauf("doku_scan", ausgeloest_von) as ergebnis:
        _doku_scan_lauf(konfiguration, ergebnis)


def _doku_scan_lauf(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    wurzel = werte.pfade.projekte
    if wurzel is None:
        ergebnis.warnen(
            "Kein Projektordner konfiguriert. Nächster Schritt: in der config.toml unter "
            "[pfade] 'projekte' auf die Wurzel der Projektordner setzen."
        )
        return

    pfad = Path(wurzel)
    if not pfad.is_dir():
        ergebnis.warnen(
            f"Der Projektordner {pfad} ist nicht erreichbar. Nächster Schritt: prüfen, ob das "
            "Laufwerk eingehängt und der Pfad in der config.toml richtig ist."
        )
        return

    try:
        with schreib_sitzung() as sitzung:
            befund = dienst.scannen(sitzung, pfad, werte.dokumente)
    except dienst.OrdnerNichtLesbar as fehler:
        ergebnis.warnen(
            f"Der Projektordner {fehler.pfad} ist nicht lesbar. Nächster Schritt: prüfen, ob "
            "das Dienstkonto darauf zugreifen darf."
        )
        return

    ergebnis.kennzahlen = {
        "projekte": befund.projekte,
        "mit_ordner": befund.mit_ordner,
        "ohne_ordner": befund.ohne_ordner,
        "mehrdeutig": befund.mehrdeutig,
        "unvollstaendig": befund.unvollstaendig,
        "verwaist": len(befund.verwaist),
    }

    teile = [f"{mehrzahl(befund.mit_ordner, 'Projektordner', 'Projektordner')} gelesen"]
    if befund.ohne_ordner:
        teile.append(f"{mehrzahl(befund.ohne_ordner, 'Projekt', 'Projekte')} ohne Ordner")
    if befund.unvollstaendig:
        teile.append(
            f"{mehrzahl(befund.unvollstaendig, 'Ordner', 'Ordner')} ohne vollständige Pflichtdoku"
        )
    meldung = ", ".join(teile) + "."

    # Mehrdeutige Ordner sind die einzige Lage, in der der Scan selbst unsicher ist: er hat
    # einen von zweien genommen. Das gehört gesagt, und zwar als Warnung.
    if befund.mehrdeutig:
        ergebnis.warnen(
            meldung
            + f" {mehrzahl(befund.mehrdeutig, 'Projekt hat', 'Projekte haben')} mehr als einen "
            "Ordner mit derselben Nummer; gelesen wurde jeweils der erste."
        )
        return

    if befund.verwaist:
        # Kein Warnfall: ein Ordner ohne Projekt ist meistens ein Altbestand und kein Versäumnis.
        beispiele = ", ".join(befund.verwaist[:3])
        weitere = len(befund.verwaist) - 3
        meldung += (
            f" {mehrzahl(len(befund.verwaist), 'Ordner', 'Ordner')} ohne Projekt im Leitstand: "
            f"{beispiele}" + (f" und {weitere} weitere." if weitere > 0 else ".")
        )

    ergebnis.meldung = meldung
