"""Fehlerbehandlung mit verständlichen deutschen Meldungen (PLAN §14).

Jede Fehlerantwort hat denselben Aufbau::

    {"code": "keine_berechtigung",
     "meldung": "Für diese Ansicht fehlt Ihnen die Berechtigung.",
     "naechster_schritt": "Wenden Sie sich an Sven oder Michael."}

Der ``code`` ist für das Frontend gedacht (Fallunterscheidung), ``meldung`` und
``naechster_schritt`` sind für den Menschen am Bildschirm. Ein Stacktrace verlässt den Server nie;
bei unerwarteten Fehlern bekommt der Nutzer eine Vorgangsnummer, mit der sich der Eintrag im
Protokoll finden lässt.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.protokoll import logger

log = logger(__name__)


class FachFehler(Exception):
    """Fehler mit einer Meldung, die so auf dem Bildschirm stehen darf.

    Wird in der Fachlogik geworfen und von der Anwendung in eine Antwort mit dem passenden
    HTTP-Status übersetzt.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "fachfehler"

    def __init__(
        self,
        meldung: str,
        naechster_schritt: str = "",
        *,
        code: str | None = None,
        status_code: int | None = None,
        felder: dict[str, str] | None = None,
    ) -> None:
        super().__init__(meldung)
        self.meldung = meldung
        self.naechster_schritt = naechster_schritt
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.felder = felder or {}

    def als_koerper(self) -> dict[str, Any]:
        koerper: dict[str, Any] = {
            "code": self.code,
            "meldung": self.meldung,
            "naechster_schritt": self.naechster_schritt,
        }
        if self.felder:
            koerper["felder"] = self.felder
        return koerper


class NichtAngemeldet(FachFehler):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "nicht_angemeldet"

    def __init__(
        self,
        meldung: str = "Ihre Anmeldung ist abgelaufen.",
        naechster_schritt: str = "Melden Sie sich erneut an.",
    ) -> None:
        super().__init__(meldung, naechster_schritt)


class KeineBerechtigung(FachFehler):
    status_code = status.HTTP_403_FORBIDDEN
    code = "keine_berechtigung"

    def __init__(
        self,
        meldung: str = "Für diesen Vorgang fehlt Ihnen die Berechtigung.",
        naechster_schritt: str = (
            "Wenden Sie sich an die Geschäftsführung, wenn Sie den Zugriff brauchen."
        ),
    ) -> None:
        super().__init__(meldung, naechster_schritt)


class NichtGefunden(FachFehler):
    status_code = status.HTTP_404_NOT_FOUND
    code = "nicht_gefunden"

    def __init__(
        self,
        meldung: str = "Der Datensatz wurde nicht gefunden.",
        naechster_schritt: str = (
            "Möglicherweise wurde er zwischenzeitlich geändert. Bitte die Liste neu laden."
        ),
    ) -> None:
        super().__init__(meldung, naechster_schritt)


class Konflikt(FachFehler):
    """Gleichzeitige Bearbeitung oder gesperrter Datensatz (Optimistic Locking, Festschreibung)."""

    status_code = status.HTTP_409_CONFLICT
    code = "konflikt"


class ZuVieleVersuche(FachFehler):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "zu_viele_versuche"


# Pydantic-Fehlertypen in Sätze übersetzen, die man einer Buchhaltungskraft zeigen kann.
_VALIDIERUNGSTEXTE: dict[str, str] = {
    "missing": "Diese Angabe fehlt.",
    "string_too_short": "Die Angabe ist zu kurz.",
    "string_too_long": "Die Angabe ist zu lang.",
    "string_pattern_mismatch": "Die Angabe hat nicht das erwartete Format.",
    "int_parsing": "Hier wird eine ganze Zahl erwartet.",
    "int_type": "Hier wird eine ganze Zahl erwartet.",
    "float_parsing": "Hier wird eine Zahl erwartet.",
    "decimal_parsing": "Hier wird eine Zahl erwartet.",
    "bool_parsing": "Hier wird ja oder nein erwartet.",
    "date_parsing": "Hier wird ein Datum erwartet.",
    "date_from_datetime_parsing": "Hier wird ein Datum erwartet.",
    "datetime_parsing": "Hier wird ein Zeitpunkt erwartet.",
    "datetime_from_date_parsing": "Hier wird ein Zeitpunkt erwartet.",
    "greater_than": "Der Wert ist zu klein.",
    "greater_than_equal": "Der Wert ist zu klein.",
    "less_than": "Der Wert ist zu groß.",
    "less_than_equal": "Der Wert ist zu groß.",
    "enum": "Dieser Wert ist hier nicht zulässig.",
    "literal_error": "Dieser Wert ist hier nicht zulässig.",
    "value_error": "Der Wert ist nicht zulässig.",
    "json_invalid": "Die Anfrage war nicht lesbar.",
    "extra_forbidden": "Dieses Feld ist hier nicht vorgesehen.",
}

