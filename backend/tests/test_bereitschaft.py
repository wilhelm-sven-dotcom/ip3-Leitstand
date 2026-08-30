"""Prüfung vor der Inbetriebnahme.

Der Wert dieses Befehls hängt an zwei Dingen, und beide werden hier geprüft: dass er
**findet**, was fehlt, und dass er nichts **doppelt** meldet. Eine Liste, auf der dasselbe
Problem zweimal steht, wird nicht abgehakt, sondern überflogen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.konfiguration import Einstellungen
from app.werkzeuge import bereitschaft


def _werte(tmp_path: Path, **felder) -> Einstellungen:
    """Einstellungen mit lokaler Datenbank, sonst leer."""
    werte = Einstellungen()
    werte.pfade.datenbank = tmp_path / "daten" / "leitstand.sqlite3"
    for schluessel, wert in felder.items():
        setattr(werte.pfade, schluessel, wert)
    return werte


class TestBefund:
    def test_unbekannte_lage_faellt_sofort_auf(self):
        """Ein Tippfehler in der Lage würde die Ausgabe stillschweigend falsch einfärben."""
        with pytest.raises(ValueError):
            bereitschaft.Befund("Test", "Titel", "gelb")


class TestOrdner:
    def test_nicht_gesetzter_ordner_nennt_den_zweck(self, tmp_path: Path):
        """„Fehlt" allein bewegt niemanden – es muss dastehen, wofür er gebraucht wird."""
        befunde = bereitschaft.ordner_pruefen(_werte(tmp_path))
        sicherung = next(b for b in befunde if b.titel == "Sicherungsordner")
        assert sicherung.lage == "hinweis"
        assert "Sicherung" in sicherung.text
        assert "[pfade]" in sicherung.naechster_schritt

    def test_nicht_erreichbarer_ordner_wird_erkannt(self, tmp_path: Path):
        werte = _werte(tmp_path, backup=tmp_path / "gibt-es-nicht")
        befunde = bereitschaft.ordner_pruefen(werte)
        sicherung = next(b for b in befunde if b.titel == "Sicherungsordner")
        assert sicherung.lage == "hinweis"
        assert "nicht erreichbar" in sicherung.text

    def test_vorhandener_ordner_ist_erledigt(self, tmp_path: Path):
        ziel = tmp_path / "04_Backup"
        ziel.mkdir()
        werte = _werte(tmp_path, backup=ziel)
        sicherung = next(
            b for b in bereitschaft.ordner_pruefen(werte) if b.titel == "Sicherungsordner"
        )
        assert sicherung.lage == "ok"
        assert "beschreibbar" in sicherung.text

    def test_nur_lesend_gebrauchte_ordner_brauchen_kein_schreibrecht(self, tmp_path: Path):
        """Der DATEV-Ordner wird nur gelesen (PLAN §2) – Schreibrecht zu verlangen wäre falsch."""
        ziel = tmp_path / "02_DATEV"
        ziel.mkdir()
        werte = _werte(tmp_path, datev=ziel)
        datev = next(b for b in bereitschaft.ordner_pruefen(werte) if b.titel == "DATEV-Ordner")
        assert datev.lage == "ok"
        assert "lesbar" in datev.text

    def test_schreibtest_legt_nichts_bleibendes_an(self, tmp_path: Path):
        ziel = tmp_path / "leer"
        ziel.mkdir()
        assert bereitschaft._schreibbar(ziel) is True
        assert list(ziel.iterdir()) == []


class TestDatenbank:
    def test_sync_ordner_blockiert(self, tmp_path: Path):
        """Eine SQLite-Datei im OneDrive wird beschädigt – das ist kein Hinweis, das ist Stopp."""
        werte = Einstellungen()
        werte.pfade.datenbank = tmp_path / "OneDrive" / "daten" / "leitstand.sqlite3"
        ort = next(b for b in bereitschaft.datenbank_pruefen(werte) if b.titel == "Ablageort")
        assert ort.lage == "blockiert"
        assert "OneDrive" in ort.text

    def test_fehlende_datei_blockiert_mit_naechstem_schritt(self, tmp_path: Path):
        befunde = bereitschaft.datenbank_pruefen(_werte(tmp_path))
        stand = next(b for b in befunde if b.titel == "Schemastand")
        assert stand.lage == "blockiert"
        assert "ip3-leitstand schema" in stand.naechster_schritt

    def test_aktuelles_schema_ist_erledigt(self, gesäte_db, test_einstellungen):
        befunde = bereitschaft.datenbank_pruefen(test_einstellungen)
        stand = next(b for b in befunde if b.titel == "Schemastand")
        assert stand.lage == "ok"


