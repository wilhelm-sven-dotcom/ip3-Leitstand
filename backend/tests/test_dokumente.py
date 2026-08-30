"""Doku-Vollständigkeitsscan der Projektordner (PLAN §7 Phase 7).

Geprüft wird beides: dass der Scan findet, was da ist, und dass er verständlich sagt, wenn er
seine Arbeit nicht tun kann. Fehlerpfade zählen zur Funktion (CLAUDE.md Regel 8).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.datenbank import lese_sitzung, schreib_sitzung
from app.dienste import dokumente as dienst
from app.konfiguration import DokumenteEinstellungen
from app.modelle import Dokument, Firma, Kunde, Projekt, Projektordner

# ------------------------------------------------------------------------------------------
# Namen lesen – ohne Datenbank
# ------------------------------------------------------------------------------------------


class TestOrdnernamen:
    @pytest.mark.parametrize(
        ("name", "erwartet"),
        [
            ("26001", 26001),
            ("26001 Muster GmbH", 26001),
            ("26001_Muster", 26001),
            ("P-26001", 26001),
            ("Muster GmbH 26001", 26001),
            # Die längste Ziffernfolge gewinnt: das Jahr vorn ist kürzer als die Nummer.
            ("2026_902601", 902601),
            ("Archiv", None),
            ("2026", 2026),
        ],
    )
    def test_nummer_aus_ordnername(self, name: str, erwartet: int | None):
        assert dienst.nummer_aus_ordnername(name) == erwartet

    def test_zu_kurze_ziffernfolgen_zaehlen_nicht(self):
        """Eine dreistellige Zahl ist keine Projektnummer (PLAN §3: JJNNN, also fünfstellig)."""
        assert dienst.nummer_aus_ordnername("Halle 12") is None


class TestTyperkennung:
    def test_umlaute_und_trennzeichen_stoeren_nicht(self):
        muster = {"abnahme": ["abnahmeprotokoll"], "konformitaet": ["konformitaetserklaerung"]}
        assert dienst.typ_erkennen("Abnahmeprotokoll_2026.pdf", muster) == "abnahme"
        assert dienst.typ_erkennen("abnahme-protokoll.pdf", muster) == "abnahme"
        assert dienst.typ_erkennen("Konformitätserklärung.pdf", muster) == "konformitaet"

    def test_reihenfolge_der_konfiguration_entscheidet(self):
        """Wer 'konformitaet' vor 'abnahme' stellt, meint das so."""
        vorn = {"konformitaet": ["protokoll"], "abnahme": ["abnahmeprotokoll"]}
        assert dienst.typ_erkennen("Abnahmeprotokoll.pdf", vorn) == "konformitaet"

    def test_unbekannter_name_ergibt_nichts(self):
        assert dienst.typ_erkennen("scan_0042.pdf", {"abnahme": ["abnahme"]}) is None


# ------------------------------------------------------------------------------------------
# Der Lauf
# ------------------------------------------------------------------------------------------


@pytest.fixture
def wurzel(tmp_path: Path) -> Path:
    """Eigener Ordner als Scan-Wurzel.

    Nicht ``tmp_path`` selbst: dort liegt auch die Testdatenbank, und die zählte sonst als
    Ordner ohne Projekt. Im Betrieb zeigt ``[pfade] projekte`` ebenso auf einen eigenen Ordner.
    """
    ordner = tmp_path / "projekte"
    ordner.mkdir()
    return ordner


@pytest.fixture
def werte() -> DokumenteEinstellungen:
    return DokumenteEinstellungen(
        pflicht=["anlagendoku"],
        muster={
            "abnahme": ["abnahmeprotokoll"],
            "anlagendoku": ["anlagendokumentation"],
            "konformitaet": ["fertigmeldung"],
        },
        endungen=[".pdf"],
        tiefe=2,
    )


def _projekt(nummer: int) -> int:
    """Ein Projekt mit dieser Nummer; Firma und Kunde kommen aus den Grunddaten."""
    with schreib_sitzung() as sitzung:
        firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
        kunde_id = sitzung.scalar(select(Kunde.id).order_by(Kunde.id).limit(1))
        if kunde_id is None:
            kunde = Kunde(kunden_nr=70001, name="Ordnerkunde", ort="Weiden", typ="b2b")
            sitzung.add(kunde)
            sitzung.flush()
            kunde_id = kunde.id
        projekt = Projekt(
            firma_id=firma_id,
            kunde_id=kunde_id,
            projekt_nr=nummer,
            bezeichnung=f"Projekt {nummer}",
            status="in_bau",
        )
        sitzung.add(projekt)
        sitzung.flush()
        return projekt.id


def _scannen(wurzel: Path, werte: DokumenteEinstellungen, heute: date | None = None):
    with schreib_sitzung() as sitzung:
        return dienst.scannen(sitzung, wurzel, werte, heute=heute)


def _dokumente(projekt_id: int) -> dict[str, Dokument]:
    with lese_sitzung() as sitzung:
        return {
            zeile.typ: zeile
            for zeile in sitzung.execute(
                select(Dokument).where(Dokument.projekt_id == projekt_id)
            ).scalars()
        }


def _ordner(projekt_id: int) -> Projektordner:
    with lese_sitzung() as sitzung:
        return sitzung.execute(
            select(Projektordner).where(Projektordner.projekt_id == projekt_id)
        ).scalar_one()


def _fehlend(projekt_id: int, werte: DokumenteEinstellungen) -> list[str]:
    with lese_sitzung() as sitzung:
        return dienst.fehlende_pflicht(sitzung, projekt_id, werte)


class TestScannen:
    def test_findet_unterlagen_und_haelt_fehlende_fest(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        projekt_id = _projekt(26001)
        ordner = wurzel / "26001 Muster GmbH"
        ordner.mkdir()
        (ordner / "Abnahmeprotokoll.pdf").write_text("x")
        (ordner / "notizen.txt").write_text("zaehlt nicht")

        ergebnis = _scannen(wurzel, werte, heute=date(2026, 8, 30))

        assert ergebnis.mit_ordner == 1
        assert ergebnis.ohne_ordner == 0
        # Die Anlagendokumentation ist Pflicht und fehlt.
        assert ergebnis.unvollstaendig == 1

        zeilen = _dokumente(projekt_id)
        assert zeilen["abnahme"].vorhanden is True
        assert zeilen["abnahme"].pfad.endswith("Abnahmeprotokoll.pdf")
        assert zeilen["anlagendoku"].vorhanden is False
        # Ohne Fund traegt der Pfad den Ordner, in dem gesucht wurde – das sagt, wohin sie gehoert.
        assert zeilen["anlagendoku"].pfad == str(ordner)
        assert zeilen["abnahme"].geprueft_am == date(2026, 8, 30)

        # Die .txt zaehlt nicht mit: nur die Endungen aus der Konfiguration.
        assert _ordner(projekt_id).dateien == 1
        assert _fehlend(projekt_id, werte) == ["anlagendoku"]

    def test_unterordner_werden_bis_zur_erlaubten_tiefe_gelesen(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        projekt_id = _projekt(26002)
        ordner = wurzel / "26002"
        (ordner / "Doku").mkdir(parents=True)
        (ordner / "Doku" / "Anlagendokumentation.pdf").write_text("x")
        # Eine Ebene zu tief: bei tiefe=2 wird sie nicht mehr gelesen.
        (ordner / "Doku" / "Fotos" / "Archiv").mkdir(parents=True)
        (ordner / "Doku" / "Fotos" / "Archiv" / "Abnahmeprotokoll.pdf").write_text("x")

        _scannen(wurzel, werte)

        assert _fehlend(projekt_id, werte) == []
        zeilen = _dokumente(projekt_id)
        assert zeilen["anlagendoku"].vorhanden is True
        assert zeilen["abnahme"].vorhanden is False

    def test_projekt_ohne_ordner_wird_als_solches_vermerkt(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        """„Kein Ordner" und „Ordner da, Unterlage fehlt" sind zwei verschiedene Auskuenfte."""
        projekt_id = _projekt(26003)

        ergebnis = _scannen(wurzel, werte)

        assert ergebnis.ohne_ordner == 1
        eintrag = _ordner(projekt_id)
        assert eintrag.gefunden is False
        assert eintrag.pfad is None

    def test_zwei_ordner_mit_derselben_nummer_werden_gemeldet(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        """Raten waere schlimmer als sagen: der erste gilt, der zweite steht im Befund."""
        projekt_id = _projekt(26004)
        (wurzel / "26004 Muster").mkdir()
        (wurzel / "26004 Muster (alt)").mkdir()

        ergebnis = _scannen(wurzel, werte)

        assert ergebnis.mehrdeutig == 1
        eintrag = _ordner(projekt_id)
        assert eintrag.gefunden is True
        assert eintrag.mehrdeutig_mit is not None
        # Der erste in sortierter Reihenfolge bleibt massgeblich.
        assert eintrag.pfad.endswith("26004 Muster")

    def test_ordner_ohne_projekt_werden_genannt(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        """Ein Ordner ohne Projekt heisst meist, dass ein Projekt im Leitstand fehlt."""
        _projekt(26005)
        (wurzel / "26005").mkdir()
        (wurzel / "19999 Altbestand").mkdir()

        ergebnis = _scannen(wurzel, werte)

        assert ergebnis.verwaist == ["19999 Altbestand"]

    def test_zweiter_lauf_aktualisiert_statt_anzuhaengen(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        """Sonst stuende „Anlagendokumentation fehlt" neben „Anlagendokumentation liegt vor"."""
        projekt_id = _projekt(26006)
        ordner = wurzel / "26006"
        ordner.mkdir()

        _scannen(wurzel, werte)
        assert _fehlend(projekt_id, werte) == ["anlagendoku"]

        (ordner / "Anlagendokumentation.pdf").write_text("x")
        _scannen(wurzel, werte)

        with lese_sitzung() as sitzung:
            zeilen = (
                sitzung.execute(
                    select(Dokument).where(
                        Dokument.projekt_id == projekt_id, Dokument.typ == "anlagendoku"
                    )
                )
                .scalars()
                .all()
            )
        assert len(zeilen) == 1
        assert zeilen[0].vorhanden is True
        assert _fehlend(projekt_id, werte) == []

    def test_nicht_erreichbare_wurzel_wirft_eine_eigene_ausnahme(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        """Damit der Job daraus eine deutsche Meldung macht statt eines Stacktrace."""
        _projekt(26007)

        with pytest.raises(dienst.OrdnerNichtLesbar) as fehler:
            _scannen(wurzel / "gibt-es-nicht", werte)
        assert "gibt-es-nicht" in str(fehler.value)


class TestFehlendePflicht:
    def test_ohne_scan_wird_nichts_gemeldet(self, gesäte_db, werte: DokumenteEinstellungen):
        """Ein Hinweis „alles fehlt", nur weil der Scan nie lief, waere falsch."""
        projekt_id = _projekt(26008)
        assert _fehlend(projekt_id, werte) == []

    def test_leere_pflichtliste_meldet_nie(
        self, gesäte_db, wurzel: Path, werte: DokumenteEinstellungen
    ):
        projekt_id = _projekt(26009)
        (wurzel / "26009").mkdir()
        ohne_pflicht = werte.model_copy(update={"pflicht": []})

        _scannen(wurzel, ohne_pflicht)

        assert _fehlend(projekt_id, ohne_pflicht) == []


