"""Eindeutigkeit der Ist-Kosten je Projekt, Quelle, Monat und Referenz

Phase 4 füllt ``ist_kosten`` zum ersten Mal. Die Regel dazu steht in PLAN §8: **jeder Lauf
ersetzt seinen Zeitraum, statt anzuhängen.** Umgesetzt ist sie im Import – vor dem Einfügen wird
der Monat gelöscht, in derselben Schreibtransaktion.

Diese Migration zieht den Riegel auf Datenbankebene nach. Er ist ausdrücklich **nicht** die
eigentliche Absicherung, sondern der Fangnetz-Fall: wenn ein künftiger Importweg das Löschen
vergisst, entstehen doppelte Beträge, und eine doppelte Zahl in der Nachkalkulation fällt
niemandem auf – sie sieht aus wie ein teures Projekt. Ein Fehlschlag beim Einfügen dagegen fällt
sofort auf.

Die Referenz gehört in den Schlüssel, weil je Projekt und Monat mehrere Zeilen entstehen: aus
DATEV eine je Konto, aus der Stückliste die Lagerbewertung, aus TimeTac die Arbeitsstunden.

``render_as_batch`` wie in den bisherigen Migrationen: SQLite kennt kein ``ADD CONSTRAINT``, die
Tabelle wird kopiert. An ``ist_kosten`` hängen keine Trigger, es ist also anders als bei 0006
kein Nachziehen nötig.

Revision: 0007
Vorgänger: 0006
Erstellt: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEDINGUNG = "uq_ist_kosten_projekt_id_quelle_monat_referenz"


def upgrade() -> None:
    with op.batch_alter_table("ist_kosten", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            BEDINGUNG, ["projekt_id", "quelle", "monat", "referenz"]
        )


def downgrade() -> None:
    with op.batch_alter_table("ist_kosten", schema=None) as batch_op:
        batch_op.drop_constraint(BEDINGUNG, type_="unique")
