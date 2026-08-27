"""Übernahme der Bestandsdaten in die Datenbank (PLAN §9).

Ein Lauf, ein Stichtag: danach ist der Leitstand führend und die Quelldateien werden
schreibgeschützt. Entsprechend läuft die Übernahme in **einer** Schreibtransaktion – sie geht
ganz durch oder gar nicht. Ein halb migrierter Bestand wäre schlimmer als keiner, weil niemand
mehr wüsste, was schon drin ist.

Vier Regeln, die hier ihren Platz haben:

1. **Nichts wird erfunden.** Fehlt ein Auftragswert, bleibt er leer; ist ein Gewerk nicht aus dem
   Text erkennbar, wird es aus den Anlagendaten des Projekts abgeleitet und der Fall vermerkt.
2. **Die Lücke zwischen Auftragswert und Zahlungsplan wird ausgewiesen, nicht gefüllt.** Die
   Auftragsliste führt nur die offenen Positionen; bei Altprojekten liegt ihre Summe deshalb
   unter dem Auftragswert. Der Bericht nennt die Differenz je Projekt (Entscheidung Svens,
   docs/OFFENE-PUNKTE.md Nr. 11).
3. **Ein zweiter Lauf wird abgewiesen**, nicht stillschweigend verdoppelt.
4. **Kontrollsummen kommen in den Importlauf.** Sie sind der Nachweis, dass die Übernahme
   vollständig war, und stehen der Abnahme nach PLAN §7 zur Verfügung.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dienste.nummernkreise import naechste_projektnummer, naechster_wert
from app.fehler import FachFehler
from app.geld import formatiere_euro
from app.migration.quellen import (
    SUMMENFEHLER,
    Auftragsliste,
    AuftragsZeile,
    Befund,
    ProjektZeile,
    Teamliste,
    auftragsliste_lesen,
    teamliste_lesen,
)
from app.migration.vokabular import vergleichsform
from app.migration.zuordnung import Art, Zuordnung, Zuordnungsvorschau, vorschau_erstellen
from app.modelle import Importlauf, Kunde, Meilenstein, Projekt, Zahlungsplanposition
from app.zeit import heute_ortszeit, jetzt_utc

QUELLE = "migration"

# Ein Lauf gilt als erfolgreich, sobald er durchgelaufen ist. 'warnung' bekommt er, wenn etwas
# Aufmerksamkeit braucht: unlesbare Werte in den Quelldateien oder Zeilen, die ohne Zuordnung
# geblieben sind. Beides ist kein Fehler – aber es soll auf der Startseite auffallen.
ABGESCHLOSSEN = ("erfolg", "warnung")

# Dateinamen, unter denen die Bestandsdateien im Migrationsordner erwartet werden. Die Endung
# steht nicht fest, weil Excel beim Speichern gern .xlsx anhängt oder Umlaute ersetzt.
DATEI_AUFTRAEGE = "Offene_Auftraege"
DATEI_TEAMLISTE = "Teambesprechung"

# Marker, die für sich sprechen. Alles andere (Kalenderwochen, Mehrfachkreuze, Freitext) wird als
# Originalinhalt an den Meilenstein geschrieben, damit die Herkunft ablesbar bleibt.
EINDEUTIGE_MARKER = ("x", "X", "-", "o", "O")

# Bis zu einem Euro Abweichung zwischen Auftragswert und Zahlungsplansumme wird keine Lücke
# gemeldet: die Auftragsliste rundet je Zeile, der Auftragswert steht als Ganzes daneben.
RUNDUNGSTOLERANZ_CENT = 100


class MigrationFehler(FachFehler):
    code = "migration"


class QuelldateiFehlt(MigrationFehler):
    def __init__(self, ordner: Path, gesucht: str, gefunden: list[str]) -> None:
        super().__init__(
            f"Im Ordner '{ordner}' liegt keine Datei, deren Name mit '{gesucht}' beginnt.",
            "Gefunden wurden: "
            + (", ".join(sorted(gefunden)) or "keine Excel-Dateien")
            + ". Bitte den Pfad in der config.toml unter [pfade] migration prüfen.",
        )


class BereitsUebernommen(MigrationFehler):
    code = "migration_bereits_gelaufen"
    status_code = 409

    def __init__(self, lauf: Importlauf) -> None:
        zeitpunkt = lauf.beendet or lauf.gestartet
        super().__init__(
            f"Die Bestandsdaten wurden am {zeitpunkt:%d.%m.%Y um %H:%M} Uhr (UTC) bereits "
            f"übernommen.",
            "Ein zweiter Lauf würde alles doppelt anlegen. Soll neu migriert werden, muss "
            "vorher eine leere Datenbank angelegt werden (ip3-leitstand schema).",
        )


class OffeneZuordnungen(MigrationFehler):
    code = "migration_zuordnung_offen"
    status_code = 409

    def __init__(self, anzahl: int, betrag_cent: int) -> None:
        super().__init__(
            f"{anzahl} Kunden der Auftragsliste sind noch keinem Projekt zugeordnet "
            f"({formatiere_euro(betrag_cent)}).",
            "In der Zuordnungsmaske je Kunde ein Projekt bestätigen oder 'als eigenes Projekt "
            "anlegen' wählen. Erst danach kann übernommen werden.",
        )


@dataclass
class Analyse:
    """Was in den Dateien steht, bevor etwas geschrieben wird."""

    auftraege: Auftragsliste
    projekte: Teamliste
    vorschau: Zuordnungsvorschau

    @property
    def befunde(self) -> list[Befund]:
        return [*self.auftraege.befunde, *self.projekte.befunde]

    def kontrollsummen(self) -> dict[str, object]:
        """Zahlen, die im Importprotokoll landen und die Abnahme belegen (PLAN §7)."""
        return {
            "auftragsliste": {
                "datei": self.auftraege.datei.name,
                "zeilen": len(self.auftraege.zeilen),
                "summe_netto_cent": self.auftraege.summe_netto_cent,
                "summe_gestellt_cent": self.auftraege.summe_gestellt_cent,
                "zeilen_gestellt": sum(1 for z in self.auftraege.zeilen if z.gestellt),
                "summe_je_monat_cent": self.auftraege.summe_je_monat(),
                "auftragssummen_ohne_zahlungsplan": sum(
                    1 for z in self.auftraege.zeilen if z.ist_projektsumme
                ),
            },
            "teamliste": {
                "datei": self.projekte.datei.name,
                "projekte": len(self.projekte.zeilen),
                "summe_ab_wert_cent": self.projekte.summe_ab_wert_cent,
                "projekte_mit_ab_wert": sum(
                    1 for z in self.projekte.zeilen if z.ab_wert_cent is not None
                ),
                "summe_pv_kwp": str(self.projekte.summe_pv_kwp),
                "anzahl_je_status": self.projekte.anzahl_je_status(),
                "meilensteine": sum(len(z.meilensteine) for z in self.projekte.zeilen),
                # Die Anlagenart ist aus PV-, Speicher- und Ladestationsdaten abgeleitet.
                # 'freiflaeche' erkennt der Import nur, wenn es im Namen steht – die Übersicht
                # macht sichtbar, wie viel davon in der Projektmaske nachzusehen ist.
                "anlagenart_abgeleitet": _zaehlen(z.anlagenart for z in self.projekte.zeilen),
            },
            "zuordnung": {
                "kunden_je_art": self.vorschau.je_art(),
                "zeilen_je_art": self.vorschau.zeilen_je_art(),
                "offen": len(self.vorschau.offene),
                "offen_betrag_cent": self.vorschau.betrag_offen_cent,
            },
            "befunde": {
                "warnung": sum(1 for b in self.befunde if b.schwere == "warnung"),
                "hinweis": sum(1 for b in self.befunde if b.schwere == "hinweis"),
            },
            # Die Dateien rechnen an ihren Kopfzeilen falsch. Das gehört ins Protokoll, sonst
            # sieht die Abweichung zu den gewohnten Zahlen wie ein Importfehler aus.
            "summenfehler_der_quelldateien": [
                {"datei": datei, "zelle": zelle, "fehler": text}
                for datei, zelle, text in SUMMENFEHLER
            ],
        }


@dataclass
class Uebernahmebericht:
    """Was die Übernahme angelegt hat."""

    importlauf_id: int | None = None
    kunden: int = 0
    projekte: int = 0
    zahlungsplan: int = 0
    meilensteine: int = 0
    zahlungsplan_gestellt: int = 0
    zahlungsplan_summe_cent: int = 0
    projekte_ohne_auftragsjahr: int = 0
    ab_luecken: list[dict[str, object]] = field(default_factory=list)
    gewerk_abgeleitet: list[dict[str, object]] = field(default_factory=list)
    nicht_uebernommen: list[dict[str, object]] = field(default_factory=list)
    gleiche_bezeichnung: list[dict[str, object]] = field(default_factory=list)

    @property
    def luecke_gesamt_cent(self) -> int:
        return sum(int(eintrag["differenz_cent"]) for eintrag in self.ab_luecken)


def _zaehlen(werte: Iterable[str | None]) -> dict[str, int]:
    """Häufigkeit je Wert, ``None`` als ``'ohne Angabe'``."""
    zaehler: dict[str, int] = {}
    for wert in werte:
        schluessel = wert or "ohne Angabe"
        zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
    return dict(sorted(zaehler.items(), key=lambda paar: (-paar[1], paar[0])))


def quelldateien_finden(ordner: Path) -> tuple[Path, Path]:
    """Sucht die beiden Bestandsdateien im Migrationsordner.

    Gesucht wird über den Namensanfang, nicht über den vollen Namen: die Dateien heißen im
    Bestand ``Offene_Auftra_ge_2025.xlsx`` mit ersetztem Umlaut, und das Jahr im Namen wechselt.
    """
    if not ordner.is_dir():
        raise MigrationFehler(
            f"Der Migrationsordner '{ordner}' gibt es nicht.",
            "Pfad in der config.toml unter [pfade] migration eintragen und die beiden "
            "Bestandsdateien dort ablegen.",
        )
    tabellen = [p for p in sorted(ordner.iterdir()) if p.suffix.lower() in (".xlsx", ".xlsm")]
    namen = [p.name for p in tabellen]

    def suchen(anfang: str) -> Path:
        passend = [p for p in tabellen if p.stem.lower().startswith(anfang.lower())]
        if not passend:
            raise QuelldateiFehlt(ordner, anfang, namen)
        return passend[0]

    return suchen(DATEI_AUFTRAEGE), suchen(DATEI_TEAMLISTE)


def analysieren(ordner: Path) -> Analyse:
    """Liest beide Dateien und erstellt die Zuordnungsvorschau. Schreibt nichts."""
    pfad_auftraege, pfad_teamliste = quelldateien_finden(ordner)
    auftraege = auftragsliste_lesen(pfad_auftraege)
    projekte = teamliste_lesen(pfad_teamliste)
    return Analyse(
        auftraege=auftraege,
        projekte=projekte,
        vorschau=vorschau_erstellen(auftraege.zeilen, projekte.zeilen),
    )


@dataclass
class _Lauf:
    """Zustand eines Übernahmelaufs.

    Bündelt, was alle Schritte brauchen. Vorher hingen dieselben sechs Argumente an jeder
    Funktion, und der Kundenspeicher wurde an einer Stelle versehentlich leer neu angelegt –
    derselbe Kunde wäre zweimal in der Datenbank gelandet.
    """

    sitzung: Session
    analyse: Analyse
    firma_id: int
    herkunft: str
    bericht: Uebernahmebericht
    kunden_je_form: dict[str, Kunde] = field(default_factory=dict)
    projekte_je_zeile: dict[int, Projekt] = field(default_factory=dict)

    @property
    def auftragszeilen_je_nummer(self) -> dict[int, AuftragsZeile]:
        return {z.zeile: z for z in self.analyse.auftraege.zeilen}


def uebernehmen(
    sitzung: Session,
    analyse: Analyse,
    firma_id: int,
    *,
    offene_zulassen: bool = False,
) -> Uebernahmebericht:
    """Schreibt Kunden, Projekte, Zahlungsplan und Meilensteine in die Datenbank.

    Muss innerhalb einer Schreibtransaktion aufgerufen werden (``schreib_transaktion``), damit
    ein Fehler alles zurücknimmt. ``offene_zulassen`` übergeht die Prüfung auf unzugeordnete
    Kunden – für den Fall, dass die Projekte zuerst und der Zahlungsplan später kommen soll.
    """
    _pruefe_erstlauf(sitzung)
    offene = analyse.vorschau.offene
    if offene and not offene_zulassen:
        raise OffeneZuordnungen(len(offene), analyse.vorschau.betrag_offen_cent)

    protokoll = Importlauf(
        quelle=QUELLE,
        datei=f"{analyse.auftraege.datei.name}, {analyse.projekte.datei.name}",
        gestartet=jetzt_utc(),
        status="laeuft",
    )
    sitzung.add(protokoll)
    sitzung.flush()

    lauf = _Lauf(
        sitzung=sitzung,
        analyse=analyse,
        firma_id=firma_id,
        herkunft=f"{QUELLE} {heute_ortszeit():%Y-%m-%d}",
        bericht=Uebernahmebericht(importlauf_id=protokoll.id),
    )
    _projekte_anlegen(lauf)
    _zahlungsplan_anlegen(lauf)
    _luecken_ermitteln(lauf)

    protokoll.beendet = jetzt_utc()
    protokoll.status = _laufstatus(lauf)
    protokoll.ergebnis = _protokoll_bauen(lauf)
    sitzung.flush()
    return lauf.bericht


def _laufstatus(lauf: _Lauf) -> str:
    """'warnung', wenn etwas nachzusehen ist, sonst 'erfolg'.

    Der Datenstand auf der Startseite zeigt den Status; ein Lauf, der Zeilen liegen gelassen hat,
    darf dort nicht wie ein glatter Erfolg aussehen.
    """
    if lauf.bericht.nicht_uebernommen:
        return "warnung"
    if any(b.schwere == "warnung" for b in lauf.analyse.befunde):
        return "warnung"
    return "erfolg"


def _protokoll_bauen(lauf: _Lauf) -> dict[str, object]:
    bericht = lauf.bericht
    return {
        "kontrollsummen": lauf.analyse.kontrollsummen(),
        "angelegt": {
            "kunden": bericht.kunden,
            "projekte": bericht.projekte,
            "zahlungsplan": bericht.zahlungsplan,
            "zahlungsplan_gestellt": bericht.zahlungsplan_gestellt,
            "zahlungsplan_summe_cent": bericht.zahlungsplan_summe_cent,
            "meilensteine": bericht.meilensteine,
            "projekte_ohne_auftragsjahr": bericht.projekte_ohne_auftragsjahr,
        },
        "ab_luecken": bericht.ab_luecken,
        "gewerk_abgeleitet": bericht.gewerk_abgeleitet,
        "nicht_uebernommen": bericht.nicht_uebernommen,
        "gleiche_bezeichnung": bericht.gleiche_bezeichnung,
        "befunde": [
            {
                "datei": b.datei,
                "zeile": b.zeile,
                "spalte": b.spalte,
                "wert": b.wert,
                "meldung": b.meldung,
                "schwere": b.schwere,
            }
            for b in lauf.analyse.befunde
        ],
    }


def _pruefe_erstlauf(sitzung: Session) -> None:
    """Ein zweiter Lauf würde alles doppelt anlegen – also abweisen."""
    vorhanden = sitzung.scalar(
        select(Importlauf)
        .where(Importlauf.quelle == QUELLE, Importlauf.status.in_(ABGESCHLOSSEN))
        .order_by(Importlauf.id)
        .limit(1)
    )
    if vorhanden is not None:
        raise BereitsUebernommen(vorhanden)


def _projekte_anlegen(lauf: _Lauf) -> None:
    """Kunden, Projekte und Meilensteine aus der Teamliste."""
    laufendes_jahr = heute_ortszeit().year

    for zeile in lauf.analyse.projekte.zeilen:
        kunde = _kunde_holen(lauf, zeile.kunde, zeile.ort)
        jahr = zeile.auftrag_vom.year if zeile.auftrag_vom else laufendes_jahr
        if zeile.auftrag_vom is None:
            # Ohne Auftragsdatum gibt es kein Auftragsjahr für die Nummer. Das laufende Jahr ist
            # die einzige nachvollziehbare Wahl; die Herkunft steht in quelle_migration, und der
            # Bericht nennt die Anzahl, damit es nicht untergeht.
            lauf.bericht.projekte_ohne_auftragsjahr += 1
        projekt = Projekt(
            projekt_nr=naechste_projektnummer(lauf.sitzung, lauf.firma_id, jahr=jahr),
            firma_id=lauf.firma_id,
            typ="projekt",
            kunde_id=kunde.id,
            standort=zeile.ort,
            pv_kwp=zeile.pv_kwp,
            wr_typ=zeile.wr_typ,
            speicher_typ=zeile.speicher_typ,
            speicher_kwh=zeile.speicher_kwh,
            ladestation=zeile.ladestation,
            anlagenart=zeile.anlagenart,
            auftrag_vom=zeile.auftrag_vom,
            ab_wert_netto=zeile.ab_wert_cent,
            pl_name=zeile.pl_name,
            status=zeile.status,
            quelle_migration=(
                f"{lauf.herkunft}; {lauf.analyse.projekte.datei.name} Zeile {zeile.zeile}"
            ),
            bemerkung=_bemerkung_bauen(zeile),
        )
        lauf.sitzung.add(projekt)
        lauf.sitzung.flush()
        lauf.projekte_je_zeile[zeile.zeile] = projekt
        lauf.bericht.projekte += 1
        lauf.bericht.meilensteine += _meilensteine_anlegen(lauf, projekt, zeile)


def _kunde_holen(lauf: _Lauf, name: str, ort: str | None) -> Kunde:
    """Kunde je Name und Ort, einmal angelegt und wiederverwendet.

    Zusammengefasst wird über die Vergleichsform: 23 Kundennamen der Teamliste kommen mehrfach
    vor, weil derselbe Kunde mehrere Projekte hat. Ein Kunde je Projektzeile wäre falsch.
    """
    schluessel = f"{vergleichsform(name)}|{vergleichsform(ort or '')}"
    vorhanden = lauf.kunden_je_form.get(schluessel)
    if vorhanden is not None:
        return vorhanden
    kunde = Kunde(
        kunden_nr=naechster_wert(lauf.sitzung, lauf.firma_id, "KD"),
        name=name,
        ort=ort,
        # Privat oder Gewerbe steht in keiner der Quelldateien. b2c ist der häufigere Fall und
        # wirkt sich erst ab Phase 3 aus (ZUGFeRD nur für Geschäftskunden); in der Kundenmaske
        # ist es umstellbar.
        typ="b2c",
        status="aktiv",
    )
    lauf.sitzung.add(kunde)
    lauf.sitzung.flush()
    lauf.kunden_je_form[schluessel] = kunde
    lauf.bericht.kunden += 1
    return kunde


def _bemerkung_bauen(zeile: ProjektZeile) -> str | None:
    """Bemerkung, Vorplanungswerte und Nachkalkulations-Altwerte als Notiz.

    Die Nachkalkulations-Altwerte kommen ausdrücklich **nicht** als Ist-Kosten in die Datenbank
    (PLAN §9): sie sind von Hand gerechnet, ihre Grundlage ist nicht nachvollziehbar. Ab Phase 4
    entstehen Ist-Kosten aus DATEV, Stückliste und Stunden.
    """
    teile: list[str] = []
    if zeile.bemerkung:
        teile.append(zeile.bemerkung)
    if zeile.vorplanung:
        werte = "; ".join(f"{k}={v}" for k, v in zeile.vorplanung.items())
        teile.append(f"Vorplanung aus der Teamliste: {werte}")
    if zeile.nachkalkulation:
        werte = "; ".join(f"{k}={v}" for k, v in zeile.nachkalkulation.items())
        teile.append(f"Nachkalkulation (Altwerte, nicht als Ist-Kosten übernommen): {werte}")
    return "\n".join(teile) or None


def _meilensteine_anlegen(lauf: _Lauf, projekt: Projekt, zeile: ProjektZeile) -> int:
    for typ, stand in zeile.meilensteine.items():
        lauf.sitzung.add(
            Meilenstein(
                projekt_id=projekt.id,
                typ=typ,
                geplant_kw=stand.geplant_kw,
                erledigt=stand.erledigt,
                # Die Teamliste kreuzt ohne Datum – ein erfundenes erledigt_am wäre eine
                # Falschangabe. Siehe Migration 0003.
                erledigt_am=None,
                bemerkung=None if stand.roh in EINDEUTIGE_MARKER else f"Quelle: {stand.roh}",
            )
        )
    lauf.sitzung.flush()
    return len(zeile.meilensteine)


def _zahlungsplan_anlegen(lauf: _Lauf) -> None:
    """Zahlungsplanpositionen aus der Auftragsliste, je zugeordnetem Projekt."""
    zeilen_je_nummer = lauf.auftragszeilen_je_nummer
    datei = lauf.analyse.auftraege.datei.name

    for zuordnung in lauf.analyse.vorschau.zuordnungen:
        projekt = _projekt_fuer(lauf, zuordnung)
        if projekt is None:
            # Nur mit offene_zulassen erreichbar: die Positionen bleiben ungeschrieben. Das
            # steht im Protokoll, damit später niemand nach fehlenden Beträgen sucht.
            lauf.bericht.nicht_uebernommen.append(
                {
                    "kunde": zuordnung.kundenteil,
                    "zeilen": zuordnung.auftrags_zeilen,
                    "betrag_cent": zuordnung.betrag_cent,
                    "grund": "keinem Projekt zugeordnet",
                }
            )
            continue

        positionen = sorted(
            (zeilen_je_nummer[n] for n in zuordnung.auftrags_zeilen),
            key=_positionsreihenfolge,
        )
        for laufend, auftragszeile in enumerate(positionen, start=1):
            lauf.sitzung.add(
                Zahlungsplanposition(
                    projekt_id=projekt.id,
                    # Fortlaufend je Projekt, nicht die Nummer aus dem Text: ein Projekt hat
                    # PV- und Speicherabschläge, beide beginnen bei 1 – als pos_nr wären sie
                    # doppelt (UNIQUE projekt_id, pos_nr).
                    pos_nr=laufend,
                    bezeichnung=_bezeichnung(auftragszeile),
                    gewerk=_gewerk_bestimmen(lauf, auftragszeile, projekt, datei),
                    art=auftragszeile.rechnungsart.art or "einmal",
                    betrag_netto=auftragszeile.betrag_cent,
                    plan_monat=auftragszeile.plan_monat,
                    quelle_migration=f"{datei} Zeile {auftragszeile.zeile}",
                    migriert_gestellt=auftragszeile.gestellt,
                )
            )
            lauf.bericht.zahlungsplan += 1
            lauf.bericht.zahlungsplan_summe_cent += auftragszeile.betrag_cent
            if auftragszeile.gestellt:
                lauf.bericht.zahlungsplan_gestellt += 1
        _gleiche_bezeichnungen_melden(lauf, projekt, positionen, datei)
        lauf.sitzung.flush()


def _projekt_fuer(lauf: _Lauf, zuordnung: Zuordnung) -> Projekt | None:
    """Projekt einer Zuordnung; legt bei ``NEUES_PROJEKT`` eines an."""
    if zuordnung.art is Art.NEUES_PROJEKT:
        return _projekt_aus_auftragsliste(lauf, zuordnung)
    if zuordnung.projekt_zeile is not None:
        return lauf.projekte_je_zeile.get(zuordnung.projekt_zeile)
    return None


def _projekt_aus_auftragsliste(lauf: _Lauf, zuordnung: Zuordnung) -> Projekt:
    """Legt ein Projekt für einen Kunden an, den nur die Auftragsliste kennt.

    16 Kunden der Auftragsliste haben kein Gegenstück in der Teamliste – meist Projekte, die
    dort nie eingetragen wurden. Sie bekommen ein Projekt ohne Anlagendaten: die Beträge sind da,
    alles Weitere trägt die Projektmaske nach.
    """
    erste = lauf.auftragszeilen_je_nummer[zuordnung.auftrags_zeilen[0]]
    kunde = _kunde_holen(lauf, erste.kunde, erste.ort)
    projekt = Projekt(
        projekt_nr=naechste_projektnummer(lauf.sitzung, lauf.firma_id),
        firma_id=lauf.firma_id,
        typ="projekt",
        kunde_id=kunde.id,
        standort=erste.ort,
        status="beauftragt",
        quelle_migration=(
            f"{lauf.herkunft}; {lauf.analyse.auftraege.datei.name} Zeile {erste.zeile} "
            "(kein Eintrag in der Teamliste)"
        ),
    )
    lauf.sitzung.add(projekt)
    lauf.sitzung.flush()
    lauf.bericht.projekte += 1
    lauf.bericht.projekte_ohne_auftragsjahr += 1
    return projekt


def _positionsreihenfolge(zeile: AuftragsZeile) -> tuple[int, int, int]:
    """Sortierung der Positionen eines Projekts: erst PV, dann Speicher, dann Rest.

    Innerhalb eines Gewerks nach Abschlagsnummer, Schlussrechnung zuletzt. So steht der
    Zahlungsplan in der Reihenfolge, in der auch abgerechnet wird.
    """
    gewerke = {"pv": 0, "speicher": 1, "ls": 2, "service": 3}
    arten = {"abschlag": 0, "einmal": 1, "schluss": 2}
    art = zeile.rechnungsart
    return (gewerke.get(art.gewerk or "", 9), arten.get(art.art or "", 9), art.nummer or 0)


def _bezeichnung(zeile: AuftragsZeile) -> str:
    """Sprechende Bezeichnung der Position.

    Vorrang hat der Originaltext der Rechnungsart – er stand so in der Auftragsliste und ist
    denen vertraut, die damit gearbeitet haben. Fehlt er, wird die Zeile benannt.
    """
    if zeile.rechnungsart.text:
        return zeile.rechnungsart.text
    return f"Auftragssumme (Altbestand, Zeile {zeile.zeile})"


def _gleiche_bezeichnungen_melden(
    lauf: _Lauf, projekt: Projekt, positionen: list[AuftragsZeile], datei: str
) -> None:
    """Melden, wenn mehrere Positionen eines Projekts denselben Text tragen.

    Die Auftragsliste führt das vor: bei HPZ, Irchenrieth heißen vier Zeilen mit
    unterschiedlichen Beträgen und Monaten alle „1. Abschlag PV". Gemeint sind offensichtlich
    der erste bis vierte Abschlag. Der Text wird **nicht** verändert – er ist die Quelle, und
    eine erfundene Nummerierung wäre eine Behauptung. Aber ab Phase 3 steht dieser Text auf der
    Rechnung, deshalb gehört er in die Liste dessen, was in der Maske nachzuziehen ist.
    """
    je_text: dict[str, list[int]] = {}
    for zeile in positionen:
        je_text.setdefault(_bezeichnung(zeile), []).append(zeile.zeile)
    for text, zeilen in je_text.items():
        if len(zeilen) > 1:
            lauf.bericht.gleiche_bezeichnung.append(
                {
                    "datei": datei,
                    "projekt_nr": projekt.projekt_nr,
                    "bezeichnung": text,
                    "zeilen": zeilen,
                }
            )


def _gewerk_bestimmen(lauf: _Lauf, zeile: AuftragsZeile, projekt: Projekt, datei: str) -> str:
    """Gewerk der Position, notfalls aus den Anlagendaten des Projekts.

    In drei Zeilen des Bestands steht das Gewerk nicht im Text ('Donhauser, Bärnau - 100 %
    Rechnung'). Dann entscheidet, was am Projekt verbaut ist: nur Speicher oder nur Ladestation
    ist eindeutig. Ist PV dabei, bleibt es bei 'pv' – dem Hauptgewerk des Hauses. Jeder solche
    Fall steht im Protokoll und ist in der Maske nachzuziehen.
    """
    aus_text = zeile.rechnungsart.gewerk
    if aus_text:
        return aus_text

    hat_pv = projekt.pv_kwp is not None
    hat_speicher = projekt.speicher_kwh is not None or projekt.speicher_typ is not None
    if hat_speicher and not hat_pv:
        abgeleitet, eindeutig = "speicher", True
    elif projekt.ladestation and not hat_pv and not hat_speicher:
        abgeleitet, eindeutig = "ls", True
    else:
        abgeleitet, eindeutig = "pv", hat_pv and not hat_speicher

    lauf.bericht.gewerk_abgeleitet.append(
        {
            "datei": datei,
            "zeile": zeile.zeile,
            "text": zeile.freitext,
            "projekt_nr": projekt.projekt_nr,
            "gewerk": abgeleitet,
            "eindeutig": eindeutig,
        }
    )
    return abgeleitet


def _luecken_ermitteln(lauf: _Lauf) -> None:
    """Differenz zwischen Auftragswert und Summe des Zahlungsplans, je Projekt.

    Die Auftragsliste führt nur die **offenen** Positionen. Bei Altprojekten liegt ihre Summe
    deshalb unter dem Auftragswert: bei KMV Medi Center stehen 5.303,95 € gegen einen
    Auftragswert von 154.070,64 €, der Rest wurde in früheren Jahren berechnet.

    Gefüllt wird die Lücke nicht (Entscheidung Svens, docs/OFFENE-PUNKTE.md Nr. 11): eine
    Sammelposition „bereits berechnet" hätte es als Rechnung nie gegeben, und Umsatz ohne
    Belegbezug gehört nicht in die Datenbank. Ausgewiesen wird sie hier.
    """
    zeilen_je_nummer = lauf.auftragszeilen_je_nummer
    plansumme_je_projekt: dict[int, int] = {}
    for zuordnung in lauf.analyse.vorschau.zuordnungen:
        if zuordnung.projekt_zeile is None:
            continue
        projekt = lauf.projekte_je_zeile.get(zuordnung.projekt_zeile)
        if projekt is None:
            continue
        summe = sum(zeilen_je_nummer[n].betrag_cent for n in zuordnung.auftrags_zeilen)
        plansumme_je_projekt[projekt.id] = plansumme_je_projekt.get(projekt.id, 0) + summe

    for projekt in lauf.projekte_je_zeile.values():
        if projekt.ab_wert_netto is None:
            continue
        plansumme = plansumme_je_projekt.get(projekt.id, 0)
        if plansumme == 0:
            # Kein Zahlungsplan aus der Auftragsliste. Das ist der Regelfall bei den
            # abgeschlossenen Altprojekten und keine Lücke, die jemand schließen müsste.
            continue
        differenz = projekt.ab_wert_netto - plansumme
        # Ein Euro Rundungsdifferenz ist keine Meldung wert: die Auftragsliste rundet je Zeile,
        # der Auftragswert steht als Ganzes daneben.
        if abs(differenz) <= RUNDUNGSTOLERANZ_CENT:
            continue
        lauf.bericht.ab_luecken.append(
            {
                "projekt_nr": projekt.projekt_nr,
                "ab_wert_cent": projekt.ab_wert_netto,
                "zahlungsplan_cent": plansumme,
                "differenz_cent": differenz,
            }
        )
    lauf.bericht.ab_luecken.sort(key=lambda eintrag: -abs(int(eintrag["differenz_cent"])))
