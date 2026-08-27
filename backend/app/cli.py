"""Kommandozeile des Leitstands: ``ip3-leitstand <befehl>``.

Alles, was am Host gemacht werden muss, läuft über diese Befehle – Serverstart, Schema, Seed,
Sicherung, Prüfung. Fehler erscheinen als Klartext mit nächstem Schritt, nicht als Stacktrace
(PLAN §14).
"""

from __future__ import annotations

import sys

import typer

from app import __version__
from app.konfiguration import KonfigurationsFehler, einstellungen, konfigurationspfad

anwendung = typer.Typer(
    help="ip³ Leitstand – Projekt- und Finanz-Cockpit der ip³ Energietechnik GmbH",
    no_args_is_help=True,
    add_completion=False,
)


def _fehler_ausgeben(fehler: Exception) -> None:
    typer.secho(f"\n{fehler}\n", fg=typer.colors.RED, err=True)


@anwendung.command("version")
def version_zeigen() -> None:
    """Version und verwendete Konfigurationsdatei anzeigen."""
    typer.echo(f"ip³ Leitstand {__version__}")
    typer.echo(f"Konfiguration: {konfigurationspfad()}")


@anwendung.command("server")
def server_starten(
    adresse: str = typer.Option(None, help="Abweichende Adresse (Standard aus config.toml)"),
    port: int = typer.Option(None, help="Abweichender Port (Standard aus config.toml)"),
    neu_laden: bool = typer.Option(
        False, "--neu-laden", help="Bei Codeänderungen neu starten (nur Entwicklung)"
    ),
) -> None:
    """Den Leitstand starten."""
    import uvicorn

    try:
        werte = einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    uvicorn.run(
        "app.main:anwendung_erzeugen",
        factory=True,
        host=adresse or werte.app.adresse,
        port=port or werte.app.port,
        reload=neu_laden,
        # Ein einziger Arbeitsprozess. Mit mehreren würden die nächtlichen Jobs mehrfach laufen –
        # doppelte Sicherungen, später doppelte Importe (PLAN §2: ein Prozess).
        workers=1,
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


@anwendung.command("schema")
def schema_aktualisieren(
    datenbank: str = typer.Option(None, help="Abweichender Pfad zur Datenbankdatei"),
) -> None:
    """Datenbankschema anlegen oder auf den aktuellen Stand bringen."""
    from pathlib import Path

    from app.werkzeuge.schema import kopf_revision, schema_anlegen, schema_revision

    try:
        ziel = Path(datenbank) if datenbank else einstellungen().pfade.datenbank
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    vorher = schema_revision(ziel) if ziel.exists() else None
    schema_anlegen(ziel)
    nachher = schema_revision(ziel)
    if vorher == nachher:
        typer.echo(f"Schema war bereits aktuell (Stand {nachher}).")
    else:
        typer.echo(f"Schema aktualisiert: {vorher or 'leer'} → {nachher}")
    if nachher != kopf_revision():
        typer.secho(
            "Achtung: Die Datenbank steht nicht auf dem Stand, den dieser Programmstand erwartet.",
            fg=typer.colors.YELLOW,
            err=True,
        )


@anwendung.command("pruefen")
def datenbank_pruefen(
    datenbank: str = typer.Option(None, help="Zu prüfende Datenbankdatei"),
) -> None:
    """Datenbank prüfen: Lesbarkeit, Integrität, Schemastand, Zeilenzahlen.

    Nach einem Restore der erste Befehl (siehe RUNBOOK).
    """
    from pathlib import Path

    from sqlalchemy import text

    from app.datenbank import engine_erzeugen
    from app.werkzeuge.schema import kopf_revision, schema_revision, tabellen

    try:
        ziel = Path(datenbank) if datenbank else einstellungen().pfade.datenbank
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    if not ziel.exists():
        typer.secho(
            f"Die Datei {ziel} gibt es nicht.\n"
            "Nächster Schritt: Pfad prüfen oder mit 'ip3-leitstand schema' eine neue "
            "Datenbank anlegen.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    typer.echo(f"Datenbank: {ziel}")
    typer.echo(f"Größe:     {ziel.stat().st_size / 1_048_576:.1f} MB")

    engine = engine_erzeugen(ziel, ohne_pool=True)
    fehlerhaft = False
    try:
        with engine.connect() as verbindung:
            ergebnis = verbindung.execute(text("PRAGMA integrity_check")).scalar()
            if ergebnis == "ok":
                typer.echo("Integrität: in Ordnung")
            else:
                fehlerhaft = True
                typer.secho(f"Integrität: FEHLER – {ergebnis}", fg=typer.colors.RED, err=True)

            vorhandene = tabellen(engine)
            typer.echo(f"Tabellen:  {len(vorhandene)}")
            zeilen = []
            for name in sorted(vorhandene):
                anzahl = verbindung.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
                if anzahl:
                    zeilen.append(f"  {name}: {anzahl}")
            if zeilen:
                typer.echo("Gefüllte Tabellen:")
                for zeile in zeilen:
                    typer.echo(zeile)
            else:
                typer.echo("Alle Tabellen sind leer.")
    finally:
        engine.dispose()

    stand = schema_revision(ziel)
    erwartet = kopf_revision()
    typer.echo(f"Schemastand: {stand or 'unbekannt'} (erwartet: {erwartet})")
    if stand != erwartet:
        typer.secho(
            "Der Schemastand passt nicht zum Programmstand.\n"
            "Nächster Schritt: 'ip3-leitstand schema' ausführen, dann erneut prüfen.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    if fehlerhaft:
        raise typer.Exit(code=1)


def main() -> None:
    """Einstiegspunkt des Skripts ``ip3-leitstand``."""
    try:
        anwendung()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        sys.exit(2)


if __name__ == "__main__":
    main()
