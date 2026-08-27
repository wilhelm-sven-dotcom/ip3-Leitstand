"""Datenmodell des Leitstands (PLAN §5).

Dieses Modul importiert alle Tabellen, damit ``Base.metadata`` vollständig ist – Alembic und die
Testausstattung verlassen sich darauf. Eine fehlende Zeile hier führt dazu, dass eine Tabelle
lautlos aus den Migrationen verschwindet, deshalb prüft ein Test die Vollständigkeit.

Das Schema ist von Anfang an komplett, obwohl Phase 0 nur Anmeldung und Systemstatus braucht:
So bleibt es an einer Stelle nachvollziehbar, und die späteren Phasen bringen Funktionen statt
Schemaumbauten mit.
"""

from __future__ import annotations

from app.modelle.anlagen import Anlage, Frist
from app.modelle.basis import Base, Cent, UtcDateTime, ZeitstempelMixin
from app.modelle.fakturierung import Absetzung, Nummernkreis, Rechnung, Rechnungsposition
from app.modelle.finanzen import DatevSaldo, FixkostenPlan, KontenMapping, Opos
from app.modelle.kalkulation import IstKosten, SollKalkulation, Stuecklistenposition, Stunden
from app.modelle.projekte import (
    Dokument,
    Meilenstein,
    Nachtrag,
    Projekt,
    Zahlungsplanposition,
)
from app.modelle.stammdaten import Ansprechpartner, Firma, Kunde
from app.modelle.system import (
    AuditEintrag,
    Berechtigung,
    Importlauf,
    JobLauf,
    Rolle,
    RollenBerechtigung,
    Sitzung,
    User,
    UserRolle,
)

__all__ = [
    "Absetzung",
    "Anlage",
    "Ansprechpartner",
    "AuditEintrag",
    "Base",
    "Berechtigung",
    "Cent",
    "DatevSaldo",
    "Dokument",
    "Firma",
    "FixkostenPlan",
    "Frist",
    "Importlauf",
    "IstKosten",
    "JobLauf",
    "KontenMapping",
    "Kunde",
    "Meilenstein",
    "Nachtrag",
    "Nummernkreis",
    "Opos",
    "Projekt",
    "Rechnung",
    "Rechnungsposition",
    "Rolle",
    "RollenBerechtigung",
    "Sitzung",
    "SollKalkulation",
    "Stuecklistenposition",
    "Stunden",
    "User",
    "UserRolle",
    "UtcDateTime",
    "Zahlungsplanposition",
    "ZeitstempelMixin",
]

# Alle Tabellen aus PLAN §5 plus die technisch nötigen (sitzungen, job_laeufe). Der Test
# tests/test_modelle.py vergleicht diese Liste mit Base.metadata – so fällt auf, wenn eine
# Tabelle im Schema fehlt oder eine unerwartete dazukommt.
ERWARTETE_TABELLEN = frozenset(
    {
        # Stammdaten
        "firmen",
        "kunden",
        "ansprechpartner",
        # Projekte
        "projekte",
        "zahlungsplan",
        "nachtraege",
        "meilensteine",
        "dokumente",
        # Fakturierung
        "rechnungen",
        "rechnungspos",
        "rechnung_absetzung",
        "nummernkreise",
        # Nachkalkulation
        "soll_kalkulation",
        "stueckliste",
        "ist_kosten",
        "stunden",
        # Anlagen und Fristen
        "anlagen",
        "fristen",
        # Firmen-Cockpit
        "fixkosten_plan",
        "datev_salden",
        "konten_mapping",
        "opos",
        # System
        "importlaeufe",
        "users",
        "rollen",
        "berechtigungen",
        "rollen_berechtigungen",
        "user_rollen",
        "audit_log",
        "sitzungen",
        "job_laeufe",
    }
)