# Standardtexte für HTTP-Status, die nicht aus der Fachlogik kommen (z. B. von Starlette selbst).
_STATUSTEXTE: dict[int, tuple[str, str, str]] = {
    401: (
        "nicht_angemeldet",
        "Ihre Anmeldung ist abgelaufen.",
        "Melden Sie sich erneut an.",
    ),
    403: (
        "keine_berechtigung",
        "Für diesen Vorgang fehlt Ihnen die Berechtigung.",
        "Wenden Sie sich an die Geschäftsführung, wenn Sie den Zugriff brauchen.",
    ),
    404: (
        "nicht_gefunden",
        "Die Adresse gibt es nicht.",
        "Bitte über das Menü neu einsteigen.",
    ),
    405: (
        "methode_nicht_erlaubt",
        "Dieser Vorgang ist an dieser Stelle nicht vorgesehen.",
        "Bitte die Seite neu laden.",
    ),
    409: (
        "konflikt",
        "Der Datensatz wurde zwischenzeitlich geändert.",
        "Bitte neu laden und die Eingabe wiederholen.",
    ),
    413: (
        "datei_zu_gross",
        "Die Datei ist zu groß.",
        "Bitte eine kleinere Datei verwenden.",
    ),
    429: (
        "zu_viele_versuche",
        "Zu viele Versuche in kurzer Zeit.",
        "Bitte einige Minuten warten und es dann erneut versuchen.",
    ),
}


def _feldname(pfad: tuple[Any, ...]) -> str:
    """Aus dem Pydantic-Pfad einen Feldnamen bauen, den das Frontend zuordnen kann."""
    teile = [str(t) for t in pfad if t not in ("body", "query", "path", "header", "cookie")]
    return ".".join(teile) if teile else "(Anfrage)"


def handler_registrieren(app: FastAPI) -> None:
    """Alle Fehler-Handler an die Anwendung hängen."""

    @app.exception_handler(FachFehler)
    async def _fachfehler(_: Request, fehler: FachFehler) -> JSONResponse:
        return JSONResponse(status_code=fehler.status_code, content=fehler.als_koerper())

    @app.exception_handler(RequestValidationError)
    async def _validierung(_: Request, fehler: RequestValidationError) -> JSONResponse:
        felder: dict[str, str] = {}
        for eintrag in fehler.errors():
            name = _feldname(tuple(eintrag.get("loc", ())))
            typ = str(eintrag.get("type", ""))
            if typ == "value_error":
                # Eigene Prüfungen tragen ihre Meldung selbst; die ist schon deutsch.
                rohtext = str(eintrag.get("msg", ""))
                text = rohtext.removeprefix("Value error, ").strip() or _VALIDIERUNGSTEXTE[typ]
            else:
                text = _VALIDIERUNGSTEXTE.get(typ, "Die Angabe ist nicht verwendbar.")
            felder.setdefault(name, text)
        return JSONResponse(
            # 422 als Zahl: Starlette hat die Konstante zwischen Versionen umbenannt.
            status_code=422,
            content={
                "code": "eingabe_unvollstaendig",
                "meldung": "Die Eingaben sind noch nicht vollständig oder nicht plausibel.",
                "naechster_schritt": "Bitte die markierten Felder prüfen.",
                "felder": felder,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, fehler: StarletteHTTPException) -> JSONResponse:
        code, meldung, schritt = _STATUSTEXTE.get(
            fehler.status_code,
            ("fehler", "Der Vorgang ist fehlgeschlagen.", "Bitte erneut versuchen."),
        )
        # Eine bewusst gesetzte Meldung (str im detail) hat Vorrang vor dem Standardtext.
        if isinstance(fehler.detail, str) and fehler.detail and fehler.status_code != 404:
            meldung = fehler.detail
        koerper = {"code": code, "meldung": meldung, "naechster_schritt": schritt}
        return JSONResponse(status_code=fehler.status_code, content=koerper, headers=fehler.headers)

    @app.exception_handler(Exception)
    async def _unerwartet(anfrage: Request, fehler: Exception) -> JSONResponse:
        vorgang = uuid.uuid4().hex[:8]
        log.exception(
            "Unerwarteter Fehler [Vorgang %s] bei %s %s",
            vorgang,
            anfrage.method,
            anfrage.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "unerwarteter_fehler",
                "meldung": "Im Leitstand ist ein unerwarteter Fehler aufgetreten. "
                f"Vorgangsnummer {vorgang}.",
                "naechster_schritt": "Bitte den Vorgang erneut versuchen. Bleibt es dabei, "
                f"die Vorgangsnummer {vorgang} an Sven weitergeben – damit lässt sich der "
                "Eintrag im Protokoll finden.",
            },
        )
