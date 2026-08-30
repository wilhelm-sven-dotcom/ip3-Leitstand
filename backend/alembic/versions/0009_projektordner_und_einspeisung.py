"""Projektordner, eigene Anlagen und Einspeiseabrechnungen

Der Rest von Phase 7 (PLAN §7): der Doku-Vollständigkeitsscan und das Vergütungs-Controlling.

``projektordner`` trägt je Projekt, **ob** überhaupt ein Ordner gefunden wurde; die schon
vorhandene Tabelle ``dokumente`` trägt je Unterlage, ob sie darin liegt. Die Trennung ist keine
Feinheit: „kein Ordner" ist fast immer ein Namensproblem, „Ordner da, Unterlage fehlt" eine
echte Lücke in der Mappe – und beides in einer Meldung zusammenzuziehen hilft niemandem.

``dokumente`` bekommt dazu den eindeutigen Index über ``(projekt_id, typ)``. Er fehlte, weil die
Tabelle seit Phase 0 leer stand und niemand hineinschrieb. Ohne ihn legte jeder nächtliche Lauf
neue Zeilen an, statt den Befund zu aktualisieren. Als **Index** und nicht als Constraint, weil
SQLite dafür die Tabelle nicht kopieren muss.

``eigene_anlagen`` steht bewusst neben ``anlagen`` statt darin. Die dortigen Anlagen gehören
Kunden und sind Bezugspunkt für Service, Wartung und Gewährleistung – ``kunde_id`` ist dort
nicht ohne Grund NOT NULL. Eine eigene Anlage hätte dort keinen Kunden, keine Gewährleistung
und keinen Wartungsvertrag, dafür einen Vergütungssatz und eine Zählernummer. Eine gemeinsame
Tabelle wäre zur Hälfte leer und beide Auswertungen müssten dauernd filtern (Entscheidung 52).

**Bewusst nicht enthalten:** die von der Autogenerierung erneut vorgeschlagenen
``server_default``-Änderungen an ``rechnungen``. SQLite meldet dort einen Unterschied, der
keiner ist – und ein ``batch_alter_table`` auf dieser Tabelle würde sie kopieren und dabei die
Festschreibsperren aus 0002 und 0006 verlieren. Dieselbe Falle wie in 0008.

Revision: 0009
Vorgänger: 0008
Erstellt: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Eigene Spaltentypen (UtcDateTime, Cent) werden mit vollem Modulpfad geschrieben.
import app.modelle.basis

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERGUETUNGSARTEN = "verguetungsart IN ('einspeisung', 'direktvermarktung')"
MONAT = (
    "(monat IS NULL) OR ("
    "length(monat) = 7 AND substr(monat, 5, 1) = '-' "
    "AND substr(monat, 6, 2) >= '01' AND substr(monat, 6, 2) <= '12')"
)


def upgrade() -> None:
    # ------------------------------------------------------------------ Doku-Scan
    op.create_table(
        "projektordner",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projekt_id", sa.Integer(), nullable=False),
        sa.Column("pfad", sa.String(length=1000), nullable=True),
        sa.Column("gefunden", sa.Boolean(), nullable=False),
        sa.Column("dateien", sa.Integer(), nullable=False),
        sa.Column("mehrdeutig_mit", sa.String(length=1000), nullable=True),
        sa.Column("geprueft_am", sa.Date(), nullable=True),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            "(dateien IS NULL) OR (dateien >= 0)", name=op.f("ck_projektordner_dateien_positiv")
        ),
        sa.ForeignKeyConstraint(
            ["projekt_id"],
            ["projekte.id"],
            name=op.f("fk_projektordner_projekt_id_projekte"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projektordner")),
    )
    with op.batch_alter_table("projektordner", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_projektordner_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_projektordner_gefunden"), ["gefunden"], unique=False)
    op.create_index("uq_projektordner_projekt", "projektordner", ["projekt_id"], unique=True)

    # Ein reiner Index, kein Constraint: SQLite legt ihn an, ohne die Tabelle zu kopieren.
    op.create_index("uq_dokumente_projekt_typ", "dokumente", ["projekt_id", "typ"], unique=True)

    # ------------------------------------------------------- Eigene Bestandsanlagen
    op.create_table(
        "eigene_anlagen",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bezeichnung", sa.String(length=200), nullable=False),
        sa.Column("standort", sa.String(length=200), nullable=True),
        sa.Column("pv_kwp", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("speicher_kwh", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("inbetriebnahme", sa.Date(), nullable=True),
        sa.Column("verguetungsart", sa.String(length=50), nullable=False),
        sa.Column("verguetung_ct_kwh", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("vermarkter_entgelt_ct_kwh", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("zaehler_nr", sa.String(length=50), nullable=True),
        sa.Column("mastr_nr", sa.String(length=50), nullable=True),
        sa.Column("netzbetreiber", sa.String(length=200), nullable=True),
        sa.Column("vermarkter", sa.String(length=200), nullable=True),
        sa.Column("aktiv", sa.Boolean(), nullable=False),
        sa.Column("bemerkung", sa.String(length=1000), nullable=True),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            VERGUETUNGSARTEN, name=op.f("ck_eigene_anlagen_verguetungsart_wert")
        ),
        sa.CheckConstraint(
            "(pv_kwp IS NULL) OR (pv_kwp >= 0)", name=op.f("ck_eigene_anlagen_pv_kwp_positiv")
        ),
        sa.CheckConstraint(
            "(speicher_kwh IS NULL) OR (speicher_kwh >= 0)",
            name=op.f("ck_eigene_anlagen_speicher_kwh_positiv"),
        ),
        sa.CheckConstraint(
            "(verguetung_ct_kwh IS NULL) OR (verguetung_ct_kwh >= 0)",
            name=op.f("ck_eigene_anlagen_verguetung_ct_kwh_positiv"),
        ),
        sa.CheckConstraint(
            "(vermarkter_entgelt_ct_kwh IS NULL) OR (vermarkter_entgelt_ct_kwh >= 0)",
            name=op.f("ck_eigene_anlagen_vermarkter_entgelt_ct_kwh_positiv"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eigene_anlagen")),
        sa.UniqueConstraint("bezeichnung", name="uq_eigene_anlagen_bezeichnung"),
    )
    with op.batch_alter_table("eigene_anlagen", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_eigene_anlagen_aktiv"), ["aktiv"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_eigene_anlagen_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_eigene_anlagen_inbetriebnahme"), ["inbetriebnahme"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_eigene_anlagen_mastr_nr"), ["mastr_nr"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_eigene_anlagen_verguetungsart"), ["verguetungsart"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_eigene_anlagen_zaehler_nr"), ["zaehler_nr"], unique=False
        )

    op.create_table(
        "einspeise_abrechnungen",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anlage_id", sa.Integer(), nullable=False),
        sa.Column("monat", sa.String(length=7), nullable=False),
        sa.Column("kwh", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("betrag_cent", app.modelle.basis.Cent(), nullable=False),
        sa.Column("bezahlt_am", sa.Date(), nullable=True),
        sa.Column("quelle_datei", sa.String(length=1000), nullable=True),
        sa.Column("eingelesen_am", app.modelle.basis.UtcDateTime(), nullable=True),
        sa.Column("bemerkung", sa.String(length=1000), nullable=True),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint(MONAT, name=op.f("ck_einspeise_abrechnungen_monat_format")),
        sa.CheckConstraint(
            "(kwh IS NULL) OR (kwh >= 0)", name=op.f("ck_einspeise_abrechnungen_kwh_positiv")
        ),
        sa.ForeignKeyConstraint(
            ["anlage_id"],
            ["eigene_anlagen.id"],
            name=op.f("fk_einspeise_abrechnungen_anlage_id_eigene_anlagen"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_einspeise_abrechnungen")),
        sa.UniqueConstraint(
            "anlage_id", "monat", name="uq_einspeise_abrechnungen_anlage_monat"
        ),
    )
    with op.batch_alter_table("einspeise_abrechnungen", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_einspeise_abrechnungen_anlage_id"), ["anlage_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_einspeise_abrechnungen_bezahlt_am"), ["bezahlt_am"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_einspeise_abrechnungen_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_einspeise_abrechnungen_monat"), ["monat"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("einspeise_abrechnungen", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_einspeise_abrechnungen_monat"))
        batch_op.drop_index(batch_op.f("ix_einspeise_abrechnungen_created_at"))
        batch_op.drop_index(batch_op.f("ix_einspeise_abrechnungen_bezahlt_am"))
        batch_op.drop_index(batch_op.f("ix_einspeise_abrechnungen_anlage_id"))
    op.drop_table("einspeise_abrechnungen")

    with op.batch_alter_table("eigene_anlagen", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eigene_anlagen_zaehler_nr"))
        batch_op.drop_index(batch_op.f("ix_eigene_anlagen_verguetungsart"))
        batch_op.drop_index(batch_op.f("ix_eigene_anlagen_mastr_nr"))
        batch_op.drop_index(batch_op.f("ix_eigene_anlagen_inbetriebnahme"))
        batch_op.drop_index(batch_op.f("ix_eigene_anlagen_created_at"))
        batch_op.drop_index(batch_op.f("ix_eigene_anlagen_aktiv"))
    op.drop_table("eigene_anlagen")

    op.drop_index("uq_dokumente_projekt_typ", table_name="dokumente")

    op.drop_index("uq_projektordner_projekt", table_name="projektordner")
    with op.batch_alter_table("projektordner", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_projektordner_gefunden"))
        batch_op.drop_index(batch_op.f("ix_projektordner_created_at"))
    op.drop_table("projektordner")