class TestVerrechnungssaetze:
    def test_vorbelegung_wird_erkannt(self):
        befund = bereitschaft.saetze_pruefen(Einstellungen())
        assert befund.lage == "hinweis"
        assert "Vorbelegung" in befund.text

    def test_eigene_saetze_sind_erledigt(self):
        werte = Einstellungen()
        werte.stundensaetze.saetze = {"monteur": 6900, "obermonteur": 7900}
        assert bereitschaft.saetze_pruefen(werte).lage == "ok"


class TestDaten:
    def test_ohne_kunden_wird_das_gesagt(self, gesäte_db):
        from app.datenbank import lese_sitzung

        with lese_sitzung() as sitzung:
            befunde = bereitschaft.daten_pruefen(sitzung)
        kunden = next(b for b in befunde if b.titel == "Kundenstamm")
        assert kunden.lage == "hinweis"

    def test_fehlende_anschrift_nennt_die_zahl_und_den_paragrafen(self, gesäte_db):
        from app.datenbank import lese_sitzung, schreib_sitzung
        from app.modelle import Kunde

        with schreib_sitzung() as sitzung:
            sitzung.add(Kunde(kunden_nr=90001, name="Ohne Anschrift", ort="Weiden", typ="b2c"))
            sitzung.add(
                Kunde(
                    kunden_nr=90002,
                    name="Mit Anschrift",
                    strasse="Bahnhofstraße 12",
                    plz="92660",
                    ort="Neustadt",
                    typ="b2b",
                )
            )

        with lese_sitzung() as sitzung:
            befunde = bereitschaft.daten_pruefen(sitzung)

        anschriften = next(b for b in befunde if b.titel == "Anschriften")
        assert anschriften.lage == "hinweis"
        assert "1 von 2" in anschriften.text
        assert "§ 14 UStG" in anschriften.text

    def test_alle_privatkunden_werden_gemeldet(self, gesäte_db):
        """Davon hängt ab, ob eine E-Rechnung entsteht – ab 1.1.2027 Pflicht für B2B."""
        from app.datenbank import lese_sitzung, schreib_sitzung
        from app.modelle import Kunde

        with schreib_sitzung() as sitzung:
            sitzung.add(
                Kunde(
                    kunden_nr=90003,
                    name="Privat",
                    strasse="Weg 1",
                    plz="92637",
                    ort="Weiden",
                    typ="b2c",
                )
            )

        with lese_sitzung() as sitzung:
            befunde = bereitschaft.daten_pruefen(sitzung)

        typ = next(b for b in befunde if b.titel == "Privat oder Gewerbe")
        assert typ.lage == "hinweis"
        assert "1.1.2027" in typ.naechster_schritt


class TestBericht:
    def test_ohne_sitzung_laeuft_der_rest_trotzdem(self, tmp_path: Path):
        """Genau der Fall vor dem ersten 'schema': die Datenbank gibt es noch gar nicht."""
        bericht = bereitschaft.bericht_erstellen(_werte(tmp_path))
        assert bericht.befunde
        assert not any(b.bereich == "Daten" for b in bericht.befunde)

    def test_jeder_punkt_steht_genau_einmal(self, tmp_path: Path):
        """Ein doppelt gemeldeter Punkt wird nicht abgehakt, sondern überflogen.

        Der erste Entwurf meldete jeden fehlenden Ordner zweimal – einmal aus der
        Konfigurationsprüfung, einmal aus der Ordnerprüfung.
        """
        bericht = bereitschaft.bericht_erstellen(_werte(tmp_path))
        schluessel = [(b.bereich, b.titel) for b in bericht.befunde]
        assert len(schluessel) == len(set(schluessel))

    def test_jeder_offene_punkt_nennt_einen_naechsten_schritt(self, tmp_path: Path):
        """Ein Hinweis ohne nächsten Schritt ist eine Beschwerde (CLAUDE.md Regel 8)."""
        bericht = bereitschaft.bericht_erstellen(_werte(tmp_path))
        ohne = [
            b.titel
            for b in bericht.befunde
            if b.lage in ("hinweis", "blockiert") and not b.naechster_schritt
        ]
        assert ohne == []

    def test_blockierend_heisst_nicht_bereit(self, tmp_path: Path):
        bericht = bereitschaft.bericht_erstellen(_werte(tmp_path))
        assert bericht.blockiert
        assert bericht.bereit is False

    def test_bereit_trotz_offener_hinweise(self, gesäte_db, test_einstellungen):
        """Eine fehlende TimeTac-Anbindung ist kein Grund, den Leitstand nicht zu starten."""
        from app.datenbank import lese_sitzung

        with lese_sitzung() as sitzung:
            bericht = bereitschaft.bericht_erstellen(test_einstellungen, sitzung)

        assert bericht.hinweise
        assert bericht.bereit is True

    def test_bereiche_behalten_ihre_reihenfolge(self, tmp_path: Path):
        bericht = bereitschaft.bericht_erstellen(_werte(tmp_path))
        assert bericht.bereiche()[:2] == ["Konfiguration", "Datenbank"]
