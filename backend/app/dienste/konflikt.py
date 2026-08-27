"""Konfliktprüfung beim Speichern (Optimistic Locking, PLAN §5).

Zwei Personen öffnen dasselbe Projekt, beide ändern etwas, beide speichern. Ohne Prüfung gewinnt
der Zweite, und die Änderung des Ersten ist verschwunden – ohne Meldung, ohne Spur. Das ist der
Fehler, den ein Werkzeug für zwei Geschäftsführer und eine Buchhaltungskraft am ehesten macht.

Die Prüfung läuft über ``updated_at``: die Bearbeitungsmaske schickt den Stand mit, den sie
gelesen hat. Weicht er ab, gibt es eine Meldung statt eines stillen Überschreibens.

Zwei Wege, beide hier:

* :func:`stand_pruefen` prüft ausdrücklich, bevor gespeichert wird – für Masken, die den Stand
  mitschicken.
* :func:`konflikt_uebersetzen` fängt den ``StaleDataError`` von SQLAlchemy, der beim Speichern
  entsteht, wenn zwischen Lesen und Schreiben jemand anderes geschrieben hat.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm.exc import StaleDataError

from app.fehler import Konflikt
from app.zeit import nach_ortszeit


class HatStand(Protocol):
    """Alles mit ``updated_at`` – also jede Tabelle mit Zeitstempel-Mixin."""

    updated_at: datetime


def _lesbar(zeitpunkt: datetime) -> str:
    ortszeit = nach_ortszeit(zeitpunkt)
    return ortszeit.strftime("%d.%m.%Y um %H:%M")


def konflikt_meldung(datensatz: HatStand, bezeichnung: str = "Der Datensatz") -> Konflikt:
    return Konflikt(
        f"{bezeichnung} wurde zwischenzeitlich von jemand anderem geändert "
        f"(zuletzt am {_lesbar(datensatz.updated_at)}).",
        "Bitte die Seite neu laden. Ihre Eingaben werden dabei verworfen – notieren Sie sie "
        "vorher, falls Sie sie erneut brauchen.",
        code="stand_veraltet",
    )


def stand_pruefen(
    datensatz: HatStand, gelesener_stand: datetime | None, bezeichnung: str = "Der Datensatz"
) -> None:
    """Prüfen, ob der Datensatz seit dem Lesen verändert wurde.

    ``gelesener_stand`` ist das ``updated_at``, das die Maske beim Öffnen bekommen hat. Fehlt es,
    wird nicht geprüft – dann arbeitet der Aufrufer ohne Konfliktschutz, was nur für Importe und
    interne Vorgänge in Ordnung ist.
    """
    if gelesener_stand is None:
        return
    # Voll genau vergleichen, einschließlich Mikrosekunden. Vorher wurde auf ganze Sekunden
    # gekürzt – aus der Sorge, der Zeitstempel könne als ISO-Text Genauigkeit verlieren. Das
    # tut er nicht (Test `test_mikrosekunden_ueberleben_die_schnittstelle`), und die Kürzung
    # hat den Schutz ausgehöhlt: zwei Speicherungen innerhalb derselben Sekunde galten als
    # derselbe Stand, der zweite überschrieb den ersten stillschweigend. Genau das soll die
    # Prüfung verhindern.
    if datensatz.updated_at != gelesener_stand:
        raise konflikt_meldung(datensatz, bezeichnung)


def konflikt_uebersetzen(fehler: Exception, bezeichnung: str = "Der Datensatz") -> None:
    """``StaleDataError`` als Konflikt weiterwerfen, alles andere unverändert lassen.

    Verwendung::

        try:
            with schreib_transaktion(sitzung):
                ...
        except Exception as fehler:
            konflikt_uebersetzen(fehler, "Das Projekt")
            raise
    """
    if isinstance(fehler, StaleDataError):
        raise Konflikt(
            f"{bezeichnung} wurde zwischenzeitlich von jemand anderem geändert.",
            "Bitte die Seite neu laden und die Eingabe wiederholen.",
            code="stand_veraltet",
        ) from fehler


def _gleichwertig(vorher: Any, nachher: Any) -> bool:
    """Ob zwei Werte dasselbe bedeuten.

    ``Decimal`` und ``float`` sind in Python nie gleich, auch wenn sie dieselbe Zahl meinen:
    ``Decimal("514.08") == 514.08`` ist ``False``. Genau das passiert bei jeder Speicherung aus
    einer Maske – die Datenbank liefert ``Decimal`` (``pv_kwp``, ``speicher_kwh``), die
    Schnittstelle schickt eine Gleitkommazahl zurück. Ohne diesen Vergleich stünde nach jedem
    Speichern „514.08 → 514.08" im Änderungsprotokoll, und die echten Änderungen gingen darin
    unter.

    Geldbeträge sind davon nicht betroffen: sie sind überall Integer in Cent (CLAUDE.md Regel 3).
    """
    if vorher == nachher:
        return True
    if isinstance(vorher, Decimal | float | int) and isinstance(nachher, Decimal | float | int):
        return Decimal(str(vorher)) == Decimal(str(nachher))
    return False


def geaenderte_felder(alt: dict[str, Any], neu: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Unterschiede zwischen zwei Zuständen – für das Änderungsprotokoll.

    Nur die tatsächlich geänderten Felder, damit im Protokoll erkennbar bleibt, was passiert ist,
    statt bei jeder Speicherung den ganzen Datensatz zu wiederholen.
    """
    unterschiede: dict[str, dict[str, Any]] = {}
    for feld in set(alt) | set(neu):
        vorher = alt.get(feld)
        nachher = neu.get(feld)
        if not _gleichwertig(vorher, nachher):
            unterschiede[feld] = {"alt": vorher, "neu": nachher}
    return unterschiede
