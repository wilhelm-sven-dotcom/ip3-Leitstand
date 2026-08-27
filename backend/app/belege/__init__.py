"""Belegdokumente: PDF im ip³-Corporate-Design und E-Rechnung (PLAN §7 Phase 3, §11).

Dieses Paket setzt das Protokoll :class:`app.dienste.festschreibung.Belegablage` um. Getrennt vom
Dienst, weil die Festschreibung ohne PDF-Werkzeug testbar bleiben soll: was hier fehlschlägt, darf
die Nummernvergabe nicht mitreißen.

Die Ablage schreibt **nur** in den konfigurierten Rechnungsordner und liest sonst nichts – der
Leitstand ändert an fremden Ordnern nichts (PLAN §12).
"""

from __future__ import annotations

from pathlib import Path

from app.dienste.festschreibung import Ablagepfade, Belegablage, Belegdateien
from app.konfiguration import einstellungen
from app.modelle import Rechnung
from app.protokoll import logger

log = logger(__name__)

__all__ = ["Rechnungsablage", "ablage_aus_konfiguration"]


class Rechnungsablage:
    """Erzeugt PDF und XML eines Belegs und legt sie im Rechnungsordner ab (PLAN §7).

    Der Ordner wird beim Schreiben angelegt, falls er fehlt – aber nur er selbst, nicht ein
    ganzer Pfad ins Nichts: liegt das übergeordnete Verzeichnis nicht vor (OneDrive nicht
    verbunden, Laufwerk nicht verfügbar), soll das auffallen und nicht in einem lokalen
    Ersatzordner enden, den niemand findet.
    """

    def __init__(self, ordner: Path) -> None:
        self.ordner = Path(ordner)

    def rendern(self, beleg: Rechnung) -> Belegdateien:
        from app.belege.pdf import dateiname, pdf_erzeugen

        return Belegdateien(pdf_name=dateiname(beleg), pdf_bytes=pdf_erzeugen(beleg))

    def pfade(self, dateien: Belegdateien) -> Ablagepfade:
        return Ablagepfade(
            pdf_pfad=str(self.ordner / dateien.pdf_name),
            xml_pfad=str(self.ordner / dateien.xml_name) if dateien.xml_name else None,
        )

    def schreiben(self, dateien: Belegdateien) -> Ablagepfade:
        if not self.ordner.parent.exists():
            raise OSError(
                2,
                f"Der übergeordnete Ordner {self.ordner.parent} ist nicht erreichbar",
                str(self.ordner),
            )
        self.ordner.mkdir(parents=False, exist_ok=True)
        ziel = self.ordner / dateien.pdf_name
        ziel.write_bytes(dateien.pdf_bytes)
        xml_ziel = None
        if dateien.xml_name and dateien.xml_bytes is not None:
            xml_ziel = self.ordner / dateien.xml_name
            xml_ziel.write_bytes(dateien.xml_bytes)
        log.info("Beleg abgelegt", extra={"datei": str(ziel)})
        return Ablagepfade(pdf_pfad=str(ziel), xml_pfad=str(xml_ziel) if xml_ziel else None)


def ablage_aus_konfiguration() -> Belegablage | None:
    """Belegablage für den konfigurierten Rechnungsordner, oder ``None``.

    Ist ``pfade.rechnungen`` nicht gesetzt, entsteht kein Dokument und der Beleg wird trotzdem
    festgeschrieben – die Nummer ist die Hauptsache, die Datei kann nachgeholt werden. Der
    Systemstatus weist auf den fehlenden Pfad hin.
    """
    ordner = einstellungen().pfade.rechnungen
    if ordner is None:
        return None
    return Rechnungsablage(ordner)
