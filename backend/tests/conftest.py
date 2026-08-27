"""Gemeinsame Test-Ausstattung.

Jeder Test bekommt eine eigene Datenbankdatei. Eine Datei statt einer Datenbank im
Arbeitsspeicher, weil mehrere Tests genau das prüfen, was nur mit Datei funktioniert:
gleichzeitige Zugriffe aus mehreren Threads, WAL-Modus und ``VACUUM INTO``.

Damit nicht jeder Test die Migrationen durchlaufen muss, wird das Schema einmal je Testlauf in
eine Vorlagedatei migriert und danach nur noch kopiert.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

# Die Konfiguration darf im Test nie die echte config.toml des Entwicklers finden.
os.environ["IP3_CONFIG"] = str(Path(__file__).parent / "fixtures" / "test-config.toml")
os.environ["IP3_ENV_DATEI"] = str(Path(__file__).parent / "fixtures" / "nicht-vorhanden.env")
os.environ.setdefault("IP3_SITZUNG_SCHLUESSEL", "testschluessel-nur-fuer-die-testsuite")

# bcrypt mit dem Betriebswert 12 kostet rund 0,3 Sekunden je Aufruf. Die Suite legt Dutzende
# Konten an und meldet sich hundertfach an – damit dauert ein Lauf Minuten, die vollständig in
# der Passwortfunktion verbracht werden. Der Test in test_seed_und_katalog.py stellt sicher,
# dass der Standard trotzdem bei 12 bleibt.
os.environ.setdefault("IP3_BCRYPT_KOSTEN", "4")


@pytest.fixture(autouse=True)
def aufraeumen():
    """Globalen Zustand nach jedem Test abräumen.

    Engine, Sitzungsfabrik, gepufferte Konfiguration und Protokoll-Handler sind
    Modulzustand. Bleibt davon etwas stehen, arbeitet der nächste Test gegen das
    temporäre Verzeichnis des vorigen – ein Fehler, der nur im Gesamtlauf auftritt und
    einzeln nicht nachvollziehbar ist.
    """
    yield
    from app import datenbank, konfiguration, protokoll

    datenbank.zuruecksetzen()
    konfiguration.zuruecksetzen()
    protokoll.zuruecksetzen()


@pytest.fixture
def daten_verzeichnis(tmp_path: Path) -> Path:
    verzeichnis = tmp_path / "daten"
    verzeichnis.mkdir()
    return verzeichnis


@pytest.fixture
def test_einstellungen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Konfiguration mit Pfaden im temporären Verzeichnis."""
    from app import datenbank, konfiguration, protokoll

    konfiguration.zuruecksetzen()
    datenbank.zuruecksetzen()
    protokoll.zuruecksetzen()

    werte = konfiguration.Einstellungen(
        app={"umgebung": "test", "erlaubte_herkunft": ["http://testserver"]},
        pfade={
            "datenbank": tmp_path / "daten" / "leitstand.sqlite3",
            "logs": tmp_path / "logs",
            "backup": tmp_path / "backup",
        },
        sitzung={"cookie_secure": False},
        sitzung_schluessel="testschluessel-nur-fuer-die-testsuite",
    )
    monkeypatch.setattr(konfiguration, "laden", lambda: werte)
    monkeypatch.setattr(konfiguration, "einstellungen", lambda: werte)
    monkeypatch.setattr("app.datenbank.einstellungen", lambda: werte)
    yield werte

    konfiguration.zuruecksetzen()
    datenbank.zuruecksetzen()
    protokoll.zuruecksetzen()


@pytest.fixture
def schema_vorlage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Einmal je Testlauf migrierte Datenbank, die von den Tests kopiert wird."""
    return _vorlage_erzeugen(tmp_path_factory)


def _vorlage_erzeugen(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from app.werkzeuge.schema import schema_anlegen

    ziel = tmp_path_factory.mktemp("vorlage") / "vorlage.sqlite3"
    if not ziel.exists():
        schema_anlegen(ziel)
    return ziel


@pytest.fixture
def db_pfad(test_einstellungen, schema_vorlage: Path) -> Iterator[Path]:
    """Frische, migrierte Datenbank für einen einzelnen Test."""
    ziel = test_einstellungen.pfade.datenbank
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(schema_vorlage, ziel)
    yield ziel


@pytest.fixture
def gesäte_db(db_pfad: Path, test_einstellungen) -> Iterator[Path]:
    """Datenbank mit Firma, Rollen, Berechtigungen und Administrator."""
    from app.datenbank import schreib_sitzung
    from app.werkzeuge.seed import grunddaten

    with schreib_sitzung() as sitzung:
        grunddaten(sitzung, test_einstellungen)
    yield db_pfad


@pytest.fixture
def client(gesäte_db: Path, test_einstellungen) -> Iterator[object]:
    """Testclient gegen eine gesäte Datenbank."""
    from fastapi.testclient import TestClient

    from app.main import anwendung_erzeugen

    with TestClient(anwendung_erzeugen(test_einstellungen)) as testclient:
        yield testclient


@pytest.fixture
def nutzer_erzeugen(gesäte_db: Path):
    """Funktion, die Nutzer mit Rolle anlegt: ``nutzer_erzeugen('a@b.de', 'team')``."""
    from app.datenbank import schreib_sitzung
    from tests.conftest_auth import nutzer_anlegen

    def anlegen(email: str, rolle: str, **kwargs):
        with schreib_sitzung() as sitzung:
            nutzer = nutzer_anlegen(sitzung, email, rolle, **kwargs)
            return nutzer.id

    return anlegen
