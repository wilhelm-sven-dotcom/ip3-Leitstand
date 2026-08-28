"""Konfiguration: Laden, Prüfen und die Sperre gegen Datenbanken in Sync-Ordnern."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import konfiguration
from app.konfiguration import Einstellungen, KonfigurationsFehler


def test_standardwerte_ohne_konfigurationsdatei(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("IP3_CONFIG", str(tmp_path / "gibt-es-nicht.toml"))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "gibt-es-nicht.env"))
    werte = konfiguration.laden()
    assert werte.app.umgebung == "entwicklung"
    assert werte.firma.kuerzel == "ip3"
    assert werte.jobs.backup_generationen == 30


def test_toml_wird_gelesen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    datei = tmp_path / "config.toml"
    datei.write_text(
        '[app]\numgebung = "test"\nport = 8123\n\n[jobs]\nbackup_generationen = 7\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("IP3_CONFIG", str(datei))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "leer.env"))
    werte = konfiguration.laden()
    assert werte.app.port == 8123
    assert werte.jobs.backup_generationen == 7


def test_umgebungsvariable_schlaegt_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    datei = tmp_path / "config.toml"
    datei.write_text("[app]\nport = 8123\n", encoding="utf-8")
    monkeypatch.setenv("IP3_CONFIG", str(datei))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "leer.env"))
    monkeypatch.setenv("IP3_APP__PORT", "8010")
    werte = konfiguration.laden()
    assert werte.app.port == 8010, "Die Testinstanz muss den Port über die Umgebung setzen können"


def test_fehlerhafte_toml_nennt_datei_und_naechsten_schritt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    datei = tmp_path / "config.toml"
    datei.write_text('[app]\numgebung = "test\n', encoding="utf-8")  # Anführungszeichen fehlt
    monkeypatch.setenv("IP3_CONFIG", str(datei))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "leer.env"))
    with pytest.raises(KonfigurationsFehler) as fehler:
        konfiguration.laden()
    text = str(fehler.value)
    assert str(datei) in text
    assert "Nächster Schritt" in text


def test_unzulaessiger_wert_nennt_das_feld(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    datei = tmp_path / "config.toml"
    datei.write_text('[app]\numgebung = "irgendwas"\n', encoding="utf-8")
    monkeypatch.setenv("IP3_CONFIG", str(datei))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "leer.env"))
    with pytest.raises(KonfigurationsFehler) as fehler:
        konfiguration.laden()
    text = str(fehler.value)
    assert "umgebung" in text
    assert "irgendwas" in text


def test_uhrzeit_wird_geprueft(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    datei = tmp_path / "config.toml"
    datei.write_text('[jobs]\nbackup_uhrzeit = "25:00"\n', encoding="utf-8")
    monkeypatch.setenv("IP3_CONFIG", str(datei))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "leer.env"))
    with pytest.raises(KonfigurationsFehler) as fehler:
        konfiguration.laden()
    assert "backup_uhrzeit" in str(fehler.value)


@pytest.mark.parametrize(
    "pfad",
    [
        r"C:\Users\sven\OneDrive - ip3\daten\leitstand.sqlite3",
        "/home/sven/Dropbox/ip3/leitstand.sqlite3",
        "/mnt/c/Users/sven/OneDrive/leitstand.sqlite3",
        "/srv/Nextcloud/ip3/db.sqlite3",
    ],
)
def test_datenbank_im_sync_ordner_wird_abgelehnt(pfad: str):
    """Eine SQLite-Datei in einem synchronisierten Ordner wird zerstört – lieber gar nicht starten."""
    with pytest.raises(KonfigurationsFehler) as fehler:
        konfiguration.pruefe_datenbankpfad(Path(pfad))
    text = str(fehler.value)
    assert "Ordnersynchronisation" in text
    assert "Nächster Schritt" in text
    assert "backup" in text, "Der Hinweis soll erklären, dass Sicherungen weiter in OneDrive gehen"


@pytest.mark.parametrize(
    "pfad",
    [
        r"D:\ip3-leitstand\daten\leitstand.sqlite3",
        "/opt/ip3-leitstand/daten/leitstand.sqlite3",
        "/var/lib/ip3/asynchron/db.sqlite3",  # 'sync' im Wortinneren ist kein Sync-Ordner
    ],
)
def test_lokaler_datenbankpfad_ist_in_ordnung(pfad: str):
    konfiguration.pruefe_datenbankpfad(Path(pfad))


def test_produktion_ohne_sitzungsschluessel_bricht_ab():
    werte = Einstellungen(
        app={"umgebung": "produktion", "erlaubte_herkunft": ["https://leitstand.ip3.local"]},
        sitzung={"cookie_secure": True},
        sitzung_schluessel="",
    )
    with pytest.raises(KonfigurationsFehler) as fehler:
        konfiguration.pruefe_betriebsbereit(werte)
    assert "IP3_SITZUNG_SCHLUESSEL" in str(fehler.value)


def test_produktion_ohne_secure_cookie_bricht_ab():
    werte = Einstellungen(
        app={"umgebung": "produktion", "erlaubte_herkunft": ["https://leitstand.ip3.local"]},
        sitzung={"cookie_secure": False},
        sitzung_schluessel="x" * 40,
    )
    with pytest.raises(KonfigurationsFehler) as fehler:
        konfiguration.pruefe_betriebsbereit(werte)
    assert "cookie_secure" in str(fehler.value)


def test_fehlendes_backupziel_ist_nur_ein_hinweis():
    werte = Einstellungen(app={"umgebung": "test"})
    hinweise = konfiguration.pruefe_betriebsbereit(werte)
    assert any("Backup-Ziel" in h for h in hinweise)


def test_unvollstaendige_firmenstammdaten_werden_gemeldet():
    werte = Einstellungen(app={"umgebung": "test"})
    hinweise = konfiguration.pruefe_betriebsbereit(werte)
    assert any("Firmenstammdaten" in h for h in hinweise)
    # Die Platzhalter aus config.example.toml gelten als nicht gesetzt.
    werte_mit_platzhaltern = Einstellungen(
        app={"umgebung": "test"},
        firma={"ust_id": "<USt-IdNr.>", "strasse": "Musterweg 1"},
    )
    fehlend = werte_mit_platzhaltern.firma.unvollstaendige_pflichtangaben()
    assert "Steuernummer oder Umsatzsteuer-Identifikationsnummer" in fehlend
    assert "Straße und Hausnummer" not in fehlend


def test_steuernummer_oder_ust_id_genuegt():
    """§ 14 Abs. 4 Nr. 2 UStG verlangt eines von beiden, nicht beides.

    Die bestehende Rechnungsvorlage führt nur die USt-IdNr. Beides zu fordern hätte die
    Fakturierung ohne Rechtsgrund blockiert.
    """
    gemeinsam = {
        "strasse": "Brandweg 1",
        "plz": "92637",
        "hrb": "HRB 5725 Amtsgericht Weiden",
        "geschaeftsfuehrer": "Sven Wilhelm, Michael Bäumler",
        "bank": {"institut": "VR Bank", "iban": "DE02120300000000202051", "bic": "GENODEF1WEV"},
    }
    nur_ust_id = Einstellungen(
        app={"umgebung": "test"}, firma={**gemeinsam, "ust_id": "DE346672260"}
    )
    assert nur_ust_id.firma.unvollstaendige_pflichtangaben() == []

    nur_steuernummer = Einstellungen(
        app={"umgebung": "test"}, firma={**gemeinsam, "st_nr": "255/123/45678"}
    )
    assert nur_steuernummer.firma.unvollstaendige_pflichtangaben() == []

    keines = Einstellungen(app={"umgebung": "test"}, firma=gemeinsam)
    assert keines.firma.unvollstaendige_pflichtangaben() == [
        "Steuernummer oder Umsatzsteuer-Identifikationsnummer"
    ]


def test_vollstaendige_firmenstammdaten_ohne_hinweis():
    """Vollständig eingerichtet heißt seit Phase 4 auch: alle vier Datenquellen stehen."""
    werte = Einstellungen(
        app={"umgebung": "test"},
        pfade={
            "backup": "/tmp/backup",
            "rechnungen": "/tmp/01_Rechnungen",
            "datev": "/tmp/02_DATEV",
            "kalkulation": "/tmp/03_Kalkulation",
        },
        timetac={"aktiv": False},
        firma={
            "strasse": "Industriestraße 1",
            "plz": "92637",
            "ust_id": "DE123456789",
            "st_nr": "255/123/45678",
            "hrb": "HRB 12345 Amtsgericht Weiden",
            "geschaeftsfuehrer": "Sven Wilhelm, Michael Bäumler",
            "bank": {
                "institut": "Sparkasse",
                "iban": "DE02120300000000202051",
                "bic": "BYLADEM1001",
            },
        },
    )
    assert konfiguration.pruefe_betriebsbereit(werte) == []


def test_fehlende_datenquellen_erscheinen_als_hinweis():
    """Ohne DATEV bleiben die Ist-Kosten leer und jede Marge sieht zu gut aus (PLAN §7)."""
    hinweise = konfiguration.pruefe_betriebsbereit(
        Einstellungen(app={"umgebung": "test"}, timetac={"aktiv": True})
    )
    zusammen = " ".join(hinweise)
    assert "02_DATEV" in zusammen
    assert "03_Kalkulation" in zusammen
    assert "IP3_TIMETAC_CLIENT_ID" in zusammen


def test_abgeschaltetes_timetac_ergibt_keinen_hinweis():
    hinweise = konfiguration.pruefe_betriebsbereit(
        Einstellungen(app={"umgebung": "test"}, timetac={"aktiv": False})
    )
    assert not any("TimeTac" in h for h in hinweise)


def test_relative_pfade_beziehen_sich_auf_die_projektwurzel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    datei = tmp_path / "config.toml"
    datei.write_text('[pfade]\ndatenbank = "daten/eigene.sqlite3"\n', encoding="utf-8")
    monkeypatch.setenv("IP3_CONFIG", str(datei))
    monkeypatch.setenv("IP3_ENV_DATEI", str(tmp_path / "leer.env"))
    werte = konfiguration.laden()
    assert werte.pfade.datenbank.is_absolute()
    assert werte.pfade.datenbank.name == "eigene.sqlite3"
