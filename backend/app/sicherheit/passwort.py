"""Passwörter hashen und prüfen.

bcrypt direkt, ohne Zwischenschicht: die Bibliothek hat genau die zwei Funktionen, die hier
gebraucht werden, und jede Abstraktion darüber wäre eine Abhängigkeit ohne Gegenwert.

**Die 72-Byte-Grenze von bcrypt** ist der Grund für die Längenprüfung. bcrypt verarbeitet nur die
ersten 72 Byte; neuere Versionen weisen längere Eingaben mit einem Fehler ab. Ohne die Prüfung
hier bekäme ein Nutzer mit einem langen Passwort eine Fehlerseite mit Vorgangsnummer statt eines
Hinweises am Feld. Achtung: Byte, nicht Zeichen – Umlaute zählen doppelt.
"""

from __future__ import annotations

import os

import bcrypt

from app.fehler import FachFehler

# bcrypt-Grenze. 72 Byte sind rund 72 ASCII-Zeichen oder 36 Umlaute.
MAX_BYTES = 72

# Aufwand des Verfahrens. 12 ist der übliche Wert: rund 0,3 Sekunden je Prüfung auf üblicher
# Bürohardware – für einen Menschen nicht wahrnehmbar, für einen Angreifer teuer.
KOSTEN = 12

# Die Testsuite legt Dutzende Konten an und meldet sich Hunderte Male an; mit Faktor 12 dauert
# ein Lauf Minuten, die vollständig in bcrypt verbracht werden. Über IP3_BCRYPT_KOSTEN lässt er
# sich für Tests senken. Ein Test stellt sicher, dass der Standard 12 bleibt: dieser Weg darf
# den Betrieb nicht schwächen.
_AUS_UMGEBUNG = os.environ.get("IP3_BCRYPT_KOSTEN")


def kosten() -> int:
    if _AUS_UMGEBUNG:
        try:
            gesetzt = int(_AUS_UMGEBUNG)
        except ValueError:
            return KOSTEN
        # bcrypt erlaubt 4 bis 31.
        return max(4, min(31, gesetzt))
    return KOSTEN


class PasswortFehler(FachFehler):
    status_code = 422
    code = "passwort_ungeeignet"


def pruefe_laenge(passwort: str, mindestlaenge: int) -> None:
    """Länge prüfen, bevor bcrypt es tut – mit einer Meldung, die am Feld stehen kann."""
    if len(passwort) < mindestlaenge:
        raise PasswortFehler(
            f"Das Passwort ist zu kurz. Es braucht mindestens {mindestlaenge} Zeichen.",
            "Ein längeres Passwort wählen. Ein Satz mit mehreren Wörtern ist leichter zu "
            "merken und sicherer als ein kurzes Passwort mit Sonderzeichen.",
            felder={"passwort": f"Mindestens {mindestlaenge} Zeichen."},
        )
    if len(passwort.encode("utf-8")) > MAX_BYTES:
        raise PasswortFehler(
            "Das Passwort ist zu lang. Es darf höchstens 72 Zeichen haben "
            "(Umlaute zählen doppelt).",
            "Ein kürzeres Passwort wählen.",
            felder={"passwort": "Höchstens 72 Zeichen (Umlaute zählen doppelt)."},
        )


def hashen(passwort: str) -> str:
    """Passwort als bcrypt-Hash. Zwei Aufrufe mit gleichem Passwort ergeben verschiedene Hashes."""
    if len(passwort.encode("utf-8")) > MAX_BYTES:
        raise PasswortFehler(
            "Das Passwort ist zu lang. Es darf höchstens 72 Zeichen haben "
            "(Umlaute zählen doppelt).",
            "Ein kürzeres Passwort wählen.",
        )
    return bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt(rounds=kosten())).decode("ascii")


def passt(passwort: str, gespeicherter_hash: str) -> bool:
    """Passwort gegen den gespeicherten Hash prüfen.

    Gibt bei jedem Fehler ``False`` zurück statt einer Ausnahme: ein beschädigter Hash in der
    Datenbank darf nicht zu einer Fehlerseite führen, sondern zu einer abgelehnten Anmeldung.
    """
    try:
        return bcrypt.checkpw(passwort.encode("utf-8"), gespeicherter_hash.encode("ascii"))
    except (ValueError, UnicodeError):
        return False


def zufallspasswort(laenge: int = 16) -> str:
    """Passwort für neu angelegte Konten.

    Ohne leicht zu verwechselnde Zeichen (0/O, 1/l/I), weil es einmal vorgelesen oder abgetippt
    wird. Es muss bei der ersten Anmeldung gewechselt werden.
    """
    import secrets

    zeichen = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(zeichen) for _ in range(laenge))
