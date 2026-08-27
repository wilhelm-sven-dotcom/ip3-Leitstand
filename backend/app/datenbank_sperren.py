"""Datenbank-Sperren in verständliche Meldungen übersetzen.

Die Trigger aus Migration 0002 melden sich mit knappen Texten wie
``festgeschriebene Rechnung nicht aenderbar``. So etwas darf niemandem auf dem Bildschirm
erscheinen. Diese Stelle macht daraus einen Satz, der erklärt, was passiert ist und wie es
weitergeht (PLAN §14).
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError, OperationalError

from app.fehler import Konflikt

# Muss zu den Meldungen in den Migrationen 0002, 0005 und 0006 passen; ein Test prüft das.
SPERRMELDUNGEN: dict[str, tuple[str, str, str]] = {
    "festgeschriebene Rechnung nicht aenderbar": (
        "beleg_festgeschrieben",
        "Der Beleg ist festgeschrieben und kann nicht mehr geändert werden.",
        "Für eine Korrektur einen Storno oder eine Gutschrift erzeugen und den Beleg neu "
        "ausstellen. Das verlangen die GoBD; eine nachträgliche Änderung ist nicht zulässig.",
    ),
    "festgeschriebene Rechnung nicht loeschbar": (
        "beleg_festgeschrieben",
        "Festgeschriebene Belege können nicht gelöscht werden.",
        "Für eine Korrektur einen Storno erzeugen. Die Rechnungsnummern müssen lückenlos bleiben.",
    ),
    "Position einer festgeschriebenen Rechnung nicht aenderbar": (
        "beleg_festgeschrieben",
        "Die Position gehört zu einem festgeschriebenen Beleg und ist nicht mehr änderbar.",
        "Für eine Korrektur einen Storno oder eine Gutschrift erzeugen.",
    ),
    "Position einer festgeschriebenen Rechnung nicht loeschbar": (
        "beleg_festgeschrieben",
        "Die Position gehört zu einem festgeschriebenen Beleg und kann nicht gelöscht werden.",
        "Für eine Korrektur einen Storno oder eine Gutschrift erzeugen.",
    ),
    "keine Position an einer festgeschriebenen Rechnung": (
        "beleg_festgeschrieben",
        "An einen festgeschriebenen Beleg lassen sich keine Positionen anfügen.",
        "Die zusätzliche Leistung auf einem neuen Beleg abrechnen.",
    ),
    "Absetzung einer festgeschriebenen Rechnung nicht aenderbar": (
        "beleg_festgeschrieben",
        "Der Absetzungsblock gehört zu einem festgeschriebenen Beleg und ist nicht mehr änderbar.",
        "Für eine Korrektur einen Storno erzeugen und die Schlussrechnung neu ausstellen. Der "
        "Absetzungsblock nach § 14 Abs. 5 UStG muss zu dem passen, was auf dem Papier steht.",
    ),
    "Absetzung einer festgeschriebenen Rechnung nicht loeschbar": (
        "beleg_festgeschrieben",
        "Der Absetzungsblock eines festgeschriebenen Belegs kann nicht gelöscht werden.",
        "Für eine Korrektur einen Storno erzeugen und die Schlussrechnung neu ausstellen.",
    ),
    "keine Absetzung an einer festgeschriebenen Rechnung": (
        "beleg_festgeschrieben",
        "An einen festgeschriebenen Beleg lässt sich kein weiterer Abschlag zum Absetzen anfügen.",
        "Der später entstandene Abschlag gehört auf eine neue Schlussrechnung. Dafür zuerst die "
        "bestehende stornieren.",
    ),
    "berechnete Zahlungsplanposition nicht aenderbar": (
        "zahlungsplan_berechnet",
        "Diese Zahlungsplanposition ist bereits berechnet und deshalb gesperrt.",
        "Wenn sich der Betrag ändern muss: zuerst die zugehörige Rechnung stornieren, dann ist "
        "die Position wieder frei.",
    ),
    "migriert gestellte Zahlungsplanposition nicht aenderbar": (
        "zahlungsplan_migriert_gestellt",
        "Diese Position ist im Altbestand als gestellt gekennzeichnet und deshalb gesperrt.",
        "Die Rechnung dazu entstand vor der Einführung des Leitstands. Wenn der Betrag oder der "
        "Monat wirklich falsch ist: zuerst das Kennzeichen „gestellt“ zurücknehmen, dann ist "
        "die Position frei. Beides steht im Änderungsprotokoll.",
    ),
    "migriert gestellte Zahlungsplanposition nicht loeschbar": (
        "zahlungsplan_migriert_gestellt",
        "Diese Position ist im Altbestand als gestellt gekennzeichnet und kann nicht gelöscht "
        "werden.",
        "Ihr Betrag zählt zum Umsatz des Altbestands. Wenn die Position wirklich nicht in den "
        "Zahlungsplan gehört: zuerst das Kennzeichen „gestellt“ zurücknehmen, dann ist sie frei.",
    ),
    "berechnete Zahlungsplanposition nicht loeschbar": (
        "zahlungsplan_berechnet",
        "Diese Zahlungsplanposition ist bereits berechnet und kann nicht gelöscht werden.",
        "Zuerst die zugehörige Rechnung stornieren.",
    ),
}


def als_fachfehler(fehler: Exception) -> Konflikt | None:
    """Datenbankfehler in einen Konflikt übersetzen, wenn eine Sperre gegriffen hat.

    ``None``, wenn es kein Sperrfall ist – dann gehört der Fehler weitergeworfen und landet in
    der allgemeinen Fehlerbehandlung.
    """
    if not isinstance(fehler, IntegrityError | OperationalError):
        return None
    text = str(fehler.orig) if fehler.orig is not None else str(fehler)
    for kennzeichen, (code, meldung, schritt) in SPERRMELDUNGEN.items():
        if kennzeichen in text:
            return Konflikt(meldung, schritt, code=code)
    return None


def sperren_uebersetzen(fehler: Exception) -> None:
    """Sperrfehler als Konflikt weiterwerfen, alles andere unverändert.

    Verwendung::

        try:
            with schreib_transaktion(sitzung):
                ...
        except Exception as fehler:
            sperren_uebersetzen(fehler)
            raise
    """
    uebersetzt = als_fachfehler(fehler)
    if uebersetzt is not None:
        raise uebersetzt from fehler
