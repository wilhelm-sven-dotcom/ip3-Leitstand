"""Sperre nach Fehlanmeldungen (PLAN §2).

Ohne Sperre kann ein Angreifer im Firmennetz Passwörter durchprobieren. Mit Sperre wird das
sinnlos, ohne dass ein Nutzer, der sich zweimal vertippt, ausgeschlossen wird.

Gezählt wird im ``audit_log`` – also dort, wo die Versuche ohnehin protokolliert werden (PLAN §2:
„Versuche im audit_log"). Eine eigene Zählertabelle wäre eine zweite Wahrheit über denselben
Sachverhalt.

Zwei Zähler:

* **je Kennung**: schützt das einzelne Konto. Nach der Wartezeit läuft die Sperre von selbst ab.
* **je Absender-IP**: schützt gegen das Durchprobieren vieler Kennungen von einem Rechner aus.
  Großzügiger bemessen, weil hinter einer IP mehrere Arbeitsplätze liegen können.

Wichtig: Während einer Sperre wird auch ein **richtiges** Passwort abgelehnt. Sonst wäre die
Sperre eine Auskunft darüber, welches Passwort stimmt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelle.system import AuditEintrag
from app.zeit import jetzt_utc

AKTION_FEHLVERSUCH = "anmeldung.fehlversuch"
AKTION_ERFOLG = "anmeldung.erfolg"

# Die IP-Grenze ist ein Mehrfaches der Kennungsgrenze: hinter einer Adresse können mehrere
# Arbeitsplätze liegen, und ein Büro soll sich nicht wegen eines Kollegen selbst aussperren.
IP_FAKTOR = 4


@dataclass
class Sperrzustand:
    gesperrt: bool
    verbleibende_minuten: int = 0
    fehlversuche: int = 0

    def meldung(self) -> str:
        if self.verbleibende_minuten <= 1:
            return "Zu viele Fehlversuche. Bitte in einer Minute erneut versuchen."
        return (
            f"Zu viele Fehlversuche. Bitte in {self.verbleibende_minuten} Minuten erneut versuchen."
        )

    def naechster_schritt(self) -> str:
        return (
            "Die Sperre läuft von selbst ab. Wenn Sie Ihr Passwort nicht mehr wissen, wenden Sie "
            "sich an die Geschäftsführung – dort kann es zurückgesetzt werden."
        )


def _versuche_seit(
    db: Session, *, kennung: str | None = None, ip: str | None = None, minuten: int
) -> tuple[int, object | None]:
    """Fehlversuche im Zeitfenster zählen und den jüngsten Zeitpunkt zurückgeben.

    Nur Versuche **nach** der letzten erfolgreichen Anmeldung zählen: wer sich zweimal vertippt,
    sich dann erfolgreich anmeldet und später wieder vertippt, fängt bei eins an.
    """
    seit = jetzt_utc() - timedelta(minutes=minuten)
    bedingungen = [AuditEintrag.aktion == AKTION_FEHLVERSUCH, AuditEintrag.ts >= seit]
    if kennung is not None:
        bedingungen.append(AuditEintrag.user == kennung)
    if ip is not None:
        bedingungen.append(AuditEintrag.ip == ip)

    letzter_erfolg = None
    if kennung is not None:
        letzter_erfolg = db.scalar(
            select(func.max(AuditEintrag.ts)).where(
                AuditEintrag.aktion == AKTION_ERFOLG,
                AuditEintrag.user == kennung,
                AuditEintrag.ts >= seit,
            )
        )
    if letzter_erfolg is not None:
        bedingungen.append(AuditEintrag.ts > letzter_erfolg)

    anzahl = db.scalar(select(func.count()).select_from(AuditEintrag).where(*bedingungen)) or 0
    jüngster = db.scalar(select(func.max(AuditEintrag.ts)).where(*bedingungen))
    return anzahl, jüngster


def zustand(
    db: Session,
    kennung: str,
    ip: str | None,
    max_fehlversuche: int,
    sperre_minuten: int,
) -> Sperrzustand:
    """Prüfen, ob Kennung oder Absenderadresse gesperrt sind."""
    anzahl, jüngster = _versuche_seit(db, kennung=kennung, minuten=sperre_minuten)
    if anzahl >= max_fehlversuche and jüngster is not None:
        return Sperrzustand(
            gesperrt=True,
            verbleibende_minuten=_restminuten(jüngster, sperre_minuten),
            fehlversuche=anzahl,
        )

    if ip:
        ip_anzahl, ip_jüngster = _versuche_seit(db, ip=ip, minuten=sperre_minuten)
        if ip_anzahl >= max_fehlversuche * IP_FAKTOR and ip_jüngster is not None:
            return Sperrzustand(
                gesperrt=True,
                verbleibende_minuten=_restminuten(ip_jüngster, sperre_minuten),
                fehlversuche=ip_anzahl,
            )

    return Sperrzustand(gesperrt=False, fehlversuche=anzahl)


def _restminuten(letzter_versuch, sperre_minuten: int) -> int:
    from datetime import UTC

    zeitpunkt = letzter_versuch
    if zeitpunkt.tzinfo is None:
        zeitpunkt = zeitpunkt.replace(tzinfo=UTC)
    frei_ab = zeitpunkt + timedelta(minutes=sperre_minuten)
    verbleibend = (frei_ab - jetzt_utc()).total_seconds() / 60
    return max(1, int(verbleibend) + (1 if verbleibend % 1 else 0))
