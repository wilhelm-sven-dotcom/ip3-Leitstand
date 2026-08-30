"""Berechtigungskatalog (PLAN §4).

Die einzige Liste aller Berechtigungsschlüssel. Was hier nicht steht, gibt es nicht: der Seed legt
genau diese Einträge an, und ein Test verlangt, dass jeder im Code geprüfte Schlüssel hier
vorkommt und umgekehrt kein Eintrag ungenutzt bleibt.

Schlüssel folgen dem Muster ``ressource.aktion``. Geprüft wird immer gegen Schlüssel, nie gegen
Rollennamen – nur so lässt sich später eine vierte Rolle anlegen, ohne Code zu ändern.

**Finanzsichtbarkeit ist von der Projektsicht getrennt** (PLAN §4). Deshalb gibt es neben
``projekte.lesen`` den eigenen Schlüssel ``projekte.werte_lesen``: ein Monteur oder Planer soll
Termine und Anlagendaten sehen können, ohne Auftragswerte und Margen. Siehe
docs/OFFENE-PUNKTE.md Nr. 1.

Der Sichtbarkeits-Scope (``alle`` oder ``eigene``) hängt an der Zuordnung Rolle → Berechtigung,
nicht am Schlüssel selbst: dieselbe Berechtigung kann für eine Rolle alle Projekte und für eine
andere nur die eigenen umfassen.
"""

from __future__ import annotations

from typing import NamedTuple


class Berechtigungsdefinition(NamedTuple):
    schluessel: str
    beschreibung: str
    # Für welche Phase die Berechtigung gedacht ist – nur Dokumentation, damit beim Lesen klar
    # ist, warum ein Schlüssel noch von keiner Route verwendet wird.
    phase: int


KATALOG: tuple[Berechtigungsdefinition, ...] = (
    # Projekte und Stammdaten
    Berechtigungsdefinition("projekte.lesen", "Projekte und Termine ansehen", 1),
    Berechtigungsdefinition(
        "projekte.werte_lesen", "Auftragswerte und Zahlungsplanbeträge ansehen", 1
    ),
    Berechtigungsdefinition("projekte.schreiben", "Projekte anlegen und bearbeiten", 1),
    Berechtigungsdefinition("kunden.lesen", "Kunden und Ansprechpartner ansehen", 1),
    Berechtigungsdefinition("kunden.schreiben", "Kunden und Ansprechpartner pflegen", 1),
    Berechtigungsdefinition("zahlungsplan.schreiben", "Zahlungsplan und Nachträge pflegen", 1),
    Berechtigungsdefinition("meilensteine.schreiben", "Termine und Status pflegen", 1),
    # Umsatz und Auswertung
    Berechtigungsdefinition("umsatz.lesen", "Umsatz, Forecast und Auftragsbestand ansehen", 2),
    Berechtigungsdefinition("nachkalkulation.lesen", "Nachkalkulation und Margen ansehen", 4),
    Berechtigungsdefinition("cockpit.lesen", "Firmen-Cockpit ansehen", 5),
    # Fakturierung
    Berechtigungsdefinition("rechnungen.lesen", "Belege ansehen", 3),
    Berechtigungsdefinition("rechnungen.erstellen", "Belege als Entwurf erstellen", 3),
    Berechtigungsdefinition(
        "rechnungen.festschreiben", "Belege festschreiben (Nummer, Hash, Sperre)", 3
    ),
    Berechtigungsdefinition("rechnungen.stornieren", "Belege stornieren und Gutschriften", 3),
    # Service und Anlagen
    Berechtigungsdefinition("anlagen.lesen", "Anlagenregister und Fristen ansehen", 6),
    Berechtigungsdefinition("anlagen.schreiben", "Anlagen, Serviceaufträge und Fristen pflegen", 6),
    # Kapazität und Pipeline
    Berechtigungsdefinition("kapazitaet.lesen", "Wochenauslastung und Mannschaft ansehen", 7),
    Berechtigungsdefinition("kapazitaet.schreiben", "Mitarbeiter und Wochenstunden pflegen", 7),
    Berechtigungsdefinition("angebote.lesen", "Angebotspipeline ansehen", 7),
    Berechtigungsdefinition("angebote.schreiben", "Angebote pflegen und einlesen", 7),
    # Eigene Bestandsanlagen. Getrennt von `anlagen.*`: dort geht es um Kundenanlagen und
    # Service, hier um eigene Erlöse – und Erlöse sind dem Team entzogen (PLAN §4).
    Berechtigungsdefinition("einspeisung.lesen", "Eigene Anlagen und ihre Vergütung ansehen", 7),
    Berechtigungsdefinition(
        "einspeisung.schreiben", "Eigene Anlagen pflegen und Abrechnungen einlesen", 7
    ),
    # Daten und Betrieb
    Berechtigungsdefinition("importe.ausfuehren", "Importe starten (DATEV, TimeTac, Migration)", 1),
    Berechtigungsdefinition("systemstatus.lesen", "Datenstand und Hintergrundläufe ansehen", 0),
    Berechtigungsdefinition("stammdaten.schreiben", "Fixkosten und Kontenzuordnung pflegen", 5),
    # Verwaltung
    Berechtigungsdefinition("admin.nutzer", "Nutzer und Rollen verwalten", 0),
    Berechtigungsdefinition("admin.konfiguration", "Konfiguration ansehen und ändern", 0),
    Berechtigungsdefinition("admin.jobs", "Hintergrundläufe von Hand starten", 0),
)

