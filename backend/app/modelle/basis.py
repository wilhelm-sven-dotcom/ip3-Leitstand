"""Grundlagen aller Tabellen (PLAN §5).

Vier Festlegungen, die sich später nicht mehr ohne Aufwand ändern lassen:

* **Benennungsschema für Constraints.** SQLite kann Spalten nicht einzeln ändern; Alembic baut
  Tabellen dafür neu (Batch-Modus). Ein unbenannter UNIQUE- oder CHECK-Constraint ist dabei nicht
  ansprechbar. Darum bekommt jeder Constraint von Anfang an einen Namen.
* **Zeitstempel in UTC** über einen eigenen Spaltentyp. SQLite verwirft bei
  ``DateTime(timezone=True)`` die Zone stillschweigend – dann steht dort eine Zahl ohne Bedeutung.
  Der Typ hier nimmt nur Zeitpunkte mit Zone an und gibt sie mit Zone zurück.
* **Geld als Integer in Cent** (PLAN §5). Der Typ ``Cent`` ist ein sprechender Name für BIGINT.
* **Optimistic Locking über ``updated_at``** (PLAN §5). Wer mit veraltetem Stand speichert,
  bekommt einen Konflikt gemeldet statt still zu überschreiben.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, MetaData, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.zeit import jetzt_utc

# Namensschema für Indizes und Constraints. Ohne dieses Schema erzeugt SQLite anonyme Constraints,
# die in späteren Migrationen nicht mehr angesprochen werden können.
NAMENSSCHEMA = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """Zeitpunkt-Spalte, die ausschließlich mit UTC arbeitet.

    Gespeichert wird ohne Zonenangabe (SQLite kann sie nicht halten), aber immer in UTC.
    Beim Lesen wird die Zone wieder gesetzt, damit im Code nie ein Zeitpunkt ohne Zone auftaucht.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "Zeitpunkte werden nur mit Zeitzone gespeichert. "
                "Nächster Schritt: app.zeit.jetzt_utc() verwenden oder die Zone setzen."
            )
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Cent(TypeDecorator[int]):
    """Geldbetrag in ganzen Cent (PLAN §5: nie Gleitkomma)."""

    impl = BigInteger
    cache_ok = True


# Wiederkehrende Spaltenlängen. Kürzer als nötig ärgert später, länger schadet in SQLite nicht –
# die Längen dokumentieren die Absicht und gelten bei einem Wechsel auf PostgreSQL.
Kurztext = String(50)
Text = String(200)
Langtext = String(1000)


class Base(DeclarativeBase):
    """Gemeinsame Basis aller Tabellen."""

    metadata = MetaData(naming_convention=NAMENSSCHEMA)


class ZeitstempelMixin:
    """``created_at``, ``updated_at`` und ``created_by`` für jede Tabelle (PLAN §2)."""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=jetzt_utc, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=jetzt_utc, onupdate=jetzt_utc
    )
    created_by: Mapped[str | None] = mapped_column(Kurztext, nullable=True)


class OptimistischMixin:
    """Optimistic Locking über ``updated_at`` (PLAN §5).

    SQLAlchemy nimmt ``updated_at`` beim UPDATE in die WHERE-Bedingung auf. Trifft das UPDATE
    keine Zeile, hat jemand anderes zwischenzeitlich gespeichert: es gibt einen Konflikt statt
    eines stillen Überschreibens.

    Als Mixin mit ``declared_attr``, nicht als Dekorator: ``__mapper_args__`` muss beim Aufbau der
    Klasse vorliegen, ein nachträglich gesetztes Attribut bleibt ohne Wirkung – der Mapper ist zu
    diesem Zeitpunkt längst konfiguriert.

    Tabellen, die nur von Importen geschrieben werden (Salden, offene Posten, Stunden), verwenden
    das Mixin bewusst nicht: dort gibt es keine konkurrierende Bearbeitung durch Menschen, und ein
    Importlauf würde sich an der Versionsprüfung nur aufhalten.

    Reihenfolge beim Erben: ``class Kunde(OptimistischMixin, ZeitstempelMixin, Base)``.
    """

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {
            "version_id_col": cls.__table__.c.updated_at,
            # Die Version ist ein Zeitpunkt, keine Zählnummer: sie ist zugleich die Auskunft
            # „wann zuletzt geändert" und geht damit unverändert in die Oberfläche.
            "version_id_generator": lambda _: jetzt_utc(),
        }
