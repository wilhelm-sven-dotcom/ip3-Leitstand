"""Alembic-Umgebung des Leitstands.

Zwei SQLite-Eigenheiten bestimmen diese Datei:

1. **``render_as_batch``.** SQLite kann Spalten nicht ändern oder löschen. Alembic baut die
   Tabelle dafür neu, kopiert die Daten und benennt um ("Batch-Modus"). Ohne diese Einstellung
   scheitert jede spätere Spaltenänderung.
2. **Fremdschlüssel während der Migration aus.** Beim Neubau einer Tabelle im Batch-Modus zeigen
   die Verweise anderer Tabellen kurzzeitig auf die alte, gerade umbenannte Tabelle. Mit aktiver
   Fremdschlüsselprüfung würde SQLite diese Verweise stillschweigend auf den Zwischennamen
   umbiegen und damit das Schema beschädigen.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Connection

from alembic import context

# Das Anwendungspaket liegt eine Ebene über diesem Verzeichnis.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datenbank import engine_erzeugen
from app.konfiguration import einstellungen
from app.modelle import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _datenbankpfad() -> Path:
    """Zieldatenbank: Vorgabe über ``-x db=…``, sonst aus der Konfiguration."""
    aus_argument = context.get_x_argument(as_dictionary=True).get("db")
    if aus_argument:
        return Path(aus_argument)
    return einstellungen().pfade.datenbank


def _fremdschluessel_abschalten(dbapi_verbindung, _verbindungsdaten) -> None:
    cursor = dbapi_verbindung.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = OFF")
    finally:
        cursor.close()


def offline_migrieren() -> None:
    """Migration als SQL-Skript ausgeben (``alembic upgrade head --sql``)."""
    context.configure(
        url=f"sqlite+pysqlite:///{_datenbankpfad()}",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _migrationen_ausfuehren(verbindung: Connection) -> None:
    context.configure(
        connection=verbindung,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def online_migrieren() -> None:
    """Migration gegen die Datenbank ausführen."""
    verbindbar = config.attributes.get("connection", None)
    if verbindbar is not None:
        # Aufruf aus dem laufenden Programm oder aus einem Test.
        _migrationen_ausfuehren(verbindbar)
        return

    ziel = _datenbankpfad()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    alembic_engine = engine_erzeugen(ziel, ohne_pool=True)
    # Die Fremdschlüsselprüfung wird nur für die Migrationsverbindung abgeschaltet; die Anwendung
    # arbeitet weiter mit aktiver Prüfung.
    event.listen(alembic_engine, "connect", _fremdschluessel_abschalten)

    with alembic_engine.connect() as verbindung:
        _migrationen_ausfuehren(verbindung)
    alembic_engine.dispose()


if context.is_offline_mode():
    offline_migrieren()
else:
    online_migrieren()
