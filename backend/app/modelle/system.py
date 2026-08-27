"""Nutzer, Berechtigungen, Sitzungen, Protokoll und Läufe (PLAN §4, §5).

Das Rechtemodell ist von Anfang an ein RBAC-Schema ohne festes Rollen-Enum: Nutzer haben Rollen,
Rollen bündeln Berechtigungen, Berechtigungen sind Schlüssel nach dem Muster ``ressource.aktion``.
Geprüft wird immer gegen Berechtigungsschlüssel, nie gegen Rollennamen (PLAN §4) – nur so lässt
sich später eine vierte Rolle anlegen, ohne Code anzufassen.

``sitzungen`` und ``job_laeufe`` stehen nicht in PLAN §5. Sie sind technisch nötig:
Server-Sitzungen brauchen eine Ablage (PLAN §2 verlangt serverseitige Sitzungen), und der
Systemstatus-Block braucht Läufe mit Ergebnis, damit ein ausgefallener nächtlicher Job auffällt.
``importlaeufe`` bleibt für die fachlichen Importe der Phasen 1 und 4 zuständig.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Text as SaText,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.modelle.basis import (
    Base,
    Kurztext,
    Langtext,
    OptimistischMixin,
    Text,
    UtcDateTime,
    ZeitstempelMixin,
)
from app.modelle.pruefungen import in_werten, in_werten_oder_leer

SCOPES = ("alle", "eigene")
LAUF_STATUS = ("laeuft", "erfolg", "warnung", "fehler")
AUSLOESER = ("zeitplan", "manuell", "start")


class User(OptimistischMixin, ZeitstempelMixin, Base):
    """Ein Nutzerkonto.

    Nutzer werden nie gelöscht, nur deaktiviert (PLAN §5): das Änderungsprotokoll verweist auf
    sie, und ein gelöschter Nutzer würde die Nachvollziehbarkeit zerstören.

    ``email`` steht nicht in PLAN §5, ist aber die Anmeldekennung aus dem Design (Login-Maske) und
    damit die naheliegende eindeutige Kennung. Siehe docs/OFFENE-PUNKTE.md Nr. 5.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    pw_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Erzwingt den Passwortwechsel bei der ersten Anmeldung und nach einem Zurücksetzen.
    muss_passwort_wechseln: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    letzte_anmeldung: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    rollen: Mapped[list[Rolle]] = relationship(secondary="user_rollen", back_populates="nutzer")
    sitzungen: Mapped[list[Sitzung]] = relationship(
        back_populates="nutzer", cascade="all, delete-orphan"
    )

    def berechtigungsschluessel(self) -> dict[str, str]:
        """Alle Berechtigungen dieses Nutzers als ``{schluessel: scope}``.

        Bei mehreren Rollen gewinnt der weitere Scope: wer über eine Rolle ``alle`` hat, sieht
        alles, auch wenn eine andere Rolle nur ``eigene`` vorsieht.
        """
        ergebnis: dict[str, str] = {}
        for rolle in self.rollen:
            for berechtigung in rolle.berechtigungen:
                vorher = ergebnis.get(berechtigung.schluessel)
                scope = berechtigung.scope or "alle"
                if vorher is None or (vorher == "eigene" and scope == "alle"):
                    ergebnis[berechtigung.schluessel] = scope
        return ergebnis

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Rolle(OptimistischMixin, ZeitstempelMixin, Base):
    __tablename__ = "rollen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Kurztext, nullable=False, unique=True)
    beschreibung: Mapped[str | None] = mapped_column(Text, nullable=True)

    nutzer: Mapped[list[User]] = relationship(secondary="user_rollen", back_populates="rollen")
    berechtigungen: Mapped[list[Berechtigung]] = relationship(
        secondary="rollen_berechtigungen", back_populates="rollen"
    )

    def __repr__(self) -> str:
        return f"<Rolle {self.name}>"


