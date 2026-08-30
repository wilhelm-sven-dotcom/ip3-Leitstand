"""Doku-Vollständigkeitsscan der Projektordner (PLAN §7 Phase 7).

Der Scan liest die Ordner unter ``[pfade] projekte``, ordnet jeden über die Projektnummer im
Namen einem Projekt zu und jede Datei über ihren Namen einem Dokumenttyp. Das Ergebnis steht in
``projektordner`` (gibt es überhaupt einen Ordner?) und ``dokumente`` (liegt die Unterlage
darin?).

**Der Leitstand liest ausschließlich** (PLAN §2). Er legt keinen Ordner an, verschiebt nichts,
benennt nichts um und löscht nichts. Wer einen Ordner umbenennt, ändert damit den Befund des
nächsten Laufs – nicht umgekehrt.

Drei Dinge, die der Scan bewusst nicht kann und die er deshalb sagt statt zu verschweigen:

* **Er sieht nur Dateinamen.** Ein Abnahmeprotokoll in einer Datei namens ``scan_0042.pdf``
  findet er nicht. Deshalb ist die Meldung ein Hinweis und keine Sperre (Entscheidung 50).
* **Er erkennt keine Mehrdeutigkeit auf.** Liegen zwei Ordner mit derselben Nummer da, nimmt er
  den ersten und nennt den zweiten – raten wäre schlimmer als fragen.
* **Er unterscheidet nicht Papier von Datei.** Was nur ausgedruckt in einem Ordner im Regal
  liegt, fehlt hier zu Recht und ist trotzdem vorhanden.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dienste.suche import AUFGELOEST
from app.konfiguration import DokumenteEinstellungen, einstellungen
from app.modelle.projekte import Dokument, Projekt, Projektordner
from app.protokoll import logger
from app.zeit import heute_ortszeit

log = logger(__name__)

# Projektnummern sind rein numerisch und höchstens achtstellig (PLAN §3). Gesucht wird die
# längste Ziffernfolge im Ordnernamen, die als Nummer taugt – „26001 Muster GmbH", „P-26001"
# und „26001_Muster" führen damit alle zum selben Projekt.
ZIFFERNFOLGE = re.compile(r"\d{4,8}")

# Wie die Typen in Meldungen heißen. Der Datenbankschlüssel ('anlagendoku') gehört nicht auf
# den Bildschirm – dieselbe Lehre wie beim Projektstatus, der als 'in_bau' dastand.
TYP_TEXT: dict[str, str] = {
    "ab": "Auftragsbestätigung",
    "abnahme": "Abnahmeprotokoll",
    "anlagendoku": "Anlagendokumentation",
    "konformitaet": "Konformitätserklärung",
    "messkonzept": "Messkonzept",
    "sonstig": "sonstige Unterlage",
}


def vergleichsform(text: str) -> str:
    """Kleinschreibung, aufgelöste Umlaute, keine Trennzeichen.

    ``Abnahmeprotokoll_Müller-2026.pdf`` und ``abnahmeprotokoll mueller 2026.pdf`` sollen
    dasselbe Muster treffen. Trennzeichen fallen weg, weil im Dateinamen mal ein Unterstrich,
    mal ein Bindestrich und mal ein Leerzeichen steht.
    """
    ergebnis = text.lower()
    for zeichen, ersatz in AUFGELOEST:
        ergebnis = ergebnis.replace(zeichen, ersatz)
    return re.sub(r"[^a-z0-9]+", "", ergebnis)


class OrdnerNichtLesbar(RuntimeError):
    """Die konfigurierte Wurzel ist nicht erreichbar.

    Eigene Ausnahme, damit der Job daraus eine verständliche Meldung machen kann statt eines
    Stacktrace (CLAUDE.md Regel 8). Der häufigste Grund ist ein OneDrive, das gerade nicht
    eingehängt ist – das ist kein Fehler des Leitstands und keiner der Daten.
    """

    def __init__(self, pfad: Path, grund: Exception) -> None:
        self.pfad = pfad
        self.grund = grund
        super().__init__(f"Der Ordner {pfad} ist nicht lesbar: {grund}")


@dataclass
class Ordnerbefund:
    """Was ein Ordner zu einem Projekt hergibt."""

    projekt_id: int
    projekt_nr: int
    pfad: Path | None = None
    dateien: int = 0
    mehrdeutig_mit: Path | None = None
    # Typ -> gefundene Datei. Ein Typ ohne Eintrag gilt als fehlend.
    gefunden: dict[str, Path] = field(default_factory=dict)

    @property
    def hat_ordner(self) -> bool:
        return self.pfad is not None


@dataclass
class Scanergebnis:
    """Was ein Lauf insgesamt ergeben hat."""

    projekte: int = 0
    mit_ordner: int = 0
    ohne_ordner: int = 0
    mehrdeutig: int = 0
    unvollstaendig: int = 0
    # Ordner unter der Wurzel, zu denen es kein Projekt im Leitstand gibt.
    verwaist: list[str] = field(default_factory=list)


def typ_erkennen(dateiname: str, muster: dict[str, list[str]]) -> str | None:
    """Welchem Dokumenttyp ein Dateiname entspricht – oder ``None``.

    Die Reihenfolge in der Konfiguration entscheidet, deshalb wird sie eingehalten und nicht
    etwa nach Trefferlänge sortiert: wer ``konformitaet`` vor ``abnahme`` stellt, meint das so.
    """
    vergleich = vergleichsform(dateiname)
    for typ, begriffe in muster.items():
        for begriff in begriffe:
            if vergleichsform(begriff) in vergleich:
                return typ
    return None


def nummer_aus_ordnername(name: str) -> int | None:
    """Die Projektnummer aus einem Ordnernamen ziehen.

    Bei mehreren Ziffernfolgen gewinnt die **längste**: „2026_26001 Muster" meint das Projekt
    26001, nicht das Jahr. Bei gleicher Länge die erste – dann steht die Nummer üblicherweise
    vorn.
    """
    treffer = ZIFFERNFOLGE.findall(name)
    if not treffer:
        return None
    beste = max(treffer, key=len)
    return int(beste)


def _dateien(ordner: Path, tiefe: int, endungen: Iterable[str]) -> Iterator[Path]:
    """Dateien bis zur erlaubten Tiefe, gefiltert nach Endung.

    Bewusst iterativ statt ``rglob``: die Tiefenbegrenzung ist der Schutz davor, dass ein
    versehentlich mitkopiertes Fotoarchiv den nächtlichen Lauf minutenlang beschäftigt.
    """
    erlaubt = {e.lower() for e in endungen}
    ebenen: list[Path] = [ordner]
    for _ in range(tiefe):
        naechste: list[Path] = []
        for verzeichnis in ebenen:
            try:
                eintraege = sorted(verzeichnis.iterdir())
            except OSError as fehler:  # Berechtigung, Sync-Konflikt, Laufwerk weg
                log.warning("Ordner nicht lesbar: %s (%s)", verzeichnis, fehler)
                continue
            for eintrag in eintraege:
                if eintrag.is_dir():
                    naechste.append(eintrag)
                elif eintrag.suffix.lower() in erlaubt:
                    yield eintrag
        ebenen = naechste


def ordner_lesen(
    wurzel: Path,
    projekte: dict[int, int],
    werte: DokumenteEinstellungen,
) -> tuple[dict[int, Ordnerbefund], list[str]]:
    """Die Ordner unter ``wurzel`` den Projekten zuordnen und ihren Inhalt einordnen.

    ``projekte`` bildet Projektnummer auf Projekt-ID ab. Zurück kommen die Befunde je Projekt
    und die Ordner, zu denen es kein Projekt gibt – letztere sind eine eigene Auskunft: ein
    Ordner ohne Projekt heißt meist, dass ein Projekt im Leitstand fehlt.
    """
    befunde: dict[int, Ordnerbefund] = {
        projekt_id: Ordnerbefund(projekt_id=projekt_id, projekt_nr=nummer)
        for nummer, projekt_id in projekte.items()
    }
    verwaist: list[str] = []

    try:
        eintraege = sorted(p for p in wurzel.iterdir() if p.is_dir())
    except OSError as fehler:
        raise OrdnerNichtLesbar(wurzel, fehler) from fehler

    for ordner in eintraege:
        nummer = nummer_aus_ordnername(ordner.name)
        projekt_id = projekte.get(nummer) if nummer is not None else None
        if projekt_id is None:
            verwaist.append(ordner.name)
            continue

        befund = befunde[projekt_id]
        if befund.hat_ordner:
            # Zweiter Ordner mit derselben Nummer: der erste bleibt maßgeblich, der zweite wird
            # gemeldet. Stillschweigend den letzten zu nehmen wäre von der Sortierung abhängig.
            if befund.mehrdeutig_mit is None:
                befund.mehrdeutig_mit = ordner
            continue

        befund.pfad = ordner
        for datei in _dateien(ordner, werte.tiefe, werte.endungen):
            befund.dateien += 1
            typ = typ_erkennen(datei.name, werte.muster)
            # Der erste Fund je Typ gewinnt; ein zweites Abnahmeprotokoll ändert nichts daran,
            # dass eines vorliegt.
            if typ is not None and typ not in befund.gefunden:
                befund.gefunden[typ] = datei

    return befunde, verwaist


def scannen(
    sitzung: Session,
    wurzel: Path,
    werte: DokumenteEinstellungen | None = None,
    heute: date | None = None,
) -> Scanergebnis:
    """Einen vollständigen Lauf ausführen und das Ergebnis speichern.

    Der Befund wird je Projekt und Typ **aktualisiert**, nicht angehängt: eine Unterlage, die
    heute vorliegt und gestern fehlte, soll eine Zeile ergeben und nicht zwei widersprüchliche.
    Dafür sorgt der eindeutige Index aus Migration 0009.
    """
    werte = werte or einstellungen().dokumente
    stichtag = heute or heute_ortszeit()

    projekte = {
        nummer: projekt_id
        for projekt_id, nummer in sitzung.execute(select(Projekt.id, Projekt.projekt_nr)).all()
    }
    befunde, verwaist = ordner_lesen(wurzel, projekte, werte)

    vorhandene_ordner = {
        eintrag.projekt_id: eintrag for eintrag in sitzung.execute(select(Projektordner)).scalars()
    }
    vorhandene_dokumente = {
        (eintrag.projekt_id, eintrag.typ): eintrag
        for eintrag in sitzung.execute(select(Dokument)).scalars()
    }

    ergebnis = Scanergebnis(projekte=len(befunde), verwaist=sorted(verwaist))
    # Nur die Typen, für die es überhaupt ein Muster gibt: für 'sonstig' gibt es keines, und
    # eine Zeile „sonstig fehlt" wäre eine Aussage über nichts.
    gesuchte_typen = sorted(werte.muster)

    for befund in befunde.values():
        eintrag = vorhandene_ordner.get(befund.projekt_id)
        if eintrag is None:
            eintrag = Projektordner(projekt_id=befund.projekt_id)
            sitzung.add(eintrag)
        eintrag.pfad = str(befund.pfad) if befund.pfad else None
        eintrag.gefunden = befund.hat_ordner
        eintrag.dateien = befund.dateien
        eintrag.mehrdeutig_mit = str(befund.mehrdeutig_mit) if befund.mehrdeutig_mit else None
        eintrag.geprueft_am = stichtag

        if befund.hat_ordner:
            ergebnis.mit_ordner += 1
        else:
            ergebnis.ohne_ordner += 1
        if befund.mehrdeutig_mit is not None:
            ergebnis.mehrdeutig += 1

        for typ in gesuchte_typen:
            datei = befund.gefunden.get(typ)
            zeile = vorhandene_dokumente.get((befund.projekt_id, typ))
            if zeile is None:
                zeile = Dokument(projekt_id=befund.projekt_id, typ=typ, pfad="")
                sitzung.add(zeile)
            # Ohne Fund trägt der Pfad den Ordner, in dem gesucht wurde. Das ist mehr wert als
            # ein leeres Feld: es sagt, wo die Unterlage hingehört.
            zeile.pfad = str(datei) if datei else (eintrag.pfad or "")
            zeile.vorhanden = datei is not None
            zeile.geprueft_am = stichtag

        # Nur ein *vorhandener* Ordner kann unvollständig sein. Ein Projekt ohne Ordner steht
        # schon in `ohne_ordner`, und die beiden Lagen haben verschiedene Ursachen: dort ein
        # Namensproblem, hier eine echte Lücke in der Mappe. Beides zusammenzuzählen meldete
        # dasselbe Projekt zweimal und nannte es obendrein „Ordner", den es nicht gibt.
        if befund.hat_ordner and [typ for typ in werte.pflicht if typ not in befund.gefunden]:
            ergebnis.unvollstaendig += 1

    sitzung.flush()
    return ergebnis


def fehlende_pflicht(
    sitzung: Session,
    projekt_id: int,
    werte: DokumenteEinstellungen | None = None,
) -> list[str]:
    """Welche Pflichtunterlagen zu einem Projekt fehlen.

    Ein Projekt, das noch nie gescannt wurde, gibt eine **leere** Liste zurück, keine
    vollständige. Ein Hinweis „alles fehlt", nur weil der Scan nie lief, wäre falsch und würde
    nach zweimal Wegklicken nie wieder gelesen.
    """
    werte = werte or einstellungen().dokumente
    if not werte.pflicht:
        return []

    ordner = sitzung.execute(
        select(Projektordner).where(Projektordner.projekt_id == projekt_id)
    ).scalar_one_or_none()
    if ordner is None or ordner.geprueft_am is None:
        return []

    vorhanden = {
        zeile.typ
        for zeile in sitzung.execute(
            select(Dokument).where(Dokument.projekt_id == projekt_id, Dokument.vorhanden.is_(True))
        ).scalars()
    }
    return [typ for typ in werte.pflicht if typ not in vorhanden]