SCHLUESSEL: frozenset[str] = frozenset(eintrag.schluessel for eintrag in KATALOG)


def beschreibung(schluessel: str) -> str:
    for eintrag in KATALOG:
        if eintrag.schluessel == schluessel:
            return eintrag.beschreibung
    raise KeyError(f"Unbekannte Berechtigung: {schluessel}")


def pruefe_bekannt(schluessel: str) -> str:
    """Schlüssel gegen den Katalog prüfen.

    Wird von :func:`app.sicherheit.abhaengigkeiten.benoetigt` aufgerufen und schlägt beim Start
    der Anwendung zu, nicht erst bei der ersten Anfrage: ein Tippfehler in einem
    Berechtigungsschlüssel würde sonst eine Route unbemerkt für alle öffnen oder für alle sperren.
    """
    if schluessel not in SCHLUESSEL:
        raise KeyError(
            f"Die Berechtigung '{schluessel}' steht nicht im Katalog "
            "(app/sicherheit/katalog.py). Entweder ist der Name falsch geschrieben, oder die "
            "Berechtigung muss dort ergänzt und im Seed verteilt werden."
        )
    return schluessel


# --------------------------------------------------------------------------------------------
# Rollen für den Seed (PLAN §4). V1 kommt ohne Rollenpflege-Oberfläche aus; das Modell steht
# bereits, sodass weitere Rollen später ohne Codeänderung möglich sind.
# --------------------------------------------------------------------------------------------


class Rollendefinition(NamedTuple):
    name: str
    beschreibung: str
    # Schlüssel mit Scope. None bedeutet 'alle' (der Scope ist dann nicht eingeschränkt).
    rechte: tuple[tuple[str, str | None], ...]


def _alle(*schluessel: str) -> tuple[tuple[str, str | None], ...]:
    return tuple((s, None) for s in schluessel)


ADMIN_RECHTE = _alle(*sorted(SCHLUESSEL))

BUCHHALTUNG_RECHTE = _alle(
    "projekte.lesen",
    "projekte.werte_lesen",
    "projekte.schreiben",
    "kunden.lesen",
    "kunden.schreiben",
    "zahlungsplan.schreiben",
    "meilensteine.schreiben",
    "umsatz.lesen",
    "rechnungen.lesen",
    "rechnungen.erstellen",
    "rechnungen.festschreiben",
    "anlagen.lesen",
    "kapazitaet.lesen",
    "einspeisung.lesen",
    "einspeisung.schreiben",
    "importe.ausfuehren",
    "systemstatus.lesen",
)

