"""Lesen der Bestandsdateien (PLAN §9).

Gearbeitet wird mit den Nachbauten aus ``tests/bestandsdateien.py``, nicht mit den echten
Dateien: die enthalten 530 Kundennamen und gehören nicht ins Repository. Die Nachbauten tragen
dafür jede Eigenheit, die im Original gefunden wurde – dort steht auch die Liste.

Leitgedanke aller Tests hier: **kein Wert verschwindet stillschweigend.** Was der Leser nicht
sicher deuten kann, wird ein Befund mit Zeile, Spalte und Originalinhalt.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.geld import euro_nach_cent
from app.migration import (
    BlattFehlt,
    auftragsliste_lesen,
    teamliste_lesen,
)
from app.migration.quellen import excel_datum, marker_lesen
from tests.bestandsdateien import (
    auftragsliste_bauen,
    auftragsliste_soll,
    teamliste_bauen,
    teamliste_soll,
)


@pytest.fixture(scope="module")
def auftragsliste(tmp_path_factory: pytest.TempPathFactory):
    pfad = auftragsliste_bauen(tmp_path_factory.mktemp("quellen") / "Offene_Auftraege.xlsx")
    return auftragsliste_lesen(pfad)


@pytest.fixture(scope="module")
def teamliste(tmp_path_factory: pytest.TempPathFactory):
    pfad = teamliste_bauen(tmp_path_factory.mktemp("quellen") / "Teambesprechung_NEU.xlsx")
    return teamliste_lesen(pfad)


class TestAuftragsliste:
    def test_kontrollsummen(self, auftragsliste):
        soll = auftragsliste_soll()
        assert len(auftragsliste.zeilen) == soll["zeilen"]
        assert auftragsliste.summe_netto_cent == euro_nach_cent(soll["summe_euro"])
        assert auftragsliste.summe_gestellt_cent == euro_nach_cent(soll["gestellt_euro"])
        gestellt = sum(1 for z in auftragsliste.zeilen if z.gestellt)
        assert gestellt == soll["gestellt_zeilen"]

    def test_summe_je_monat_und_unterminiert(self, auftragsliste):
        """Positionen ohne Monatsmarker sind 'unterminiert', nicht 'Januar'."""
        je_monat = auftragsliste.summe_je_monat()
        soll = auftragsliste_soll()
        assert je_monat["unterminiert"] == euro_nach_cent(soll["unterminiert_euro"])
        # Das Jahr steht nicht in der Datei; 2026 ist entschieden (OFFENE-PUNKTE Nr. 8).
        assert all(m.startswith("2026-") for m in je_monat if m != "unterminiert")
        assert sum(je_monat.values()) == auftragsliste.summe_netto_cent

    def test_leerzeilen_beenden_das_lesen_nicht(self, auftragsliste):
        """Im Original stehen drei Leerzeilen vor den letzten drei Projekten.

        Ein Leser, der bei der ersten Leerzeile aufhört, verliert sie – im Original wären das
        1.091.257,53 € gewesen.
        """
        assert any(z.kunde == "Ärztehaus Weiden" for z in auftragsliste.zeilen)

    def test_unlesbarer_betrag_wird_gemeldet_nicht_geraten(self, auftragsliste):
        soll = auftragsliste_soll()
        warnungen = [b for b in auftragsliste.befunde if b.schwere == "warnung"]
        betragsbefunde = [b for b in warnungen if b.spalte == "B"]
        assert len(betragsbefunde) == soll["unlesbare_betraege"]
        assert "?" in betragsbefunde[0].wert
        assert not any("Lang" in z.kunde for z in auftragsliste.zeilen)

    def test_rechnungsarten_in_allen_schreibweisen(self, auftragsliste):
        nach_text = {z.freitext: z.rechnungsart for z in auftragsliste.zeilen}
        erwartet = {
            "Aigner, Mitterteich - 1. Abschlag PV": ("abschlag", 1, "pv"),
            "Aigner, Mitterteich - Schlussrechnung PV": ("schluss", None, "pv"),
            "Brunner Hof, Erbendorf - Schlussrechnung - Speicher": ("schluss", None, "speicher"),
            "Cramer, Floß - 3 .Abschlag Speicher": ("abschlag", 3, "speicher"),
            "Denk, Wiesau - 5. Abschlag PV": ("abschlag", 5, "pv"),
            "Eder, Bärnau - Rechnung 100 % Wallbox": ("einmal", None, "ls"),
            "Fuchs, Neustadt - 100% Notstromfunktion": ("einmal", None, None),
            "Gruber, Bechtsrieth - 1. Abschlag": ("abschlag", 1, None),
        }
        for text, (art, nummer, gewerk) in erwartet.items():
            gelesen = nach_text[text]
            assert (gelesen.art, gelesen.nummer, gelesen.gewerk) == (art, nummer, gewerk), text

    def test_abschlagsnummer_geht_ueber_vier(self, auftragsliste):
        """Die Teamliste hat vier Abschlagsspalten, die Auftragsliste kennt fünf.

        Eine Positionsnummer bei 4 zu deckeln hätte die fünften Abschläge verloren.
        """
        nummern = {z.rechnungsart.nummer for z in auftragsliste.zeilen if z.rechnungsart.nummer}
        assert 5 in nummern

    def test_zeilen_ohne_rechnungsart_sind_auftragssummen(self, auftragsliste):
        summen = [z for z in auftragsliste.zeilen if z.ist_projektsumme]
        assert len(summen) == auftragsliste_soll()["projektsummen"]
        assert {z.kunde for z in summen} == {
            "Speicherprojekt Irlbacher",
            "Gewerbepark Konnersreuth",
        }
        # Sie werden gemeldet, damit die Maske sie zeigt – aber als Hinweis, nicht als Warnung.
        hinweise = [b for b in auftragsliste.befunde if b.schwere == "hinweis"]
        assert any("Auftragssumme ohne" in b.meldung for b in hinweise)

    def test_kunde_und_ort_getrennt(self, auftragsliste):
        nach_kunde = {z.kunde: z.ort for z in auftragsliste.zeilen}
        assert nach_kunde["Aigner"] == "Mitterteich"
        assert nach_kunde["Brunner Hof"] == "Erbendorf"
        # Firmenname ohne Komma: kein erfundener Ort.
        assert nach_kunde["Ärztehaus Weiden"] is None

    def test_falsches_blatt_nennt_die_vorhandenen(self, tmp_path: Path):
        from openpyxl import Workbook

        pfad = tmp_path / "falsch.xlsx"
        mappe = Workbook()
        mappe.active.title = "Tabelle1"
        mappe.save(pfad)
        with pytest.raises(BlattFehlt) as fehler:
            auftragsliste_lesen(pfad)
        assert "Et-Einnahmen" in fehler.value.meldung
        assert "Tabelle1" in fehler.value.naechster_schritt
        assert "falsch.xlsx" in fehler.value.meldung


class TestTeamliste:
    def test_kontrollsummen(self, teamliste):
        soll = teamliste_soll()
        assert len(teamliste.zeilen) == soll["projekte"]
        assert teamliste.summe_ab_wert_cent == euro_nach_cent(soll["ab_wert_euro"])
        mit_wert = sum(1 for z in teamliste.zeilen if z.ab_wert_cent is not None)
        assert mit_wert == soll["mit_ab_wert"]

    def test_unlesbarer_auftragswert_bleibt_leer(self, teamliste):
        """'22.604.28 €' hat zwei Trennzeichen. Bei Geld wird nicht geraten (PLAN §6).

        Eine erfundene Zahl im Auftragsbestand wäre schlimmer als eine erkennbare Lücke.
        """
        eder = next(z for z in teamliste.zeilen if z.kunde == "Eder")
        assert eder.ab_wert_cent is None
        befund = next(b for b in teamliste.befunde if b.zeile == eder.zeile and b.spalte == "I")
        assert befund.schwere == "warnung"
        assert befund.wert == "22.604.28 €"

    def test_speicherbezeichnung_und_kapazitaet(self, teamliste):
        """Die Speicherspalte ist Produkttext. Kapazität lesen, Bezeichnung behalten."""
        nach_kunde = {z.kunde: z for z in teamliste.zeilen}
        aigner = nach_kunde["Aigner"]
        assert aigner.speicher_typ == "2x BYD HVM 22.1"
        assert aigner.speicher_kwh == Decimal("44.2")  # zwei Geräte à 22,1 kWh
        # Dezimalkomma statt Punkt kommt im Bestand vor.
        assert nach_kunde["Brunner Hof"].speicher_kwh == Decimal("13.5")
        assert nach_kunde["Cramer"].speicher_kwh == Decimal("10.2")

    def test_strich_heisst_ohne_angabe(self, teamliste):
        """'-' ist keine Leistung von null, sondern 'nicht vorhanden'."""
        cramer = next(z for z in teamliste.zeilen if z.kunde == "Cramer")
        assert cramer.pv_kwp is None

    def test_auftragsdatum_aus_seriennummer(self, teamliste):
        nach_kunde = {z.kunde: z for z in teamliste.zeilen}
        assert nach_kunde["Aigner"].auftrag_vom == date(2020, 10, 19)
        assert nach_kunde["Brunner Hof"].auftrag_vom == date(2021, 5, 30)

    def test_unlesbares_und_fehlendes_datum(self, teamliste):
        soll = teamliste_soll()
        ohne = [z for z in teamliste.zeilen if z.auftrag_vom is None]
        assert len(ohne) == soll["ohne_auftragsdatum"]
        # Der Tippfehler wird gemeldet, die leere Zelle nicht – dort ist nichts zu beanstanden.
        warnungen = [b for b in teamliste.befunde if b.spalte == "H" and b.schwere == "warnung"]
        assert len(warnungen) == 1
        assert warnungen[0].wert == "30.11.222"

    def test_terminspalten_werden_eigene_meilensteine(self, teamliste):
        aigner = next(z for z in teamliste.zeilen if z.kunde == "Aigner")
        assert aigner.meilensteine["montage_uk"].erledigt is True
        assert aigner.meilensteine["montage_elektro"].erledigt is True
        assert aigner.meilensteine["abnahme"].erledigt is True
        # Nicht gesetzte Spalten erzeugen keinen Meilenstein – nichts erfinden.
        assert "lieferung_wallbox" not in aigner.meilensteine

    def test_kalenderwoche_statt_kreuz(self, teamliste):
        cramer = next(z for z in teamliste.zeilen if z.kunde == "Cramer")
        stand = cramer.meilensteine["lieferung_speicher"]
        assert stand.geplant_kw == "26/23"
        assert stand.erledigt is None  # eine Kalenderwoche sagt nichts über 'erledigt'

    def test_o_heisst_offen_und_strich_heisst_nicht_erledigt(self, teamliste):
        cramer = next(z for z in teamliste.zeilen if z.kunde == "Cramer")
        assert cramer.meilensteine["montage_uk"].erledigt is False
        assert cramer.meilensteine["abnahme"].erledigt is False

    def test_freitext_im_terminblock_wird_gemeldet(self, teamliste):
        """In zwei Zeilen des Originals steht ein Personenname in der Statusspalte."""
        denk = next(z for z in teamliste.zeilen if z.kunde == "Denk")
        assert denk.meilensteine["fertigmeldung"].erledigt is None
        befund = next(
            b for b in teamliste.befunde if b.zeile == denk.zeile and b.wert == "Benjamin"
        )
        assert befund.schwere == "warnung"
        # Ein doppeltes Kreuz bleibt ein Kreuz.
        assert denk.meilensteine["lieferung_wr_pv"].erledigt is True

    def test_statusableitung(self, teamliste):
        """PLAN §9: Abnahme gesetzt heißt abgeschlossen, sonst in_bau oder beauftragt."""
        nach_kunde = {z.kunde: z.status for z in teamliste.zeilen}
        assert nach_kunde["Aigner"] == "abgeschlossen"
        assert nach_kunde["Ärztehaus Weiden"] == "in_bau"  # Montage, aber keine Abnahme
        assert nach_kunde["Cramer"] == "beauftragt"  # Montage offen, Abnahme ausdrücklich nein

    def test_projektleiter_werden_normalisiert(self, teamliste):
        """Im Original gibt es 16 Schreibweisen für 11 Personen."""
        namen = {z.pl_name for z in teamliste.zeilen if z.pl_name}
        assert "Stefan" in namen
        assert "  Stefan " not in namen
        assert len(namen) == teamliste_soll()["projektleiter"]

    def test_modulspalte_wird_nicht_uebernommen(self, teamliste):
        """Spalte AK heißt 'Module reserviert [Stück]', enthält aber Bruchzahlen und Fehler."""
        fuchs = next(z for z in teamliste.zeilen if z.kunde == "Fuchs")
        assert "module" not in " ".join(fuchs.meilensteine).lower()
        hinweis = next(
            b for b in teamliste.befunde if b.zeile == fuchs.zeile and b.wert == "#VALUE!"
        )
        assert hinweis.schwere == "hinweis"

    def test_vorplanungsspalten_werden_notiz_und_gemeldet(self, teamliste):
        """Abweichung von PLAN §9, begründet: 14 gefüllte Zellen auf 530 Zeilen.

        Acht zusätzliche Meilenstein-Typen für Spalten, die der Termin- und Statusblock schon
        abdeckt, wären Schemaballast. Verloren geht nichts: der Wert steht als Notiz am Projekt
        und im Importprotokoll.
        """
        gruber = next(z for z in teamliste.zeilen if z.kunde == "Gruber")
        assert gruber.vorplanung  # der Wert ist da
        assert not any(t.startswith("1.") for t in gruber.meilensteine)
        hinweis = next(
            b for b in teamliste.befunde if b.zeile == gruber.zeile and "Vorplanung" in b.meldung
        )
        assert hinweis.schwere == "hinweis"

    def test_abschlagskreuze_der_buchhaltung(self, teamliste):
        aigner = next(z for z in teamliste.zeilen if z.kunde == "Aigner")
        assert aigner.abschlaege_gestellt[("pv", 1)] is True
        assert aigner.abschlaege_gestellt[("speicher", 1)] is True

    def test_zwei_projekte_desselben_kunden(self, teamliste):
        """Im Original stehen 23 Kundennamen doppelt – zwei Projekte, ein Kunde."""
        huber = [z for z in teamliste.zeilen if z.kunde == "Huber"]
        assert len(huber) == 2
        assert {z.pv_kwp for z in huber} == {Decimal("29.58"), Decimal("210.67")}


class TestHilfsfunktionen:
    @pytest.mark.parametrize(
        ("wert", "erledigt", "kw"),
        [
            ("x", True, None),
            ("X", True, None),
            ("-", False, None),
            ("o", False, None),
            ("28/22", None, "28/22"),
            ("7/23", None, "07/23"),  # führende Null, damit sortierbar
            ("x, x", True, None),
            ("DEG?", None, None),
            ("", None, None),
            (None, None, None),
        ],
    )
    def test_marker_lesen(self, wert, erledigt, kw):
        stand = marker_lesen(wert)
        assert (stand.erledigt, stand.geplant_kw) == (erledigt, kw)

    @pytest.mark.parametrize(
        ("wert", "erwartet"),
        [
            (44123, date(2020, 10, 19)),
            (45000, date(2023, 3, 15)),
            (date(2026, 1, 2), date(2026, 1, 2)),
            ("30.11.222", None),  # Tippfehler
            ("?", None),
            ("-", None),
            (None, None),
            (12, None),  # zu klein für ein plausibles Datum
        ],
    )
    def test_excel_datum(self, wert, erwartet):
        assert excel_datum(wert) == erwartet
