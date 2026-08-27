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


@anwendung.command("seed")
def seed_ausfuehren(
    demodaten: bool = typer.Option(
        False, "--demodaten", help="Erfundene Projekte für Entwicklung und Schulung anlegen"
    ),
    admin_email: str = typer.Option(
        "s.wilhelm@ip3-energie.de", help="E-Mail des ersten Administrators"
    ),
    admin_name: str = typer.Option("Sven Wilhelm", help="Name des ersten Administrators"),
) -> None:
    """Grunddaten einrichten: Firma, Rollen, Berechtigungen, Administrator.

    Wiederholbar – ein zweiter Lauf ergänzt nur, was fehlt (etwa neue Berechtigungen).
    """
    from app.datenbank import schreib_sitzung
    from app.werkzeuge.seed import SeedFehler, grunddaten
    from app.werkzeuge.seed import demodaten as demodaten_anlegen

    try:
        werte = einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    try:
        with schreib_sitzung() as sitzung:
            ergebnis = grunddaten(sitzung, werte, admin_email=admin_email, admin_name=admin_name)
            if demodaten:
                ergebnis.demodaten = demodaten_anlegen(sitzung, werte)
    except SeedFehler as fehler:
        typer.secho(
            f"\n{fehler.meldung}\nNächster Schritt: {fehler.naechster_schritt}\n",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from fehler

    typer.echo(ergebnis.als_text())
    if ergebnis.admin_angelegt:
        typer.echo("")
        typer.secho("Zugangsdaten für die erste Anmeldung:", bold=True)
        typer.echo(f"  E-Mail:   {ergebnis.admin_email}")
        typer.echo(f"  Passwort: {ergebnis.admin_passwort}")
        typer.echo("")
        typer.secho(
            "Dieses Passwort erscheint nur jetzt und muss bei der ersten Anmeldung "
            "gewechselt werden.",
            fg=typer.colors.YELLOW,
        )


@anwendung.command("nutzer-anlegen")
def nutzer_anlegen(
    email: str = typer.Argument(..., help="E-Mail-Adresse, die zugleich die Anmeldekennung ist"),
    name: str = typer.Argument(..., help="Vor- und Nachname"),
    rolle: str = typer.Option(..., help="Rolle: admin, buchhaltung oder team"),
    passwort: str = typer.Option(None, help="Startpasswort; ohne Angabe wird eines erzeugt"),
) -> None:
    """Ein Nutzerkonto anlegen.

    Bis es eine Nutzerverwaltung in der Oberfläche gibt (spätere Phase), ist das der Weg, um
    Konten für die Geschäftsführung, die Buchhaltung und das Team einzurichten. Das Startpasswort
    muss bei der ersten Anmeldung gewechselt werden.
    """
    from sqlalchemy import select

    from app.datenbank import schreib_sitzung
    from app.modelle import Rolle, User
    from app.sicherheit import passwort as pw

    try:
        werte = einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    kennung = email.strip().lower()
    klartext = passwort or pw.zufallspasswort()

    try:
        pw.pruefe_laenge(klartext, werte.anmeldung.passwort_mindestlaenge)
    except pw.PasswortFehler as fehler:
        typer.secho(
            f"\n{fehler.meldung}\nNächster Schritt: {fehler.naechster_schritt}\n",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from fehler

    with schreib_sitzung() as sitzung:
        if sitzung.scalar(select(User).where(User.email == kennung)) is not None:
            typer.secho(
                f"Es gibt bereits einen Nutzer mit der E-Mail {kennung}.\n"
                "Nächster Schritt: Um das Passwort zu ersetzen, 'ip3-leitstand passwort-setzen' "
                "verwenden.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)

        rollen_eintrag = sitzung.scalar(select(Rolle).where(Rolle.name == rolle))
        if rollen_eintrag is None:
            vorhandene = ", ".join(r.name for r in sitzung.scalars(select(Rolle)).all()) or "keine"
            typer.secho(
                f"Die Rolle '{rolle}' gibt es nicht. Vorhanden sind: {vorhandene}.\n"
                "Nächster Schritt: Schreibweise prüfen. Fehlen die Rollen ganz, zuerst "
                "'ip3-leitstand seed' ausführen.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)

        neuer = User(
            name=name.strip(),
            email=kennung,
            pw_hash=pw.hashen(klartext),
            aktiv=True,
            # Das Passwort ist über die Kommandozeile gelaufen und stand auf dem Bildschirm.
            muss_passwort_wechseln=True,
            created_by="kommandozeile",
        )
        neuer.rollen.append(rollen_eintrag)
        sitzung.add(neuer)

    typer.echo(f"Nutzer angelegt: {name} <{kennung}>, Rolle {rolle}")
    typer.echo(f"Startpasswort: {klartext}")
    typer.secho(
        "Muss bei der ersten Anmeldung gewechselt werden.",
        fg=typer.colors.YELLOW,
    )


@anwendung.command("nutzer-deaktivieren")
def nutzer_deaktivieren(
    email: str = typer.Argument(..., help="E-Mail des Nutzers"),
    wieder_aktivieren: bool = typer.Option(
        False, "--aktivieren", help="Statt zu deaktivieren wieder freigeben"
    ),
) -> None:
    """Ein Konto sperren oder wieder freigeben.

    Nutzer werden nie gelöscht (PLAN §5): das Änderungsprotokoll verweist auf sie. Ein
    deaktiviertes Konto verliert seine offenen Sitzungen sofort.
    """
    from sqlalchemy import select

    from app.datenbank import schreib_sitzung
    from app.modelle import User
    from app.sicherheit.sitzungen import alle_beenden

    try:
        einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    with schreib_sitzung() as sitzung:
        nutzer = sitzung.scalar(select(User).where(User.email == email.strip().lower()))
        if nutzer is None:
            typer.secho(
                f"Es gibt keinen Nutzer mit der E-Mail {email}.\n"
                "Nächster Schritt: Vorhandene Nutzer zeigt 'ip3-leitstand nutzer-liste'.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        nutzer.aktiv = wieder_aktivieren
        name = nutzer.name
        beendet = 0 if wieder_aktivieren else alle_beenden(sitzung, nutzer.id)

    if wieder_aktivieren:
        typer.echo(f"{name} ist wieder freigegeben.")
    else:
        typer.echo(f"{name} ist deaktiviert. {beendet} offene Sitzung(en) beendet.")


@anwendung.command("passwort-setzen")
def passwort_setzen(
    email: str = typer.Argument(..., help="E-Mail des Nutzers"),
    passwort: str = typer.Option(None, help="Neues Passwort; ohne Angabe wird eines erzeugt"),
) -> None:
    """Passwort eines Nutzers zurücksetzen (bis es eine Nutzerverwaltung gibt).

    Der Nutzer muss es bei der nächsten Anmeldung wechseln.
    """
    from sqlalchemy import select

    from app.datenbank import schreib_sitzung
    from app.modelle import User
    from app.sicherheit import passwort as pw

    try:
        einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    klartext = passwort or pw.zufallspasswort()
    with schreib_sitzung() as sitzung:
        nutzer = sitzung.scalar(select(User).where(User.email == email))
        if nutzer is None:
            typer.secho(
                f"Es gibt keinen Nutzer mit der E-Mail {email}.\n"
                "Nächster Schritt: Schreibweise prüfen. Vorhandene Nutzer zeigt "
                "'ip3-leitstand nutzer-liste'.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        nutzer.pw_hash = pw.hashen(klartext)
        nutzer.muss_passwort_wechseln = True
        name = nutzer.name

    typer.echo(f"Passwort für {name} ({email}) gesetzt.")
    typer.echo(f"Neues Passwort: {klartext}")
    typer.secho("Muss bei der nächsten Anmeldung gewechselt werden.", fg=typer.colors.YELLOW)


@anwendung.command("nutzer-liste")
def nutzer_liste() -> None:
    """Nutzer mit Rollen und Status anzeigen."""
    from sqlalchemy import select

    from app.datenbank import lese_sitzung
    from app.modelle import User

    try:
        einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    with lese_sitzung() as sitzung:
        nutzer = sitzung.scalars(select(User).order_by(User.name)).all()
        if not nutzer:
            typer.echo("Noch keine Nutzer. Mit 'ip3-leitstand seed' den Administrator anlegen.")
            return
        for eintrag in nutzer:
            rollen = ", ".join(r.name for r in eintrag.rollen) or "keine Rolle"
            zustand = "aktiv" if eintrag.aktiv else "deaktiviert"
            hinweis = " (Passwortwechsel offen)" if eintrag.muss_passwort_wechseln else ""
            typer.echo(f"{eintrag.email:35s} {eintrag.name:25s} {zustand:12s} {rollen}{hinweis}")


@anwendung.command("backup")
def backup_ausfuehren() -> None:
    """Datensicherung sofort ausführen.

    Nach der Einrichtung einmal von Hand ausführen und die Datei im Zielordner nachsehen –
    sonst weiß niemand, ob der nächtliche Lauf funktioniert (RUNBOOK, Abschnitt Backup).
    """
    from app.jobs.backup import sicherung_durchfuehren
    from app.jobs.lauf import protokollierter_lauf

    try:
        werte = einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    if werte.pfade.backup is None:
        typer.secho(
            "Es ist kein Backup-Ziel eingerichtet.\n"
            "Nächster Schritt: in config.toml unter [pfade] den Eintrag backup auf den "
            "OneDrive-Ordner 04_Backup setzen.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    with protokollierter_lauf("backup", "manuell") as ergebnis:
        bericht = sicherung_durchfuehren(werte)
        groesse_mb = round(bericht.groesse_bytes / 1_048_576, 1)
        ergebnis.meldung = f"Sicherung {bericht.datei.name} geschrieben ({groesse_mb} MB)"
        ergebnis.kennzahlen = {"datei": bericht.datei.name, "groesse_mb": groesse_mb}

        typer.echo(f"Sicherung:   {bericht.datei}")
        typer.echo(f"Größe:       {groesse_mb} MB")
        typer.echo(
            "Integrität:  "
            + ("in Ordnung" if bericht.integritaet_ok else "FEHLERHAFT – bitte prüfen!")
        )
        if bericht.geloeschte_generationen:
            typer.echo(f"Aufgeräumt:  {bericht.geloeschte_generationen} alte Generation(en)")
        if not bericht.integritaet_ok:
            typer.secho(
                "Die Sicherung wurde geschrieben, ist aber nicht in Ordnung. "
                "Nächster Schritt: 'ip3-leitstand pruefen' auf der laufenden Datenbank.",
                fg=typer.colors.RED,
                err=True,
            )


@anwendung.command("openapi")
def openapi_exportieren(
    ziel: str = typer.Option(None, help="Abweichender Zielpfad (Standard: backend/openapi.json)"),
) -> None:
    """OpenAPI-Spezifikation nach backend/openapi.json schreiben.

    Danach im Frontend 'npm run api' ausführen, damit die TypeScript-Typen dazu passen.
    """
    from pathlib import Path

    from app.werkzeuge.openapi_export import schreiben

    pfad = schreiben(Path(ziel) if ziel else None)
    typer.echo(f"Geschrieben: {pfad}")
    typer.echo("Nächster Schritt: im Ordner frontend 'npm run api' ausführen.")


@anwendung.command("berechtigungen-doku")
def berechtigungen_doku() -> None:
    """docs/BERECHTIGUNGEN.md aus dem Berechtigungskatalog neu erzeugen."""
    from pathlib import Path

    from app.sicherheit.katalog import markdown_uebersicht

    ziel = Path(__file__).resolve().parents[2] / "docs" / "BERECHTIGUNGEN.md"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(markdown_uebersicht(), encoding="utf-8")
    typer.echo(f"Geschrieben: {ziel}")


def main() -> None:
    """Einstiegspunkt des Skripts ``ip3-leitstand``."""
    try:
        anwendung()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        sys.exit(2)


if __name__ == "__main__":
    main()
