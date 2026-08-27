"""Herkunft und Gestellt-Kennzeichen am Zahlungsplan

Die Auftragsliste markiert 150 ihrer 280 Zeilen mit einem Kreuz in der Spalte „erledigt". Laut
Sven heißt das „Rechnung gestellt" (docs/OFFENE-PUNKTE.md Nr. 9); die zugehörigen Belege
entstanden vor der Einführung des Leitstands und liegen hier nicht vor.

Damit fehlt eine Stelle, an der das stehen kann: PLAN §6.7 rechnet den Umsatz-Ist aus
festgeschriebenen Rechnungen, und die gibt es für den Altbestand nicht. Ein erfundener Beleg mit
erfundener Nummer wäre der falsche Weg – Rechnungsnummern müssen lückenlos sein, und das alte
Schema ist noch nicht entschieden. Also trägt die Zahlungsplanposition selbst das Kennzeichen:

* ``quelle_migration`` nennt Datei und Zeile, aus der die Position stammt.
* ``migriert_gestellt`` sagt, ob sie im Altbestand als berechnet markiert war. NULL bedeutet
  „keine Migrationsposition"; der Zahlungsstatus bleibt offen, bis der OPOS-Import in Phase 5
  ihn liefert.

Nur zwei neue Spalten, keine geänderte Prüfbedingung – ein Tabellenneubau ist nicht nötig.

Revision: 0004
Vorgänger: 0003
Erstellt: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("zahlungsplan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("quelle_migration", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("migriert_gestellt", sa.Boolean(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_zahlungsplan_migriert_gestellt"), ["migriert_gestellt"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("zahlungsplan", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_zahlungsplan_migriert_gestellt"))
        batch_op.drop_column("migriert_gestellt")
        batch_op.drop_column("quelle_migration")
