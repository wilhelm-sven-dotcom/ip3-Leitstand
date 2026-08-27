"""Projektbezeichnung, Anlagenart und die Sperre migriert-gestellter Positionen

Drei Änderungen, zwei aus dem Designsystem, eine aus einer Entscheidung Svens.

**Die beiden Felder** verlangt ``design/Projektliste.dc.html``, und PLAN §11 macht das
Designsystem verbindlich:

* ``projekte.bezeichnung`` – die Liste zeigt einen Projektnamen über dem Kunden
  („Freiflächenanlage Kirchendemenreuth" / „Agrar Weiß GbR"). Die Bestandsdateien führen keinen,
  das Feld bleibt für die migrierten Projekte leer, und die Anzeige fällt auf den Kundennamen
  zurück – so wie es die zweite Beispielzeile des Mockups ohnehin zeigt.
* ``projekte.anlagenart`` – die Liste filtert nach Aufdach, Aufdach + Speicher, Freifläche und
  Speicher. Aus PV- und Speicherdaten sind die ersten beiden und „speicher" ableitbar,
  **Freifläche nicht**: das steht in keinem Feld. Bei der Migration hilft ein Stichwortabgleich,
  ansonsten wird die Art in der Projektmaske gepflegt.

**Die Sperre** kommt aus docs/OFFENE-PUNKTE.md Nr. 5: die 150 Zahlungsplanpositionen, die der
Altbestand als „Rechnung gestellt" markiert, zählen ab Phase 2 zum Umsatz-Ist. Ändert jemand
Betrag oder Planmonat, verschiebt sich rückwirkend Umsatz zwischen Monaten – ohne Beleg, an dem
sich das nachvollziehen ließe. Nach dem Muster von 0002 sitzt die Sperre deshalb in einem
**Trigger** und nicht nur in der Anwendung: auch ein Importskript oder ein direkter Zugriff mit
einem Datenbankwerkzeug darf den Umsatz-Ist des Altbestands nicht verändern.

Erlaubt bleibt genau ein Weg: das Kennzeichen ``migriert_gestellt`` ausdrücklich zurücknehmen.
Danach ist die Position frei. Der Vorgang steht im Änderungsprotokoll, und die Rücknahme ist
eine eigene, sichtbare Entscheidung – kein Nebeneffekt einer Betragsänderung.

Revision: 0005
Vorgänger: 0004
Erstellt: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Der Meldungstext steht auch in app/datenbank_sperren.py; ein Test prüft, dass beide passen.
MELDUNG_GESTELLT = "migriert gestellte Zahlungsplanposition nicht aenderbar"

ANLAGENARTEN = (
    "aufdach",
    "aufdach_speicher",
    "freiflaeche",
    "speicher",
    "ladestation",
    "sonstig",
)

# Der zweite Meldungstext: Löschen entzieht dem Umsatz-Ist einen Betrag genauso still wie eine
# Betragsänderung, deshalb ist auch das gesperrt.
MELDUNG_GESTELLT_LOESCHEN = "migriert gestellte Zahlungsplanposition nicht loeschbar"

# Die fachlichen Felder der Position. Solange das Kennzeichen steht, müssen sie unverändert
# bleiben – gleich, was der übrige Teil des UPDATE tut.
_UNVERAENDERT = " AND ".join(
    f"NEW.{feld} IS OLD.{feld}"
    for feld in ("betrag_netto", "plan_monat", "bezeichnung", "gewerk", "art")
)

# Die Sperre greift, solange OLD.migriert_gestellt = 1 ist. Genau zwei Wege bleiben offen, und
# beide lassen die fachlichen Felder unangetastet:
#   * das Kennzeichen zurücknehmen – der ausdrückliche Weg zur Korrektur,
#   * die Position in Phase 3 mit einem echten Beleg verknüpfen; ab dann sperrt sie der Trigger
#     aus 0002.
# Ohne die Bedingung `_UNVERAENDERT` im zweiten Zweig ließe sich der Betrag im selben UPDATE
# mitverändern, in dem die Verknüpfung entsteht.
TRIGGER = {
    "trg_zahlungsplan_migriert_gestellt": f"""
    CREATE TRIGGER trg_zahlungsplan_migriert_gestellt
    BEFORE UPDATE ON zahlungsplan
    FOR EACH ROW
    WHEN OLD.migriert_gestellt = 1
         AND NOT (NEW.migriert_gestellt IS NOT 1 AND {_UNVERAENDERT})
         AND NOT (NEW.rechnung_id IS NOT OLD.rechnung_id AND {_UNVERAENDERT})
    BEGIN
        SELECT RAISE(ABORT, '{MELDUNG_GESTELLT}');
    END
""",
    "trg_zahlungsplan_migriert_gestellt_delete": f"""
    CREATE TRIGGER trg_zahlungsplan_migriert_gestellt_delete
    BEFORE DELETE ON zahlungsplan
    FOR EACH ROW
    WHEN OLD.migriert_gestellt = 1
    BEGIN
        SELECT RAISE(ABORT, '{MELDUNG_GESTELLT_LOESCHEN}');
    END
""",
}


def upgrade() -> None:
    with op.batch_alter_table("projekte", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bezeichnung", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("anlagenart", sa.String(length=50), nullable=True))
        batch_op.create_check_constraint(
            "anlagenart_wert",
            "(anlagenart IS NULL) OR (anlagenart IN ("
            + ", ".join(f"'{a}'" for a in ANLAGENARTEN)
            + "))",
        )
        batch_op.create_index(batch_op.f("ix_projekte_anlagenart"), ["anlagenart"], unique=False)

    for anweisung in TRIGGER.values():
        op.execute(anweisung.strip())


def downgrade() -> None:
    for name in TRIGGER:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table("projekte", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_projekte_anlagenart"))
        batch_op.drop_constraint("anlagenart_wert", type_="check")
        batch_op.drop_column("anlagenart")
        batch_op.drop_column("bezeichnung")
