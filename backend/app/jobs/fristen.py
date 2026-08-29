"""Nächtlicher Fristenwächter (PLAN §7 Phase 6).

Der Lauf leitet die MaStR-Fristen aus den Inbetriebnahmedaten ab, hakt erfüllte ab und zählt,
was ansteht. **Er verschickt nichts** (Entscheidung 34): PLAN §12 und CLAUDE.md schließen
automatischen Mailversand aus. Das Ergebnis steht im Job-Protokoll und am nächsten Morgen auf
der Startseite.

Überfällige Fristen machen den Lauf zur Warnung. Das ist die einzige Stelle, an der eine
fachliche Lage – nicht ein technischer Ausfall – den Systemstatus einfärbt, und sie ist es
wert: eine verpasste Gewährleistungsanzeige kostet mehr als ein fehlgeschlagener Import.
"""

from __future__ import annotations

from app.datenbank import schreib_sitzung
from app.dienste import fristen as dienst
from app.jobs.lauf import LaufErgebnis, protokollierter_lauf
from app.konfiguration import Einstellungen, einstellungen


def fristen_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """Fristen ableiten, abhaken und zählen."""
    konfiguration = werte or einstellungen()
    with protokollierter_lauf("fristen", ausgeloest_von) as ergebnis:
        _fristen_lauf(konfiguration, ergebnis)


def _fristen(anzahl: int, einzahl: str, mehrzahl: str) -> str:
    """„1 Frist ist überfällig" statt „1 Fristen sind überfällig".

    Eine Meldung mit falschem Numerus liest sich wie eine Maschinenausgabe, und genau so wird
    sie dann auch behandelt: überlesen.
    """
    return f"1 Frist {einzahl}" if anzahl == 1 else f"{anzahl} Fristen {mehrzahl}"


def _fristen_lauf(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    with schreib_sitzung() as sitzung:
        wacht = dienst.wachen(sitzung, mastr_tage=werte.fristen.mastr_tage)

    ergebnis.kennzahlen = {
        "mastr_gesetzt": wacht.gesetzt,
        "mastr_erledigt": wacht.erledigt,
        "ueberfaellig": wacht.ueberfaellig,
        "faellig": wacht.faellig,
    }

    if wacht.ueberfaellig:
        # Höchstens drei Zeilen: das Job-Protokoll ist kein Ersatz für die Fristenliste, es soll
        # nur sagen, dass hingeschaut werden muss.
        ergebnis.warnen(
            _fristen(wacht.ueberfaellig, "ist überfällig", "sind überfällig")
            + ". "
            + " ".join(wacht.hinweise[:3])
            + " Nächster Schritt: die Fristenliste auf der Startseite durchgehen."
        )
        return

    ergebnis.meldung = (
        _fristen(wacht.faellig, "steht an", "stehen an") + ", keine überfällig."
        if wacht.faellig
        else "Keine Frist steht an."
    )
    if wacht.gesetzt or wacht.erledigt:
        ergebnis.meldung += (
            f" MaStR: {wacht.gesetzt} Fristen gesetzt, {wacht.erledigt} durch nachgetragene "
            "Nummer erledigt."
        )
