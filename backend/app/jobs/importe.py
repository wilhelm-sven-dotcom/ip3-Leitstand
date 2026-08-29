"""Die nächtlichen Importläufe (PLAN §8).

Ein Job, der still fehlt, ist schlimmer als einer, der als „noch nicht eingerichtet" dasteht
(``app/jobs/katalog.py``). Deshalb gilt hier für alle drei dasselbe:

* **Eine fehlende Voraussetzung ist eine Warnung, kein Absturz.** Kein DATEV-Ordner, keine
  TimeTac-Zugangsdaten, kein Kalkulationsordner: der Lauf endet mit einer Meldung, die sagt, was
  fehlt, und der Systemstatus zeigt sie. Ein Fehlschlag mit Stacktrace stünde dort nur als
  „Fehler".
* **Ein Fehler löscht nichts.** Die Importe leeren ihren Zeitraum in derselben Transaktion, in
  der sie ihn neu füllen; bricht etwas ab, bleibt der alte Stand stehen. Beim Netzfehler in
  TimeTac wird gar nicht erst geschrieben.
* **Zwei Protokolle.** ``job_laeufe`` beantwortet „ist der Lauf gelaufen", ``importlaeufe`` „was
  hat er bewirkt". Beide entstehen, und beide werden gebraucht.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.datenbank import schreib_sitzung
from app.fehler import FachFehler
from app.jobs.lauf import LaufErgebnis, protokollierter_lauf
from app.konfiguration import Einstellungen, einstellungen
from app.protokoll import logger

log = logger(__name__)


def _konfiguration(werte: Einstellungen | None) -> Einstellungen:
    return werte or einstellungen()


# ---------------------------------------------------------------------------
# DATEV
# ---------------------------------------------------------------------------


@dataclass
class Teilergebnis:
    """Was eine der drei DATEV-Quellen beigetragen hat."""

    quelle: str
    dateien: int = 0
    zeitraeume: list[str] = field(default_factory=list)
    zeilen: int = 0
    summe_cent: int = 0
    fehler: list[str] = field(default_factory=list)
    hinweis: str = ""

    @property
    def hat_geliefert(self) -> bool:
        return bool(self.zeitraeume)


def datev_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """Alle drei Kanzlei-Exporte aus ``02_DATEV`` übernehmen (PLAN §8).

    Kostenträger, Summen- und Saldenliste und offene Posten liegen im selben Ordner und kommen
    im selben Monatsrhythmus – deshalb ein Lauf und nicht drei. Jede Quelle wird für sich
    verarbeitet: eine unlesbare SuSa hält die Kostenträger nicht auf.
    """
    konfiguration = _konfiguration(werte)
    with protokollierter_lauf("datev_import", ausgeloest_von) as ergebnis:
        _datev_lauf(konfiguration, ergebnis)


def _datev_lauf(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    ordner = werte.pfade.datev
    if ordner is None or not ordner.is_dir():
        ergebnis.warnen(
            "Kein erreichbarer DATEV-Ordner eingerichtet. In der config.toml unter [pfade] den "
            "Eintrag datev auf den OneDrive-Ordner 02_DATEV setzen."
        )
        return

    teile = [
        _kostentraeger_lauf(werte, ordner),
        _susa_lauf(werte, ordner),
        _opos_lauf(werte, ordner),
    ]
    ergebnis.kennzahlen = {
        teil.quelle: {
            "dateien": teil.dateien,
            "zeitraeume": teil.zeitraeume,
            "zeilen": teil.zeilen,
            "summe_cent": teil.summe_cent,
            "uebersprungen": len(teil.fehler),
        }
        for teil in teile
    }

    fehler = [meldung for teil in teile for meldung in teil.fehler]
    hinweise = [teil.hinweis for teil in teile if teil.hinweis and not teil.hat_geliefert]

    if fehler:
        ergebnis.warnen(
            f"{sum(len(t.zeitraeume) for t in teile)} Zeiträume übernommen, "
            f"{len(fehler)} Datei(en) übersprungen: " + "; ".join(fehler)
        )
        return
    if not any(teil.hat_geliefert for teil in teile):
        ergebnis.warnen(f"Im Ordner {ordner.name} liegt keine Kanzlei-Datei. " + " ".join(hinweise))
        return

    geschafft = ", ".join(
        f"{teil.quelle} {len(teil.zeitraeume)}" for teil in teile if teil.hat_geliefert
    )
    ergebnis.meldung = f"Übernommen: {geschafft} (Zeiträume)."
    if hinweise:
        # Eine noch nicht gelieferte Quelle wird genannt, macht den Lauf aber **nicht** zur
        # Warnung. Die Kanzlei liefert SuSa und OPOS erst nach der Abstimmung; sie monatelang
        # jede Nacht rot zu melden, gewöhnt alle daran, den Systemstatus zu übergehen. Dass
        # Zahlen fehlen, sagt das Cockpit an der Stelle, an der sie fehlen – dort lässt sich
        # etwas dagegen tun.
        ergebnis.meldung += " Noch ohne: " + " ".join(hinweise)


def _kostentraeger_lauf(werte: Einstellungen, ordner: Path) -> Teilergebnis:
    from app.importe.datev import kostentraeger_lesen, monat_aus_dateiname, uebernehmen

    teil = Teilergebnis(quelle="kostentraeger")
    dateien = sorted(
        (p for p in ordner.glob("kostentraeger*.csv") if monat_aus_dateiname(p)),
        key=lambda p: monat_aus_dateiname(p) or "",
    )
    teil.dateien = len(dateien)
    if not dateien:
        teil.hinweis = (
            "Die Kostenträgerauswertung fehlt ('kostentraeger_JJJJ-MM.csv') – ohne sie bleiben "
            "die Ist-Kosten der Projekte leer."
        )
        return teil

    for pfad in dateien:
        try:
            datei = kostentraeger_lesen(pfad, werte.datev.kostentraeger)
            with schreib_sitzung() as sitzung:
                ergebnis = uebernehmen(sitzung, datei)
            teil.zeitraeume.append(ergebnis.monat)
            teil.zeilen += ergebnis.zeilen
            teil.summe_cent += ergebnis.summe_cent
        except FachFehler as ausfall:
            # Eine unlesbare Datei darf die anderen Monate nicht aufhalten.
            teil.fehler.append(f"{pfad.name}: {ausfall.meldung}")
            log.warning("DATEV-Import übersprungen: %s – %s", pfad.name, ausfall.meldung)
    return teil


def _susa_lauf(werte: Einstellungen, ordner: Path) -> Teilergebnis:
    from app.datenbank import lese_sitzung
    from app.dienste.konten import bereiche_laden
    from app.importe.susa import monat_aus_dateiname, susa_lesen, uebernehmen

    teil = Teilergebnis(quelle="susa")
    dateien = sorted(
        (p for p in ordner.glob("susa*.csv") if monat_aus_dateiname(p)),
        key=lambda p: monat_aus_dateiname(p) or "",
    )
    teil.dateien = len(dateien)
    if not dateien:
        teil.hinweis = (
            "Die Summen- und Saldenliste fehlt ('susa_JJJJ-MM.csv') – ohne sie hat das "
            "Firmen-Cockpit keinen Fixkostenblock."
        )
        return teil

    with lese_sitzung() as sitzung:
        bereiche = bereiche_laden(sitzung)

    for pfad in dateien:
        try:
            datei = susa_lesen(pfad, werte.datev.susa, bereiche)
            with schreib_sitzung() as sitzung:
                ergebnis = uebernehmen(sitzung, datei)
            teil.zeitraeume.append(ergebnis.monat)
            teil.zeilen += ergebnis.zeilen
            teil.summe_cent += ergebnis.summe_cent
        except FachFehler as ausfall:
            teil.fehler.append(f"{pfad.name}: {ausfall.meldung}")
            log.warning("SuSa-Import übersprungen: %s – %s", pfad.name, ausfall.meldung)
    return teil


def _opos_lauf(werte: Einstellungen, ordner: Path) -> Teilergebnis:
    from app.importe.opos import opos_lesen, stichtag_aus_dateiname, uebernehmen

    teil = Teilergebnis(quelle="opos")
    dateien = sorted(
        (p for p in ordner.glob("opos*.csv") if stichtag_aus_dateiname(p)),
        key=lambda p: stichtag_aus_dateiname(p) or date.min,
    )
    teil.dateien = len(dateien)
    if not dateien:
        teil.hinweis = (
            "Die Liste der offenen Posten fehlt ('opos_JJJJ-MM-TT.csv') – ohne sie ist zu jeder "
            "Rechnung nur bekannt, dass sie gestellt wurde."
        )
        return teil

    for pfad in dateien:
        try:
            datei = opos_lesen(pfad, werte.datev.opos)
            with schreib_sitzung() as sitzung:
                ergebnis = uebernehmen(sitzung, datei)
            teil.zeitraeume.append(ergebnis.stichtag.isoformat())
            teil.zeilen += ergebnis.posten
            teil.summe_cent += ergebnis.offen_cent
        except FachFehler as ausfall:
            teil.fehler.append(f"{pfad.name}: {ausfall.meldung}")
            log.warning("OPOS-Import übersprungen: %s – %s", pfad.name, ausfall.meldung)
    return teil


# ---------------------------------------------------------------------------
# TimeTac
# ---------------------------------------------------------------------------


def timetac_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """Stunden des laufenden und des vorigen Monats holen (PLAN §8)."""
    konfiguration = _konfiguration(werte)
    with protokollierter_lauf("timetac_sync", ausgeloest_von) as ergebnis:
        _timetac_lauf(konfiguration, ergebnis)


def _timetac_lauf(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    from app.importe.timetac import uebernehmen
    from app.importe.timetac_api import TimeTacClient, abholen, monate_bestimmen

    if not werte.timetac.aktiv:
        ergebnis.warnen(
            "Der TimeTac-Abgleich ist abgeschaltet ([timetac] aktiv = false). Ohne ihn fehlt die "
            "Eigenleistung im Projekt-Ist."
        )
        return

    try:
        client = TimeTacClient(
            werte.timetac,
            client_id=werte.timetac_client_id,
            client_secret=werte.timetac_client_secret,
            konto=werte.timetac_konto,
        )
        monate = monate_bestimmen(werte.timetac)
        lieferung = abholen(client, monate)
    except FachFehler as ausfall:
        # Nichts geschrieben, nichts gelöscht: die vorhandenen Stunden bleiben stehen.
        ergebnis.warnen(f"{ausfall.meldung} {ausfall.naechster_schritt}")
        return

    with schreib_sitzung() as sitzung:
        teil = uebernehmen(sitzung, lieferung, werte.stundensaetze)

    ergebnis.kennzahlen = {
        "monate": teil.monate,
        "stundenzeilen": teil.stundenzeilen,
        "stunden": str(teil.summe_stunden),
        "summe_cent": teil.summe_cent,
        "ohne_satzgruppe": teil.ohne_satz,
    }
    if teil.ohne_satz:
        ergebnis.warnen(
            f"{teil.stundenzeilen} Stundenzeilen übernommen. Für "
            + ", ".join(teil.ohne_satz)
            + " ist keine Satzgruppe hinterlegt – gerechnet wurde mit dem Standardsatz. "
            "Eintragen in der config.toml unter [stundensaetze.mitarbeiter]."
        )
        return
    ergebnis.meldung = (
        f"{teil.stundenzeilen} Stundenzeilen übernommen ({teil.summe_stunden} Stunden, "
        f"{', '.join(teil.monate)})."
    )


# ---------------------------------------------------------------------------
# Kalkulationsblätter
# ---------------------------------------------------------------------------


def kalkulation_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """``03_Kalkulation`` scannen und die Sollwerte übernehmen (PLAN §8)."""
    konfiguration = _konfiguration(werte)
    with protokollierter_lauf("kalkulation_scan", ausgeloest_von) as ergebnis:
        _kalkulation_lauf(konfiguration, ergebnis)


def _kalkulation_lauf(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    from app.importe import laeufe
    from app.importe.kalkulationsblatt import (
        KalkulationsblattFehler,
        blatt_lesen,
        ordner_scannen,
        uebernehmen,
    )

    ordner: Path | None = werte.pfade.kalkulation
    if ordner is None or not ordner.is_dir():
        ergebnis.warnen(
            "Kein erreichbarer Kalkulationsordner eingerichtet. In der config.toml unter [pfade] "
            "den Eintrag kalkulation auf den OneDrive-Ordner 03_Kalkulation setzen."
        )
        return

    dateien, befunde = ordner_scannen(ordner)
    uebernommen = 0
    positionen = 0
    with schreib_sitzung() as sitzung:
        lauf = laeufe.lauf_beginnen(
            sitzung,
            quelle="kalkulation",
            datei=f"{len(dateien)} Blätter aus {ordner.name}",
        )
        for eintrag in dateien:
            try:
                blatt = blatt_lesen(eintrag.pfad)
            except KalkulationsblattFehler as ausfall:
                from app.importe.befunde import Befund

                befunde.append(
                    Befund(
                        datei=eintrag.pfad.name,
                        zeile=0,
                        spalte="datei",
                        wert=str(eintrag.projekt_nr),
                        meldung=f"{ausfall.meldung} {ausfall.naechster_schritt}",
                    )
                )
                continue
            teil = uebernehmen(sitzung, blatt)
            befunde.extend(teil.befunde)
            if teil.soll_geschrieben:
                uebernommen += 1
                positionen += teil.positionen_neu + teil.positionen_geaendert
        laeufe.lauf_abschliessen(
            sitzung,
            lauf,
            befunde=befunde,
            kontrollsummen={"blaetter": len(dateien), "uebernommen": uebernommen},
            unvollstaendig=uebernommen < len(dateien),
            weiteres={"positionen": positionen},
        )

    ergebnis.kennzahlen = {
        "blaetter": len(dateien),
        "uebernommen": uebernommen,
        "positionen": positionen,
        "befunde": len(befunde),
    }
    if uebernommen < len(dateien):
        ergebnis.warnen(
            f"{uebernommen} von {len(dateien)} Kalkulationsblättern übernommen. Die übrigen "
            "stehen mit Grund im Importprotokoll."
        )
        return
    ergebnis.meldung = (
        f"{uebernommen} Kalkulationsblätter übernommen, {positionen} Stücklistenpositionen."
    )