# ------------------------------------------------------------------------------------------
# Der nächtliche Lauf
# ------------------------------------------------------------------------------------------


class TestJob:
    def test_ohne_konfigurierten_ordner_warnt_der_lauf_verstaendlich(
        self, gesäte_db, test_einstellungen
    ):
        """Kein Stacktrace, sondern die Meldung mit dem nächsten Schritt (CLAUDE.md Regel 8)."""
        from app.jobs.dokumente import doku_scan_job

        werte = test_einstellungen.model_copy(deep=True)
        werte.pfade.projekte = None
        doku_scan_job("manuell", werte)

        lauf = _letzter_lauf("doku_scan")
        assert lauf.status == "warnung"
        assert "config.toml" in lauf.meldung
        assert "[pfade]" in lauf.meldung

    def test_nicht_erreichbarer_ordner_warnt_statt_zu_werfen(
        self, gesäte_db, test_einstellungen, tmp_path: Path
    ):
        from app.jobs.dokumente import doku_scan_job

        werte = test_einstellungen.model_copy(deep=True)
        werte.pfade.projekte = tmp_path / "nicht-eingehaengt"
        doku_scan_job("manuell", werte)

        lauf = _letzter_lauf("doku_scan")
        assert lauf.status == "warnung"
        assert "nicht erreichbar" in lauf.meldung

    def test_erfolgreicher_lauf_zaehlt_und_meldet_im_richtigen_numerus(
        self, gesäte_db, test_einstellungen, tmp_path: Path
    ):
        """„1 Projekt ohne Ordner", nicht „1 Projekte ohne Ordner"."""
        from app.jobs.dokumente import doku_scan_job

        wurzel = tmp_path / "projekte"
        wurzel.mkdir()
        _projekt(26101)
        _projekt(26102)
        (wurzel / "26101").mkdir()
        (wurzel / "26101" / "Anlagendokumentation.pdf").write_text("x")

        werte = test_einstellungen.model_copy(deep=True)
        werte.pfade.projekte = wurzel
        doku_scan_job("manuell", werte)

        lauf = _letzter_lauf("doku_scan")
        assert lauf.status == "erfolg"
        assert lauf.kennzahlen["mit_ordner"] == 1
        assert lauf.kennzahlen["ohne_ordner"] == 1
        assert "1 Projekt ohne Ordner" in lauf.meldung

    def test_unvollstaendige_ordner_faerben_den_status_nicht_ein(
        self, gesäte_db, test_einstellungen, tmp_path: Path
    ):
        """Ein Systemstatus, der neun Monate im Jahr gelb steht, sagt nichts mehr."""
        from app.jobs.dokumente import doku_scan_job

        wurzel = tmp_path / "projekte"
        wurzel.mkdir()
        _projekt(26103)
        (wurzel / "26103").mkdir()

        werte = test_einstellungen.model_copy(deep=True)
        werte.pfade.projekte = wurzel
        doku_scan_job("manuell", werte)

        lauf = _letzter_lauf("doku_scan")
        assert lauf.status == "erfolg"
        assert lauf.kennzahlen["unvollstaendig"] == 1

    def test_mehrdeutige_ordner_sind_eine_warnung(
        self, gesäte_db, test_einstellungen, tmp_path: Path
    ):
        """Die einzige Lage, in der der Scan selbst unsicher ist – das gehört gesagt."""
        from app.jobs.dokumente import doku_scan_job

        wurzel = tmp_path / "projekte"
        wurzel.mkdir()
        _projekt(26104)
        (wurzel / "26104 neu").mkdir()
        (wurzel / "26104 alt").mkdir()

        werte = test_einstellungen.model_copy(deep=True)
        werte.pfade.projekte = wurzel
        doku_scan_job("manuell", werte)

        lauf = _letzter_lauf("doku_scan")
        assert lauf.status == "warnung"
        assert "1 Projekt hat mehr als einen Ordner" in lauf.meldung


def _letzter_lauf(job: str):
    from app.modelle import JobLauf

    with lese_sitzung() as sitzung:
        return sitzung.execute(
            select(JobLauf).where(JobLauf.job == job).order_by(JobLauf.id.desc()).limit(1)
        ).scalar_one()
