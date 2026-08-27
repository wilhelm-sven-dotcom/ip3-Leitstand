"""Nächtliche Datensicherung (PLAN §2).

``VACUUM INTO`` erzeugt eine in sich geschlossene Kopie der Datenbank – auch während andere
schreiben. Das ist der entscheidende Punkt gegenüber einem einfachen Dateikopieren: eine mit
``copy`` erstellte Kopie einer SQLite-Datei im WAL-Modus kann mitten in einer Transaktion
entstehen und ist dann unbrauchbar, ohne dass es auffällt. Und sie hätte die Begleitdateien
``-wal`` und ``-shm`` nicht dabei.

Drei Eigenheiten, die im Betrieb Ärger machen würden:

* ``VACUUM INTO`` scheitert, wenn die Zieldatei schon existiert – deshalb ein eindeutiger Name.
* Der Befehl darf nicht in einer Transaktion laufen, also auf einer Verbindung mit AUTOCOMMIT.
* Die Rotation im OneDrive-Ordner darf die alten Kopien **nur betrachten, nie öffnen**. Ein
  ``open`` würde OneDrive dazu bringen, die Datei aus der Cloud zu holen; nach einigen Nächten
  wäre die Festplatte mit 30 Datenbankkopien belegt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.datenbank import engine_erzeugen
from app.jobs.lauf import LaufErgebnis, protokollierter_lauf
from app.konfiguration import Einstellungen, einstellungen
from app.protokoll import logger
from app.zeit import jetzt_utc, nach_ortszeit

log = logger(__name__)

# Namensschema der Sicherungen. Die Rotation löscht ausschließlich Dateien, die genau dazu passen –
# fremde Dateien im Zielordner bleiben unberührt.
NAMENSVORLAGE = "leitstand_{stempel}.sqlite3"
NAMENSMUSTER = re.compile(r"^leitstand_\d{8}-\d{6}(?:_\d+)?\.sqlite3$")


@dataclass
class Sicherungsergebnis:
    datei: Path
    groesse_bytes: int
    geloeschte_generationen: int
    integritaet_ok: bool


def _zieldateiname(zeitpunkt: datetime) -> str:
    ortszeit = nach_ortszeit(zeitpunkt)
    return NAMENSVORLAGE.format(stempel=ortszeit.strftime("%Y%m%d-%H%M%S"))


def _freien_namen_finden(verzeichnis: Path, zeitpunkt: datetime) -> Path:
    """Eindeutigen Zielnamen bestimmen.

    ``VACUUM INTO`` bricht ab, wenn die Datei existiert. Statt eine vorhandene Sicherung zu
    überschreiben – womöglich die einzige brauchbare – wird angehängt.
    """
    ziel = verzeichnis / _zieldateiname(zeitpunkt)
    if not ziel.exists():
        return ziel
    for nummer in range(2, 100):
        kandidat = verzeichnis / ziel.name.replace(".sqlite3", f"_{nummer}.sqlite3")
        if not kandidat.exists():
            return kandidat
    raise OSError(
        f"Im Verzeichnis {verzeichnis} liegen bereits sehr viele Sicherungen desselben "
        "Zeitpunkts. Bitte den Ordner prüfen."
    )


def sicherung_erstellen(quelle: Path, zielverzeichnis: Path) -> tuple[Path, int]:
    """Datenbank nach ``zielverzeichnis`` kopieren. Rückgabe: Zieldatei und Größe."""
    if not quelle.exists():
        raise FileNotFoundError(f"Die Datenbank {quelle} gibt es nicht.")
    zielverzeichnis.mkdir(parents=True, exist_ok=True)
    ziel = _freien_namen_finden(zielverzeichnis, jetzt_utc())

    engine = engine_erzeugen(quelle, ohne_pool=True)
    try:
        # AUTOCOMMIT: VACUUM INTO läuft nicht innerhalb einer Transaktion.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as verbindung:
            verbindung.execute(text("VACUUM INTO :ziel"), {"ziel": str(ziel)})
    finally:
        engine.dispose()

    if not ziel.exists():
        raise OSError(f"Die Sicherung {ziel} wurde nicht angelegt.")
    return ziel, ziel.stat().st_size


def sicherung_pruefen(datei: Path) -> bool:
    """Integritätsprüfung der Kopie.

    Eine Sicherung, die niemand geprüft hat, ist eine Vermutung. Der Prüflauf kostet bei dieser
    Datenmenge Sekundenbruchteile.

    Eine so stark beschädigte Datei, dass sie sich nicht einmal öffnen lässt, gilt ebenfalls als
    nicht in Ordnung: SQLite bricht dann schon beim Verbindungsaufbau ab, und die Ausnahme darf
    nicht als „Prüfung nicht durchführbar" durchgehen.
    """
    engine = engine_erzeugen(datei, ohne_pool=True)
    try:
        with engine.connect() as verbindung:
            return verbindung.execute(text("PRAGMA integrity_check")).scalar() == "ok"
    except Exception as fehler:
        log.warning("Sicherung %s ist nicht lesbar: %s", datei.name, fehler)
        return False
    finally:
        engine.dispose()


def generationen_aufraeumen(verzeichnis: Path, behalten: int) -> int:
    """Älteste Sicherungen löschen, bis nur noch ``behalten`` übrig sind.

    Nur Dateien, die dem Namensmuster entsprechen. Und nur ``stat``, niemals ``open``: im
    OneDrive-Ordner würde ein Lesezugriff die Datei aus der Cloud zurückholen.
    """
    if behalten <= 0 or not verzeichnis.exists():
        return 0

    passende = [
        eintrag
        for eintrag in verzeichnis.iterdir()
        if eintrag.is_file() and NAMENSMUSTER.match(eintrag.name)
    ]
    if len(passende) <= behalten:
        return 0

    # Nach Änderungszeitpunkt, nicht nach Namen: ein umbenannter Restore-Stand soll nicht
    # fälschlich als jüngste Sicherung durchgehen.
    passende.sort(key=lambda p: p.stat().st_mtime)
    zu_loeschen = passende[: len(passende) - behalten]
    geloescht = 0
    for eintrag in zu_loeschen:
        try:
            eintrag.unlink()
            geloescht += 1
        except OSError as fehler:
            # Eine nicht löschbare alte Sicherung ist kein Grund, den Lauf abzubrechen.
            log.warning("Alte Sicherung %s ließ sich nicht löschen: %s", eintrag.name, fehler)
    return geloescht


def sicherung_durchfuehren(werte: Einstellungen) -> Sicherungsergebnis:
    """Vollständiger Ablauf: kopieren, prüfen, alte Generationen aufräumen."""
    if werte.pfade.backup is None:
        raise FileNotFoundError(
            "Es ist kein Backup-Ziel eingerichtet. In config.toml unter [pfade] den Eintrag "
            "backup auf den OneDrive-Ordner 04_Backup setzen."
        )

    ziel, groesse = sicherung_erstellen(werte.pfade.datenbank, werte.pfade.backup)
    integritaet = sicherung_pruefen(ziel)
    geloescht = generationen_aufraeumen(werte.pfade.backup, werte.jobs.backup_generationen)
    return Sicherungsergebnis(
        datei=ziel,
        groesse_bytes=groesse,
        geloeschte_generationen=geloescht,
        integritaet_ok=integritaet,
    )


def backup_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """Der Job, wie ihn der Zeitplan und der Handbetrieb aufrufen."""
    konfiguration = werte or einstellungen()
    with protokollierter_lauf("backup", ausgeloest_von) as ergebnis:
        _sicherung_mit_bericht(konfiguration, ergebnis)


def _sicherung_mit_bericht(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    bericht = sicherung_durchfuehren(werte)
    groesse_mb = round(bericht.groesse_bytes / 1_048_576, 1)
    ergebnis.kennzahlen = {
        "datei": bericht.datei.name,
        "groesse_mb": groesse_mb,
        "geloeschte_generationen": bericht.geloeschte_generationen,
        "integritaet": "ok" if bericht.integritaet_ok else "fehlerhaft",
    }
    if not bericht.integritaet_ok:
        ergebnis.warnen(
            f"Die Sicherung {bericht.datei.name} wurde geschrieben, die Integritätsprüfung "
            "meldet aber einen Fehler. Bitte Sven informieren – die Datenbank sollte geprüft "
            "werden ('ip3-leitstand pruefen')."
        )
        return

    ergebnis.meldung = f"Sicherung {bericht.datei.name} geschrieben ({groesse_mb} MB)"
    if bericht.geloeschte_generationen:
        ergebnis.meldung += f", {bericht.geloeschte_generationen} alte Generation(en) entfernt"


def sitzungen_aufraeumen_job(ausgeloest_von: str = "zeitplan") -> None:
    """Alte, beendete Sitzungen löschen. Läuft mit dem Backup-Zeitplan mit."""
    from app.datenbank import schreib_sitzung
    from app.sicherheit.sitzungen import abgelaufene_aufraeumen

    with schreib_sitzung() as sitzung:
        anzahl = abgelaufene_aufraeumen(sitzung)
    if anzahl:
        log.info("%d abgelaufene Sitzungen entfernt", anzahl)
