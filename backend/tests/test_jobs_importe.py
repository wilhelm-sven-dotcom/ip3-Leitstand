"""Die drei nächtlichen Importläufe (PLAN §8, §2).

Der Punkt dieser Datei: **eine fehlende Voraussetzung ist eine Warnung, kein Absturz.** Kein
DATEV-Ordner, keine TimeTac-Zugangsdaten, kein Kalkulationsordner – der Lauf endet mit einer
Meldung, die im Systemstatus lesbar ist. Ein Job, der still fehlt, ist schlimmer als einer, der
als „noch nicht eingerichtet" dasteht (``app/jobs/katalog.py``).

Und: **ein Fehler löscht nichts.** Bricht der TimeTac-Lauf am Netz ab, bleiben die vorhandenen
Stunden stehen.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.jobs.importe import datev_job, kalkulation_job, timetac_job
from app.modelle import Firma, Importlauf, IstKosten, Kunde, Projekt, Stunden
from app.modelle.system import JobLauf

KOPF = (
    "Belegdatum;Konto;Kontobezeichnung;Buchungstext;Belegfeld 1;Umsatz;Soll/Haben-Kennzeichen;KOST2"
)


@pytest.fixture
def projekt(gesäte_db) -> int:
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=20001, name="Job GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()
        eintrag = Projekt(
            projekt_nr=26001,
            firma_id=firma_id,
            kunde_id=kunde.id,
            status="in_bau",
            ab_wert_netto=5000000,
        )
        sitzung.add(eintrag)
        sitzung.flush()
        return eintrag.id


def job_lauf(job: str) -> JobLauf:
    with lese_sitzung() as sitzung:
        lauf = sitzung.scalars(
            select(JobLauf).where(JobLauf.job == job).order_by(JobLauf.id.desc())
        ).first()
        assert lauf is not None, f"Der Lauf {job} hat keinen Protokolleintrag hinterlassen"
        return lauf


# ---------------------------------------------------------------------------
# Fehlende Voraussetzungen
# ---------------------------------------------------------------------------


def test_datev_ohne_ordner_warnt(test_einstellungen, gesäte_db) -> None:
    test_einstellungen.pfade.datev = None
    datev_job("manuell", test_einstellungen)

    lauf = job_lauf("datev_import")
    assert lauf.status == "warnung"
    assert "02_DATEV" in lauf.meldung


def test_datev_ohne_datei_warnt(test_einstellungen, gesäte_db, tmp_path: Path) -> None:
    ordner = tmp_path / "02_DATEV"
    ordner.mkdir()
    test_einstellungen.pfade.datev = ordner
    datev_job("manuell", test_einstellungen)

    lauf = job_lauf("datev_import")
    assert lauf.status == "warnung"
    assert "kostentraeger_JJJJ-MM.csv" in lauf.meldung


def test_kalkulation_ohne_ordner_warnt(test_einstellungen, gesäte_db) -> None:
    test_einstellungen.pfade.kalkulation = None
    kalkulation_job("manuell", test_einstellungen)

    lauf = job_lauf("kalkulation_scan")
    assert lauf.status == "warnung"
    assert "03_Kalkulation" in lauf.meldung


def test_timetac_ohne_zugangsdaten_warnt(test_einstellungen, gesäte_db) -> None:
    test_einstellungen.timetac_client_id = ""
    timetac_job("manuell", test_einstellungen)

    lauf = job_lauf("timetac_sync")
    assert lauf.status == "warnung"
    assert "IP3_TIMETAC_CLIENT_ID" in lauf.meldung
    assert ".env" in lauf.meldung


def test_abgeschaltetes_timetac_warnt_statt_zu_scheitern(test_einstellungen, gesäte_db) -> None:
    test_einstellungen.timetac.aktiv = False
    timetac_job("manuell", test_einstellungen)
    assert "abgeschaltet" in job_lauf("timetac_sync").meldung


# ---------------------------------------------------------------------------
# Erfolgsfälle
# ---------------------------------------------------------------------------


def test_datev_lauf_uebernimmt_alle_monate(
    test_einstellungen, projekt: int, tmp_path: Path
) -> None:
    ordner = tmp_path / "02_DATEV"
    ordner.mkdir()
    test_einstellungen.pfade.datev = ordner
    for monat, betrag in (("2026-07", "1.000,00"), ("2026-08", "2.000,00")):
        (ordner / f"kostentraeger_{monat}.csv").write_text(
            KOPF + f"\n05.{monat[5:]}.2026;3400;Wareneingang;Module;RE-1;{betrag};S;26001\n",
            encoding="utf-8",
        )

    datev_job("manuell", test_einstellungen)

    lauf = job_lauf("datev_import")
    assert lauf.status == "erfolg"
    assert lauf.kennzahlen["monate"] == ["2026-07", "2026-08"]
    with lese_sitzung() as sitzung:
        zeilen = list(sitzung.scalars(select(IstKosten).where(IstKosten.quelle == "datev")))
        assert sorted(z.monat for z in zeilen) == ["2026-07", "2026-08"]
        assert sum(z.betrag for z in zeilen) == 300000


def test_kaputte_datei_haelt_die_uebrigen_monate_nicht_auf(
    test_einstellungen, projekt: int, tmp_path: Path
) -> None:
    ordner = tmp_path / "02_DATEV"
    ordner.mkdir()
    test_einstellungen.pfade.datev = ordner
    (ordner / "kostentraeger_2026-07.csv").write_text(
        KOPF + "\n05.07.2026;3400;Wareneingang;Module;RE-1;1.000,00;S;26001\n", encoding="utf-8"
    )
    (ordner / "kostentraeger_2026-08.csv").write_text(
        "Ganz andere Spalten;ohne;alles\nx;y;z\n", encoding="utf-8"
    )

    datev_job("manuell", test_einstellungen)

    lauf = job_lauf("datev_import")
    assert lauf.status == "warnung"
    assert lauf.kennzahlen["monate"] == ["2026-07"]
    assert lauf.kennzahlen["uebersprungen"] == 1
    assert "kostentraeger_2026-08.csv" in lauf.meldung


def test_kalkulationslauf_schreibt_sollwerte(
    test_einstellungen, projekt: int, tmp_path: Path
) -> None:
    from openpyxl import load_workbook

    from app.importe.kalkulationsblatt import vorlage_erzeugen
    from app.modelle import SollKalkulation

    ordner = tmp_path / "03_Kalkulation"
    ordner.mkdir()
    test_einstellungen.pfade.kalkulation = ordner
    pfad = vorlage_erzeugen(ordner / "26001_Job.xlsx")
    mappe = load_workbook(pfad)
    blatt = mappe["EXPORT"]
    blatt["B6"], blatt["B7"], blatt["B10"] = 26001, 40000, 18
    mappe.save(pfad)
    mappe.close()

    kalkulation_job("manuell", test_einstellungen)

    lauf = job_lauf("kalkulation_scan")
    assert lauf.status == "erfolg"
    assert lauf.kennzahlen["uebernommen"] == 1
    with lese_sitzung() as sitzung:
        soll = sitzung.get(SollKalkulation, projekt)
        assert soll.material_soll == 4000000
        assert soll.marge_soll == 180
        # Beide Protokolle entstehen: job_laeufe und importlaeufe (PLAN §2, §8).
        assert sitzung.scalars(select(Importlauf).where(Importlauf.quelle == "kalkulation")).first()


def test_timetac_lauf_holt_und_schreibt(test_einstellungen, projekt: int, monkeypatch) -> None:
    from app.importe import timetac_api

    test_einstellungen.timetac_client_id = "CLIENT__API_USER_1"
    test_einstellungen.timetac_client_secret = "geheim"
    test_einstellungen.timetac_konto = "ip3energie"
    test_einstellungen.stundensaetze.mitarbeiter = {"Wilhelm, Sven": "planung"}

    def transport(anfrage: httpx.Request) -> httpx.Response:
        if anfrage.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "Results": [
                    {
                        "user_name": "Wilhelm, Sven",
                        "project_number": "26001",
                        "project_name": "Job GmbH",
                        "date": "2026-07-06",
                        "duration": 28800,
                    }
                ]
            },
        )

    echter_client = timetac_api.TimeTacClient

    def mit_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return echter_client(*args, **kwargs)

    monkeypatch.setattr(timetac_api, "TimeTacClient", mit_transport)
    monkeypatch.setattr(
        timetac_api, "monate_bestimmen", lambda _einstellungen, heute=None: ["2026-07"]
    )

    timetac_job("manuell", test_einstellungen)

    lauf = job_lauf("timetac_sync")
    assert lauf.status == "erfolg"
    assert lauf.kennzahlen["stundenzeilen"] == 1
    with lese_sitzung() as sitzung:
        stunde = sitzung.scalars(select(Stunden)).one()
        assert stunde.stunden == Decimal("8.00") and stunde.satz == 8500


def test_netzfehler_laesst_vorhandene_stunden_stehen(
    test_einstellungen, projekt: int, monkeypatch
) -> None:
    """Ein Ausfall darf keinen Monat leeren – sonst wären die Stunden weg und niemand merkt es."""
    from app.importe import timetac_api

    with schreib_sitzung() as sitzung:
        sitzung.add(
            Stunden(
                projekt_id=projekt,
                monat="2026-07",
                mitarbeiter="Wilhelm, Sven",
                stunden=Decimal("8.00"),
                satz=8500,
            )
        )

    test_einstellungen.timetac_client_id = "CLIENT__API_USER_1"
    test_einstellungen.timetac_client_secret = "geheim"
    test_einstellungen.timetac_konto = "ip3energie"

    def ausfall(anfrage: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Netz weg")

    echter_client = timetac_api.TimeTacClient

    def mit_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(ausfall)
        return echter_client(*args, **kwargs)

    monkeypatch.setattr(timetac_api, "TimeTacClient", mit_transport)
    timetac_job("manuell", test_einstellungen)

    lauf = job_lauf("timetac_sync")
    assert lauf.status == "warnung"
    assert "nicht erreichbar" in lauf.meldung
    with lese_sitzung() as sitzung:
        assert len(list(sitzung.scalars(select(Stunden)))) == 1, "die Stunden stehen noch"


def test_unbekannter_mitarbeiter_setzt_den_lauf_auf_warnung(
    test_einstellungen, projekt: int, monkeypatch
) -> None:
    from app.importe import timetac_api

    test_einstellungen.timetac_client_id = "CLIENT__API_USER_1"
    test_einstellungen.timetac_client_secret = "geheim"
    test_einstellungen.timetac_konto = "ip3energie"

    def transport(anfrage: httpx.Request) -> httpx.Response:
        if anfrage.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "Results": [
                    {
                        "user_name": "Neu, Kollege",
                        "project_number": "26001",
                        "project_name": "Job GmbH",
                        "date": "2026-07-06",
                        "duration": 3600,
                    }
                ]
            },
        )

    echter_client = timetac_api.TimeTacClient
    monkeypatch.setattr(
        timetac_api,
        "TimeTacClient",
        lambda *a, **k: echter_client(*a, **{**k, "transport": httpx.MockTransport(transport)}),
    )
    monkeypatch.setattr(
        timetac_api, "monate_bestimmen", lambda _einstellungen, heute=None: ["2026-07"]
    )

    timetac_job("manuell", test_einstellungen)

    lauf = job_lauf("timetac_sync")
    assert lauf.status == "warnung"
    assert "[stundensaetze.mitarbeiter]" in lauf.meldung
