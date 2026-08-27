"""Schema anlegen und prüfen.

Der Weg über Alembic ist auch in Tests der richtige: ``Base.metadata.create_all`` würde ein
Schema erzeugen, das dem Modell entspricht, aber nicht dem, was auf dem Bürorechner steht –
Trigger und Migrationsschritte fehlen dann. Wer gegen ein anderes Schema testet als er betreibt,
testet das Falsche.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from alembic import command
from app.datenbank import engine_erzeugen
from app.protokoll import logger

log = logger(__name__)


def alembic_konfiguration(datenbank: Path) -> Config:
    """Alembic-Konfiguration für eine bestimmte Datenbankdatei."""
    wurzel = Path(__file__).resolve().parents[2]
    konfiguration = Config(str(wurzel / "alembic.ini"))
    konfiguration.set_main_option("script_location", str(wurzel / "alembic"))
    konfiguration.cmd_opts = type("Opts", (), {"x": [f"db={datenbank}"]})()  # type: ignore[assignment]
    return konfiguration


def schema_anlegen(datenbank: Path) -> None:
    """Alle Migrationen auf die genannte Datenbank anwenden."""
    datenbank.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_konfiguration(datenbank), "head")


def schema_revision(datenbank: Path) -> str | None:
    """Aktuelle Alembic-Revision der Datenbank; ``None`` bei einer leeren Datei."""
    engine = engine_erzeugen(datenbank)
    try:
        with engine.connect() as verbindung:
            return MigrationContext.configure(verbindung).get_current_revision()
    finally:
        engine.dispose()


def kopf_revision() -> str | None:
    """Revision, die der aktuelle Code erwartet."""
    from alembic.script import ScriptDirectory

    wurzel = Path(__file__).resolve().parents[2]
    return ScriptDirectory(str(wurzel / "alembic")).get_current_head()


def tabellen(engine: Engine) -> set[str]:
    """Tabellennamen der Datenbank ohne Alembics eigene Verwaltungstabelle."""
    return {name for name in inspect(engine).get_table_names() if name != "alembic_version"}
