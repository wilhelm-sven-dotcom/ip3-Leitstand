"""Belegdokumente: PDF im ip³-Corporate-Design und E-Rechnung (PLAN §7 Phase 3, §11).

Dieses Paket ist die Umsetzung des Protokolls :class:`app.dienste.festschreibung.Belegablage`.
Getrennt vom Dienst, weil die Festschreibung ohne PDF-Werkzeug testbar bleiben soll: was hier
fehlschlägt, darf die Nummernvergabe nicht mitreißen.

:func:`ablage_aus_konfiguration` liefert ``None``, wenn kein Rechnungsordner konfiguriert ist.
Dann entsteht kein Dokument, und der Beleg wird trotzdem festgeschrieben – die Nummer ist die
Hauptsache, die Datei kann nachgeholt werden. Der Systemstatus weist auf den fehlenden Pfad hin.
"""

from __future__ import annotations

from app.dienste.festschreibung import Belegablage
from app.konfiguration import einstellungen


def ablage_aus_konfiguration() -> Belegablage | None:
    """Belegablage für den konfigurierten Rechnungsordner, oder ``None``.

    Die Erzeugung der Dokumente selbst folgt im nächsten Schritt dieser Phase; solange sie fehlt,
    wird ein Beleg ohne Datei festgeschrieben und ``pdf_pfad`` bleibt leer. Das ist der Zustand,
    den auch ein Betrieb ohne gesetzten Rechnungsordner hat – nichts geht dabei verloren, und die
    Ablage lässt sich später nachholen.
    """
    if einstellungen().pfade.rechnungen is None:
        return None
    return None
