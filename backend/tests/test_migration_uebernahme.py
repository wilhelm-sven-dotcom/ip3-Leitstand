"""Übernahme der Bestandsdaten in die Datenbank (PLAN §9).

Gearbeitet wird mit den Nachbauten aus ``tests/bestandsdateien.py``. Die Tests prüfen vor allem,
dass nichts erfunden und nichts stillschweigend verdoppelt wird – die beiden Fehler, die eine
Migration unbrauchbar machen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.migration.uebernahme import (
    BereitsUebernommen,
    MigrationFehler,
    OffeneZuordnungen,
    QuelldateiFehlt,
    analysieren,
    quelldateien_finden,
    uebernehmen,
)
from app.migration.zuordnung import Art, bestaetigen
from app.modelle import Firma, Importlauf, Kunde, Meilenstein, Projekt, Zahlungsplanposition
from tests.bestandsdateien import auftragsliste_bauen, teamliste_bauen


@pytest.fixture
def quellordner(tmp_path: Path) -> Path:
    """Ordner mit beiden Nachbauten, so benannt wie im Betrieb."""
    ordner = tmp_path / "migration-quellen"
    ordner.mkdir()
    auftragsliste_bauen(ordner / "Offene_Auftraege_2025.xlsx")
    teamliste_bauen(ordner / "Teambesprechung_NEU.xlsx")
    return ordner


@pytest.fixture
def analyse(quellordner: Path):
    return analysieren(quellordner)


@pytest.fixture
def firma_id(gesäte_db) -> int:
    with lese_sitzung() as sitzung:
        return sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))


def _alles_zuordnen(analyse) -> None:
    """Jede offene Zuordnung auf den ersten Vorschlag setzen, sonst neues Projekt."""
    entscheidungen = {
        z.kundenteil: (z.vorschlaege[0].projekt_zeile if z.vorschlaege else None)
        for z in analyse.vorschau.offene
    }
    bestaetigen(analyse.vorschau, entscheidungen)


def _uebernehmen(analyse, firma_id: int, **kw):
    with schreib_sitzung() as sitzung:
        return uebernehmen(sitzung, analyse, firma_id, **kw)


class TestQuelldateienFinden:
    def test_findet_beide_dateien(self, quellordner: Path):
        auftraege, teamliste = quelldateien_finden(quellordner)
        assert auftraege.name.startswith("Offene_Auftraege")
        assert teamliste.name.startswith("Teambesprechung")

    def test_fehlende_datei_nennt_die_vorhandenen(self, tmp_path: Path):
        """Der häufigste Grund ist eine verwechselte Datei – dann hilft die Liste."""
        ordner = tmp_path / "quellen"
        ordner.mkdir()
        teamliste_bauen(ordner / "Teambesprechung_NEU.xlsx")
        with pytest.raises(QuelldateiFehlt) as fehler:
            quelldateien_finden(ordner)
        assert "Offene_Auftraege" in fehler.value.meldung
        assert "Teambesprechung_NEU.xlsx" in fehler.value.naechster_schritt

    def test_fehlender_ordner_nennt_die_konfiguration(self, tmp_path: Path):
        with pytest.raises(MigrationFehler) as fehler:
            quelldateien_finden(tmp_path / "gibt-es-nicht")
        assert "[pfade] migration" in fehler.value.naechster_schritt


class TestSchutzmechanismen:
    def test_offene_zuordnungen_verhindern_die_uebernahme(self, analyse, firma_id):
        """Lieber abbrechen als einen Zahlungsplan ohne Projekt anlegen."""
        assert analyse.vorschau.offene
        with pytest.raises(OffeneZuordnungen) as fehler:
            _uebernehmen(analyse, firma_id)
        assert "Zuordnungsmaske" in fehler.value.naechster_schritt
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Projekt).limit(1)) is None

    def test_zweiter_lauf_wird_abgewiesen(self, analyse, quellordner, firma_id):
        """Ein zweiter Lauf würde alles doppelt anlegen."""
        _alles_zuordnen(analyse)
        erster = _uebernehmen(analyse, firma_id)

        zweite = analysieren(quellordner)
        _alles_zuordnen(zweite)
        with pytest.raises(BereitsUebernommen) as fehler:
            _uebernehmen(zweite, firma_id)
        assert "bereits übernommen" in fehler.value.meldung
        assert "leere Datenbank" in fehler.value.naechster_schritt

        # Der Bestand ist unverändert: kein Projekt, kein Kunde, kein Protokolleintrag doppelt.
        with lese_sitzung() as sitzung:
            assert len(list(sitzung.scalars(select(Projekt)))) == erster.projekte
            assert len(list(sitzung.scalars(select(Kunde)))) == erster.kunden
            assert len(list(sitzung.scalars(select(Zahlungsplanposition)))) == erster.zahlungsplan
            assert len(list(sitzung.scalars(select(Importlauf)))) == 1

    def test_fehler_nimmt_alles_zurueck(self, analyse, firma_id, monkeypatch):
        """Ein halb migrierter Bestand wäre schlimmer als keiner."""
        _alles_zuordnen(analyse)

        def platzen(*_args, **_kw):
            raise RuntimeError("Absicht")

        monkeypatch.setattr("app.migration.uebernahme._zahlungsplan_anlegen", platzen)
        with pytest.raises(RuntimeError, match="Absicht"):
            _uebernehmen(analyse, firma_id)
        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(Projekt).limit(1)) is None
            assert sitzung.scalar(select(Importlauf).limit(1)) is None


class TestUebernahme:
    @pytest.fixture
    def bericht(self, analyse, firma_id):
        _alles_zuordnen(analyse)
        return _uebernehmen(analyse, firma_id)

    def test_alle_projekte_angelegt(self, bericht, analyse):
        assert bericht.projekte >= len(analyse.projekte.zeilen)
        with lese_sitzung() as sitzung:
            assert len(list(sitzung.scalars(select(Projekt)))) == bericht.projekte

    def test_kunden_werden_zusammengefasst(self, bericht, analyse):
        """Derselbe Kunde mit zwei Projekten ist ein Kunde, nicht zwei."""
        with lese_sitzung() as sitzung:
            huber = list(sitzung.scalars(select(Kunde).where(Kunde.name == "Huber")))
            assert len(huber) == 1
            projekte = list(sitzung.scalars(select(Projekt).where(Projekt.kunde_id == huber[0].id)))
            assert len(projekte) == 2

    def test_projektnummern_nach_auftragsjahr(self, bericht):
        """JJNNN nach PLAN §3, das Jahr aus dem Auftragsdatum."""
        with lese_sitzung() as sitzung:
            nummern = {
                p.projekt_nr: p.auftrag_vom
                for p in sitzung.scalars(select(Projekt))
                if p.auftrag_vom is not None
            }
        for nummer, datum in nummern.items():
            assert nummer // 1000 == datum.year % 100, f"{nummer} passt nicht zu {datum}"
        assert len(nummern) == len(set(nummern))

    def test_projekte_ohne_datum_ins_laufende_jahr(self, bericht):
        """Ohne Auftragsdatum gibt es kein Auftragsjahr – das laufende ist die einzige
        nachvollziehbare Wahl, und der Bericht nennt die Anzahl."""
        from app.zeit import heute_ortszeit

        assert bericht.projekte_ohne_auftragsjahr >= 1
        with lese_sitzung() as sitzung:
            ohne = [p for p in sitzung.scalars(select(Projekt)) if p.auftrag_vom is None]
        assert ohne
        for projekt in ohne:
            assert projekt.projekt_nr // 1000 == heute_ortszeit().year % 100

    def test_herkunft_steht_am_datensatz(self, bericht):
        """Jeder Betrag muss bis in die Quelldatei zurückverfolgbar sein."""
        with lese_sitzung() as sitzung:
            projekt = sitzung.scalar(select(Projekt).order_by(Projekt.projekt_nr).limit(1))
            assert projekt.quelle_migration
            assert "Teambesprechung_NEU.xlsx" in projekt.quelle_migration
            assert "Zeile" in projekt.quelle_migration
            position = sitzung.scalar(select(Zahlungsplanposition).limit(1))
            assert "Offene_Auftraege_2025.xlsx" in position.quelle_migration

    def test_meilensteine_mit_drei_zustaenden(self, bericht):
        with lese_sitzung() as sitzung:
            staende = {(m.typ, m.erledigt) for m in sitzung.scalars(select(Meilenstein))}
        assert any(erledigt is True for _typ, erledigt in staende)
        assert any(erledigt is False for _typ, erledigt in staende)
        assert any(erledigt is None for _typ, erledigt in staende)
        with lese_sitzung() as sitzung:
            # Kein erfundenes Datum: die Teamliste kreuzt ohne Datum.
            assert all(m.erledigt_am is None for m in sitzung.scalars(select(Meilenstein)))

    def test_kalenderwoche_landet_am_meilenstein(self, bericht):
        with lese_sitzung() as sitzung:
            mit_kw = [m for m in sitzung.scalars(select(Meilenstein)) if m.geplant_kw is not None]
        assert mit_kw
        assert any(m.geplant_kw == "26/23" for m in mit_kw)

    def test_auffaellige_zelle_wird_am_meilenstein_vermerkt(self, bericht):
        """'x, x' und Freitext bleiben nachlesbar, statt zu verschwinden."""
        with lese_sitzung() as sitzung:
            vermerke = [m.bemerkung for m in sitzung.scalars(select(Meilenstein)) if m.bemerkung]
        assert any("Benjamin" in v for v in vermerke)

    def test_zahlungsplan_positionsnummern_je_projekt_eindeutig(self, bericht):
        """Ein Projekt hat PV- und Speicherabschläge, beide beginnen im Text bei 1."""
        with lese_sitzung() as sitzung:
            positionen = list(sitzung.scalars(select(Zahlungsplanposition)))
        je_projekt: dict[int, list[int]] = {}
        for position in positionen:
            je_projekt.setdefault(position.projekt_id, []).append(position.pos_nr)
        for projekt_id, nummern in je_projekt.items():
            assert len(nummern) == len(set(nummern)), f"Projekt {projekt_id} doppelt"
            assert sorted(nummern) == list(range(1, len(nummern) + 1))

    def test_zahlungsplan_reihenfolge_pv_dann_speicher(self, bericht):
        with lese_sitzung() as sitzung:
            aigner = sitzung.scalar(select(Kunde).where(Kunde.name == "Aigner"))
            projekt = sitzung.scalar(select(Projekt).where(Projekt.kunde_id == aigner.id))
            positionen = sorted(
                sitzung.scalars(
                    select(Zahlungsplanposition).where(
                        Zahlungsplanposition.projekt_id == projekt.id
                    )
                ),
                key=lambda p: p.pos_nr,
            )
        # Vier PV-Positionen: drei Abschläge, dann die Schlussrechnung.
        assert [p.art for p in positionen] == ["abschlag", "abschlag", "abschlag", "schluss"]
        assert all(p.gewerk == "pv" for p in positionen)

    def test_gleiche_bezeichnung_wird_gemeldet_nicht_umbenannt(self, bericht):
        """Der Text bleibt, wie die Auftragsliste ihn führt – aber er fällt auf.

        Bei HPZ, Irchenrieth heißen vier Zeilen mit verschiedenen Beträgen und Monaten alle
        „1. Abschlag PV". Eine erfundene Nummerierung wäre eine Behauptung über die Quelle;
        stillschweigend durchlassen wäre schlimmer, weil dieser Text ab Phase 3 auf der Rechnung
        steht. Also: unverändert übernehmen und melden.
        """
        assert bericht.gleiche_bezeichnung, "Der doppelte Text wurde nicht gemeldet"
        eintrag = bericht.gleiche_bezeichnung[0]
        assert eintrag["bezeichnung"] == "2. Abschlag Speicher"
        assert len(eintrag["zeilen"]) == 2

        with lese_sitzung() as sitzung:
            huber = sitzung.scalar(select(Kunde).where(Kunde.name == "Huber"))
            positionen = list(
                sitzung.scalars(
                    select(Zahlungsplanposition)
                    .join(Projekt, Projekt.id == Zahlungsplanposition.projekt_id)
                    .where(Projekt.kunde_id == huber.id)
                )
            )
        gleich = [p for p in positionen if p.bezeichnung == "2. Abschlag Speicher"]
        assert len(gleich) == 2
        # Unterschiedliche Beträge, gleicher Text: genau der Fall, um den es geht.
        assert {p.betrag_netto for p in gleich} == {250000, 170000}

    def test_gestelltes_kreuz_wird_uebernommen(self, bericht, analyse):
        """PLAN §9: das Kreuz heißt 'Rechnung gestellt'. PLAN §6.7: nicht 'bezahlt'."""
        assert bericht.zahlungsplan_gestellt > 0
        with lese_sitzung() as sitzung:
            gestellt = list(
                sitzung.scalars(
                    select(Zahlungsplanposition).where(
                        Zahlungsplanposition.migriert_gestellt.is_(True)
                    )
                )
            )
        assert len(gestellt) == bericht.zahlungsplan_gestellt
        # Kein Beleg – die Rechnungen entstanden vor der Einführung des Leitstands.
        assert all(p.rechnung_id is None for p in gestellt)

    def test_planmonat_mit_jahr(self, bericht):
        with lese_sitzung() as sitzung:
            monate = {
                p.plan_monat for p in sitzung.scalars(select(Zahlungsplanposition)) if p.plan_monat
            }
        assert monate
        assert all(m.startswith("2026-") for m in monate)

    def test_nachkalkulation_kommt_als_notiz_nicht_als_kosten(self, bericht):
        """PLAN §9: die Altwerte sind von Hand gerechnet und nicht nachvollziehbar."""
        from app.modelle import IstKosten

        with lese_sitzung() as sitzung:
            assert sitzung.scalar(select(IstKosten).limit(1)) is None

    def test_ab_luecke_wird_ausgewiesen_nicht_gefuellt(self, bericht):
        """Entscheidung Svens (OFFENE-PUNKTE Nr. 11): keine erfundene Sammelposition."""
        with lese_sitzung() as sitzung:
            bezeichnungen = [p.bezeichnung for p in sitzung.scalars(select(Zahlungsplanposition))]
        assert not any("bereits berechnet" in b.lower() for b in bezeichnungen)

    def test_importprotokoll_haelt_die_kontrollsummen(self, bericht, analyse):
        with lese_sitzung() as sitzung:
            lauf = sitzung.scalar(select(Importlauf).where(Importlauf.id == bericht.importlauf_id))
        assert lauf.status in ("erfolg", "warnung")
        assert lauf.beendet is not None
        summen = lauf.ergebnis["kontrollsummen"]
        assert summen["auftragsliste"]["summe_netto_cent"] == analyse.auftraege.summe_netto_cent
        assert summen["teamliste"]["projekte"] == len(analyse.projekte.zeilen)
        # Die falschen Summenformeln der Quelldateien stehen im Protokoll.
        assert summen["summenfehler_der_quelldateien"]
        assert lauf.ergebnis["befunde"]

    def test_warnung_wenn_etwas_nachzusehen_ist(self, bericht):
        """Der Datenstand auf der Startseite darf einen Lauf mit Warnungen nicht als glatten
        Erfolg zeigen."""
        with lese_sitzung() as sitzung:
            lauf = sitzung.scalar(select(Importlauf).where(Importlauf.id == bericht.importlauf_id))
        assert lauf.status == "warnung"


class TestOffeneZulassen:
    def test_nicht_uebernommene_zeilen_stehen_im_protokoll(self, analyse, firma_id):
        """Wer mit offenen Zuordnungen migriert, muss nachlesen können, was fehlt."""
        offene_vorher = len(analyse.vorschau.offene)
        bericht = _uebernehmen(analyse, firma_id, offene_zulassen=True)
        assert len(bericht.nicht_uebernommen) == offene_vorher
        with lese_sitzung() as sitzung:
            lauf = sitzung.scalar(select(Importlauf).where(Importlauf.id == bericht.importlauf_id))
        assert lauf.ergebnis["nicht_uebernommen"]
        assert lauf.status == "warnung"

    def test_projekte_entstehen_trotzdem(self, analyse, firma_id):
        bericht = _uebernehmen(analyse, firma_id, offene_zulassen=True)
        assert bericht.projekte == len(analyse.projekte.zeilen)


class TestNeuesProjekt:
    def test_kunde_nur_in_der_auftragsliste_bekommt_ein_projekt(self, analyse, firma_id):
        """16 Kunden der Auftragsliste haben kein Gegenstück in der Teamliste."""
        ohne_kandidat = [z for z in analyse.vorschau.offene if not z.vorschlaege]
        assert ohne_kandidat
        bestaetigen(analyse.vorschau, {z.kundenteil: None for z in analyse.vorschau.offene})
        assert all(
            z.art is Art.NEUES_PROJEKT for z in analyse.vorschau.zuordnungen if not z.zugeordnet
        )
        bericht = _uebernehmen(analyse, firma_id)
        assert bericht.projekte > len(analyse.projekte.zeilen)
        with lese_sitzung() as sitzung:
            neu = [
                p
                for p in sitzung.scalars(select(Projekt))
                if p.quelle_migration and "kein Eintrag in der Teamliste" in p.quelle_migration
            ]
        assert len(neu) == len(analyse.vorschau.zuordnungen) - sum(
            1 for z in analyse.vorschau.zuordnungen if z.zugeordnet
        )
