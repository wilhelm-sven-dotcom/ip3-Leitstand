"""Die drei nächtlichen Importläufe der Phase 4 (PLAN §8).

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


def datev_job(ausgeloest_von: str = "zeitplan", werte: Einstellungen | None = None) -> None:
    """Alle noch nicht eingelesenen Kostenträgerdateien aus ``02_DATEV`` übernehmen."""
    konfiguration = _konfiguration(werte)
    with protokollierter_lauf("datev_import", ausgeloest_von) as ergebnis:
        _datev_lauf(konfiguration, ergebnis)


def _datev_lauf(werte: Einstellungen, ergebnis: LaufErgebnis) -> None:
    from app.importe.datev import kostentraeger_lesen, monat_aus_dateiname, uebernehmen

    ordner = werte.pfade.datev
    if ordner is None or not ordner.is_dir():
        ergebnis.warnen(
            "Kein erreichbarer DATEV-Ordner eingerichtet. In der config.toml unter [pfade] den "
            "Eintrag datev auf den OneDrive-Ordner 02_DATEV setzen."
        )
        return

    dateien = sorted(
        (p for p in ordner.glob("kostentraeger*.csv") if monat_aus_dateiname(p)),
        key=lambda p: monat_aus_dateiname(p) or "",
    )
    if not dateien:
        ergebnis.warnen(
            f"Im Ordner {ordner.name} liegt keine Kostenträgerdatei. Die Kanzlei liefert sie "
            "monatlich als 'kostentraeger_JJJJ-MM.csv'."
        )
        return

    monate: list[str] = []
    zeilen = 0
    summe = 0
    fehler: list[str] = []
    for pfad in dateien:
        try:
            datei = kostentraeger_lesen(pfad, werte.datev.kostentraeger)
            with schreib_sitzung() as sitzung:
                teil = uebernehmen(sitzung, datei)
            monate.append(teil.monat)
            zeilen += teil.zeilen
            summe += teil.summe_cent
        except FachFehler as ausfall:
            # Eine unlesbare Datei darf die anderen Monate nicht aufhalten.
            fehler.append(f"{pfad.name}: {ausfall.meldung}")
            log.warning("DATEV-Import übersprungen: %s – %s", pfad.name, ausfall.meldung)

    ergebnis.kennzahlen = {
        "dateien": len(dateien),
        "monate": monate,
        "zeilen": zeilen,
        "summe_cent": summe,
        "uebersprungen": len(fehler),
    }
    if fehler:
        ergebnis.warnen(
            f"{len(monate)} Monate übernommen, {len(fehler)} Datei(en) übersprungen: "
            + "; ".join(fehler)
        )
        return
    ergebnis.meldung = (
        f"{len(monate)} Monate übernommen ({', '.join(monate)}), {zeilen} Kostenzeilen."
    )


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
