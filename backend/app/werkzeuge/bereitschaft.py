"""Prüfung vor der Inbetriebnahme (PLAN §13, RUNBOOK).

Ein Befehl, der alles auf einmal prüft, was zwischen „installiert" und „läuft produktiv"
steht. Bisher lag das verstreut: die Konfiguration prüft
:func:`app.konfiguration.pruefe_betriebsbereit`, die Datenbank ``ip3-leitstand pruefen``, den
Rest wusste nur die RUNBOOK-Liste – und eine Liste im Fließtext hakt niemand zuverlässig ab.

**Drei Arten von Befund**, und der Unterschied ist der Zweck dieses Moduls:

* ``blockiert`` – so startet der Leitstand nicht oder nimmt Schaden. Das sind wenige Dinge:
  Konfiguration unlesbar, Schemastand veraltet, Datenbank in einem Sync-Ordner.
* ``hinweis`` – der Leitstand läuft, aber eine bestimmte Funktion kann nicht arbeiten. Jeder
  Hinweis sagt, **wofür** die fehlende Angabe gebraucht wird; „fehlt" allein bewegt niemanden.
* ``ok`` – erledigt. Wird mit ausgegeben, weil eine Liste, auf der nur Probleme stehen, den
  Fortschritt verschweigt.

Geprüft wird **lesend**. Der Befehl legt keinen Ordner an und ändert keine Einstellung; er
stellt fest. Was zu tun ist, steht im Befund und wird von Hand getan – ein Werkzeug, das
ungefragt Ordner im OneDrive anlegt, wäre schlimmer als eines, das sie vermisst.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select

from app.konfiguration import (
    Einstellungen,
    KonfigurationsFehler,
    _pfad_wirkt_synchronisiert,
    pruefe_betriebsbereit,
)

LAGEN = ("ok", "hinweis", "blockiert")


@dataclass
class Befund:
    """Ein geprüfter Punkt."""

    bereich: str
    titel: str
    lage: str = "ok"
    text: str = ""
    naechster_schritt: str = ""

    def __post_init__(self) -> None:
        if self.lage not in LAGEN:
            raise ValueError(f"Unbekannte Lage: {self.lage}")


@dataclass
class Bericht:
    befunde: list[Befund] = field(default_factory=list)

    def melden(self, *befunde: Befund) -> None:
        self.befunde.extend(befunde)

    @property
    def blockiert(self) -> list[Befund]:
        return [b for b in self.befunde if b.lage == "blockiert"]

    @property
    def hinweise(self) -> list[Befund]:
        return [b for b in self.befunde if b.lage == "hinweis"]

    @property
    def erledigt(self) -> list[Befund]:
        return [b for b in self.befunde if b.lage == "ok"]

    @property
    def bereit(self) -> bool:
        """Ob der Leitstand starten kann. **Nicht**, ob alles eingerichtet ist."""
        return not self.blockiert

    def bereiche(self) -> list[str]:
        """Bereiche in der Reihenfolge ihres ersten Auftretens."""
        gesehen: list[str] = []
        for befund in self.befunde:
            if befund.bereich not in gesehen:
                gesehen.append(befund.bereich)
        return gesehen


# ------------------------------------------------------------------------------------------
# Ordner
# ------------------------------------------------------------------------------------------


def _schreibbar(ordner: Path) -> bool:
    """Ob sich in den Ordner schreiben lässt – durch einen echten Versuch.

    ``os.access`` lügt auf Windows-Freigaben und bei ACLs regelmäßig: es prüft die
    Berechtigungsbits, nicht was das Dateisystem tatsächlich zulässt. Eine Testdatei anzulegen
    und sofort zu löschen ist der einzige verlässliche Weg – und genau dieser Fall (Dienstkonto
    darf nicht ins OneDrive schreiben) ist der, den die Inbetriebnahme finden soll.
    """
    try:
        with tempfile.NamedTemporaryFile(dir=ordner, prefix=".ip3-schreibtest-"):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class Ordnerpflicht:
    """Ein konfigurierter Ordner und wofür er gebraucht wird."""

    schluessel: str
    bezeichnung: str
    zweck: str
    schreibend: bool


ORDNER: tuple[Ordnerpflicht, ...] = (
    Ordnerpflicht(
        "backup",
        "Sicherungsordner",
        "Ohne ihn läuft keine nächtliche Sicherung – und ein Restore ist nur so gut wie die "
        "letzte Kopie.",
        schreibend=True,
    ),
    Ordnerpflicht(
        "rechnungen",
        "Rechnungsordner",
        "Belege lassen sich sonst festschreiben, aber nicht ablegen: das PDF fehlt und muss "
        "nachgeholt werden.",
        schreibend=True,
    ),
    Ordnerpflicht(
        "datev",
        "DATEV-Ordner",
        "Ohne ihn bleiben die Ist-Kosten der Projekte leer, und jede Marge sieht zu gut aus.",
        schreibend=False,
    ),
    Ordnerpflicht(
        "kalkulation",
        "Kalkulationsordner",
        "Ohne ihn gibt es keine Sollwerte und damit keinen Soll-Ist-Vergleich.",
        schreibend=False,
    ),
    Ordnerpflicht(
        "projekte",
        "Projektordner",
        "Ohne ihn läuft der Doku-Vollständigkeitsscan nicht; fehlende Unterlagen fallen dann "
        "erst bei der Schlussrechnung auf.",
        schreibend=False,
    ),
    Ordnerpflicht(
        "einspeisung",
        "Abrechnungsordner",
        "Nur für das Vergütungs-Controlling der eigenen Anlagen. Ohne ihn werden die "
        "Abrechnungen von Hand erfasst, was ebenfalls vollständig geht.",
        schreibend=False,
    ),
)


def ordner_pruefen(werte: Einstellungen) -> list[Befund]:
    """Jeden konfigurierten Ordner auf Erreichbarkeit und – wo nötig – Schreibrecht prüfen."""
    befunde: list[Befund] = []
    for pflicht in ORDNER:
        pfad = getattr(werte.pfade, pflicht.schluessel)
        if pfad is None:
            befunde.append(
                Befund(
                    "Ordner",
                    pflicht.bezeichnung,
                    "hinweis",
                    f"Nicht gesetzt. {pflicht.zweck}",
                    f"In der config.toml unter [pfade] '{pflicht.schluessel}' eintragen.",
                )
            )
            continue

        ordner = Path(pfad)
        if not ordner.is_dir():
            befunde.append(
                Befund(
                    "Ordner",
                    pflicht.bezeichnung,
                    "hinweis",
                    f"{ordner} ist nicht erreichbar. {pflicht.zweck}",
                    "Prüfen, ob der Ordner angelegt ist und OneDrive ihn synchronisiert hat. "
                    "Der Leitstand legt ihn bewusst nicht selbst an.",
                )
            )
            continue

        if pflicht.schreibend and not _schreibbar(ordner):
            befunde.append(
                Befund(
                    "Ordner",
                    pflicht.bezeichnung,
                    "hinweis",
                    f"{ordner} ist da, aber das Dienstkonto darf nicht hineinschreiben. "
                    f"{pflicht.zweck}",
                    "Schreibrecht des Kontos prüfen, unter dem der Dienst läuft.",
                )
            )
            continue

        wie = "beschreibbar" if pflicht.schreibend else "lesbar"
        befunde.append(Befund("Ordner", pflicht.bezeichnung, "ok", f"{ordner} ({wie})"))
    return befunde


# ------------------------------------------------------------------------------------------
# Datenbank
# ------------------------------------------------------------------------------------------


def datenbank_pruefen(werte: Einstellungen) -> list[Befund]:
    """Ort, Vorhandensein und Schemastand der Datenbank."""
    from app.werkzeuge.schema import kopf_revision, schema_revision

    befunde: list[Befund] = []
    pfad = Path(werte.pfade.datenbank)

    verdaechtig = _pfad_wirkt_synchronisiert(pfad)
    if verdaechtig:
        befunde.append(
            Befund(
                "Datenbank",
                "Ablageort",
                "blockiert",
                f"Die Datenbank liegt unter {pfad}; der Ordner '{verdaechtig}' deutet auf eine "
                "Ordnersynchronisation hin. SQLite wird darin beschädigt.",
                "In der config.toml unter [pfade] die Datenbank auf ein lokales Verzeichnis "
                "legen. Die Sicherungen dürfen weiter ins OneDrive.",
            )
        )
    elif str(pfad).startswith("\\\\"):
        befunde.append(
            Befund(
                "Datenbank",
                "Ablageort",
                "blockiert",
                f"Die Datenbank liegt auf einem Netzlaufwerk ({pfad}). SQLite-Sperren arbeiten "
                "über SMB nicht zuverlässig.",
                "Die Datenbank auf eine lokale Festplatte des Hosts legen.",
            )
        )
    else:
        befunde.append(Befund("Datenbank", "Ablageort", "ok", f"{pfad} (lokal)"))

    if not pfad.exists():
        befunde.append(
            Befund(
                "Datenbank",
                "Schemastand",
                "blockiert",
                "Die Datenbankdatei gibt es noch nicht.",
                "'ip3-leitstand schema' ausführen, danach 'ip3-leitstand seed'.",
            )
        )
        return befunde

    stand = schema_revision(pfad)
    erwartet = kopf_revision()
    if stand == erwartet:
        befunde.append(Befund("Datenbank", "Schemastand", "ok", f"Revision {stand}"))
    else:
        befunde.append(
            Befund(
                "Datenbank",
                "Schemastand",
                "blockiert",
                f"Die Datenbank steht auf {stand or 'unbekannt'}, das Programm erwartet "
                f"{erwartet}.",
                "'ip3-leitstand schema' ausführen. Vorher eine Sicherung ziehen.",
            )
        )
    return befunde


# ------------------------------------------------------------------------------------------
# Rechnungs-PDF
# ------------------------------------------------------------------------------------------


def pdf_pruefen() -> Befund:
    """Ob WeasyPrint samt Grafikbibliotheken lädt.

    Der bekannteste Stolperstein auf einem Windows-Host: ohne GTK/Pango wirft der erste Klick
    auf „PDF-Vorschau" einen unerwarteten Fehler, und zwar erst dann – also genau in dem
    Moment, in dem eine Rechnung rausgehen soll.
    """
    try:
        import weasyprint  # noqa: F401
    except Exception as fehler:  # ImportError, aber auch OSError beim Nachladen der Bibliothek
        return Befund(
            "Rechnungs-PDF",
            "WeasyPrint",
            "hinweis",
            f"Die PDF-Erzeugung lädt nicht: {fehler}",
            "Auf Windows das GTK-Runtime-Paket installieren, auf dem Mac 'brew install pango'. "
            "Belege lassen sich bis dahin anlegen und festschreiben, aber nicht ausgeben.",
        )
    return Befund("Rechnungs-PDF", "WeasyPrint", "ok", "Grafikbibliotheken geladen")


# ------------------------------------------------------------------------------------------
# Daten
# ------------------------------------------------------------------------------------------


def daten_pruefen(sitzung) -> list[Befund]:
    """Was in der Datenbank steht und die erste echte Rechnung verhindern würde.

    Diese Prüfungen sind der Grund für den ganzen Befehl: die Konfiguration kann vollständig
    sein und die erste Rechnung trotzdem scheitern, weil 484 migrierte Kunden keine Anschrift
    haben. Das steht in keiner Einstellung.
    """
    from app.modelle import Kunde, Projekt, User

    befunde: list[Befund] = []

    kunden = sitzung.scalar(select(func.count()).select_from(Kunde)) or 0
    if kunden == 0:
        befunde.append(
            Befund(
                "Daten",
                "Kundenstamm",
                "hinweis",
                "Es ist kein Kunde erfasst.",
                "Bestandsdaten übernehmen (RUNBOOK §9) oder Kunden von Hand anlegen.",
            )
        )
    else:
        ohne_anschrift = (
            sitzung.scalar(
                select(func.count())
                .select_from(Kunde)
                .where((Kunde.strasse.is_(None)) | (Kunde.plz.is_(None)))
            )
            or 0
        )
        if ohne_anschrift:
            befunde.append(
                Befund(
                    "Daten",
                    "Anschriften",
                    "hinweis",
                    f"{ohne_anschrift} von {kunden} Kunden haben keine vollständige Anschrift. "
                    "§ 14 UStG verlangt sie; der Leitstand weist einen solchen Beleg ab.",
                    "Mindestens für die Kunden nachtragen, die als Nächstes eine Rechnung "
                    "bekommen. Die Kundenmaske zeigt, was fehlt.",
                )
            )
        else:
            befunde.append(
                Befund("Daten", "Anschriften", "ok", f"alle {kunden} Kunden vollständig")
            )

        nur_privat = (
            sitzung.scalar(select(func.count()).select_from(Kunde).where(Kunde.typ == "b2c")) or 0
        )
        if kunden and nur_privat == kunden:
            befunde.append(
                Befund(
                    "Daten",
                    "Privat oder Gewerbe",
                    "hinweis",
                    f"Alle {kunden} Kunden stehen auf „Privatkunde“. Die Quelldateien sagten "
                    "nichts dazu, die Migration setzt deshalb b2c.",
                    "Gewerbekunden umstellen. Davon hängt ab, ob eine E-Rechnung entsteht – "
                    "ab 1.1.2027 Pflicht für inländische B2B-Umsätze.",
                )
            )

    projekte = sitzung.scalar(select(func.count()).select_from(Projekt)) or 0
    befunde.append(
        Befund(
            "Daten",
            "Projekte",
            "ok" if projekte else "hinweis",
            f"{projekte} Projekte erfasst" if projekte else "Es ist kein Projekt erfasst.",
            "" if projekte else "Bestandsdaten übernehmen (RUNBOOK §9).",
        )
    )

    ohne_pl = (
        sitzung.scalar(
            select(func.count()).select_from(Projekt).where(Projekt.pl_user_id.is_(None))
        )
        or 0
    )
    if projekte and ohne_pl == projekte:
        befunde.append(
            Befund(
                "Daten",
                "Projektleiter",
                "hinweis",
                f"Bei allen {projekte} Projekten fehlt die Zuordnung zu einem Nutzerkonto.",
                "Projektleiter zuordnen – sonst greift der Sichtbarkeits-Scope „eigene“ nicht "
                "und diese Nutzer sehen nichts.",
            )
        )

    nutzer = sitzung.scalar(select(func.count()).select_from(User).where(User.aktiv.is_(True))) or 0
    if nutzer <= 1:
        befunde.append(
            Befund(
                "Daten",
                "Nutzerkonten",
                "hinweis",
                "Es gibt nur ein aktives Konto." if nutzer == 1 else "Es gibt kein aktives Konto.",
                "Konten für Buchhaltung und Team anlegen: 'ip3-leitstand nutzer-anlegen'.",
            )
        )
    else:
        befunde.append(Befund("Daten", "Nutzerkonten", "ok", f"{nutzer} aktive Konten"))

    return befunde


# ------------------------------------------------------------------------------------------
# Verrechnungssätze
# ------------------------------------------------------------------------------------------


def saetze_pruefen(werte: Einstellungen) -> Befund:
    """Ob die Verrechnungssätze noch unverändert auf der Vorbelegung stehen.

    Verglichen wird gegen die Vorgabewerte der Einstellungsklasse selbst, nicht gegen eine
    zweite Liste hier: eine Kopie würde beim ersten Ändern der Vorbelegung stillschweigend
    falsch und meldete dann entweder immer oder nie.
    """
    from app.konfiguration import StundensaetzeEinstellungen

    vorbelegung = StundensaetzeEinstellungen().saetze
    if dict(werte.stundensaetze.saetze) == dict(vorbelegung):
        return Befund(
            "Nachkalkulation",
            "Verrechnungssätze",
            "hinweis",
            "Die vier Sätze stehen unverändert auf der Vorbelegung aus der Beispieldatei.",
            "Mit der Buchhaltung bestätigen und in der config.toml unter "
            "[stundensaetze.saetze] eintragen. Bis dahin ist jede Eigenleistung geschätzt.",
        )
    return Befund("Nachkalkulation", "Verrechnungssätze", "ok", "eigene Sätze hinterlegt")


# ------------------------------------------------------------------------------------------
# Gesamtlauf
# ------------------------------------------------------------------------------------------


def bericht_erstellen(werte: Einstellungen, sitzung=None) -> Bericht:
    """Alle Prüfungen ausführen.

    ``sitzung`` darf fehlen: dann bleiben die Datenprüfungen aus, und der Rest läuft trotzdem –
    genau der Fall, in dem die Datenbank noch gar nicht angelegt ist.
    """
    bericht = Bericht()

    # ``pruefe_betriebsbereit`` wird nur für die *harten* Fälle aufgerufen: fehlender
    # Sitzungsschlüssel, cookie_secure aus, keine erlaubte Herkunft. Die weichen Hinweise
    # daraus bleiben bewusst ungenutzt – sie melden fehlende Pfade, und das tut der
    # Ordnerabschnitt weiter unten genauer, weil er zusätzlich Erreichbarkeit und Schreibrecht
    # prüft. Beides zu melden hieße, dasselbe Problem zweimal auf die Liste zu setzen.
    try:
        pruefe_betriebsbereit(werte)
    except KonfigurationsFehler as fehler:
        meldung, _, schritt = str(fehler).partition("Nächster Schritt:")
        bericht.melden(
            Befund(
                "Konfiguration",
                "Produktionsbetrieb",
                "blockiert",
                meldung.strip(),
                schritt.strip(),
            )
        )

    fehlende_angaben = werte.firma.unvollstaendige_pflichtangaben()
    bericht.melden(
        Befund(
            "Konfiguration",
            "Firmenstammdaten",
            "hinweis" if fehlende_angaben else "ok",
            f"Es fehlen: {', '.join(fehlende_angaben)}."
            if fehlende_angaben
            else "vollständig für den Rechnungskopf",
            "In der config.toml unter [firma] ergänzen. § 14 UStG verlangt sie; ohne sie "
            "weist die Festschreibung jeden Beleg ab."
            if fehlende_angaben
            else "",
        )
    )

    timetac_fehlt = werte.timetac.aktiv and not (werte.timetac_client_id and werte.timetac_konto)
    bericht.melden(
        Befund(
            "Konfiguration",
            "TimeTac-Zugang",
            "hinweis" if timetac_fehlt else "ok",
            "Zugangsdaten fehlen. Ohne sie fehlt die Eigenleistung im Projekt-Ist, und jede "
            "Marge sieht zu gut aus."
            if timetac_fehlt
            else ("Zugangsdaten hinterlegt" if werte.timetac.aktiv else "abgeschaltet"),
            "IP3_TIMETAC_CLIENT_ID, IP3_TIMETAC_CLIENT_SECRET und IP3_TIMETAC_KONTO in die "
            ".env auf dem Host eintragen – nie in die config.toml. Prüfen mit "
            "'ip3-leitstand timetac-test'."
            if timetac_fehlt
            else "",
        )
    )

    umgebung = werte.app.umgebung
    bericht.melden(
        Befund(
            "Konfiguration",
            "Umgebung",
            "ok" if umgebung == "produktion" else "hinweis",
            f"Umgebung: {umgebung}",
            ""
            if umgebung == "produktion"
            else 'Für den Echtbetrieb in der config.toml unter [app] umgebung = "produktion" '
            "setzen. Erst dann greifen die Sicherheitsprüfungen für Cookies und Herkunft.",
        )
    )

    bericht.melden(*datenbank_pruefen(werte))
    bericht.melden(*ordner_pruefen(werte))
    bericht.melden(pdf_pruefen())
    bericht.melden(saetze_pruefen(werte))

    if sitzung is not None:
        bericht.melden(*daten_pruefen(sitzung))

    return bericht
