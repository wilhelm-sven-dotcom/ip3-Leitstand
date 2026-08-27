"""Grunddaten und Demodaten einrichten (PLAN §7, Phase 0).

Zwei getrennte Aufgaben:

* :func:`grunddaten` legt an, was der Leitstand zum Arbeiten braucht: die Firma, die drei Rollen
  aus PLAN §4 mit ihren Berechtigungen und ein Administratorkonto. Der Aufruf ist wiederholbar –
  ein zweiter Lauf ändert nichts, ergänzt aber neue Berechtigungen aus dem Katalog. Das ist
  wichtig, weil jede Phase neue Schlüssel mitbringt.

* :func:`demodaten` legt erfundene Projekte, Kunden und Belege an, damit die Oberfläche in der
  Entwicklung und bei Schulungen nicht leer ist. In der Umgebung ``produktion`` verweigert die
  Funktion den Dienst, und sie bricht ab, wenn schon echte Daten vorhanden sind – Demodaten
  zwischen echten Projekten wären in einer Auswertung nicht mehr auseinanderzuhalten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dienste import nummernkreise
from app.fehler import FachFehler
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
from app.protokoll import logger
from app.sicherheit import passwort as pw
from app.sicherheit.katalog import KATALOG, SEED_ROLLEN, beschreibung
from app.zeit import heute_ortszeit

log = logger(__name__)


@dataclass
class SeedErgebnis:
    firma_angelegt: bool = False
    rollen_angelegt: int = 0
    berechtigungen_angelegt: int = 0
    rollen_rechte_ergaenzt: int = 0
    admin_angelegt: bool = False
    admin_email: str = ""
    admin_passwort: str = ""
    demodaten: dict[str, int] | None = None

    def als_text(self) -> str:
        zeilen = []
        if self.firma_angelegt:
            zeilen.append("Firma ip³ angelegt")
        if self.rollen_angelegt:
            zeilen.append(f"{self.rollen_angelegt} Rollen angelegt")
        if self.berechtigungen_angelegt:
            zeilen.append(f"{self.berechtigungen_angelegt} Berechtigungen angelegt")
        if self.rollen_rechte_ergaenzt:
            zeilen.append(f"{self.rollen_rechte_ergaenzt} Rollenrechte ergänzt")
        if self.admin_angelegt:
            zeilen.append(f"Administrator {self.admin_email} angelegt")
        if self.demodaten:
            teile = ", ".join(f"{anzahl} {name}" for name, anzahl in self.demodaten.items())
            zeilen.append(f"Demodaten: {teile}")
        return "\n".join(zeilen) if zeilen else "Nichts zu tun – alles war bereits vorhanden."


class SeedFehler(FachFehler):
    code = "seed_nicht_moeglich"
    status_code = 409


def grunddaten(
    sitzung: Session,
    werte: Einstellungen,
    admin_email: str = "s.wilhelm@ip3-energie.de",
    admin_name: str = "Sven Wilhelm",
    admin_passwort: str | None = None,
) -> SeedErgebnis:
    """Firma, Berechtigungen, Rollen, Nummernkreise und Administrator einrichten.

    Wiederholbar: vorhandene Einträge bleiben unberührt, fehlende werden ergänzt.
    """
    ergebnis = SeedErgebnis()

    firma = sitzung.scalar(select(Firma).where(Firma.kuerzel == werte.firma.kuerzel))
    if firma is None:
        firma = Firma(
            kuerzel=werte.firma.kuerzel,
            firmierung=werte.firma.firmierung,
            anschrift=_anschrift(werte),
            ust_id=werte.firma.ust_id or None,
            st_nr=werte.firma.st_nr or None,
            hrb=werte.firma.hrb or None,
            bank={
                "institut": werte.firma.bank.institut,
                "iban": werte.firma.bank.iban,
                "bic": werte.firma.bank.bic,
            },
            aktiv=True,
            created_by="seed",
        )
        sitzung.add(firma)
        sitzung.flush()
        ergebnis.firma_angelegt = True

    # Berechtigungen aus dem Katalog. Jede Phase bringt neue mit, deshalb wird hier ergänzt und
    # nicht nur beim ersten Lauf angelegt.
    vorhandene = {(b.schluessel, b.scope): b for b in sitzung.scalars(select(Berechtigung)).all()}
    for eintrag in KATALOG:
        if (eintrag.schluessel, None) not in vorhandene:
            neu = Berechtigung(
                schluessel=eintrag.schluessel,
                scope=None,
                beschreibung=eintrag.beschreibung,
                created_by="seed",
            )
            sitzung.add(neu)
            sitzung.flush()
            vorhandene[(eintrag.schluessel, None)] = neu
            ergebnis.berechtigungen_angelegt += 1

    # Rollen mit ihren Rechten.
    for definition in SEED_ROLLEN:
        rolle = sitzung.scalar(select(Rolle).where(Rolle.name == definition.name))
        if rolle is None:
            rolle = Rolle(
                name=definition.name, beschreibung=definition.beschreibung, created_by="seed"
            )
            sitzung.add(rolle)
            sitzung.flush()
            ergebnis.rollen_angelegt += 1

        bereits_zugeordnet = {(b.schluessel, b.scope) for b in rolle.berechtigungen}
        for schluessel, scope in definition.rechte:
            if (schluessel, scope) in bereits_zugeordnet:
                continue
            berechtigung = vorhandene.get((schluessel, scope))
            if berechtigung is None:
                # Ein Recht mit Scope, das der Katalog nicht als eigenen Eintrag kennt.
                berechtigung = Berechtigung(
                    schluessel=schluessel,
                    scope=scope,
                    beschreibung=beschreibung(schluessel),
                    created_by="seed",
                )
                sitzung.add(berechtigung)
                sitzung.flush()
                vorhandene[(schluessel, scope)] = berechtigung
                ergebnis.berechtigungen_angelegt += 1
            rolle.berechtigungen.append(berechtigung)
            ergebnis.rollen_rechte_ergaenzt += 1

    # Nummernkreise für das laufende Jahr anstoßen, damit sie in der Datenbank sichtbar sind.
    for kreis in ("RE", "SR", "AB", "KD", "PR", "SA"):
        nummernkreise.zaehler_mindestens(
            sitzung,
            firma.id,
            kreis,
            nummernkreise.STARTWERTE.get(kreis, 0),
        )

    # Administratorkonto.
    if sitzung.scalar(select(func.count()).select_from(User)) == 0:
        klartext = admin_passwort or pw.zufallspasswort()
        admin_rolle = sitzung.scalar(select(Rolle).where(Rolle.name == "admin"))
        admin = User(
            name=admin_name,
            email=admin_email,
            pw_hash=pw.hashen(klartext),
            aktiv=True,
            # Das Passwort ist über die Kommandozeile gelaufen und stand kurz auf dem Bildschirm:
            # es muss bei der ersten Anmeldung gewechselt werden.
            muss_passwort_wechseln=True,
            created_by="seed",
        )
        if admin_rolle is not None:
            admin.rollen.append(admin_rolle)
        sitzung.add(admin)
        sitzung.flush()
        ergebnis.admin_angelegt = True
        ergebnis.admin_email = admin_email
        ergebnis.admin_passwort = klartext

    return ergebnis


def _anschrift(werte: Einstellungen) -> str | None:
    teile = [werte.firma.strasse, f"{werte.firma.plz} {werte.firma.ort}".strip()]
    zusammen = ", ".join(teil for teil in teile if teil and not teil.startswith("<"))
    return zusammen or None


# --------------------------------------------------------------------------------------------
# Demodaten
# --------------------------------------------------------------------------------------------

# Erfundene Projekte, die die typischen Fälle abdecken: Gewerbe mit 19 %, Wohngebäude mit 0 %
# nach § 12 Abs. 3 UStG, ein Speicherprojekt und ein abgeschlossenes Projekt für das
# Anlagenregister. Namen und Orte sind erfunden.
DEMO_KUNDEN = [
    ("Maschinenbau Köstler GmbH", "Weiden", "b2b", "DE811234567"),
    ("Autohaus Winkler GmbH & Co. KG", "Neustadt", "b2b", "DE811234568"),
    ("Familie Hausner", "Püllersreuth", "b2c", None),
    ("Solarpark Pirk Süd GmbH", "Pirk", "b2b", "DE811234569"),
    ("Familie Berger", "Theisseil", "b2c", None),
]


def demodaten(sitzung: Session, werte: Einstellungen) -> dict[str, int]:
    """Erfundene Projekte und Zahlungspläne anlegen.

    Nur für Entwicklung, Test und Schulung. In der Produktion und neben echten Daten verweigert.
    """
    if werte.ist_produktion:
        raise SeedFehler(
            "Demodaten lassen sich in der Umgebung 'produktion' nicht anlegen.",
            'Wenn das ein Testsystem ist: in config.toml unter [app] umgebung = "test" setzen.',
        )

    vorhandene_projekte = sitzung.scalar(select(func.count()).select_from(Projekt)) or 0
    if vorhandene_projekte:
        raise SeedFehler(
            f"In der Datenbank stehen bereits {vorhandene_projekte} Projekte. "
            "Demodaten würden sich nicht mehr von echten Daten unterscheiden lassen.",
            "Demodaten nur in einer leeren Datenbank anlegen. Für einen frischen Stand die "
            "Datenbankdatei beiseitelegen und 'ip3-leitstand schema' neu ausführen.",
        )

    firma = sitzung.scalar(select(Firma).where(Firma.kuerzel == werte.firma.kuerzel))
    if firma is None:
        raise SeedFehler(
            "Die Firma ist noch nicht angelegt.",
            "Zuerst 'ip3-leitstand seed' ohne --demodaten ausführen.",
        )

    zaehler = {"Kunden": 0, "Projekte": 0, "Zahlungsplanpositionen": 0, "Meilensteine": 0}
    heute = heute_ortszeit()

    kunden: list[Kunde] = []
    for name, ort, typ, ust_id in DEMO_KUNDEN:
        kunde = Kunde(
            kunden_nr=nummernkreise.naechster_wert(sitzung, firma.id, "KD"),
            name=name,
            ort=ort,
            plz="92637",
            strasse="Beispielweg 1",
            typ=typ,
            ust_id=ust_id,
            status="aktiv",
            created_by="seed",
        )
        sitzung.add(kunde)
        kunden.append(kunde)
        zaehler["Kunden"] += 1
    sitzung.flush()

    # (Kunde, kWp, Speicher, AB-Wert in Cent, ust_kz, Status, Projektleiter, Zahlungsplan)
    vorlagen = [
        (
            kunden[0],
            "Dachanlage Halle 1",
            285.5,
            None,
            36750000,
            "19",
            "in_bau",
            "Michael Bäumler",
            [
                ("1. Abschlag PV", "pv", "abschlag", 9187500, 0, "lieferung"),
                ("2. Abschlag PV", "pv", "abschlag", 14700000, 1, "montage"),
                ("Schlussrechnung PV", "pv", "schluss", 12862500, 2, "abnahme"),
            ],
        ),
        (
            kunden[1],
            "Dachanlage Halle 2 mit Speicher",
            145.2,
            120.0,
            22400000,
            "19",
            "in_bau",
            "Sven Wilhelm",
            [
                ("1. Abschlag PV", "pv", "abschlag", 6720000, -1, None),
                ("1. Abschlag Speicher", "speicher", "abschlag", 4480000, 0, "lieferung"),
                ("Schlussrechnung", "pv", "schluss", 11200000, 2, "abnahme"),
            ],
        ),
        (
            kunden[2],
            "Aufdachanlage Wohnhaus",
            18.7,
            15.0,
            3890000,
            "0",  # 0 % nach § 12 Abs. 3 UStG für Anlagen auf Wohngebäuden (PLAN §6.2)
            "beauftragt",
            "Sven Wilhelm",
            [("Rechnung 100 %", "pv", "einmal", 3890000, 1, "abnahme")],
        ),
        (
            kunden[3],
            "Freiflächenanlage Pirk Süd",
            5695.0,
            None,
            486000000,
            "19",
            "in_bau",
            "Michael Bäumler",
            [
                ("1. Abschlag Freifläche", "pv", "abschlag", 145800000, -2, None),
                ("2. Abschlag Freifläche", "pv", "abschlag", 194400000, 0, "lieferung"),
                ("Schlussrechnung Freifläche", "pv", "schluss", 145800000, 3, "abnahme"),
            ],
        ),
        (
            kunden[4],
            "Aufdachanlage mit Wallbox",
            12.4,
            10.0,
            2650000,
            "0",
            "abgeschlossen",
            "Sven Wilhelm",
            [("Rechnung 100 %", "pv", "einmal", 2650000, -3, None)],
        ),
    ]

    for kunde, standort, kwp, speicher, ab_wert, ust_kz, status, pl, plan in vorlagen:
        projekt = Projekt(
            projekt_nr=nummernkreise.naechste_projektnummer(sitzung, firma.id),
            firma_id=firma.id,
            typ="projekt",
            kunde_id=kunde.id,
            standort=f"{standort}, {kunde.ort}",
            pv_kwp=kwp,
            speicher_kwh=speicher,
            auftrag_vom=heute - timedelta(days=120),
            ab_wert_netto=ab_wert,
            pl_name=pl,
            ust_kz=ust_kz,
            status=status,
            created_by="seed",
        )
        sitzung.add(projekt)
        sitzung.flush()
        zaehler["Projekte"] += 1

        for pos_nr, (bezeichnung, gewerk, art, betrag, monatsversatz, ausloeser) in enumerate(
            plan, start=1
        ):
            plan_monat = _monat_mit_versatz(heute, monatsversatz)
            sitzung.add(
                Zahlungsplanposition(
                    projekt_id=projekt.id,
                    pos_nr=pos_nr,
                    bezeichnung=bezeichnung,
                    gewerk=gewerk,
                    art=art,
                    betrag_netto=betrag,
                    plan_monat=plan_monat,
                    trigger_status=ausloeser,
                    created_by="seed",
                )
            )
            zaehler["Zahlungsplanpositionen"] += 1

        # Meilensteine: was erledigt ist, hängt am Projektstatus.
        erledigte = ["uebergabetermin", "freigabe_planung", "plan_erstellt"]
        if status in ("in_bau", "abgeschlossen"):
            erledigte += ["anmeldung_nb", "lieferung"]
        if status == "abgeschlossen":
            erledigte += ["montage", "fertigmeldung", "zaehler", "abnahme", "inbetriebnahme"]
        for versatz, typ in enumerate(erledigte):
            sitzung.add(
                Meilenstein(
                    projekt_id=projekt.id,
                    typ=typ,
                    erledigt_am=heute - timedelta(days=100 - versatz * 10),
                    created_by="seed",
                )
            )
            zaehler["Meilensteine"] += 1

    sitzung.flush()
    return zaehler


def _monat_mit_versatz(bezug: date, versatz: int) -> str:
    """Monat als ``'JJJJ-MM'``, um ``versatz`` Monate verschoben."""
    monat_gesamt = bezug.year * 12 + (bezug.month - 1) + versatz
    return f"{monat_gesamt // 12:04d}-{monat_gesamt % 12 + 1:02d}"
