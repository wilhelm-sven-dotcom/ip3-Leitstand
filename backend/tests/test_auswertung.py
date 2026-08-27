"""Umsatz, Forecast und Auftragsbestand (PLAN §6.7, §6.12, §7 Phase 2).

Geprüft wird der Dienst, nicht die Route: die Rechenregeln sind der Teil, der stimmen muss, und
sie gelten ab Phase 5 auch für das Firmen-Cockpit. Zwei Dinge stehen dabei im Vordergrund:

* **Ist ist nicht bezahlt** (PLAN §6.7). Ist heißt: berechnet oder im Altbestand als gestellt
  gekennzeichnet. Der Zahlungsstatus kommt erst mit dem OPOS-Import.
* **Unterminierte Positionen verschwinden nicht.** Sie dürfen in keiner Monatssäule stehen und
  müssen trotzdem in der Summe auftauchen – im Bestand sind das 689.698,50 €.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import auswertung
from app.modelle import (
    Firma,
    Kunde,
    Nachtrag,
    Projekt,
    Rechnung,
    Zahlungsplanposition,
)


def _alle_projekte():
    """Sichtbarkeitsabfrage ohne Einschränkung – in den Routen kommt scope_filter davor."""
    return select(Projekt)


@pytest.fixture
def bestand(gesäte_db) -> dict:
    """Drei Projekte mit gemischten Zuständen, von Hand gerechnet.

    | Projekt | Status | AB-Wert | Positionen |
    |---|---|---|---|
    | 26001 | beauftragt | 100.000,00 € | 30.000 gestellt (05), 40.000 offen (09), 10.000 offen ohne Monat |
    | 26002 | in_bau | 50.000,00 € | 20.000 berechnet (06), 5.000 gestellt ohne Monat |
    | 26003 | abgeschlossen | 20.000,00 € | 20.000 gestellt (2025-11) |
    | 26004 | storniert | 90.000,00 € | 90.000 offen (09) – zählt nirgends |
    """
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde = Kunde(kunden_nr=13001, name="Auswertung GmbH", ort="Weiden", typ="b2b")
        sitzung.add(kunde)
        sitzung.flush()

        def projekt(nr: int, status: str, ab: int | None, pl: str = "Stefan") -> Projekt:
            eintrag = Projekt(
                projekt_nr=nr,
                firma_id=firma_id,
                kunde_id=kunde.id,
                status=status,
                ab_wert_netto=ab,
                pl_name=pl,
                anlagenart="aufdach",
            )
            sitzung.add(eintrag)
            sitzung.flush()
            return eintrag

        eins = projekt(26001, "beauftragt", 10000000)
        zwei = projekt(26002, "in_bau", 5000000, pl="Günther")
        drei = projekt(26003, "abgeschlossen", 2000000)
        vier = projekt(26004, "storniert", 9000000)

        rechnung = Rechnung(
            firma_id=firma_id,
            art="abschlag",
            projekt_id=zwei.id,
            kunde_id=zwei.kunde_id,
            datum=date(2026, 6, 1),
            netto=2000000,
            ust=380000,
            brutto=2380000,
            status="entwurf",
        )
        sitzung.add(rechnung)
        sitzung.flush()

        def position(
            p: Projekt,
            pos_nr: int,
            betrag: int,
            monat: str | None,
            *,
            gestellt: bool = False,
            rechnung_id: int | None = None,
            gewerk: str = "pv",
        ) -> None:
            sitzung.add(
                Zahlungsplanposition(
                    projekt_id=p.id,
                    pos_nr=pos_nr,
                    bezeichnung=f"Position {pos_nr}",
                    gewerk=gewerk,
                    art="abschlag",
                    betrag_netto=betrag,
                    plan_monat=monat,
                    migriert_gestellt=True if gestellt else None,
                    rechnung_id=rechnung_id,
                )
            )

        position(eins, 1, 3000000, "2026-05", gestellt=True)
        position(eins, 2, 4000000, "2026-09")
        position(eins, 3, 1000000, None)
        position(zwei, 1, 2000000, "2026-06", rechnung_id=rechnung.id)
        position(zwei, 2, 500000, None, gestellt=True, gewerk="speicher")
        position(drei, 1, 2000000, "2025-11", gestellt=True)
        position(vier, 1, 9000000, "2026-09")
        sitzung.flush()
        return {"kunde": kunde.id}


class TestJahresverlauf:
    def test_monate_und_summen(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        je_monat = {m.monat: m for m in verlauf.monate}
        assert len(verlauf.monate) == 12
        assert je_monat["2026-05"].ist_cent == 3000000
        assert je_monat["2026-05"].plan_cent == 0
        assert je_monat["2026-06"].ist_cent == 2000000, "berechnete Position zählt zum Ist"
        assert je_monat["2026-09"].plan_cent == 4000000, "stornierte Projekte zählen nicht mit"
        assert je_monat["2026-01"].summe_cent == 0

    def test_das_ganze_jahr_steht_da(self, bestand):
        """Ein Verlauf mit Lücken ist kein Verlauf – Januar bis Dezember, auch leer."""
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        assert [m.monat for m in verlauf.monate] == [f"2026-{m:02d}" for m in range(1, 13)]

    def test_jahressummen(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        assert verlauf.ist_cent == 3000000 + 2000000
        assert verlauf.plan_cent == 4000000

    def test_anderes_jahr_bleibt_draussen(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        assert all(m.monat.startswith("2026-") for m in verlauf.monate)
        assert verlauf.ist_cent + verlauf.plan_cent == 9000000, "2025 gehört nicht ins Jahr 2026"

    def test_jahr_2025_findet_seine_position(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2025)
        assert verlauf.ist_cent == 2000000
        assert verlauf.plan_cent == 0

    def test_jahr_ohne_daten_ergibt_zwoelf_leere_monate(self, bestand):
        """Eine leere Auswertung ist eine Auskunft, kein Fehler."""
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2030)
        assert len(verlauf.monate) == 12
        assert verlauf.ist_cent == 0 and verlauf.plan_cent == 0
        assert verlauf.unterminiert.summe_cent == 1500000, (
            "unterminierte Positionen hängen an keinem Jahr und werden immer ausgewiesen"
        )

    def test_unterminiert_getrennt_nach_ist_und_plan(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        assert verlauf.unterminiert.plan_cent == 1000000
        assert verlauf.unterminiert.ist_cent == 500000, "gestellter Umsatz ohne Monat"
        assert verlauf.unterminiert.anzahl == 2

    def test_unterminiertes_steht_in_keiner_saeule(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        summe_saeulen = sum(m.summe_cent for m in verlauf.monate)
        assert summe_saeulen == 3000000 + 2000000 + 4000000

    def test_anzahl_je_monat(self, bestand):
        with lese_sitzung() as db:
            verlauf = auswertung.jahresverlauf(db, _alle_projekte(), 2026)
        je_monat = {m.monat: m for m in verlauf.monate}
        assert je_monat["2026-05"].ist_anzahl == 1
        assert je_monat["2026-09"].plan_anzahl == 1

    def test_sichtbarkeit_wirkt_auf_die_summen(self, bestand):
        """Der Scope `eigene` darf nicht nur die Liste, sondern muss auch die Zahlen begrenzen."""
        with lese_sitzung() as db:
            nur_eins = select(Projekt).where(Projekt.projekt_nr == 26001)
            verlauf = auswertung.jahresverlauf(db, nur_eins, 2026)
        assert verlauf.ist_cent == 3000000
        assert verlauf.plan_cent == 4000000
        assert verlauf.unterminiert.plan_cent == 1000000
        assert verlauf.unterminiert.ist_cent == 0

    def test_jahre_kommen_aus_den_daten(self, bestand):
        with lese_sitzung() as db:
            assert auswertung.jahre_mit_daten(db, _alle_projekte()) == [2026, 2025]


class TestAuftragsbestand:
    def test_nur_laufende_projekte(self, bestand):
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        assert [p.projekt_nr for p in best.projekte] == [26001, 26002]

    def test_rest_je_projekt(self, bestand):
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        je_nr = {p.projekt_nr: p for p in best.projekte}
        # 100.000 Auftrag, 30.000 gestellt → 70.000 offen
        assert je_nr[26001].rest_cent == 7000000
        # 50.000 Auftrag, 20.000 berechnet + 5.000 gestellt → 25.000 offen
        assert je_nr[26002].rest_cent == 2500000
        assert best.bestand_cent == 9500000

    def test_beauftragter_nachtrag_erhoeht_den_bestand(self, bestand):
        with schreib_sitzung() as sitzung:
            projekt_id = sitzung.scalar(select(Projekt.id).where(Projekt.projekt_nr == 26001))
            sitzung.add_all(
                [
                    Nachtrag(
                        projekt_id=projekt_id,
                        bezeichnung="Mehr Module",
                        betrag_netto=1000000,
                        status="beauftragt",
                    ),
                    Nachtrag(
                        projekt_id=projekt_id,
                        bezeichnung="Angebot Speicher",
                        betrag_netto=5000000,
                        status="angeboten",
                    ),
                ]
            )
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        je_nr = {p.projekt_nr: p for p in best.projekte}
        assert je_nr[26001].nachtraege_cent == 1000000, "nur beauftragte zählen"
        assert je_nr[26001].soll_cent == 11000000
        assert je_nr[26001].rest_cent == 8000000

    def test_differenz_zum_zahlungsplan(self, bestand):
        """Die Zahl, die erklärt, warum Kachel und Diagramm nicht gleich sind."""
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        # offen: 40.000 + 10.000 (26001), 0 (26002) = 50.000
        assert best.zahlungsplan_offen_cent == 5000000
        assert best.nicht_verplant_cent == 9500000 - 5000000

    def test_projekt_ohne_auftragswert_wird_ausgewiesen(self, bestand):
        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
            sitzung.add(
                Projekt(
                    projekt_nr=26005,
                    firma_id=firma_id,
                    kunde_id=kunde_id,
                    status="beauftragt",
                    ab_wert_netto=None,
                )
            )
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        ohne = [p.projekt_nr for p in best.ohne_auftragswert]
        assert ohne == [26005]
        assert best.bestand_cent == 9500000, "ohne Auftragswert kein Beitrag zum Bestand"

    def test_ueberdeckung_wird_nicht_geklammert(self, bestand):
        """Mehr gestellt als beauftragt: die Zahl bleibt negativ und das Projekt fällt auf."""
        with schreib_sitzung() as sitzung:
            projekt = sitzung.scalar(select(Projekt).where(Projekt.projekt_nr == 26002))
            projekt.ab_wert_netto = 1000000
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        je_nr = {p.projekt_nr: p for p in best.projekte}
        assert je_nr[26002].rest_cent == 1000000 - 2500000
        assert [p.projekt_nr for p in best.zu_pruefen] == [26002]

    def test_groesster_rest_zuerst(self, bestand):
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        reste = [p.rest_cent for p in best.projekte if p.rest_cent is not None]
        assert reste == sorted(reste, reverse=True)

    def test_leerer_bestand(self, gesäte_db):
        with lese_sitzung() as db:
            best = auswertung.auftragsbestand(db, _alle_projekte())
        assert best.projekte == []
        assert best.bestand_cent == 0
        assert best.nicht_verplant_cent == 0
