"""Berechtigungskatalog, Rollen-Seed und Demodaten (PLAN §4, §7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.datenbank import engine_erzeugen, schreib_transaktion
from app.konfiguration import Einstellungen
from app.modelle import (
    Berechtigung,
    Firma,
    Kunde,
    Meilenstein,
    Projekt,
    Rolle,
    User,
    Zahlungsplanposition,
)
from app.sicherheit import passwort as pw
from app.sicherheit.katalog import (
    KATALOG,
    SCHLUESSEL,
    SEED_ROLLEN,
    markdown_uebersicht,
    pruefe_bekannt,
)
from app.werkzeuge.seed import SeedFehler, demodaten, grunddaten


@pytest.fixture
def db(db_pfad: Path):
    engine = engine_erzeugen(db_pfad)
    yield engine
    engine.dispose()


@pytest.fixture
def werte(test_einstellungen) -> Einstellungen:
    return test_einstellungen


class TestKatalog:
    def test_schluessel_folgen_dem_muster(self):
        for eintrag in KATALOG:
            assert "." in eintrag.schluessel, eintrag.schluessel
            ressource, aktion = eintrag.schluessel.split(".", 1)
            assert ressource.islower() and ressource.isidentifier(), eintrag.schluessel
            assert aktion.islower(), eintrag.schluessel

    def test_keine_doppelten_schluessel(self):
        alle = [eintrag.schluessel for eintrag in KATALOG]
        assert len(alle) == len(set(alle))

    def test_jeder_eintrag_hat_eine_beschreibung(self):
        for eintrag in KATALOG:
            assert eintrag.beschreibung.strip(), eintrag.schluessel

    def test_unbekannter_schluessel_wird_abgewiesen(self):
        """Ein Tippfehler würde eine Route sonst unbemerkt öffnen oder sperren."""
        with pytest.raises(KeyError, match="steht nicht im Katalog"):
            pruefe_bekannt("projekte.leesen")

    def test_bekannter_schluessel_kommt_zurueck(self):
        assert pruefe_bekannt("projekte.lesen") == "projekte.lesen"

    def test_finanzsichtbarkeit_ist_getrennt(self):
        """PLAN §4: Beträge und Margen sind von der Projektsicht abgetrennt."""
        assert "projekte.lesen" in SCHLUESSEL
        assert "projekte.werte_lesen" in SCHLUESSEL
        assert "nachkalkulation.lesen" in SCHLUESSEL
        assert "cockpit.lesen" in SCHLUESSEL

    def test_alle_rollenrechte_stehen_im_katalog(self):
        for rolle in SEED_ROLLEN:
            for schluessel, _ in rolle.rechte:
                assert schluessel in SCHLUESSEL, f"{rolle.name}: {schluessel} fehlt im Katalog"


class TestSeedRollen:
    """Die Rechte der drei Rollen als ausdrückliche Aufstellung.

    Ein Schnappschuss mit Absicht: er ändert sich nur, wenn jemand die Rechte bewusst ändert –
    und dann fällt es in der Durchsicht auf. Genau das will man bei Berechtigungen.
    """

    def test_admin_hat_alle_rechte(self):
        admin = next(r for r in SEED_ROLLEN if r.name == "admin")
        assert {s for s, _ in admin.rechte} == set(SCHLUESSEL)

    def test_buchhaltung_darf_fakturieren_aber_keine_margen_sehen(self):
        buchhaltung = next(r for r in SEED_ROLLEN if r.name == "buchhaltung")
        rechte = {s for s, _ in buchhaltung.rechte}
        assert "rechnungen.festschreiben" in rechte
        assert "importe.ausfuehren" in rechte
        assert "projekte.werte_lesen" in rechte
        # PLAN §4: Nachkalkulation und Cockpit stehen dort nicht.
        assert "nachkalkulation.lesen" not in rechte
        assert "cockpit.lesen" not in rechte
        # Und keine Verwaltung.
        assert not any(s.startswith("admin.") for s in rechte)

    def test_team_liest_ohne_betraege(self):
        """PLAN §4 und docs/OFFENE-PUNKTE.md Nr. 1."""
        team = next(r for r in SEED_ROLLEN if r.name == "team")
        rechte = {s for s, _ in team.rechte}
        assert rechte == {
            "projekte.lesen",
            "kunden.lesen",
            "anlagen.lesen",
            "systemstatus.lesen",
        }
        assert "projekte.werte_lesen" not in rechte
        assert "nachkalkulation.lesen" not in rechte
        assert "cockpit.lesen" not in rechte
        assert not any(s.endswith(".schreiben") for s in rechte)
        assert "rechnungen.lesen" not in rechte


class TestGrunddaten:
    def test_seed_legt_firma_rollen_und_admin_an(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            ergebnis = grunddaten(sitzung, werte)

        assert ergebnis.firma_angelegt
        assert ergebnis.rollen_angelegt == 3
        assert ergebnis.admin_angelegt
        assert ergebnis.admin_passwort

        with Session(db) as sitzung:
            assert sitzung.scalar(select(func.count()).select_from(Firma)) == 1
            assert sitzung.scalar(select(func.count()).select_from(Rolle)) == 3
            assert sitzung.scalar(select(func.count()).select_from(User)) == 1
            assert sitzung.scalar(select(func.count()).select_from(Berechtigung)) == len(KATALOG)

    def test_seed_ist_wiederholbar(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
        with Session(db) as sitzung:
            vorher = {
                "firmen": sitzung.scalar(select(func.count()).select_from(Firma)),
                "rollen": sitzung.scalar(select(func.count()).select_from(Rolle)),
                "nutzer": sitzung.scalar(select(func.count()).select_from(User)),
                "rechte": sitzung.scalar(select(func.count()).select_from(Berechtigung)),
            }

        with Session(db) as sitzung, schreib_transaktion(sitzung):
            zweites = grunddaten(sitzung, werte)

        assert not zweites.firma_angelegt
        assert zweites.rollen_angelegt == 0
        assert not zweites.admin_angelegt
        with Session(db) as sitzung:
            assert vorher == {
                "firmen": sitzung.scalar(select(func.count()).select_from(Firma)),
                "rollen": sitzung.scalar(select(func.count()).select_from(Rolle)),
                "nutzer": sitzung.scalar(select(func.count()).select_from(User)),
                "rechte": sitzung.scalar(select(func.count()).select_from(Berechtigung)),
            }

    def test_neue_berechtigung_wird_beim_zweiten_lauf_ergaenzt(self, db, werte, monkeypatch):
        """Jede Phase bringt neue Schlüssel mit; der Seed muss sie nachtragen."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)

        from app.sicherheit import katalog

        erweitert = (
            *katalog.KATALOG,
            katalog.Berechtigungsdefinition("neues.recht", "Ein Recht aus einer späteren Phase", 9),
        )
        monkeypatch.setattr("app.werkzeuge.seed.KATALOG", erweitert)

        with Session(db) as sitzung, schreib_transaktion(sitzung):
            zweites = grunddaten(sitzung, werte)
        assert zweites.berechtigungen_angelegt == 1

        with Session(db) as sitzung:
            assert sitzung.scalar(
                select(Berechtigung).where(Berechtigung.schluessel == "neues.recht")
            )

    def test_admin_muss_passwort_wechseln(self, db, werte):
        """Das Seed-Passwort stand auf dem Bildschirm und in der Terminalhistorie."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
        with Session(db) as sitzung:
            admin = sitzung.scalar(select(User))
            assert admin.muss_passwort_wechseln is True

    def test_admin_passwort_ist_gehasht(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            ergebnis = grunddaten(sitzung, werte)
        with Session(db) as sitzung:
            admin = sitzung.scalar(select(User))
            assert ergebnis.admin_passwort not in admin.pw_hash
            assert admin.pw_hash.startswith("$2b$")
            assert pw.passt(ergebnis.admin_passwort, admin.pw_hash)

    def test_admin_hat_die_admin_rolle(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
        with Session(db) as sitzung:
            admin = sitzung.scalar(select(User))
            assert [r.name for r in admin.rollen] == ["admin"]
            assert set(admin.berechtigungsschluessel()) == set(SCHLUESSEL)

    def test_nummernkreise_werden_angelegt(self, db, werte):
        from app.modelle import Nummernkreis

        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
        with Session(db) as sitzung:
            kreise = {k.kreis for k in sitzung.scalars(select(Nummernkreis)).all()}
            assert {"RE", "SR", "AB", "KD", "PR", "SA"} <= kreise

    def test_zweiter_nutzer_wird_nicht_angelegt(self, db, werte):
        """Der Seed legt nur den ersten Administrator an, keine weiteren Konten."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            ergebnis = grunddaten(sitzung, werte, admin_email="anders@ip3-energie.de")
        assert not ergebnis.admin_angelegt
        with Session(db) as sitzung:
            assert sitzung.scalar(select(func.count()).select_from(User)) == 1


