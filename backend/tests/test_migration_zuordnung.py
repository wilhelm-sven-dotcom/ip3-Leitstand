"""Zuordnung der Auftragsliste zu den Projekten der Teamliste (PLAN §9).

Der wichtigste Test steht ganz oben: ``test_falschtreffer_wird_nicht_zugeordnet``. Im echten
Bestand liefert ein Ähnlichkeitsmaß von 0,80 den Treffer „Nachtmann, Weiden" → „Hubmann,
Weiden" – zwei verschiedene Kunden, 550.000 € am falschen Projekt. Der Nachbau enthält diesen
Fall als 'Nachbauer' gegen 'Hubmaier'.
"""

from __future__ import annotations

import pytest

from app.migration import auftragsliste_lesen, teamliste_lesen
from app.migration.zuordnung import (
    Art,
    UnbekannterKunde,
    bestaetigen,
    guete,
    vorschau_erstellen,
)
from tests.bestandsdateien import auftragsliste_bauen, teamliste_bauen


@pytest.fixture(scope="module")
def quellen(tmp_path_factory: pytest.TempPathFactory):
    """Beide Nachbauten einmal je Testmodul lesen – das Bauen der Dateien kostet Zeit."""
    ordner = tmp_path_factory.mktemp("zuordnung")
    auftraege = auftragsliste_lesen(auftragsliste_bauen(ordner / "Offene_Auftraege.xlsx"))
    projekte = teamliste_lesen(teamliste_bauen(ordner / "Teambesprechung_NEU.xlsx"))
    return auftraege, projekte


@pytest.fixture
def vorschau(quellen):
    """Frische Vorschau je Test.

    Absichtlich nicht modulweit: ``bestaetigen`` verändert die Vorschau, und ein Test darf nicht
    davon abhängen, ob ein anderer vorher gelaufen ist.
    """
    auftraege, projekte = quellen
    return vorschau_erstellen(auftraege.zeilen, projekte.zeilen)


@pytest.fixture
def projektzeilen(quellen):
    return quellen[1].zeilen


def _finden(vorschau, anfang: str):
    return next(z for z in vorschau.zuordnungen if z.kundenteil.startswith(anfang))


class TestFalschtreffer:
    def test_falschtreffer_wird_nicht_zugeordnet(self, vorschau, projektzeilen):
        """Gleicher Ort, anderer Name: keine automatische Zuordnung, kein Vorschlag.

        Der Ort allein darf keinen Treffer erzeugen. Im Bestand teilen sich 60 Projekte den Ort
        Weiden – ein Maß, das nur auf den Gesamttext schaut, ordnet dort beliebig zu.
        """
        nachbauer = _finden(vorschau, "Nachbauer")
        assert nachbauer.art is Art.OHNE
        assert nachbauer.projekt_zeile is None
        assert nachbauer.vorschlaege == []
        # Der Namensvetter existiert in der Teamliste – er wird nur nicht vorgeschlagen.
        assert any(z.kunde == "Hubmaier" for z in projektzeilen)

    def test_guete_ohne_namensaehnlichkeit_ist_null(self):
        assert guete("Nachbauer", "Weiden", "Hubmaier", "Weiden") == 0.0
        # Derselbe Name an einem anderen Ort bleibt ein Kandidat, nur mit weniger Punkten.
        mit_ort = guete("Hößl", "Grafenwöhr", "Hößl", "Grafenwöhr")
        anderer_ort = guete("Hößl", "Grafenwöhr", "Hößl", "Erbendorf")
        assert mit_ort == 100.0
        assert 0 < anderer_ort < mit_ort

    def test_ort_kann_fremden_namen_nicht_retten(self):
        """Selbst bei identischem Ort bleibt ein fremder Name bei null."""
        assert guete("Volksfestplatz Weiden 1", None, "Winter", "Weiden") == 0.0


class TestZuordnung:
    def test_eindeutiger_name_wird_automatisch_zugeordnet(self, vorschau):
        aigner = _finden(vorschau, "Aigner")
        assert aigner.art is Art.EXAKT
        assert aigner.projekt_zeile is not None
        assert not aigner.offen

    def test_zeilen_eines_kunden_werden_gemeinsam_entschieden(self, vorschau):
        """Die vier Abschlagszeilen eines Projekts gehören zusammen.

        Achtmal dieselbe Frage zu stellen wäre in der Maske eine Zumutung und lädt zum
        Durchklicken ein – dann ist die Bestätigung wertlos.
        """
        aigner = _finden(vorschau, "Aigner")
        assert len(aigner.auftrags_zeilen) == 4
        assert aigner.betrag_cent == 5000_00 + 3000_00 + 2000_50 + 1000_25

    def test_mehrfacher_kundenname_braucht_entscheidung(self, vorschau):
        """Zwei Projekte desselben Kunden: der Text stimmt exakt, eindeutig ist er nicht."""
        huber = _finden(vorschau, "Huber")
        assert huber.art is Art.VORSCHLAG
        assert huber.projekt_zeile is None
        assert len(huber.vorschlaege) == 2
        assert vorschau.mehrdeutige_kunden

    def test_projektzusatz_in_der_teamliste_trifft_trotzdem(self, vorschau):
        """'Brunner Hof, Erbendorf' steht in beiden Dateien – Zusätze dürfen nicht stören."""
        brunner = _finden(vorschau, "Brunner Hof")
        assert brunner.zugeordnet

    def test_kunde_ohne_gegenstueck_bleibt_offen(self, vorschau):
        # 'Speicherprojekt Irlbacher' gibt es in der Teamliste nicht.
        irlbacher = _finden(vorschau, "Speicherprojekt Irlbacher")
        assert irlbacher.offen
        assert not irlbacher.zugeordnet

    def test_summen_nach_art(self, vorschau):
        je_art = vorschau.zeilen_je_art()
        assert sum(je_art.values()) == sum(len(z.auftrags_zeilen) for z in vorschau.zuordnungen)
        assert vorschau.betrag_offen_cent == sum(z.betrag_cent for z in vorschau.offene)

    def test_nach_betrag_sortiert(self, vorschau):
        """Die größten Posten zuerst – dort tut eine Fehlzuordnung am meisten weh."""
        betraege = [z.betrag_cent for z in vorschau.zuordnungen]
        assert betraege == sorted(betraege, reverse=True)


class TestBestaetigen:
    def test_bestaetigung_setzt_das_projekt(self, vorschau):
        huber = _finden(vorschau, "Huber")
        ziel = huber.vorschlaege[0].projekt_zeile
        bestaetigen(vorschau, {huber.kundenteil: ziel})
        assert huber.art is Art.BESTAETIGT
        assert huber.projekt_zeile == ziel
        assert not huber.offen

    def test_ohne_projekt_heisst_neu_anlegen(self, vorschau):
        irlbacher = _finden(vorschau, "Speicherprojekt Irlbacher")
        bestaetigen(vorschau, {irlbacher.kundenteil: None})
        assert irlbacher.art is Art.NEUES_PROJEKT
        assert irlbacher.projekt_zeile is None
        assert not irlbacher.offen

    def test_unbekannter_kunde_wird_abgewiesen(self, vorschau):
        """Ein Tippfehler in der Maske darf nicht als Erfolg durchgehen."""
        with pytest.raises(UnbekannterKunde) as fehler:
            bestaetigen(vorschau, {"Gibt es nicht, Nirgendwo": 8})
        assert "Gibt es nicht" in str(fehler.value)