# Lesen mit Scope 'alle', aber ohne Beträge, ohne Nachkalkulation, ohne Cockpit (PLAN §4).
TEAM_RECHTE = _alle(
    "projekte.lesen",
    "kunden.lesen",
    "anlagen.lesen",
    # Die Wochenauslastung zeigt Stunden, keine Beträge – sie ist der eigene Terminplan
    # und nicht Teil der Finanzsichtbarkeit (PLAN §4).
    "kapazitaet.lesen",
    "systemstatus.lesen",
)

SEED_ROLLEN: tuple[Rollendefinition, ...] = (
    Rollendefinition(
        "admin",
        "Geschäftsführung: alle Berechtigungen inklusive Konfiguration, Fixkosten, "
        "Nutzerverwaltung und Stornofreigabe",
        ADMIN_RECHTE,
    ),
    Rollendefinition(
        "buchhaltung",
        "Kunden, Projekte und Zahlungsplan pflegen, Fakturierung inklusive Festschreibung, "
        "Importe ausführen",
        BUCHHALTUNG_RECHTE,
    ),
    Rollendefinition(
        "team",
        "Lesender Zugriff auf Projekte und Termine ohne Beträge, ohne Nachkalkulation, "
        "ohne Firmen-Cockpit",
        TEAM_RECHTE,
    ),
)


def markdown_uebersicht() -> str:
    """Berechtigungsübersicht als Markdown für ``docs/BERECHTIGUNGEN.md``.

    Erzeugt statt gepflegt: eine handgeschriebene Tabelle wäre nach der zweiten Änderung falsch,
    und falsche Dokumentation über Berechtigungen ist schlimmer als keine.
    """
    zeilen: list[str] = [
        "# Berechtigungen",
        "",
        "**Diese Datei wird erzeugt.** Sie entsteht aus `backend/app/sicherheit/katalog.py`",
        "beim Ausführen von `ip3-leitstand berechtigungen-doku`. Änderungen hier gehen verloren.",
        "",
        "Berechtigungen sind Schlüssel nach dem Muster `ressource.aktion`. Jede Route und jede",
        "Aktion prüft gegen diese Schlüssel, nie gegen Rollennamen (PLAN §4). Der",
        "Sichtbarkeits-Scope `eigene` beschränkt auf Datensätze, bei denen der Nutzer als",
        "Projektleiter eingetragen ist.",
        "",
        "## Rollen",
        "",
        "| Rolle | Beschreibung |",
        "|---|---|",
    ]
    for rolle in SEED_ROLLEN:
        zeilen.append(f"| `{rolle.name}` | {rolle.beschreibung} |")

    spaltenkoepfe = ["Berechtigung", "Bedeutung", "Ab Phase", *(r.name for r in SEED_ROLLEN)]
    zeilen += [
        "",
        "## Berechtigungen je Rolle",
        "",
        "| " + " | ".join(spaltenkoepfe) + " |",
        "|" + "---|" * len(spaltenkoepfe),
    ]

    for eintrag in sorted(KATALOG):
        rechte_der_rollen = [
            "ja" if any(s == eintrag.schluessel for s, _ in rolle.rechte) else "–"
            for rolle in SEED_ROLLEN
        ]
        spalten = [
            f"`{eintrag.schluessel}`",
            eintrag.beschreibung,
            str(eintrag.phase),
            *rechte_der_rollen,
        ]
        zeilen.append("| " + " | ".join(spalten) + " |")

    zeilen += [
        "",
        "## Hinweise",
        "",
        "- `projekte.werte_lesen` ist von `projekte.lesen` getrennt, damit Mitarbeiter",
        "  Projektdaten und Termine sehen können, ohne Auftragswerte und Margen zu sehen.",
        "- Fehlt eine Berechtigung, blendet die Oberfläche das Element aus; ausgegraute",
        "  Schaltflächen gibt es nicht.",
        "- Die Prüfung erfolgt ausschließlich serverseitig. Das Frontend blendet nur",
        "  zusätzlich aus.",
        "",
    ]
    return "\n".join(zeilen)
