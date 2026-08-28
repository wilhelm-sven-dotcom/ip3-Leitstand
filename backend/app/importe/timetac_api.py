"""Schnittstelle zu TimeTac, REST v3 mit OAuth2-Client-Credentials (PLAN §8).

Der Leitstand meldet sich als Maschine an: Client-ID und Secret, kein persönliches Konto. Beide
kommen **ausschließlich aus der Umgebung** (``IP3_TIMETAC_CLIENT_ID``,
``IP3_TIMETAC_CLIENT_SECRET``, ``IP3_TIMETAC_KONTO``); sie stehen nie in der config.toml, nie im
Protokoll und nie im ``audit_log`` (CLAUDE.md Regel 7).

**Was hier noch nicht am lebenden Objekt geprüft ist.** Die Entwicklungsumgebung erreicht
``api.timetac.com`` nicht – die Netzwerkrichtlinie lehnt die Verbindung ab. Gebaut ist der Client
deshalb nach der v3-Dokumentation, geprüft gegen abgelegte Antworten, und an zwei Stellen bewusst
verstellbar, damit der erste echte Lauf auf dem Windows-Host ohne Codeänderung glückt:

* :func:`abfrage_bauen` – die einzige Stelle, an der Seitenlauf und Filter formuliert werden.
* ``[timetac.felder]`` in der config.toml – welches Feld der Antwort Projekt, Mitarbeiter, Datum
  und Dauer ist.

``ip3-leitstand timetac-test`` zeigt beides an einer echten Antwort, ohne etwas zu schreiben.

Ein Netzfehler darf keinen Monat leeren: :func:`abholen` schreibt nichts und wirft; erst der
Aufrufer übergibt das Ergebnis an :func:`app.importe.timetac.uebernehmen`. Ein abgebrochener Lauf
lässt damit die vorhandenen Stunden stehen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.fehler import FachFehler
from app.importe.befunde import Befund
from app.importe.timetac import SEKUNDEN_JE_STUNDE, Stundenlieferung, Zeitbuchung
from app.konfiguration import TimeTacEinstellungen
from app.zeit import heute_ortszeit, jetzt_utc

log = logging.getLogger(__name__)

TOKENPFAD = "/auth/oauth2/token"
RESSOURCE_ZEITEN = "timeTrackings"

# Ein Token gilt üblicherweise eine Stunde. So viele Sekunden vor Ablauf wird erneuert, damit
# eine laufende Abfrage nicht mitten im Seitenlauf ins Leere greift.
SICHERHEITSABSTAND = 60

# Mehr Seiten holt ein Lauf nicht. Bei 200 Buchungen je Seite sind das 100.000 Zeitbuchungen –
# weit jenseits eines Monats. Die Grenze schützt vor einer Antwort, die immer weiterzählt.
MAX_SEITEN = 500


class TimeTacFehler(FachFehler):
    code = "timetac_fehler"


class ZugangsdatenFehlen(TimeTacFehler):
    code = "timetac_zugangsdaten_fehlen"

    def __init__(self, fehlend: list[str]) -> None:
        super().__init__(
            "Für TimeTac fehlen Zugangsdaten: " + ", ".join(fehlend) + ".",
            "Die Werte in die .env auf dem Host eintragen (nicht in die config.toml) und den "
            "Leitstand neu starten. Client-ID und Secret kommen von TimeTac, der Kontoname ist "
            "der Teil der TimeTac-Adresse vor '.timetac.com'.",
        )


class AnmeldungAbgelehnt(TimeTacFehler):
    code = "timetac_anmeldung_abgelehnt"

    def __init__(self, status: int) -> None:
        super().__init__(
            f"TimeTac hat die Anmeldung abgelehnt (HTTP {status}).",
            "Client-ID und Secret in der .env prüfen. Wurde der API-Zugang bei TimeTac "
            "erneuert, ändert sich das Secret – die alten Werte gelten dann nicht mehr.",
        )


class ZugriffAbgelehnt(TimeTacFehler):
    code = "timetac_zugriff_abgelehnt"

    def __init__(self, ressource: str) -> None:
        super().__init__(
            f"TimeTac verweigert den Zugriff auf '{ressource}'.",
            "Der API-Zugang ist angemeldet, darf diese Daten aber nicht lesen. Bei TimeTac die "
            "Berechtigungen des API-Benutzers erweitern lassen.",
        )


class ZuVieleAnfragen(TimeTacFehler):
    code = "timetac_zu_viele_anfragen"

    def __init__(self, wartezeit: str | None) -> None:
        super().__init__(
            "TimeTac hat wegen zu vieler Anfragen abgewiesen.",
            (
                f"In {wartezeit} Sekunden erneut versuchen."
                if wartezeit
                else "Später erneut versuchen; der nächtliche Lauf holt die Stunden nach."
            ),
        )


class NichtErreichbar(TimeTacFehler):
    code = "timetac_nicht_erreichbar"

    def __init__(self, grund: str) -> None:
        super().__init__(
            f"TimeTac ist nicht erreichbar: {grund}",
            "Netzverbindung und die Adresse unter [timetac] basis_url prüfen. Die bereits "
            "eingelesenen Stunden bleiben unverändert; der nächste Lauf holt sie nach.",
        )


class AntwortUnverstaendlich(TimeTacFehler):
    code = "timetac_antwort_unverstaendlich"

    def __init__(self, ressource: str, grund: str) -> None:
        super().__init__(
            f"Die Antwort von TimeTac zu '{ressource}' lässt sich nicht deuten: {grund}",
            "Mit 'ip3-leitstand timetac-test' ansehen, was tatsächlich ankommt, und die "
            "Feldnamen in der config.toml unter [timetac.felder] nachziehen.",
        )


@dataclass
class Zugang:
    """Ein gültiges Token mit seinem Ablauf. Der Wert wird nie protokolliert."""

    token: str
    gueltig_bis: datetime

    def ist_gueltig(self) -> bool:
        return jetzt_utc() < self.gueltig_bis - timedelta(seconds=SICHERHEITSABSTAND)


class TimeTacClient:
    """Dünne Hülle um die v3-Schnittstelle. Liest nur, schreibt nie nach TimeTac."""

    def __init__(
        self,
        einstellungen: TimeTacEinstellungen,
        *,
        client_id: str,
        client_secret: str,
        konto: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        fehlend = [
            name
            for name, wert in (
                ("IP3_TIMETAC_CLIENT_ID", client_id),
                ("IP3_TIMETAC_CLIENT_SECRET", client_secret),
                ("IP3_TIMETAC_KONTO", konto),
            )
            if not wert.strip()
        ]
        if fehlend:
            raise ZugangsdatenFehlen(fehlend)

        self.einstellungen = einstellungen
        self._client_id = client_id
        self._client_secret = client_secret
        self.konto = konto
        self._zugang: Zugang | None = None
        self._transport = transport

    # -- Adressen ---------------------------------------------------------

    @property
    def basis(self) -> str:
        return self.einstellungen.basis_url.rstrip("/")

    def token_adresse(self) -> str:
        return f"{self.basis}{TOKENPFAD}"

    def ressourcen_adresse(self, ressource: str) -> str:
        return f"{self.basis}/{self.konto}/api/v3/{ressource}.json"

    # -- Anmeldung --------------------------------------------------------

    def token(self) -> str:
        """Gültiges Zugangstoken, bei Bedarf neu geholt."""
        if self._zugang is not None and self._zugang.ist_gueltig():
            return self._zugang.token
        self._zugang = self._token_holen()
        return self._zugang.token

    def _token_holen(self) -> Zugang:
        antwort = self._senden(
            "POST",
            self.token_adresse(),
            daten={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if antwort.status_code in (400, 401):
            raise AnmeldungAbgelehnt(antwort.status_code)
        self._auf_fehler_pruefen(antwort, "Anmeldung")
        inhalt = self._json(antwort, "Anmeldung")
        token = inhalt.get("access_token")
        if not token:
            raise AntwortUnverstaendlich("Anmeldung", "die Antwort enthält kein access_token")
        gueltig = int(inhalt.get("expires_in") or 3600)
        # Das Token selbst wird nirgends protokolliert – nur, dass es eines gibt.
        log.info("TimeTac: Zugangstoken erneuert, gültig für %d Sekunden", gueltig)
        return Zugang(token=token, gueltig_bis=jetzt_utc() + timedelta(seconds=gueltig))

    # -- Abfragen ---------------------------------------------------------

    def lesen(self, ressource: str, *, filter_: dict[str, str] | None = None) -> list[dict]:
        """Alle Datensätze einer Ressource, über alle Seiten."""
        eintraege: list[dict] = []
        for seite in range(MAX_SEITEN):
            abfrage = abfrage_bauen(
                filter_ or {},
                grenze=self.einstellungen.seitengroesse,
                versatz=seite * self.einstellungen.seitengroesse,
            )
            antwort = self._senden(
                "GET",
                self.ressourcen_adresse(ressource),
                abfrage=abfrage,
                kopf={"Authorization": f"Bearer {self.token()}"},
            )
            if antwort.status_code == 403:
                raise ZugriffAbgelehnt(ressource)
            if antwort.status_code == 429:
                raise ZuVieleAnfragen(antwort.headers.get("Retry-After"))
            self._auf_fehler_pruefen(antwort, ressource)
            teil = _datensaetze(self._json(antwort, ressource), ressource)
            eintraege.extend(teil)
            if len(teil) < self.einstellungen.seitengroesse:
                return eintraege
        raise AntwortUnverstaendlich(
            ressource, f"mehr als {MAX_SEITEN} Seiten – der Seitenlauf endet nicht"
        )

    # -- Innereien --------------------------------------------------------

    def _senden(
        self,
        verfahren: str,
        adresse: str,
        *,
        abfrage: dict[str, Any] | None = None,
        daten: dict[str, str] | None = None,
        kopf: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            with httpx.Client(
                timeout=self.einstellungen.zeitlimit_sekunden,
                transport=self._transport,
            ) as client:
                return client.request(verfahren, adresse, params=abfrage, data=daten, headers=kopf)
        except httpx.TimeoutException as fehler:
            raise NichtErreichbar(
                f"Zeitüberschreitung nach {self.einstellungen.zeitlimit_sekunden:.0f} Sekunden"
            ) from fehler
        except httpx.HTTPError as fehler:
            raise NichtErreichbar(str(fehler) or type(fehler).__name__) from fehler

    @staticmethod
    def _auf_fehler_pruefen(antwort: httpx.Response, ressource: str) -> None:
        if antwort.status_code >= 400:
            raise NichtErreichbar(f"'{ressource}' beantwortet mit HTTP {antwort.status_code}")

    @staticmethod
    def _json(antwort: httpx.Response, ressource: str) -> dict:
        try:
            inhalt = antwort.json()
        except ValueError as fehler:
            raise AntwortUnverstaendlich(ressource, "keine gültige JSON-Antwort") from fehler
        if not isinstance(inhalt, dict):
            raise AntwortUnverstaendlich(ressource, "die Antwort ist kein Objekt")
        return inhalt


def abfrage_bauen(filter_: dict[str, str], *, grenze: int, versatz: int) -> dict[str, Any]:
    """Abfrageparameter für eine v3-Ressource.

    **Die eine Stelle, die der erste echte Lauf bestätigen muss.** Nach der v3-Dokumentation
    heißen Seitenlauf und Filter ``limit``/``offset`` bzw. ``filter``; weicht die Schnittstelle
    ab, wird nur hier nachgezogen. ``ip3-leitstand timetac-test`` zeigt die gesendete Abfrage
    und die Antwort im Klartext.
    """
    abfrage: dict[str, Any] = {"limit": grenze, "offset": versatz}
    if filter_:
        abfrage["filter"] = ",".join(f"{feld}{wert}" for feld, wert in sorted(filter_.items()))
    return abfrage


def _datensaetze(inhalt: dict, ressource: str) -> list[dict]:
    """Die Nutzdaten aus einer v3-Antwort: ``{"Success": true, "Results": [...]}``."""
    for schluessel in ("Results", "results", "data", "Data"):
        wert = inhalt.get(schluessel)
        if isinstance(wert, list):
            return [e for e in wert if isinstance(e, dict)]
    raise AntwortUnverstaendlich(
        ressource, f"keine Ergebnisliste gefunden (Schlüssel: {', '.join(sorted(inhalt))})"
    )


# ---------------------------------------------------------------------------
# Abholen und in Zeitbuchungen übersetzen
# ---------------------------------------------------------------------------


def monate_bestimmen(einstellungen: TimeTacEinstellungen, heute: date | None = None) -> list[str]:
    """Der laufende Monat und so viele davor, wie eingestellt ist (PLAN §8)."""
    stichtag = heute or heute_ortszeit()
    monate = []
    jahr, monat = stichtag.year, stichtag.month
    for _ in range(einstellungen.monate_rueckwirkend + 1):
        monate.append(f"{jahr:04d}-{monat:02d}")
        monat -= 1
        if monat == 0:
            jahr, monat = jahr - 1, 12
    return sorted(monate)


def abholen(
    client: TimeTacClient, monate: list[str], *, heute: date | None = None
) -> Stundenlieferung:
    """Zeitbuchungen der genannten Monate holen und deuten. Schreibt nichts."""
    von = f"{min(monate)}-01"
    bis = _monatsende(max(monate))
    lieferung = Stundenlieferung(herkunft=f"TimeTac {client.konto}", monate=sorted(monate))

    rohdaten = client.lesen(RESSOURCE_ZEITEN, filter_={"date>=": von, "date<=": bis.isoformat()})
    felder = client.einstellungen.felder
    for nummer, satz in enumerate(rohdaten, start=1):
        buchung = _buchung_deuten(satz, felder, nummer, lieferung)
        if buchung is not None:
            lieferung.buchungen.append(buchung)
    return lieferung


def _monatsende(monat: str) -> date:
    jahr, nummer = int(monat[:4]), int(monat[5:])
    if nummer == 12:
        return date(jahr, 12, 31)
    return date(jahr, nummer + 1, 1) - timedelta(days=1)


def _feld(satz: dict, namen: list[str]) -> Any:
    for name in namen:
        if name in satz and satz[name] not in (None, ""):
            return satz[name]
    return None


def _buchung_deuten(
    satz: dict, felder: dict[str, list[str]], nummer: int, lieferung: Stundenlieferung
) -> Zeitbuchung | None:
    def befund(spalte: str, wert: Any, meldung: str) -> None:
        lieferung.befunde.append(
            Befund(
                datei=lieferung.herkunft,
                zeile=nummer,
                spalte=spalte,
                wert="" if wert is None else str(wert),
                meldung=meldung,
            )
        )

    projekt_nr = _feld(satz, felder.get("projekt_nr", []))
    projekt_text = _feld(satz, felder.get("projekt", []))
    if projekt_text is None and projekt_nr is None:
        befund("projekt", satz.get("id"), "Buchung ohne Projekt – nicht übernommen")
        return None

    mitarbeiter = _feld(satz, felder.get("mitarbeiter", []))
    if mitarbeiter is None:
        befund("mitarbeiter", satz.get("id"), "Buchung ohne Mitarbeiter – nicht übernommen")
        return None

    tag = _datum_deuten(_feld(satz, felder.get("datum", [])))
    if tag is None:
        befund("datum", _feld(satz, felder.get("datum", [])), "Kein lesbares Datum")
        return None

    stunden = _stunden_deuten(satz, felder)
    if stunden is None:
        befund("dauer", satz.get("id"), "Keine lesbare Dauer – Buchung nicht übernommen")
        return None
    if stunden <= 0:
        # Kommt vor: eine begonnene, noch nicht beendete Zeitbuchung hat die Dauer 0.
        return None

    return Zeitbuchung(
        herkunft=lieferung.herkunft,
        zeile=nummer,
        # Die Nummer voranstellen, wenn TimeTac eine führt – dann greift die exakte Zuordnung
        # in app/importe/timetac.py auch bei einem Projektnamen ohne Nummer.
        projekt_text=f"{projekt_nr} {projekt_text or ''}".strip()
        if projekt_nr
        else str(projekt_text),
        mitarbeiter=str(mitarbeiter).strip(),
        datum=tag,
        stunden=stunden,
    )


def _datum_deuten(wert: Any) -> date | None:
    if isinstance(wert, date) and not isinstance(wert, datetime):
        return wert
    if isinstance(wert, datetime):
        return wert.date()
    text = str(wert or "").strip()
    if not text:
        return None
    # '2026-07-06' und '2026-07-06 08:15:00' sind beide üblich.
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _stunden_deuten(satz: dict, felder: dict[str, list[str]]) -> Decimal | None:
    """Dauer als Stunden – wahlweise aus einem Sekunden- oder einem Stundenfeld."""
    direkt = _feld(satz, felder.get("dauer_stunden", []))
    if direkt is not None:
        gelesen = _dezimal(direkt)
        if gelesen is not None:
            return gelesen.quantize(Decimal("0.01"))
    sekunden = _feld(satz, felder.get("dauer_sekunden", []))
    if sekunden is not None:
        gelesen = _dezimal(sekunden)
        if gelesen is not None:
            return (gelesen / SEKUNDEN_JE_STUNDE).quantize(Decimal("0.01"))
    return None


def _dezimal(wert: Any) -> Decimal | None:
    try:
        return Decimal(str(wert).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
