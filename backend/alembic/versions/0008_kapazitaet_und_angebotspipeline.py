"""Kapazität je Woche und Angebotspipeline

Phase 7 bringt zwei Tabellen, die dieselbe Frage von zwei Seiten stellen – **reicht es?**

``mitarbeiter`` trägt die Wochenstunden, die tatsächlich zur Verfügung stehen. Sie stehen in der
Datenbank und nicht in der ``config.toml``, weil sie sich häufiger ändern als eine Konfiguration
und weil sie gepflegt werden sollen, ohne dass jemand auf den Host muss (Entscheidung 40).

``angebote`` trägt die Pipeline. ``angebot_nr`` ist eindeutig, damit ein erneuter Import dieselbe
Zeile wiedererkennt statt eine zweite anzulegen; NULL bleibt mehrfach erlaubt, weil ein von Hand
erfasstes Angebot keine Nummer aus dem Angebots-Tool hat. ``summe_netto`` ist die eine Ausnahme
von der Regel, dass Geldbeträge negativ sein dürfen: ein Angebot über einen Minusbetrag gibt es
nicht, und ein Vorzeichenfehler im Import würde die Pipeline stillschweigend kleinrechnen.

**Bewusst nicht enthalten:** die von der Autogenerierung vorgeschlagenen ``server_default``-
Änderungen an ``rechnungen``. SQLite meldet dort einen Unterschied, der keiner ist – und ein
``batch_alter_table`` auf dieser Tabelle würde sie kopieren und dabei die Festschreibsperren aus
0002 und 0006 verlieren. Genau das musste 0006 schon einmal mühsam nachziehen.

Revision: 0008
Vorgänger: 0007
Erstellt: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Eigene Spaltentypen (UtcDateTime, Cent) werden mit vollem Modulpfad geschrieben.
import app.modelle.basis

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SATZGRUPPEN = (
    "(satzgruppe IS NULL) OR "
    "(satzgruppe IN ('monteur', 'obermonteur', 'elektriker', 'planung'))"
)
MONAT = (
    "(erwarteter_monat IS NULL) OR ("
    "length(erwarteter_monat) = 7 AND substr(erwarteter_monat, 5, 1) = '-' "
    "AND substr(erwarteter_monat, 6, 2) >= '01' "
    "AND substr(erwarteter_monat, 6, 2) <= '12')"
)


def upgrade() -> None:
    op.create_table(
        "mitarbeiter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("satzgruppe", sa.String(length=50), nullable=True),
        sa.Column("wochenstunden", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("aktiv", sa.Boolean(), nullable=False),
        sa.Column("von", sa.Date(), nullable=True),
        sa.Column("bis", sa.Date(), nullable=True),
        sa.Column("bemerkung", sa.String(length=1000), nullable=True),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint(SATZGRUPPEN, name=op.f("ck_mitarbeiter_satzgruppe_wert")),
        sa.CheckConstraint(
            "(wochenstunden IS NULL) OR (wochenstunden >= 0)",
            name=op.f("ck_mitarbeiter_wochenstunden_positiv"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mitarbeiter")),
        sa.UniqueConstraint("name", name="uq_mitarbeiter_name"),
    )
    with op.batch_alter_table("mitarbeiter", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_mitarbeiter_aktiv"), ["aktiv"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_mitarbeiter_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_mitarbeiter_satzgruppe"), ["satzgruppe"], unique=False
        )

    op.create_table(
        "angebote",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("angebot_nr", sa.String(length=50), nullable=True),
        sa.Column("kunde_id", sa.Integer(), nullable=True),
        sa.Column("kunde_name", sa.String(length=200), nullable=False),
        sa.Column("bezeichnung", sa.String(length=200), nullable=True),
        sa.Column("summe_netto", app.modelle.basis.Cent(), nullable=False),
        sa.Column("wahrscheinlichkeit_promille", sa.Integer(), nullable=False),
        sa.Column("erwarteter_monat", sa.String(length=7), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("projekt_id", sa.Integer(), nullable=True),
        sa.Column("quelle_datei", sa.String(length=1000), nullable=True),
        sa.Column("eingelesen_am", app.modelle.basis.UtcDateTime(), nullable=True),
        sa.Column("bemerkung", sa.String(length=1000), nullable=True),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint(MONAT, name=op.f("ck_angebote_erwarteter_monat_format")),
        sa.CheckConstraint(
            "status IN ('offen', 'gewonnen', 'verloren')",
            name=op.f("ck_angebote_status_wert"),
        ),
        sa.CheckConstraint(
            "(summe_netto IS NULL) OR (summe_netto >= 0)",
            name=op.f("ck_angebote_summe_netto_positiv"),
        ),
        sa.ForeignKeyConstraint(
            ["kunde_id"], ["kunden.id"], name=op.f("fk_angebote_kunde_id_kunden")
        ),
        sa.ForeignKeyConstraint(
            ["projekt_id"], ["projekte.id"], name=op.f("fk_angebote_projekt_id_projekte")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_angebote")),
        sa.UniqueConstraint("angebot_nr", name=op.f("uq_angebote_angebot_nr")),
    )
    with op.batch_alter_table("angebote", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_angebote_created_at"), ["created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_angebote_erwarteter_monat"), ["erwarteter_monat"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_angebote_kunde_id"), ["kunde_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_angebote_projekt_id"), ["projekt_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_angebote_status"), ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("angebote", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_angebote_status"))
        batch_op.drop_index(batch_op.f("ix_angebote_projekt_id"))
        batch_op.drop_index(batch_op.f("ix_angebote_kunde_id"))
        batch_op.drop_index(batch_op.f("ix_angebote_erwarteter_monat"))
        batch_op.drop_index(batch_op.f("ix_angebote_created_at"))
    op.drop_table("angebote")

    with op.batch_alter_table("mitarbeiter", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mitarbeiter_satzgruppe"))
        batch_op.drop_index(batch_op.f("ix_mitarbeiter_created_at"))
        batch_op.drop_index(batch_op.f("ix_mitarbeiter_aktiv"))
    op.drop_table("mitarbeiter")
