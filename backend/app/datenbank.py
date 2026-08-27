"""Datenbankzugriff auf SQLite (PLAN §2).

Vier Dinge sind hier wichtiger als sie aussehen:

1. **PRAGMAs gehören ins ``connect``-Ereignis.** ``foreign_keys`` und ``busy_timeout`` gelten je
   Verbindung, nicht je Datenbank. Einmalig beim Start gesetzt greifen sie nur auf der ersten
   Verbindung des Verbindungspools – die Fremdschlüsselprüfung würde je nach Zufall wirken.
2. **WAL-Modus** erlaubt Lesen während eines Schreibvorgangs. Ohne ihn blockiert jeder Import die
   ganze Oberfläche.
3. **``BEGIN IMMEDIATE`` für Schreibvorgänge.** ``busy_timeout`` hilft nicht, wenn eine
   Lesetransaktion zur Schreibtransaktion hochgestuft werden soll: SQLite bricht dann sofort ab
   (``SQLITE_BUSY_SNAPSHOT``). Wer schreibt, sagt es also von Anfang an.
4. **Kurze Schreibtransaktionen.** Der Kontextmanager :func:`schreib_transaktion` hält die Sperre
   nur für den Block; langlaufende Arbeit (Dateien lesen, PDFs erzeugen) gehört davor.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.konfiguration import Einstellungen, einstellungen
from app.protokoll import logger

log = logger(__name__)

# Wie lange eine Anfrage auf eine belegte Datenbank wartet, bevor sie aufgibt. Fünf Sekunden sind
# reichlich für die Schreibvorgänge dieser Anwendung und kurz genug, dass niemand denkt, es hängt.
BUSY_TIMEOUT_MS = 5000

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _pragmas_setzen(dbapi_verbindung: sqlite3.Connection, _verbindungsdaten: object) -> None:
    """PRAGMAs für jede neue Verbindung setzen."""
    cursor = dbapi_verbindung.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        # FULL statt NORMAL: bei Stromausfall darf keine festgeschriebene Rechnung fehlen.
        cursor.execute("PRAGMA synchronous = FULL")
        cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys")
    finally:
        cursor.close()


def engine_erzeugen(datenbank: Path, echo: bool = False) -> Engine:
    """Engine für eine Datenbankdatei erzeugen (auch von Tests und der Kommandozeile genutzt)."""
    datenbank.parent.mkdir(parents=True, exist_ok=True)
    neue_engine = create_engine(
        f"sqlite+pysqlite:///{datenbank}",
        echo=echo,
        future=True,
        # Der nächtliche Job läuft in einem eigenen Thread; SQLite-Verbindungen sind nicht
        # threadübergreifend nutzbar, deshalb gibt der Pool jedem Thread eine eigene.
        connect_args={"check_same_thread": False},
    )
    event.listen(neue_engine, "connect", _pragmas_setzen)
    return neue_engine


def engine() -> Engine:
    """Engine der Anwendung (einmal erzeugt, dann wiederverwendet)."""
    global _engine
    if _engine is None:
        werte: Einstellungen = einstellungen()
        _engine = engine_erzeugen(werte.pfade.datenbank)
        log.info("Datenbank: %s", werte.pfade.datenbank)
    return _engine


def session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    return _session_factory


def zuruecksetzen() -> None:
    """Engine und Sitzungsfabrik verwerfen – für Tests und nach Konfigurationswechsel."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def lese_sitzung() -> Iterator[Session]:
    """Sitzung für lesende Zugriffe."""
    sitzung = session_factory()()
    try:
        yield sitzung
    finally:
        sitzung.close()


@contextmanager
def schreib_sitzung() -> Iterator[Session]:
    """Sitzung für Schreibzugriffe: ``BEGIN IMMEDIATE``, Commit am Ende, Rollback bei Fehler."""
    sitzung = session_factory()()
    try:
        with schreib_transaktion(sitzung):
            yield sitzung
    finally:
        sitzung.close()


@contextmanager
def schreib_transaktion(sitzung: Session) -> Iterator[Session]:
    """Schreibtransaktion in einer bestehenden Sitzung.

    Startet ausdrücklich mit ``BEGIN IMMEDIATE``, damit die Schreibsperre sofort gesetzt wird und
    nicht mitten in der Änderung an einem gleichzeitigen Schreiber scheitert.
    """
    if not sitzung.in_transaction():
        sitzung.begin()
    verbindung = sitzung.connection()
    # SQLAlchemy hat mit begin() bereits eine Transaktion eröffnet (deferred). Das folgende
    # COMMIT beendet sie ohne Wirkung, danach eröffnen wir sie selbst als IMMEDIATE.
    rohverbindung = verbindung.connection.dbapi_connection
    if isinstance(rohverbindung, sqlite3.Connection) and rohverbindung.in_transaction:
        rohverbindung.execute("COMMIT")
    if isinstance(rohverbindung, sqlite3.Connection):
        rohverbindung.execute("BEGIN IMMEDIATE")
    try:
        yield sitzung
        sitzung.commit()
    except Exception:
        sitzung.rollback()
        raise


def fremdschluessel_aktiv(engine_: Engine | None = None) -> bool:
    """Prüft, ob die Fremdschlüsselprüfung auf einer frischen Verbindung greift.

    Als Test gedacht: schlägt sie fehl, sind Verweise auf gelöschte Datensätze möglich.
    """
    ziel = engine_ or engine()
    with ziel.connect() as verbindung:
        return bool(verbindung.execute(text("PRAGMA foreign_keys")).scalar())