class Berechtigung(ZeitstempelMixin, Base):
    """Ein Berechtigungsschlüssel, optional mit Sichtbarkeits-Scope.

    Derselbe Schlüssel kann zweimal vorkommen – einmal mit Scope ``alle``, einmal mit ``eigene`` –,
    damit ein Projektleiter nur seine Projekte sieht (PLAN §4).
    """

    __tablename__ = "berechtigungen"
    __table_args__ = (
        UniqueConstraint("schluessel", "scope", name="uq_berechtigungen_schluessel_scope"),
        in_werten_oder_leer("scope", SCOPES),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schluessel: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    scope: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    beschreibung: Mapped[str | None] = mapped_column(Text, nullable=True)

    rollen: Mapped[list[Rolle]] = relationship(
        secondary="rollen_berechtigungen", back_populates="berechtigungen"
    )

    def __repr__(self) -> str:
        return f"<Berechtigung {self.schluessel}:{self.scope or 'alle'}>"


class RollenBerechtigung(Base):
    """Verknüpfung Rolle ↔ Berechtigung.

    Die zweite Spalte des Primärschlüssels bekommt einen eigenen Index: der zusammengesetzte
    Schlüssel deckt nur Abfragen ab, die mit ``rolle_id`` beginnen. Die Frage „welche Rollen
    tragen diese Berechtigung" – gestellt bei jeder Änderung am Berechtigungskatalog – läuft in
    die andere Richtung.
    """

    __tablename__ = "rollen_berechtigungen"

    rolle_id: Mapped[int] = mapped_column(
        ForeignKey("rollen.id", ondelete="CASCADE"), primary_key=True
    )
    berechtigung_id: Mapped[int] = mapped_column(
        ForeignKey("berechtigungen.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class UserRolle(Base):
    """Verknüpfung Nutzer ↔ Rolle. Index auf ``rolle_id`` wie bei RollenBerechtigung."""

    __tablename__ = "user_rollen"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    rolle_id: Mapped[int] = mapped_column(
        ForeignKey("rollen.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Sitzung(ZeitstempelMixin, Base):
    """Serverseitige Sitzung (PLAN §2).

    Gespeichert wird nur der Hash des Sitzungsschlüssels. Wer die Datenbank liest – etwa in einer
    Sicherungskopie im OneDrive –, kann damit keine Sitzung übernehmen.
    """

    __tablename__ = "sitzungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    laeuft_ab: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    letzte_aktivitaet: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    angemeldet_bleiben: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip: Mapped[str | None] = mapped_column(Kurztext, nullable=True)
    browser: Mapped[str | None] = mapped_column(Text, nullable=True)
    beendet_am: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    nutzer: Mapped[User] = relationship(back_populates="sitzungen")

    def __repr__(self) -> str:
        return f"<Sitzung Nutzer {self.user_id} bis {self.laeuft_ab}>"


class AuditEintrag(Base):
    """Änderungsprotokoll (PLAN §5).

    Wird nur geschrieben, nie geändert oder gelöscht – es gibt in der Anwendung keinen Pfad dafür.
    Passwörter, Hashes und Sitzungsschlüssel werden vor dem Schreiben herausgefiltert.

    Ohne ``ZeitstempelMixin``: ein Protokolleintrag hat einen Zeitpunkt (``ts``) und wird nie
    aktualisiert; ``created_at``/``updated_at`` wären hier irreführend.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    # Nutzer als Text, nicht als Fremdschlüssel: das Protokoll soll auch Einträge zu einer
    # Anmeldung mit unbekannter Kennung aufnehmen können (Fehlversuche, PLAN §2).
    user: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    aktion: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    tabelle: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    datensatz_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    neu: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(Kurztext, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditEintrag {self.ts} {self.aktion}>"


class Importlauf(ZeitstempelMixin, Base):
    """Ein fachlicher Importlauf (DATEV, TimeTac, Kalkulationsblatt, Migration).

    Jeder Lauf ersetzt seinen Zeitraum, statt anzuhängen (PLAN §8). ``ergebnis`` hält die
    Kontrollsummen, mit denen sich der Lauf nachträglich prüfen lässt.
    """

    __tablename__ = "importlaeufe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quelle: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    datei: Mapped[str | None] = mapped_column(Langtext, nullable=True)
    zeitraum: Mapped[str | None] = mapped_column(Kurztext, nullable=True, index=True)
    gestartet: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    beendet: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="laeuft", index=True)
    ergebnis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (in_werten("status", LAUF_STATUS),)

    def __repr__(self) -> str:
        return f"<Importlauf {self.quelle} {self.zeitraum}>"


class JobLauf(ZeitstempelMixin, Base):
    """Ein Lauf eines Hintergrundjobs (Sicherung, später Synchronisierungen und Scans).

    Grundlage des Systemstatus-Blocks auf der Startseite: PLAN §2 verlangt, dass stille
    Job-Ausfälle nicht vorkommen. Ohne Protokoll in der Datenbank fällt ein nicht gelaufener Job
    erst auf, wenn man ihn braucht.
    """

    __tablename__ = "job_laeufe"
    __table_args__ = (
        in_werten("status", LAUF_STATUS),
        in_werten("ausgeloest_von", AUSLOESER),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(Kurztext, nullable=False, index=True)
    gestartet: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    beendet: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(Kurztext, nullable=False, default="laeuft", index=True)
    ausgeloest_von: Mapped[str] = mapped_column(Kurztext, nullable=False, default="zeitplan")
    # Für Menschen lesbare Zusammenfassung, die im Systemstatus angezeigt wird.
    meldung: Mapped[str | None] = mapped_column(SaText, nullable=True)
    dauer_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kennzahlen: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    @property
    def erfolgreich(self) -> bool:
        return self.status in ("erfolg", "warnung")

    def __repr__(self) -> str:
        return f"<JobLauf {self.job} {self.status}>"