class TestDemodaten:
    def test_demodaten_werden_angelegt(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            zaehler = demodaten(sitzung, werte)

        assert zaehler["Kunden"] == 5
        assert zaehler["Projekte"] == 5
        assert zaehler["Zahlungsplanpositionen"] > 0
        with Session(db) as sitzung:
            assert sitzung.scalar(select(func.count()).select_from(Projekt)) == 5

    def test_demodaten_sind_in_sich_stimmig(self, db, werte):
        """Jede Zahlungsplansumme entspricht dem Auftragswert des Projekts (PLAN §6.12)."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            demodaten(sitzung, werte)

        with Session(db) as sitzung:
            for projekt in sitzung.scalars(select(Projekt)).all():
                summe = sum(p.betrag_netto for p in projekt.zahlungsplan)
                assert summe == projekt.ab_wert_netto, (
                    f"Projekt {projekt.projekt_nr}: Zahlungsplan {summe} "
                    f"≠ Auftragswert {projekt.ab_wert_netto}"
                )

    def test_demodaten_haben_gueltige_verweise(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            demodaten(sitzung, werte)
        with Session(db) as sitzung:
            for projekt in sitzung.scalars(select(Projekt)).all():
                assert sitzung.get(Kunde, projekt.kunde_id) is not None
                assert sitzung.get(Firma, projekt.firma_id) is not None

    def test_meilensteine_je_projekt_eindeutig(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            demodaten(sitzung, werte)
        with Session(db) as sitzung:
            paare = [(m.projekt_id, m.typ) for m in sitzung.scalars(select(Meilenstein)).all()]
            assert len(paare) == len(set(paare))

    def test_demodaten_deckt_die_steuerfaelle_ab(self, db, werte):
        """0 % für Wohngebäude und 19 % für Gewerbe müssen beide vorkommen (PLAN §6.2)."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            demodaten(sitzung, werte)
        with Session(db) as sitzung:
            kennzeichen = {p.ust_kz for p in sitzung.scalars(select(Projekt)).all()}
            assert "19" in kennzeichen
            assert "0" in kennzeichen

    def test_planmonate_sind_gueltig(self, db, werte):
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            demodaten(sitzung, werte)
        from app.zeit import monat_gueltig

        with Session(db) as sitzung:
            for position in sitzung.scalars(select(Zahlungsplanposition)).all():
                if position.plan_monat is not None:
                    assert monat_gueltig(position.plan_monat), position.plan_monat

    def test_demodaten_in_produktion_verweigert(self, db, werte):
        werte.app.umgebung = "produktion"
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
        with (
            Session(db) as sitzung,
            pytest.raises(SeedFehler) as fehler,
            schreib_transaktion(sitzung),
        ):
            demodaten(sitzung, werte)
        assert "produktion" in fehler.value.meldung
        assert fehler.value.naechster_schritt

    def test_demodaten_neben_echten_daten_verweigert(self, db, werte):
        """Erfundene Projekte zwischen echten wären in einer Auswertung nicht trennbar."""
        with Session(db) as sitzung, schreib_transaktion(sitzung):
            grunddaten(sitzung, werte)
            demodaten(sitzung, werte)
        with (
            Session(db) as sitzung,
            pytest.raises(SeedFehler) as fehler,
            schreib_transaktion(sitzung),
        ):
            demodaten(sitzung, werte)
        assert "bereits" in fehler.value.meldung

    def test_demodaten_ohne_firma_verweigert(self, db, werte):
        with (
            Session(db) as sitzung,
            pytest.raises(SeedFehler) as fehler,
            schreib_transaktion(sitzung),
        ):
            demodaten(sitzung, werte)
        assert "Firma" in fehler.value.meldung


class TestBerechtigungsdoku:
    def test_uebersicht_enthaelt_alle_schluessel(self):
        text = markdown_uebersicht()
        for eintrag in KATALOG:
            assert f"`{eintrag.schluessel}`" in text

    def test_uebersicht_enthaelt_alle_rollen(self):
        text = markdown_uebersicht()
        for rolle in SEED_ROLLEN:
            assert rolle.name in text

    def test_datei_ist_aktuell(self):
        """docs/BERECHTIGUNGEN.md wird erzeugt; eine veraltete Datei wäre falsche Auskunft.

        Neu erzeugen mit: ``uv run ip3-leitstand berechtigungen-doku``
        """
        datei = Path(__file__).resolve().parents[2] / "docs" / "BERECHTIGUNGEN.md"
        assert datei.exists(), "docs/BERECHTIGUNGEN.md fehlt"
        assert datei.read_text(encoding="utf-8") == markdown_uebersicht(), (
            "docs/BERECHTIGUNGEN.md ist nicht auf dem Stand des Katalogs. "
            "Neu erzeugen mit: uv run ip3-leitstand berechtigungen-doku"
        )


class TestPasswort:
    def test_gleiches_passwort_ergibt_verschiedene_hashes(self):
        """Ohne Salt wären zwei gleiche Passwörter in der Datenbank als gleich erkennbar."""
        assert pw.hashen("Sonnenstrom2026!") != pw.hashen("Sonnenstrom2026!")

    def test_richtiges_passwort_passt(self):
        hash_ = pw.hashen("Sonnenstrom2026!")
        assert pw.passt("Sonnenstrom2026!", hash_)
        assert not pw.passt("sonnenstrom2026!", hash_)

    def test_beschaedigter_hash_fuehrt_nicht_zum_absturz(self):
        assert pw.passt("egal", "kein gültiger Hash") is False
        assert pw.passt("egal", "") is False

    def test_zu_kurzes_passwort_wird_abgewiesen(self):
        with pytest.raises(pw.PasswortFehler) as fehler:
            pw.pruefe_laenge("kurz", 12)
        assert fehler.value.status_code == 422
        assert "12" in fehler.value.felder["passwort"]

    def test_zu_langes_passwort_wird_abgewiesen(self):
        """bcrypt verarbeitet nur 72 Byte; ohne Prüfung gäbe es eine Fehlerseite statt Hinweis."""
        with pytest.raises(pw.PasswortFehler) as fehler:
            pw.pruefe_laenge("a" * 73, 12)
        assert "72" in fehler.value.meldung

    def test_umlaute_zaehlen_doppelt(self):
        """Umlaute sind in UTF-8 zwei Byte – 40 Umlaute sind 80 Byte und damit zu lang."""
        with pytest.raises(pw.PasswortFehler):
            pw.pruefe_laenge("ü" * 40, 12)
        pw.pruefe_laenge("ü" * 20, 12)

    def test_hashen_weist_zu_langes_passwort_ab(self):
        with pytest.raises(pw.PasswortFehler):
            pw.hashen("a" * 100)

    def test_zufallspasswort_ohne_verwechselbare_zeichen(self):
        for _ in range(20):
            erzeugt = pw.zufallspasswort()
            assert len(erzeugt) == 16
            assert not set(erzeugt) & set("0O1lI")

    def test_kostenfaktor_bleibt_im_betrieb_bei_zwoelf(self):
        """Die Testsuite senkt den Faktor über IP3_BCRYPT_KOSTEN, damit sie in Sekunden läuft.

        Dieser Weg darf den Betrieb nicht schwächen: ohne die Umgebungsvariable muss der Wert
        bei 12 liegen. Ein Hash mit Faktor 4 wäre um Größenordnungen leichter angreifbar.
        """
        assert pw.KOSTEN == 12

    def test_umgebungsvariable_bleibt_in_gueltigen_grenzen(self, monkeypatch):
        monkeypatch.setattr(pw, "_AUS_UMGEBUNG", "1")
        assert pw.kosten() == 4, "Unter 4 lässt bcrypt keinen Faktor zu"
        monkeypatch.setattr(pw, "_AUS_UMGEBUNG", "99")
        assert pw.kosten() == 31, "Über 31 lässt bcrypt keinen Faktor zu"
        monkeypatch.setattr(pw, "_AUS_UMGEBUNG", "unsinn")
        assert pw.kosten() == 12, "Ein unlesbarer Wert fällt auf den Betriebswert zurück"
