"""Konfiguration des Leitstands aus config.toml und .env.

Grundsatz aus PLAN §2: keine Pfade und keine Zugangsdaten im Code. Die fachlichen Werte stehen in
der `config.toml`, Geheimnisse in der `.env`. Einzelne Werte lassen sich über Umgebungsvariablen
nach dem Muster ``IP3_ABSCHNITT__SCHLUESSEL`` überschreiben – das ist der bequemste Weg, die
Testinstanz auf einen anderen Port zu legen.

Fehlerhafte Konfiguration führt zu einer Meldung in Klartext mit dem nächsten Schritt, nicht zu
einem Stacktrace (PLAN §14).
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Ordnernamen, die auf eine Ordnersynchronisation hindeuten. Eine SQLite-Datei in einem solchen
# Ordner wird zuverlässig irgendwann beschädigt (PLAN §2), deshalb verweigert der Leitstand dort
# den Start – lieber ein klarer Abbruch als eine unbemerkt zerstörte Datenbank.
SYNC_ORDNER_KENNZEICHEN = (
    "onedrive",
    "dropbox",
    "google drive",
    "googledrive",
    "nextcloud",
    "owncloud",
    "sharepoint",
    "icloud",
    # Der macOS-Pfad von iCloud Drive heißt nicht 'iCloud': mit synchronisiertem Schreibtisch
    # und Dokumentenordner liegen beide unter ~/Library/Mobile Documents/com~apple~CloudDocs,
    # und ~/Documents ist nur noch eine Verknüpfung dorthin. Weil der Pfad vor der Prüfung
    # aufgelöst wird, greift der Riegel damit auch für einen Mac.
    "mobile documents",
    "com~apple~clouddocs",
    "magentacloud",
    "sync",
)


class KonfigurationsFehler(RuntimeError):
    """Konfiguration ist unbrauchbar. Die Meldung ist für Menschen gedacht."""


class AppEinstellungen(BaseModel):
    umgebung: str = "entwicklung"
    adresse: str = "127.0.0.1"
    port: int = 8000
    erlaubte_herkunft: list[str] = Field(default_factory=list)

    @field_validator("umgebung")
    @classmethod
    def umgebung_pruefen(cls, wert: str) -> str:
        erlaubt = {"entwicklung", "test", "produktion"}
        if wert not in erlaubt:
            raise ValueError(
                f"'{wert}' ist keine gültige Umgebung. Erlaubt sind: {', '.join(sorted(erlaubt))}."
            )
        return wert


class PfadEinstellungen(BaseModel):
    datenbank: Path = Path("daten/leitstand.sqlite3")
    logs: Path = Path("logs")
    backup: Path | None = None
    rechnungen: Path | None = None
    datev: Path | None = None
    kalkulation: Path | None = None
    # Ordner mit den Excel-Bestandsdateien der Einmal-Migration (PLAN §9). Wird nur gelesen und
    # darf nach der Übernahme leer bleiben.
    migration: Path | None = None
    frontend: Path | None = None
    # Corporate-Design-Assets (Schriften, Logos) für das Rechnungs-PDF. Leer heißt: der Ordner
    # `assets/cd` neben der Anwendung. Nur zu setzen, wenn die Assets im Betrieb woanders liegen.
    cd_assets: Path | None = None

    @field_validator(
        "backup",
        "rechnungen",
        "datev",
        "kalkulation",
        "migration",
        "frontend",
        "cd_assets",
        mode="before",
    )
    @classmethod
    def leer_als_none(cls, wert: Any) -> Any:
        # Ein leerer Eintrag in der TOML-Datei bedeutet „noch nicht festgelegt", nicht „Pfad ''".
        if isinstance(wert, str) and not wert.strip():
            return None
        return wert


class BankEinstellungen(BaseModel):
    institut: str = ""
    iban: str = ""
    bic: str = ""


class FirmaEinstellungen(BaseModel):
    kuerzel: str = "ip3"
    firmierung: str = "ip³ Energietechnik GmbH"
    strasse: str = ""
    plz: str = ""
    ort: str = "Theisseil"
    ust_id: str = ""
    st_nr: str = ""
    hrb: str = ""
    geschaeftsfuehrer: str = ""
    telefon: str = ""
    telefax: str = ""
    email: str = "info@ip3-energie.de"
    web: str = "www.ip3-energie.de"
    bank: BankEinstellungen = Field(default_factory=BankEinstellungen)

    def _gesetzt(self, feld: str) -> bool:
        """Wert vorhanden und kein Platzhalter der Beispielkonfiguration (``<…>``)."""
        wert = str(getattr(self, feld, "") or "").strip()
        return bool(wert) and not wert.startswith("<")

    def unvollstaendige_pflichtangaben(self) -> list[str]:
        """Für den Rechnungskopf nach § 14 UStG nötige Angaben, die noch fehlen.

        In Phase 0 nur ein Hinweis im Systemstatus; ab Phase 3 blockiert es die Festschreibung.

        **Steuernummer oder USt-IdNr., nicht beides.** § 14 Abs. 4 Nr. 2 UStG verlangt „die dem
        leistenden Unternehmer vom Finanzamt erteilte Steuernummer **oder** die ihm vom
        Bundeszentralamt für Steuern erteilte Umsatzsteuer-Identifikationsnummer". Die bestehende
        Rechnungsvorlage führt nur die USt-IdNr., und das genügt – beides zu fordern hätte die
        Fakturierung ohne Rechtsgrund blockiert. Die Steuernummer bleibt trotzdem wünschenswert
        (docs/OFFENE-PUNKTE.md), sie ist nur keine Voraussetzung.
        """
        pflicht = {
            "strasse": "Straße und Hausnummer",
            "plz": "Postleitzahl",
            "ort": "Ort",
            "hrb": "Handelsregistereintrag",
            "geschaeftsfuehrer": "Geschäftsführer",
        }
        fehlend = [bezeichnung for feld, bezeichnung in pflicht.items() if not self._gesetzt(feld)]
        if not self._gesetzt("ust_id") and not self._gesetzt("st_nr"):
            fehlend.append("Steuernummer oder Umsatzsteuer-Identifikationsnummer")
        if not self.bank.iban.strip() or self.bank.iban.startswith("<"):
            fehlend.append("Bankverbindung")
        return fehlend


class SitzungEinstellungen(BaseModel):
    dauer_stunden: int = 12
    dauer_angemeldet_bleiben_tage: int = 30
    leerlauf_stunden: int = 8
    cookie_secure: bool = True


class AnmeldungEinstellungen(BaseModel):
    max_fehlversuche: int = 5
    sperre_minuten: int = 15
    passwort_mindestlaenge: int = 12

    @field_validator("passwort_mindestlaenge")
    @classmethod
    def mindestlaenge_pruefen(cls, wert: int) -> int:
        # bcrypt verarbeitet höchstens 72 Byte; eine Mindestlänge darüber wäre nicht erfüllbar.
        if not 8 <= wert <= 64:
            raise ValueError("passwort_mindestlaenge muss zwischen 8 und 64 Zeichen liegen.")
        return wert


class BelegtexteEinstellungen(BaseModel):
    """Textbausteine des Rechnungs-PDF (Entscheidung 17).

    Wörtlich aus der bestehenden Word-Vorlage übernommen und hier hinterlegt, damit sich der Ton
    ohne Codeänderung anpassen lässt. Die Platzhalter in Klammern werden beim Rendern ersetzt:
    ``{anrede}``, ``{objekt}``, ``{faellig_am}``, ``{zahlungsziel_tage}``.

    Die Pflichthinweise zur Umsatzsteuer stehen **nicht** hier, sondern in
    ``app/dienste/belege.py``: sie sind steuerlich verlangt und gehören nicht zu den Texten, die
    man nach Belieben umformuliert.
    """

    anrede_firma: str = "Sehr geehrte Damen und Herren,"
    anrede_privat: str = "Sehr geehrte Damen und Herren,"
    einleitung_abschlag: str = (
        "wir danken für Ihr Vertrauen in unsere für Sie erbrachten Leistungen und erlauben uns, "
        "diese vereinbarungsgemäß wie folgt zu verrechnen:"
    )
    einleitung_schluss: str = (
        "wir danken für Ihr Vertrauen und rechnen die erbrachten Leistungen nach Fertigstellung "
        "wie folgt endgültig ab:"
    )
    einleitung_service: str = (
        "wir danken für Ihr Vertrauen in unsere für Sie erbrachten Serviceleistungen und erlauben "
        "uns, diese wie folgt zu verrechnen:"
    )
    einleitung_ab: str = (
        "wir danken für Ihren Auftrag und bestätigen Ihnen den Umfang und die vereinbarten "
        "Zahlungen wie folgt:"
    )
    zahlungsbedingung: str = (
        "Wir bitten Sie, den Rechnungsbetrag ohne Abzug bis zum {faellig_am} "
        "({zahlungsziel_tage} Tage) auf das unten genannte Konto zu leisten."
    )
    grussformel: str = "Mit freundlichen Grüßen"


class FakturierungEinstellungen(BaseModel):
    zahlungsziel_tage: int = 14
    skonto_toleranz_prozent: float = 3.0
    kleinbetrag_grenze_cent: int = 25000
    texte: BelegtexteEinstellungen = Field(default_factory=BelegtexteEinstellungen)


class KostentraegerEinstellungen(BaseModel):
    """Der DATEV-Kostenträgerimport (PLAN §8).

    Die Spaltennamen stehen hier und nicht im Code: sie weichen je Kanzlei-Export ab, und der
    Leitstand soll dafür nicht geändert werden müssen. Je Feld sind mehrere Schreibweisen
    erlaubt; die erste, die im Kopf der Datei vorkommt, gewinnt.
    """

    # Kontenbereiche, aus denen Kosten übernommen werden – als 'von-bis'. Vorbelegt mit dem
    # Aufwandsbereich des SKR03 (3000 Wareneingang bis 4999 Betriebsausgaben). Erlöse (8000er)
    # bleiben damit draußen: eine Kostenträgerauswertung führt sie mit, sie gehören aber nicht
    # in die Ist-Kosten. Vor dem ersten echten Export mit der Buchhaltung abstimmen
    # (PLAN §13.4, §13.5).
    kostenkonten: list[str] = Field(default_factory=lambda: ["3000-4999"])

    spalten: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "kostentraeger": ["KOST2", "KOST2 - Kostenstelle", "Kostenträger", "Kostentraeger"],
            "konto": ["Konto", "Sachkonto", "Kontonummer"],
            "kontobezeichnung": ["Kontobezeichnung", "Kontenbeschriftung", "Konto-Bezeichnung"],
            "betrag": ["Umsatz", "Umsatz (ohne Soll/Haben-Kz)", "Betrag", "Wert"],
            "soll_haben": ["Soll/Haben-Kennzeichen", "S/H", "SH", "Soll/Haben"],
            "datum": ["Belegdatum", "Datum", "Buchungsdatum"],
            "beleg": ["Belegfeld 1", "Belegnummer", "Beleg"],
            "buchungstext": ["Buchungstext", "Text", "Bezeichnung"],
        }
    )

    @field_validator("kostenkonten")
    @classmethod
    def bereiche_pruefen(cls, werte: list[str]) -> list[str]:
        for eintrag in werte:
            von, _, bis = eintrag.partition("-")
            if not (von.strip().isdigit() and bis.strip().isdigit()):
                raise ValueError(
                    f"'{eintrag}' ist kein Kontenbereich. Erwartet wird 'von-bis', z. B. "
                    "'3000-4999'."
                )
            if int(von) > int(bis):
                raise ValueError(f"Im Kontenbereich '{eintrag}' ist die Untergrenze die größere.")
        return werte

    def bereiche(self) -> list[tuple[int, int]]:
        """Die Kontenbereiche als Zahlenpaare."""
        paare = []
        for eintrag in self.kostenkonten:
            von, _, bis = eintrag.partition("-")
            paare.append((int(von), int(bis)))
        return paare

    def ist_kostenkonto(self, konto: str) -> bool:
        """Ob ein Konto in einem der Bereiche liegt.

        Ein nicht rein numerisches Konto zählt nicht als Kostenkonto: es landet mit Begründung
        in der Vorschau, statt stillschweigend zu verschwinden.
        """
        ziffern = konto.strip()
        if not ziffern.isdigit():
            return False
        nummer = int(ziffern)
        return any(von <= nummer <= bis for von, bis in self.bereiche())


class SusaEinstellungen(BaseModel):
    """Die Summen- und Saldenliste für den Fixkostenblock (PLAN §8, Phase 5).

    Spaltennamen wie beim Kostenträgerimport aus der Konfiguration, nicht aus dem Code: sie
    weichen je Kanzlei-Export ab.
    """

    spalten: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "konto": ["Konto", "Sachkonto", "Kontonummer"],
            "bezeichnung": ["Kontobezeichnung", "Kontenbeschriftung", "Bezeichnung"],
            "saldo": ["Saldo", "Endsaldo", "Saldo kumuliert", "Betrag"],
            "soll_haben": ["Soll/Haben-Kennzeichen", "S/H", "SH", "Soll/Haben"],
            "monatssaldo": ["Monatssaldo", "Periodensaldo", "Bewegung", "Umsatz Periode"],
        }
    )

    # Eine SuSa führt die Salden oft kumuliert seit Jahresbeginn *und* je Periode. Für den
    # Monatsausweis zählt die Periode; steht sie nicht in der Datei, wird der Saldo genommen
    # und im Protokoll vermerkt, damit niemand kumulierte Werte für Monatswerte hält.
    monatssaldo_bevorzugen: bool = True


class OposEinstellungen(BaseModel):
    """Offene Posten der Debitoren (PLAN §8, §6.7)."""

    spalten: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "rechnung_nr": ["Rechnungsnummer", "Beleg", "Belegfeld 1", "Belegnummer"],
            "kunde": ["Kunde", "Debitor", "Name", "Kontobezeichnung"],
            "betrag": ["Rechnungsbetrag", "Betrag", "Umsatz", "Bruttobetrag"],
            "offen_betrag": ["Offener Betrag", "Offen", "Restbetrag", "Saldo"],
            "faellig_am": ["Fälligkeit", "Faelligkeit", "Fällig am", "Faellig am", "Nettofällig"],
            "datum": ["Belegdatum", "Rechnungsdatum", "Datum"],
        }
    )


class DatevEinstellungen(BaseModel):
    kostentraeger: KostentraegerEinstellungen = Field(default_factory=KostentraegerEinstellungen)
    susa: SusaEinstellungen = Field(default_factory=SusaEinstellungen)
    opos: OposEinstellungen = Field(default_factory=OposEinstellungen)


class StundensaetzeEinstellungen(BaseModel):
    """Verrechnungssätze für die kalkulatorische Eigenleistung (PLAN §6.6, Entscheidung 20).

    Zwei Ebenen, damit ein neuer Mitarbeiter keine neue Satzgruppe braucht: ``saetze`` führt die
    Gruppen mit ihrem Satz in Cent je Stunde, ``mitarbeiter`` ordnet Namen den Gruppen zu.

    Ein Name ohne Zuordnung rechnet mit ``standard`` und erscheint als Pflegehinweis im
    Importprotokoll. Die Stunde fällt damit nicht unter den Tisch – sie wäre sonst im Ist des
    Projekts nicht enthalten, und die Marge sähe besser aus, als sie ist.
    """

    standard: int = 6500
    saetze: dict[str, int] = Field(
        default_factory=lambda: {
            "monteur": 6500,
            "obermonteur": 7500,
            "elektriker": 7800,
            "planung": 8500,
        }
    )
    mitarbeiter: dict[str, str] = Field(default_factory=dict)

    @field_validator("saetze", "mitarbeiter")
    @classmethod
    def nicht_leer(cls, werte: dict[str, object]) -> dict[str, object]:
        for schluessel in werte:
            if not schluessel.strip():
                raise ValueError("Ein Eintrag ohne Namen ist keine Zuordnung.")
        return werte

    @model_validator(mode="after")
    def gruppen_pruefen(self) -> StundensaetzeEinstellungen:
        unbekannt = sorted({g for g in self.mitarbeiter.values() if g not in self.saetze})
        if unbekannt:
            raise ValueError(
                "In [stundensaetze.mitarbeiter] stehen Gruppen, die es in [stundensaetze.saetze] "
                f"nicht gibt: {', '.join(unbekannt)}. Entweder die Gruppe anlegen oder den "
                "Mitarbeiter einer vorhandenen zuordnen."
            )
        return self

    def satz_fuer(self, mitarbeiter: str) -> tuple[int, str | None]:
        """``(Satz in Cent, Gruppe)``. Ohne Zuordnung der Standardsatz und ``None``.

        Verglichen wird ohne Rücksicht auf Groß-/Kleinschreibung und Leerzeichen: TimeTac
        schreibt „Wilhelm, Sven", die config vielleicht „Wilhelm,Sven".
        """
        gesucht = " ".join(mitarbeiter.casefold().split())
        for name, gruppe in self.mitarbeiter.items():
            if " ".join(name.casefold().split()) == gesucht:
                return self.saetze.get(gruppe, self.standard), gruppe
        return self.standard, None


class TimeTacEinstellungen(BaseModel):
    """Schnittstelle zu TimeTac (PLAN §8).

    Zugangsdaten stehen **nicht hier**, sondern in der Umgebung: ``IP3_TIMETAC_CLIENT_ID``,
    ``IP3_TIMETAC_CLIENT_SECRET`` und ``IP3_TIMETAC_KONTO`` (Felder auf :class:`Einstellungen`).
    Die config.toml liegt im Repository-Umfeld, Geheimnisse haben dort nichts zu suchen.

    ``basis_url`` und ``felder`` sind konfigurierbar, weil der erste echte Lauf erst auf dem
    Windows-Host stattfinden kann – die Entwicklungsumgebung erreicht api.timetac.com nicht.
    Weicht die Antwort ab, wird hier nachgezogen und nicht im Code.
    """

    aktiv: bool = True
    basis_url: str = "https://api.timetac.com"
    zeitlimit_sekunden: float = 30.0
    seitengroesse: int = 200
    # Monate, die der nächtliche Lauf holt: der laufende und der vorige (PLAN §8).
    monate_rueckwirkend: int = 1

    felder: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "projekt": ["project_name", "projectName", "project"],
            "projekt_nr": ["project_number", "projectNumber", "external_id"],
            "mitarbeiter": ["user_name", "userName", "employee", "user"],
            "datum": ["date", "start_time", "startTime"],
            "dauer_sekunden": ["duration", "duration_seconds", "worked_time"],
            "dauer_stunden": ["hours", "duration_hours"],
        }
    )

    # Spaltennamen des CSV-Berichtsexports (Rückfallebene, PLAN §8, Entscheidung 25).
    spalten: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "projekt": ["Projekt", "Project", "Projektname"],
            "mitarbeiter": ["Mitarbeiter", "Benutzer", "Name", "User"],
            "datum": ["Datum", "Date", "Tag"],
            "dauer": ["Dauer", "Stunden", "Arbeitszeit", "Duration"],
            "aufgabe": ["Aufgabe", "Task", "Taetigkeit", "Tätigkeit"],
        }
    )


class NachkalkulationEinstellungen(BaseModel):
    """Anzeige der Marge gegen die Sollmarge (PLAN §7 Phase 4).

    ``ampel_gelb_promille`` ist der Abstand zur Sollmarge, ab dem eine Marge als „knapp" gilt –
    50 Promille sind 5 Prozentpunkte. Konfigurierbar, weil das eine Einschätzung ist und keine
    Rechengröße; die Marge selbst wird davon nicht berührt.
    """

    ampel_gelb_promille: int = Field(default=50, ge=0, le=1000)


class JobEinstellungen(BaseModel):
    backup_uhrzeit: str = "01:30"
    backup_generationen: int = 30
    backup_max_alter_stunden: int = 26

    @field_validator("backup_uhrzeit")
    @classmethod
    def uhrzeit_pruefen(cls, wert: str) -> str:
        teile = wert.split(":")
        if len(teile) != 2 or not all(t.isdigit() for t in teile):
            raise ValueError(f"'{wert}' ist keine Uhrzeit im Format HH:MM.")
        stunde, minute = int(teile[0]), int(teile[1])
        if not (0 <= stunde <= 23 and 0 <= minute <= 59):
            raise ValueError(f"'{wert}' liegt außerhalb eines Tages (00:00 bis 23:59).")
        return wert

    @property
    def backup_stunde(self) -> int:
        return int(self.backup_uhrzeit.split(":")[0])

    @property
    def backup_minute(self) -> int:
        return int(self.backup_uhrzeit.split(":")[1])


class ProtokollEinstellungen(BaseModel):
    stufe: str = "INFO"
    datei_max_mb: int = 10
    generationen: int = 10

    @field_validator("stufe")
    @classmethod
    def stufe_pruefen(cls, wert: str) -> str:
        erlaubt = {"DEBUG", "INFO", "WARNING", "ERROR"}
        gross = wert.upper()
        if gross not in erlaubt:
            raise ValueError(
                f"'{wert}' ist keine gültige Protokollstufe. Erlaubt: {', '.join(sorted(erlaubt))}."
            )
        return gross


class TomlQuelle(PydanticBaseSettingsSource):
    """Liest die config.toml als Konfigurationsquelle.

    Als eigene Quelle statt als Init-Argumente, damit die Rangfolge stimmt: Umgebungsvariablen
    schlagen die Datei. Nur so lässt sich die Testinstanz mit ``IP3_APP__PORT=8010`` auf einen
    anderen Port legen, ohne eine zweite config.toml zu pflegen.
    """

    def __init__(self, settings_cls: type[BaseSettings], daten: dict[str, Any] | None = None):
        super().__init__(settings_cls)
        self._daten = daten if daten is not None else _toml_lesen(konfigurationspfad())

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._daten.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._daten)


class Einstellungen(BaseSettings):
    """Gesamtkonfiguration. Wird über :func:`einstellungen` geladen, nicht direkt erzeugt."""

    model_config = SettingsConfigDict(
        env_prefix="IP3_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Rangfolge von stark nach schwach: ausdrückliche Argumente (Tests), Umgebung, config.toml.
        return (init_settings, env_settings, dotenv_settings, TomlQuelle(settings_cls))

    app: AppEinstellungen = Field(default_factory=AppEinstellungen)
    pfade: PfadEinstellungen = Field(default_factory=PfadEinstellungen)
    firma: FirmaEinstellungen = Field(default_factory=FirmaEinstellungen)
    sitzung: SitzungEinstellungen = Field(default_factory=SitzungEinstellungen)
    anmeldung: AnmeldungEinstellungen = Field(default_factory=AnmeldungEinstellungen)
    fakturierung: FakturierungEinstellungen = Field(default_factory=FakturierungEinstellungen)
    datev: DatevEinstellungen = Field(default_factory=DatevEinstellungen)
    jobs: JobEinstellungen = Field(default_factory=JobEinstellungen)
    protokoll: ProtokollEinstellungen = Field(default_factory=ProtokollEinstellungen)
    stundensaetze: StundensaetzeEinstellungen = Field(default_factory=StundensaetzeEinstellungen)
    timetac: TimeTacEinstellungen = Field(default_factory=TimeTacEinstellungen)
    nachkalkulation: NachkalkulationEinstellungen = Field(
        default_factory=NachkalkulationEinstellungen
    )

    # Geheimnisse kommen ausschließlich aus der Umgebung, nie aus der config.toml.
    sitzung_schluessel: str = ""
    # TimeTac-Zugangsdaten: ausschließlich aus der Umgebung (.env auf dem Host), nie aus
    # der config.toml und nie ins Repository. Client-Credentials-Flow (Entscheidung 23).
    timetac_client_id: str = ""
    timetac_client_secret: str = ""
    timetac_konto: str = ""

    @property
    def ist_produktion(self) -> bool:
        return self.app.umgebung == "produktion"

    def datenbank_url(self) -> str:
        return f"sqlite+pysqlite:///{self.pfade.datenbank}"


def projektwurzel() -> Path:
    """Wurzel des Projekts – Bezugspunkt für relative Pfade aus der config.toml."""
    # backend/app/konfiguration.py -> backend/app -> backend -> Projektwurzel
    return Path(__file__).resolve().parents[2]


def konfigurationspfad() -> Path:
    """Pfad zur config.toml: aus ``IP3_CONFIG``, sonst neben dem Projekt."""
    aus_umgebung = os.environ.get("IP3_CONFIG")
    if aus_umgebung:
        return Path(aus_umgebung).expanduser()
    return projektwurzel() / "config.toml"


def _toml_lesen(pfad: Path) -> dict[str, Any]:
    if not pfad.exists():
        # Ohne config.toml lässt sich in der Entwicklung arbeiten (alle Werte haben Standards),
        # im Betrieb wäre das ein Fehler – das prüft pruefe_betriebsbereit().
        return {}
    try:
        with pfad.open("rb") as datei:
            return tomllib.load(datei)
    except tomllib.TOMLDecodeError as fehler:
        raise KonfigurationsFehler(
            f"Die Konfigurationsdatei {pfad} ist fehlerhaft: {fehler}\n"
            "Nächster Schritt: Die genannte Zeile prüfen. Windows-Pfade in einfache "
            "Anführungszeichen setzen, zum Beispiel "
            "datenbank = 'D:\\ip3-leitstand\\daten\\db.sqlite3'."
        ) from fehler
    except OSError as fehler:
        raise KonfigurationsFehler(
            f"Die Konfigurationsdatei {pfad} lässt sich nicht lesen: {fehler}\n"
            "Nächster Schritt: Zugriffsrechte des Dienstkontos auf diese Datei prüfen."
        ) from fehler


def _env_datei_laden() -> None:
    """.env einlesen, ohne zusätzliche Abhängigkeit.

    Bereits gesetzte Umgebungsvariablen haben Vorrang – im Dienstbetrieb kommen sie aus der
    Dienstkonfiguration und dürfen nicht von einer Datei überschrieben werden.
    """
    pfad = Path(os.environ.get("IP3_ENV_DATEI", projektwurzel() / ".env"))
    if not pfad.exists():
        return
    try:
        inhalt = pfad.read_text(encoding="utf-8")
    except OSError as fehler:
        raise KonfigurationsFehler(
            f"Die Datei {pfad} lässt sich nicht lesen: {fehler}\n"
            "Nächster Schritt: Zugriffsrechte prüfen oder die Datei entfernen."
        ) from fehler
    for zeile in inhalt.splitlines():
        text = zeile.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        schluessel, _, wert = text.partition("=")
        schluessel = schluessel.strip()
        wert = wert.strip().strip('"').strip("'")
        os.environ.setdefault(schluessel, wert)


def _pfad_wirkt_synchronisiert(pfad: Path) -> str | None:
    """Namen des verdächtigen Ordners zurückgeben, wenn der Pfad in einem Sync-Ordner liegt."""
    for teil in pfad.resolve().parts:
        klein = teil.lower()
        for kennzeichen in SYNC_ORDNER_KENNZEICHEN:
            # "sync" nur als eigenständiges Wort, sonst schlägt es bei "Asynchron" oder
            # Firmennamen mit "sync" im Wortinneren fälschlich an.
            if kennzeichen == "sync":
                if klein == "sync" or klein.startswith("sync ") or klein.endswith(" sync"):
                    return teil
            elif kennzeichen in klein:
                return teil
    return None


def pruefe_datenbankpfad(pfad: Path) -> None:
    """Prüft, ob die Datenbank an einem tragfähigen Ort liegt.

    SQLite verträgt keine Ordnersynchronisation und kein Netzlaufwerk: Die Sperren, mit denen
    SQLite gleichzeitige Zugriffe absichert, funktionieren dort nicht zuverlässig. Ein Abbruch
    beim Start ist deutlich billiger als eine beschädigte Datenbank.
    """
    verdaechtig = _pfad_wirkt_synchronisiert(pfad)
    if verdaechtig:
        raise KonfigurationsFehler(
            f"Die Datenbank soll unter {pfad} liegen. Der Ordner '{verdaechtig}' deutet auf eine "
            "Ordnersynchronisation hin (OneDrive, Dropbox und ähnliche).\n"
            "Eine SQLite-Datenbank in einem synchronisierten Ordner wird beschädigt.\n"
            "Nächster Schritt: In config.toml unter [pfade] die Datenbank auf ein lokales "
            "Verzeichnis legen, zum Beispiel 'D:\\ip3-leitstand\\daten\\leitstand.sqlite3'. "
            "Die Sicherungen landen weiterhin im OneDrive-Ordner unter [pfade] backup."
        )
    if str(pfad).startswith("\\\\"):
        raise KonfigurationsFehler(
            f"Die Datenbank soll unter {pfad} liegen, also auf einem Netzlaufwerk. "
            "SQLite-Sperren arbeiten über SMB nicht zuverlässig.\n"
            "Nächster Schritt: Die Datenbank auf eine lokale Festplatte des Hosts legen."
        )


def pruefe_betriebsbereit(werte: Einstellungen) -> list[str]:
    """Prüft die Konfiguration für den produktiven Betrieb.

    Rückgabe: Liste von Hinweisen (leer heißt „alles gesetzt"). Harte Fehler werden als
    :class:`KonfigurationsFehler` geworfen, weil der Leitstand damit nicht sinnvoll läuft.
    """
    hinweise: list[str] = []

    if werte.ist_produktion:
        if not werte.sitzung_schluessel:
            raise KonfigurationsFehler(
                "In der Umgebung 'produktion' fehlt der Sitzungsschlüssel.\n"
                "Nächster Schritt: In der .env IP3_SITZUNG_SCHLUESSEL setzen. Neuen Wert erzeugen "
                'mit: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if not werte.sitzung.cookie_secure:
            raise KonfigurationsFehler(
                "In der Umgebung 'produktion' ist cookie_secure abgeschaltet. Ohne dieses Merkmal "
                "kann das Sitzungs-Cookie unverschlüsselt durchs Netz gehen.\n"
                "Nächster Schritt: In config.toml unter [sitzung] cookie_secure = true setzen "
                "und den Leitstand hinter Caddy mit TLS betreiben."
            )
        if not werte.app.erlaubte_herkunft:
            raise KonfigurationsFehler(
                "In der Umgebung 'produktion' fehlt die erlaubte Herkunft.\n"
                "Nächster Schritt: In config.toml unter [app] erlaubte_herkunft auf die Adresse "
                'setzen, unter der die Nutzer den Leitstand aufrufen, z. B. ["https://leitstand.ip3.local"].'
            )

    if not werte.pfade.backup:
        hinweise.append(
            "Kein Backup-Ziel gesetzt: In config.toml unter [pfade] backup den "
            "OneDrive-Ordner 04_Backup eintragen. Ohne Ziel läuft keine Sicherung."
        )
    if not werte.pfade.datev:
        hinweise.append(
            "Kein DATEV-Ordner gesetzt: In config.toml unter [pfade] datev den OneDrive-Ordner "
            "02_DATEV eintragen. Ohne ihn bleiben die Ist-Kosten der Projekte leer und jede "
            "Marge ist zu gut."
        )
    if not werte.pfade.kalkulation:
        hinweise.append(
            "Kein Kalkulationsordner gesetzt: In config.toml unter [pfade] kalkulation den "
            "OneDrive-Ordner 03_Kalkulation eintragen. Ohne ihn gibt es keine Sollwerte und "
            "damit keinen Soll-Ist-Vergleich."
        )
    if werte.timetac.aktiv and not (werte.timetac_client_id and werte.timetac_konto):
        hinweise.append(
            "TimeTac-Zugangsdaten fehlen: IP3_TIMETAC_CLIENT_ID, IP3_TIMETAC_CLIENT_SECRET und "
            "IP3_TIMETAC_KONTO in die .env auf dem Host eintragen (nicht in die config.toml). "
            "Ohne sie fehlt die Eigenleistung im Projekt-Ist. Prüfen mit "
            "'ip3-leitstand timetac-test'."
        )
    if not werte.pfade.rechnungen:
        hinweise.append(
            "Kein Rechnungsordner gesetzt: In config.toml unter [pfade] rechnungen den "
            "OneDrive-Ordner 01_Rechnungen eintragen. Belege lassen sich sonst festschreiben, "
            "aber nicht ablegen – das PDF fehlt dann und muss nachgeholt werden."
        )
    fehlende_firmenangaben = werte.firma.unvollstaendige_pflichtangaben()
    if fehlende_firmenangaben:
        hinweise.append(
            "Firmenstammdaten unvollständig ("
            + ", ".join(fehlende_firmenangaben)
            + "). Für Rechnungen sind diese Angaben Pflicht (§ 14 UStG); "
            "in config.toml unter [firma] ergänzen. Ohne sie weist die Festschreibung "
            "einen Beleg ab."
        )
    return hinweise


def laden() -> Einstellungen:
    """Konfiguration frisch laden. Für den Normalfall :func:`einstellungen` verwenden."""
    _env_datei_laden()
    # Die config.toml liest die TomlQuelle selbst; hier wird sie nur vorab geprüft, damit ein
    # Syntaxfehler in der Datei eine eigene, deutlichere Meldung bekommt.
    _toml_lesen(konfigurationspfad())
    try:
        werte = Einstellungen()
    except ValidationError as fehler:
        zeilen = []
        for eintrag in fehler.errors():
            ort = " → ".join(str(teil) for teil in eintrag["loc"]) or "(oberste Ebene)"
            zeilen.append(f"  [{ort}] {eintrag['msg']}")
        raise KonfigurationsFehler(
            f"Die Konfiguration in {konfigurationspfad()} ist nicht verwendbar:\n"
            + "\n".join(zeilen)
            + "\nNächster Schritt: Die genannten Einträge korrigieren. "
            "config.example.toml im Projektverzeichnis zeigt die erwarteten Werte."
        ) from fehler

    # Relative Pfade beziehen sich auf die Projektwurzel, nicht auf das Arbeitsverzeichnis des
    # Dienstes – sonst landet die Datenbank je nach Startort an einer anderen Stelle.
    wurzel = projektwurzel()
    for feld in ("datenbank", "logs", "backup", "rechnungen", "datev", "kalkulation", "frontend"):
        pfad = getattr(werte.pfade, feld)
        if pfad is not None and not Path(pfad).is_absolute():
            setattr(werte.pfade, feld, (wurzel / pfad).resolve())

    pruefe_datenbankpfad(werte.pfade.datenbank)
    return werte


@lru_cache(maxsize=1)
def _geladene_einstellungen() -> Einstellungen:
    return laden()


def einstellungen() -> Einstellungen:
    """Zwischengespeicherte Konfiguration; im Test über :func:`zuruecksetzen` verwerfen."""
    return _geladene_einstellungen()


def zuruecksetzen() -> None:
    """Zwischenspeicher verwerfen – nur für Tests und die Kommandozeile.

    Greift auf die gepufferte Funktion zu, nicht auf :func:`einstellungen`: Tests ersetzen diese
    öffentliche Funktion, das Aufräumen muss trotzdem funktionieren.
    """
    _geladene_einstellungen.cache_clear()
