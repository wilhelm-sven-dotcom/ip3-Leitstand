"""CSRF-Schutz (PLAN §2: „CSRF-Schutz für alle schreibenden Requests").

Das Sitzungs-Cookie schickt der Browser bei jeder Anfrage an den Leitstand mit – auch bei einer
Anfrage, die eine fremde Seite ausgelöst hat. Ohne weitere Prüfung könnte eine solche Seite im
Namen des angemeldeten Nutzers schreiben.

Zwei Sperren, beide nötig:

1. **Token im Kopf der Anfrage.** Jede Sitzung hat ein Token, das die Oberfläche beim Anmelden
   bekommt und bei schreibenden Anfragen im Kopf ``X-CSRF-Token`` mitschickt. Eine fremde Seite
   kann das Token nicht lesen (sie kommt an die Antwort nicht heran) und es damit nicht setzen.
2. **Herkunftsprüfung.** ``Origin`` bzw. ``Referer`` müssen zur konfigurierten Adresse passen.
   Das fängt Fälle, in denen ein Browser Kopfzeilen anders behandelt als erwartet.

Lesende Anfragen (GET, HEAD, OPTIONS) brauchen kein Token. Sie verändern nichts, und ein Token
für jede Leseanfrage würde nur dazu führen, dass die erste Seite ohne Sitzung nicht lädt.
"""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import Request

from app.fehler import FachFehler

KOPFZEILE = "X-CSRF-Token"
SICHERE_METHODEN = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CsrfFehler(FachFehler):
    status_code = 403
    code = "csrf_ungueltig"

    def __init__(self, meldung: str) -> None:
        super().__init__(
            meldung,
            "Bitte die Seite neu laden und den Vorgang wiederholen. Tritt es wieder auf, "
            "einmal ab- und neu anmelden.",
        )


def braucht_pruefung(methode: str) -> bool:
    return methode.upper() not in SICHERE_METHODEN


def _herkunft_passt(anfrage: Request, erlaubte: list[str]) -> bool:
    """Origin oder Referer gegen die erlaubten Adressen prüfen.

    Ohne konfigurierte Adressen (Entwicklung) wird nicht geprüft: dort läuft die Oberfläche über
    den Vite-Entwicklungsserver, und eine feste Adresse wäre nur eine Fehlerquelle.
    """
    if not erlaubte:
        return True

    herkunft = anfrage.headers.get("origin")
    if not herkunft:
        referer = anfrage.headers.get("referer")
        if referer:
            teile = urlparse(referer)
            herkunft = f"{teile.scheme}://{teile.netloc}"
    if not herkunft:
        # Manche Browser senden bei gleicher Herkunft keines von beiden. Das Token allein muss
        # dann genügen – es ist die eigentliche Sperre.
        return True

    erlaubte_normiert = {eintrag.rstrip("/") for eintrag in erlaubte}
    return herkunft.rstrip("/") in erlaubte_normiert


def pruefen(anfrage: Request, erwartetes_token: str, erlaubte_herkunft: list[str]) -> None:
    """CSRF-Prüfung für eine schreibende Anfrage."""
    if not _herkunft_passt(anfrage, erlaubte_herkunft):
        raise CsrfFehler("Die Anfrage kam von einer unerwarteten Adresse und wurde abgelehnt.")

    mitgeschickt = anfrage.headers.get(KOPFZEILE, "")
    if not mitgeschickt:
        raise CsrfFehler("Der Sicherheitsschlüssel für diese Aktion fehlt.")
    # Zeitkonstanter Vergleich: ein einfacher Vergleich bricht beim ersten unterschiedlichen
    # Zeichen ab und verrät damit über die Laufzeit, wie viele Zeichen stimmen.
    if not hmac.compare_digest(mitgeschickt, erwartetes_token):
        raise CsrfFehler("Der Sicherheitsschlüssel für diese Aktion ist nicht mehr gültig.")
