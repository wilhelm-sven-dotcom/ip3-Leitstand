"""Felder, die die Bestandsdateien der Migration erzwingen

Drei Nachzüge am Schema aus 0001, alle an den echten Quelldateien (PLAN §9) nachgemessen und
nicht angenommen:

1. ``meilensteine.erledigt`` – die Teamliste kennt in den Status- und Terminspalten nur Kreuze
   ohne Datum. Ein erfundenes ``erledigt_am`` wäre eine Falschangabe, und ``erledigt_am IS
   NULL`` als „nicht erledigt" zu lesen würde die Kreuze verschlucken: allein bei der Abnahme
   über 450 Projekte. NULL heißt unbekannt, ``0`` ausdrücklich offen, ``1`` erledigt.

2. Erweiterung der erlaubten Meilenstein-Typen um die acht Spalten des Terminblocks
   (AC–AJ: Montage Unterkonstruktion und Elektro, Zählerschrank, Lieferung von
   Unterkonstruktion, Wechselrichter PV und Speicher, Speicher, Wallbox). Wegen
   ``UNIQUE(projekt_id, typ)`` würden diese acht Spalten unter den Sammeltypen ``montage`` und
   ``lieferung`` beim Import auf zwei Zeilen zusammenfallen.

3. ``projekte.speicher_typ`` – die Speicherspalte der Teamliste führt eine
   Produktbezeichnung ('2x BYD HVM 22.1'), keine Zahl. Die Kapazität wird daraus gelesen und
   bleibt in ``speicher_kwh``; die Bezeichnung benennt das verbaute Gerät und wird für Service
   und Gewährleistung gebraucht.

Die Änderung der CHECK-Bedingung erzwingt unter SQLite einen Tabellenneubau. Der läuft über
``batch_alter_table`` mit ``copy_from``: damit steht die alte Struktur im Skript und muss nicht
aus der Datenbank gelesen werden – ein Lauf auf einer leicht abweichenden Datenbank scheitert
dann sichtbar statt stillschweigend etwas anderes zu bauen.

Revision: 0003
Vorgänger: 0002
Erstellt: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.modelle.basis

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPEN_ALT = (
    "uebergabetermin",
    "freigabe_planung",
    "plan_erstellt",
    "anmeldung_nb",
    "mastr",
    "lieferung",
    "montage",
    "fertigmeldung",
    "zaehler",
    "abnahme",
    "inbetriebnahme",
)

TYPEN_NEU = (
    "uebergabetermin",
    "freigabe_planung",
    "plan_erstellt",
    "anmeldung_nb",
    "mastr",
    "fertigmeldung",
    "zaehler",
    "abnahme",
    "montage_uk",
    "montage_elektro",
    "zaehlerschrank",
    "lieferung_uk",
    "lieferung_wr_pv",
    "lieferung_wr_speicher",
    "lieferung_speicher",
    "lieferung_wallbox",
    "montage",
    "lieferung",
    "inbetriebnahme",
)


def _bedingung(typen: tuple[str, ...]) -> str:
    return "typ IN (" + ", ".join(f"'{t}'" for t in typen) + ")"


def _meilensteine_alt() -> sa.Table:
    """Struktur der Tabelle vor dieser Revision, wie 0001 sie angelegt hat."""
    # Dasselbe Namensschema wie die Anwendung, sonst heißt die CHECK-Bedingung hier anders als
    # in der Datenbank und der Neubau findet sie nicht.
    return sa.Table(
        "meilensteine",
        sa.MetaData(naming_convention=app.modelle.basis.NAMENSSCHEMA),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projekt_id", sa.Integer(), nullable=False),
        sa.Column("typ", sa.String(length=50), nullable=False),
        sa.Column("geplant_kw", sa.String(length=50), nullable=True),
        sa.Column("erledigt_am", sa.Date(), nullable=True),
        sa.Column("bemerkung", sa.String(length=1000), nullable=True),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint(_bedingung(TYPEN_ALT), name="typ_wert"),
        sa.ForeignKeyConstraint(
            ["projekt_id"],
            ["projekte.id"],
            name="fk_meilensteine_projekt_id_projekte",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_meilensteine"),
        sa.UniqueConstraint("projekt_id", "typ", name="uq_meilensteine_projekt_id_typ"),
        # Die Indizes gehören zwingend hierher: batch_alter_table baut die Tabelle nach dieser
        # Beschreibung neu auf und legt nur an, was hier steht. Ohne diese drei Zeilen wären die
        # Indizes aus 0001 nach der Revision verschwunden – lautlos, weil kein Fehler entsteht.
        sa.Index("ix_meilensteine_created_at", "created_at"),
        sa.Index("ix_meilensteine_erledigt_am", "erledigt_am"),
        sa.Index("ix_meilensteine_projekt_id", "projekt_id"),
    )


def upgrade() -> None:
    with op.batch_alter_table(
        "meilensteine", schema=None, copy_from=_meilensteine_alt()
    ) as batch_op:
        batch_op.add_column(sa.Column("erledigt", sa.Boolean(), nullable=True))
        batch_op.drop_constraint("typ_wert", type_="check")
        batch_op.create_check_constraint("typ_wert", _bedingung(TYPEN_NEU))
        batch_op.create_index(batch_op.f("ix_meilensteine_erledigt"), ["erledigt"], unique=False)

    with op.batch_alter_table("projekte", schema=None) as batch_op:
        batch_op.add_column(sa.Column("speicher_typ", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projekte", schema=None) as batch_op:
        batch_op.drop_column("speicher_typ")

    # Zurück auf die alte Typenliste. Zeilen mit einem der neuen Typen würden die alte
    # CHECK-Bedingung verletzen, deshalb werden sie vorher auf die Sammeltypen abgebildet –
    # Datenverlust in der Feinheit, aber kein Abbruch mitten im Tabellenneubau.
    op.execute(
        "UPDATE meilensteine SET typ = 'montage' "
        "WHERE typ IN ('montage_uk', 'montage_elektro', 'zaehlerschrank')"
    )
    op.execute(
        "UPDATE meilensteine SET typ = 'lieferung' "
        "WHERE typ IN ('lieferung_uk', 'lieferung_wr_pv', 'lieferung_wr_speicher', "
        "'lieferung_speicher', 'lieferung_wallbox')"
    )
    # Der Tabellenneubau würde sonst an UNIQUE(projekt_id, typ) scheitern.
    op.execute(
        "DELETE FROM meilensteine WHERE id NOT IN "
        "(SELECT MIN(id) FROM meilensteine GROUP BY projekt_id, typ)"
    )

    neu = _meilensteine_alt()
    neu.append_column(sa.Column("erledigt", sa.Boolean(), nullable=True))
    sa.Index("ix_meilensteine_erledigt", neu.c.erledigt)
    for bedingung in list(neu.constraints):
        if isinstance(bedingung, sa.CheckConstraint):
            neu.constraints.discard(bedingung)
    neu.append_constraint(
        sa.CheckConstraint(_bedingung(TYPEN_NEU), name="typ_wert")
    )
    with op.batch_alter_table("meilensteine", schema=None, copy_from=neu) as batch_op:
        batch_op.drop_index(batch_op.f("ix_meilensteine_erledigt"))
        batch_op.drop_constraint("typ_wert", type_="check")
        batch_op.create_check_constraint("typ_wert", _bedingung(TYPEN_ALT))
        batch_op.drop_column("erledigt")
