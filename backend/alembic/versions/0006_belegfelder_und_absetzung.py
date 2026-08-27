"""Belegfelder, Absetzungsblock und die nachgezogenen Festschreibsperren

Phase 3 macht aus dem vorbereiteten Belegschema ein benutztes. Vier Dinge fehlten dafür:

* **Der Empfänger am Beleg.** ``rechnungen.kunde_id``: eine Servicerechnung kann ohne Projekt
  entstehen (PLAN §10) und hätte sonst keinen Adressaten. Der ``kunde_snapshot`` ist die Kopie
  für den Beleg, kein Schlüssel, über den sich suchen und filtern ließe.
* **Das Steuerkennzeichen am Beleg** (``ust_kz``, PLAN §6.2). Vorbelegt aus dem Projekt, danach
  eingefroren: ändert jemand später das Kennzeichen am Projekt, bleibt ein ausgestellter Beleg
  richtig.
* **Der Absetzungsblock** als eigene Tabelle ``rechnung_absetzung`` (§ 14 Abs. 5 UStG,
  PLAN §6.1). Gespeichert statt beim Anzeigen abgeleitet – ein später entstehender Abschlag darf
  eine festgeschriebene Schlussrechnung nicht rückwirkend verändern.
* **Summen, die auf dem Papier stehen**: ``ust_details`` (Aufteilung je Steuersatz),
  ``absetzung_netto``, ``absetzung_ust`` und ``zahlbetrag``. Ohne sie müsste jede Anzeige und
  jedes erneute Rendern nachrechnen, und eine Rundungsänderung in einer künftigen Phase würde
  alte Belege verändern.

**Die Trigger aus 0002 werden neu erzeugt, nicht nur ergänzt.** Zwei Gründe:

1. ``batch_alter_table`` baut die Tabelle ``rechnungen`` in SQLite neu auf (Kopie, Drop,
   Umbenennung). Die daran hängenden Trigger verschwinden dabei. Ohne Neuanlage wäre der
   festgeschriebene Beleg nach dieser Migration **ungeschützt** – und niemand würde es merken,
   weil nichts fehlschlägt.
2. ``trg_rechnungen_storno_nur_status`` zählt die Felder auf, die ein Storno nicht verändern
   darf. Die neuen Betragsspalten gehören dazu, sonst ist der Storno ein Schlupfloch, um einen
   festgeschriebenen Beleg umzuschreiben.

Der Absetzungsblock bekommt dieselbe Sperre wie die Positionen: an einem festgeschriebenen Beleg
ist er unveränderbar, unlöschbar und nicht erweiterbar.

Revision: 0006
Vorgänger: 0005
Erstellt: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.modelle.basis

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UST_KENNZEICHEN = ("19", "0", "13b", "gemischt")

# Die Meldungstexte der Trigger aus 0002 werden hier wörtlich wiederholt, weil die Trigger neu
# erzeugt werden. Sie stehen ebenfalls in app/datenbank_sperren.py; test_trigger.py prüft, dass
# Migrationen und Übersetzung deckungsgleich bleiben.
MELDUNG_RECHNUNG_UPDATE = "festgeschriebene Rechnung nicht aenderbar"
MELDUNG_RECHNUNG_DELETE = "festgeschriebene Rechnung nicht loeschbar"
MELDUNG_ABSETZUNG_UPDATE = "Absetzung einer festgeschriebenen Rechnung nicht aenderbar"
MELDUNG_ABSETZUNG_DELETE = "Absetzung einer festgeschriebenen Rechnung nicht loeschbar"
MELDUNG_ABSETZUNG_NEU = "keine Absetzung an einer festgeschriebenen Rechnung"
MELDUNG_POSITION_UPDATE = "Position einer festgeschriebenen Rechnung nicht aenderbar"
MELDUNG_POSITION_DELETE = "Position einer festgeschriebenen Rechnung nicht loeschbar"
MELDUNG_POSITION_NEU = "keine Position an einer festgeschriebenen Rechnung"

# Beim Storno unveränderliche Felder. Erlaubt bleibt der Statuswechsel samt storno_ref.
_STORNO_TABU = (
    "rechnung_nr",
    "netto",
    "ust",
    "brutto",
    "ust_details",
    "absetzung_netto",
    "absetzung_ust",
    "zahlbetrag",
    "datum",
    "hash",
    "festgeschrieben_am",
    "art",
    "firma_id",
    "projekt_id",
    "kunde_id",
    "ust_kz",
    "kunde_snapshot",
)

_STORNO_BEDINGUNG = "\n                  OR ".join(
    f"NEW.{feld} IS NOT OLD.{feld}" for feld in _STORNO_TABU
)

# Trigger aus 0002, die vor dem Tabellenumbau weichen müssen. Nicht nur die auf ``rechnungen``:
# auch die auf ``rechnungspos``, weil ihr Rumpf ``rechnungen`` abfragt. SQLite prüft beim
# ``ALTER TABLE ... RENAME`` alle Trigger der Datenbank und bricht ab, solange einer davon auf
# eine Tabelle zeigt, die es in diesem Moment nicht gibt ("no such table: main.rechnungen").
NACHGEZOGEN = (
    "trg_rechnungen_festgeschrieben_update",
    "trg_rechnungen_festgeschrieben_delete",
    "trg_rechnungen_storno_nur_status",
    "trg_rechnungspos_update",
    "trg_rechnungspos_delete",
    "trg_rechnungspos_insert",
)

TRIGGER = {
    "trg_rechnungen_festgeschrieben_update": f"""
        CREATE TRIGGER trg_rechnungen_festgeschrieben_update
        BEFORE UPDATE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status = 'festgeschrieben'
             AND NOT (NEW.status = 'storniert' AND NEW.storno_ref IS NOT NULL)
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_RECHNUNG_UPDATE}');
        END
    """,
    "trg_rechnungen_festgeschrieben_delete": f"""
        CREATE TRIGGER trg_rechnungen_festgeschrieben_delete
        BEFORE DELETE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_RECHNUNG_DELETE}');
        END
    """,
    "trg_rechnungen_storno_nur_status": f"""
        CREATE TRIGGER trg_rechnungen_storno_nur_status
        BEFORE UPDATE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status = 'festgeschrieben'
             AND NEW.status = 'storniert'
             AND ({_STORNO_BEDINGUNG})
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_RECHNUNG_UPDATE}');
        END
    """,
    "trg_rechnungspos_update": f"""
        CREATE TRIGGER trg_rechnungspos_update
        BEFORE UPDATE ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_POSITION_UPDATE}');
        END
    """,
    "trg_rechnungspos_delete": f"""
        CREATE TRIGGER trg_rechnungspos_delete
        BEFORE DELETE ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_POSITION_DELETE}');
        END
    """,
    "trg_rechnungspos_insert": f"""
        CREATE TRIGGER trg_rechnungspos_insert
        BEFORE INSERT ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = NEW.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_POSITION_NEU}');
        END
    """,
    "trg_rechnung_absetzung_update": f"""
        CREATE TRIGGER trg_rechnung_absetzung_update
        BEFORE UPDATE ON rechnung_absetzung
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_ABSETZUNG_UPDATE}');
        END
    """,
    "trg_rechnung_absetzung_delete": f"""
        CREATE TRIGGER trg_rechnung_absetzung_delete
        BEFORE DELETE ON rechnung_absetzung
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_ABSETZUNG_DELETE}');
        END
    """,
    "trg_rechnung_absetzung_insert": f"""
        CREATE TRIGGER trg_rechnung_absetzung_insert
        BEFORE INSERT ON rechnung_absetzung
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = NEW.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_ABSETZUNG_NEU}');
        END
    """,
}


def upgrade() -> None:
    # Die Trigger vor dem Tabellenumbau abräumen: batch_alter_table baut 'rechnungen' neu auf,
    # und ein Trigger auf einer Tabelle, die es zwischenzeitlich nicht gibt, bricht die
    # Migration ab.
    for name in NACHGEZOGEN:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table("rechnungen", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kunde_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("ust_kz", sa.String(length=50), nullable=False, server_default="19")
        )
        batch_op.add_column(sa.Column("abschlag_nr", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("betreff", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("anschreiben", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("schlusstext", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("ust_details", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("absetzung_netto", app.modelle.basis.Cent(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("absetzung_ust", app.modelle.basis.Cent(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("zahlbetrag", app.modelle.basis.Cent(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "ust_kz_wert", "ust_kz IN (" + ", ".join(f"'{k}'" for k in UST_KENNZEICHEN) + ")"
        )

    # kunde_id kommt in zwei Schritten: erst nullable anlegen, dann füllen, dann festziehen.
    # Zum Zeitpunkt dieser Migration gibt es noch keine Belege – der UPDATE ist die Vorsorge
    # für eine Datenbank, in der doch schon einer steht (etwa aus einem Testlauf).
    op.execute(
        "UPDATE rechnungen SET kunde_id = ("
        "SELECT kunde_id FROM projekte WHERE projekte.id = rechnungen.projekt_id"
        ") WHERE kunde_id IS NULL AND projekt_id IS NOT NULL"
    )
    op.execute("DELETE FROM rechnungen WHERE kunde_id IS NULL")

    with op.batch_alter_table("rechnungen", schema=None) as batch_op:
        batch_op.alter_column("kunde_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_rechnungen_kunde_id_kunden"), "kunden", ["kunde_id"], ["id"]
        )
        batch_op.create_index(batch_op.f("ix_rechnungen_kunde_id"), ["kunde_id"], unique=False)

    op.create_table(
        "rechnung_absetzung",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rechnung_id", sa.Integer(), nullable=False),
        sa.Column("abschlag_id", sa.Integer(), nullable=False),
        sa.Column("pos", sa.Integer(), nullable=False),
        sa.Column("rechnung_nr", sa.String(length=50), nullable=False),
        sa.Column("datum", sa.Date(), nullable=False),
        sa.Column("netto", app.modelle.basis.Cent(), nullable=False),
        sa.Column("ust_satz", sa.Integer(), nullable=False),
        sa.Column("ust", app.modelle.basis.Cent(), nullable=False),
        sa.Column("created_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("updated_at", app.modelle.basis.UtcDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=True),
        sa.CheckConstraint("(ust_satz IS NULL) OR (ust_satz >= 0)", name=op.f("ck_rechnung_absetzung_ust_satz_positiv")),
        sa.ForeignKeyConstraint(
            ["rechnung_id"],
            ["rechnungen.id"],
            name=op.f("fk_rechnung_absetzung_rechnung_id_rechnungen"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["abschlag_id"], ["rechnungen.id"], name=op.f("fk_rechnung_absetzung_abschlag_id_rechnungen")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rechnung_absetzung")),
        sa.UniqueConstraint("rechnung_id", "abschlag_id", name=op.f("uq_rechnung_absetzung_beleg")),
    )
    op.create_index(
        op.f("ix_rechnung_absetzung_created_at"), "rechnung_absetzung", ["created_at"]
    )
    op.create_index(
        op.f("ix_rechnung_absetzung_rechnung_id"), "rechnung_absetzung", ["rechnung_id"]
    )
    op.create_index(
        op.f("ix_rechnung_absetzung_abschlag_id"), "rechnung_absetzung", ["abschlag_id"]
    )

    for anweisung in TRIGGER.values():
        op.execute(anweisung.strip())


def downgrade() -> None:
    for name in TRIGGER:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    op.drop_index(op.f("ix_rechnung_absetzung_abschlag_id"), table_name="rechnung_absetzung")
    op.drop_index(op.f("ix_rechnung_absetzung_rechnung_id"), table_name="rechnung_absetzung")
    op.drop_table("rechnung_absetzung")

    with op.batch_alter_table("rechnungen", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_rechnungen_kunde_id"))
        batch_op.drop_constraint("ust_kz_wert", type_="check")
        batch_op.drop_column("zahlbetrag")
        batch_op.drop_column("absetzung_ust")
        batch_op.drop_column("absetzung_netto")
        batch_op.drop_column("ust_details")
        batch_op.drop_column("schlusstext")
        batch_op.drop_column("anschreiben")
        batch_op.drop_column("betreff")
        batch_op.drop_column("abschlag_nr")
        batch_op.drop_column("ust_kz")
        batch_op.drop_column("kunde_id")

    # Die Sperren aus 0002 wiederherstellen: die drei auf 'rechnungen' ohne die neuen Spalten,
    # und die drei auf 'rechnungspos' unverändert. Sie mussten oben ebenfalls weichen, weil ihr
    # Rumpf 'rechnungen' abfragt – ohne diese Zeilen bliebe ein festgeschriebener Beleg nach dem
    # Downgrade über seine Positionen änderbar.
    op.execute(
        """
        CREATE TRIGGER trg_rechnungspos_update
        BEFORE UPDATE ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, 'Position einer festgeschriebenen Rechnung nicht aenderbar');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rechnungspos_delete
        BEFORE DELETE ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, 'Position einer festgeschriebenen Rechnung nicht loeschbar');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rechnungspos_insert
        BEFORE INSERT ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = NEW.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, 'keine Position an einer festgeschriebenen Rechnung');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rechnungen_festgeschrieben_update
        BEFORE UPDATE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status = 'festgeschrieben'
             AND NOT (NEW.status = 'storniert' AND NEW.storno_ref IS NOT NULL)
        BEGIN
            SELECT RAISE(ABORT, 'festgeschriebene Rechnung nicht aenderbar');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rechnungen_festgeschrieben_delete
        BEFORE DELETE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, 'festgeschriebene Rechnung nicht loeschbar');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rechnungen_storno_nur_status
        BEFORE UPDATE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status = 'festgeschrieben'
             AND NEW.status = 'storniert'
             AND (NEW.rechnung_nr IS NOT OLD.rechnung_nr
                  OR NEW.netto IS NOT OLD.netto
                  OR NEW.ust IS NOT OLD.ust
                  OR NEW.brutto IS NOT OLD.brutto
                  OR NEW.datum IS NOT OLD.datum
                  OR NEW.hash IS NOT OLD.hash
                  OR NEW.festgeschrieben_am IS NOT OLD.festgeschrieben_am
                  OR NEW.art IS NOT OLD.art
                  OR NEW.firma_id IS NOT OLD.firma_id
                  OR NEW.projekt_id IS NOT OLD.projekt_id
                  OR NEW.kunde_snapshot IS NOT OLD.kunde_snapshot)
        BEGIN
            SELECT RAISE(ABORT, 'festgeschriebene Rechnung nicht aenderbar');
        END
        """
    )
