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


def main() -> None:
    """Einstiegspunkt des Skripts ``ip3-leitstand``."""
    try:
        anwendung()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        sys.exit(2)


if __name__ == "__main__":
    main()
