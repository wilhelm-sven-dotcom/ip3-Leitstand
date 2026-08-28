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
    """Fehlermeldung mit nächstem Schritt (CLAUDE.md Regel 8).

    Ein ``FachFehler`` trägt beides; ``str()`` gibt nur die Meldung zurück. Ohne den nächsten
    Schritt stünde auf der Kommandozeile nur, was nicht geht, und nicht, was zu tun ist – genau
    die Auskunft, die am Host fehlt.
    """
    typer.secho(f"\n{fehler}", fg=typer.colors.RED, err=True)
    naechster_schritt = getattr(fehler, "naechster_schritt", "")
    if naechster_schritt:
        typer.secho(f"Nächster Schritt: {naechster_schritt}", fg=typer.colors.YELLOW, err=True)
    typer.echo("", err=True)


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


@anwendung.command("timetac-test")
def timetac_test(
    monat: str = typer.Option(None, help="Monat 'JJJJ-MM' (Standard: laufender und voriger)"),
    zeilen: int = typer.Option(5, help="Wie viele Buchungen im Klartext angezeigt werden"),
) -> None:
    """Die TimeTac-Schnittstelle prüfen, ohne etwas zu schreiben.

    Der erste Schritt nach dem Eintragen der Zugangsdaten in die .env. Zeigt die aufgelöste
    Adresse, die Anmeldung (**ohne Secret**), die gesendete Abfrage und die ersten Buchungen
    mitsamt der erkannten Projektzuordnung. Weicht etwas ab, wird es in der config.toml unter
    [timetac.felder] nachgezogen – die Datenbank bleibt dabei unberührt.
    """
    from app.importe.timetac import projektnummer_aus_text
    from app.importe.timetac_api import (
        RESSOURCE_ZEITEN,
        TimeTacClient,
        abfrage_bauen,
        abholen,
        monate_bestimmen,
    )

    werte = _konfiguration_holen()
    monate = [monat] if monat else monate_bestimmen(werte.timetac)

    try:
        client = TimeTacClient(
            werte.timetac,
            client_id=werte.timetac_client_id,
            client_secret=werte.timetac_client_secret,
            konto=werte.timetac_konto,
        )
    except Exception as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    typer.echo(f"Konto:     {client.konto}")
    typer.echo(f"Anmeldung: POST {client.token_adresse()} (grant_type=client_credentials)")
    typer.echo(f"Abfrage:   GET  {client.ressourcen_adresse(RESSOURCE_ZEITEN)}")
    beispiel = abfrage_bauen(
        {"date>=": f"{min(monate)}-01"}, grenze=werte.timetac.seitengroesse, versatz=0
    )
    typer.echo(f"Parameter: {beispiel}")
    typer.echo(f"Monate:    {', '.join(monate)}\n")

    try:
        lieferung = abholen(client, monate)
    except Exception as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    typer.secho(
        f"{len(lieferung.buchungen)} Buchungen, {lieferung.summe_stunden} Stunden",
        fg=typer.colors.GREEN,
    )
    for buchung in lieferung.buchungen[:zeilen]:
        nummer = projektnummer_aus_text(buchung.projekt_text)
        satz, gruppe = werte.stundensaetze.satz_fuer(buchung.mitarbeiter)
        typer.echo(
            f"  {buchung.datum}  {buchung.stunden:>6} h  {buchung.mitarbeiter:<22} "
            f"{buchung.projekt_text[:34]:<34} "
            f"Projekt {nummer if nummer else '?'}  "
            f"{satz / 100:.2f} €/h ({gruppe or 'Standardsatz'})"
        )
    if len(lieferung.buchungen) > zeilen:
        typer.echo(f"  … und {len(lieferung.buchungen) - zeilen} weitere")

    if lieferung.befunde:
        typer.secho(f"\n{len(lieferung.befunde)} Befunde:", fg=typer.colors.YELLOW)
        for befund in lieferung.befunde[:zeilen]:
            typer.echo(f"  {befund.als_text()}")

    typer.echo(
        "\nEs wurde nichts geschrieben. Stimmen die Zahlen, den Lauf mit "
        "'timetac_sync' im Systemstatus starten."
    )


@anwendung.command("timetac-csv")
def timetac_csv(
    datei: str = typer.Argument(..., help="TimeTac-Berichtsexport als CSV"),
    monat: str = typer.Option(
        None,
        help="Nur diesen Monat 'JJJJ-MM' ersetzen (Standard: alle Monate, die in der Datei stehen)",
    ),
    zeilen: int = typer.Option(5, help="Wie viele Buchungen vor der Rückfrage angezeigt werden"),
    ja: bool = typer.Option(False, "--ja", help="Ohne Rückfrage übernehmen"),
) -> None:
    """Stunden aus einem TimeTac-Berichtsexport einlesen – die Rückfallebene (PLAN §8).

    Für die beiden Fälle, in denen die Schnittstelle nicht trägt: sie ist gestört, oder der
    gesuchte Monat liegt vor der Freischaltung und wird von ihr nicht mehr geliefert. Das
    Ergebnis ist dasselbe wie beim nächtlichen Abgleich – jeder gelieferte Monat wird ersetzt,
    nicht ergänzt.
    """
    from pathlib import Path

    from app.datenbank import schreib_sitzung
    from app.fehler import FachFehler
    from app.importe.timetac import bericht_lesen, projektnummer_aus_text, uebernehmen

    werte = _konfiguration_holen()
    pfad = Path(datei)
    if not pfad.is_file():
        typer.secho(
            f"Die Datei {pfad} gibt es nicht.\n"
            "Nächster Schritt: den Pfad zum TimeTac-Berichtsexport prüfen.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        lieferung = bericht_lesen(pfad, werte.timetac, monate=[monat] if monat else None)
    except FachFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    typer.echo(f"Datei:  {pfad}")
    typer.echo(f"Monate: {', '.join(lieferung.monate) or '–'}")
    typer.secho(
        f"{len(lieferung.buchungen)} Buchungen, {lieferung.summe_stunden} Stunden",
        fg=typer.colors.GREEN,
    )
    for buchung in lieferung.buchungen[:zeilen]:
        nummer = projektnummer_aus_text(buchung.projekt_text)
        satz, gruppe = werte.stundensaetze.satz_fuer(buchung.mitarbeiter)
        typer.echo(
            f"  {buchung.datum}  {buchung.stunden:>6} h  {buchung.mitarbeiter:<22} "
            f"{buchung.projekt_text[:34]:<34} "
            f"Projekt {nummer if nummer else '?'}  "
            f"{satz / 100:.2f} €/h ({gruppe or 'Standardsatz'})"
        )
    if len(lieferung.buchungen) > zeilen:
        typer.echo(f"  … und {len(lieferung.buchungen) - zeilen} weitere")

    if lieferung.befunde:
        typer.secho(f"\n{len(lieferung.befunde)} Befunde:", fg=typer.colors.YELLOW)
        for befund in lieferung.befunde[:zeilen]:
            typer.echo(f"  {befund.als_text()}")

    if not lieferung.buchungen:
        typer.secho(
            "\nKeine übernehmbare Zeile. Es wurde nichts geschrieben.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)

    if not ja:
        typer.confirm(
            f"\nDie Monate {', '.join(lieferung.monate)} werden ersetzt. Jetzt übernehmen?",
            abort=True,
        )

    with schreib_sitzung() as sitzung:
        ergebnis = uebernehmen(sitzung, lieferung, werte.stundensaetze)

    typer.secho(
        f"{ergebnis.stundenzeilen} Stundenzeilen übernommen "
        f"({ergebnis.summe_stunden} Stunden, {ergebnis.summe_cent / 100:,.2f} €).",
        fg=typer.colors.GREEN,
    )
    if ergebnis.ohne_satz:
        typer.secho(
            "Ohne Satzgruppe (gerechnet mit dem Standardsatz): "
            + ", ".join(ergebnis.ohne_satz)
            + "\nNächster Schritt: in der config.toml unter [stundensaetze.mitarbeiter] "
            "eintragen und danach erneut einlesen.",
            fg=typer.colors.YELLOW,
        )


@anwendung.command("kalkulationsblatt-vorlage")
def kalkulationsblatt_vorlage(
    ziel: str = typer.Option(
        None,
        help="Ablageort der Vorlage (Standard: vorlagen/Kalkulationsblatt-Vorlage.xlsx)",
    ),
) -> None:
    """Die Excel-Vorlage mit dem Blatt EXPORT erzeugen (PLAN §8).

    Das Blatt wird einmalig in das eigene Kalkulationsblatt übernommen; die benannten Zellen
    (exp_…) werden dort mit der eigenen Kalkulation verknüpft. Danach liest der nächtliche Lauf
    die Sollwerte aus jedem Blatt in 03_Kalkulation.
    """
    from pathlib import Path

    from app.importe.kalkulationsblatt import VORLAGE_DATEINAME, vorlage_erzeugen
    from app.konfiguration import projektwurzel

    pfad = Path(ziel) if ziel else projektwurzel() / "vorlagen" / VORLAGE_DATEINAME
    geschrieben = vorlage_erzeugen(pfad)
    typer.echo(f"Vorlage geschrieben: {geschrieben}")
    typer.echo(
        "Nächster Schritt: das Blatt EXPORT in das eigene Kalkulationsblatt kopieren und die "
        "Zellen in Spalte B mit der Kalkulation verknüpfen."
    )


@anwendung.command("migration-analysieren")
def migration_analysieren(
    ordner: str = typer.Option(None, help="Abweichender Quellordner (Standard: [pfade] migration)"),
    ausfuehrlich: bool = typer.Option(False, "--ausfuehrlich", help="Alle Befunde auflisten"),
) -> None:
    """Bestandsdateien lesen und den Bericht zeigen, ohne etwas zu schreiben.

    Der erste Schritt der Migration (PLAN §9). Zeigt Kontrollsummen, offene Zuordnungen und
    alles, was in den Dateien auffällig ist. Die Datenbank wird dabei nicht angefasst.
    """
    from app.migration.uebernahme import analysieren

    werte = _konfiguration_holen()
    quelle = _migrationsordner(werte, ordner)
    analyse = analysieren(quelle)
    _analyse_ausgeben(analyse, ausfuehrlich=ausfuehrlich)


@anwendung.command("migration-uebernehmen")
def migration_uebernehmen(
    ordner: str = typer.Option(None, help="Abweichender Quellordner (Standard: [pfade] migration)"),
    offene_zulassen: bool = typer.Option(
        False,
        "--offene-zulassen",
        help="Auch übernehmen, wenn Zuordnungen offen sind (deren Zahlungsplan fehlt dann)",
    ),
    ja: bool = typer.Option(False, "--ja", help="Ohne Rückfrage übernehmen"),
) -> None:
    """Bestandsdaten in die Datenbank übernehmen.

    Läuft in einer Transaktion: entweder ganz oder gar nicht. Ein zweiter Lauf wird abgewiesen,
    weil er alles doppelt anlegen würde.
    """
    from sqlalchemy import select

    from app.datenbank import schreib_sitzung
    from app.migration.uebernahme import MigrationFehler, analysieren, uebernehmen
    from app.modelle import Firma

    werte = _konfiguration_holen()
    quelle = _migrationsordner(werte, ordner)
    try:
        analyse = analysieren(quelle)
    except MigrationFehler as fehler:
        _fachfehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler

    _analyse_ausgeben(analyse, ausfuehrlich=False)
    if analyse.vorschau.offene and not offene_zulassen:
        typer.secho(
            f"\n{len(analyse.vorschau.offene)} Zuordnungen sind offen. Sie lassen sich in der "
            "Oberfläche entscheiden; für einen Lauf ohne diese Zahlungsplanpositionen "
            "--offene-zulassen angeben.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)

    if not ja:
        typer.confirm("\nJetzt in die Datenbank übernehmen?", abort=True)

    # schreib_sitzung öffnet die Schreibtransaktion selbst und nimmt sie bei einem Fehler
    # zurück – die Übernahme geht damit ganz durch oder gar nicht.
    try:
        with schreib_sitzung() as sitzung:
            firma_id = sitzung.scalar(select(Firma.id).order_by(Firma.id).limit(1))
            if firma_id is None:
                typer.secho(
                    "In der Datenbank ist keine Firma angelegt.\n"
                    "Nächster Schritt: 'ip3-leitstand seed' ausführen, dann erneut migrieren.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=2)
            bericht = uebernehmen(sitzung, analyse, firma_id, offene_zulassen=offene_zulassen)
    except MigrationFehler as fehler:
        _fachfehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler
    _bericht_ausgeben(bericht)


def _konfiguration_holen():
    try:
        return einstellungen()
    except KonfigurationsFehler as fehler:
        _fehler_ausgeben(fehler)
        raise typer.Exit(code=2) from fehler


def _fachfehler_ausgeben(fehler) -> None:
    typer.secho(fehler.meldung, fg=typer.colors.RED, err=True)
    if fehler.naechster_schritt:
        typer.secho(f"Nächster Schritt: {fehler.naechster_schritt}", fg=typer.colors.RED, err=True)


def _migrationsordner(werte, ordner: str | None):
    from pathlib import Path

    if ordner:
        return Path(ordner)
    if werte.pfade.migration is None:
        typer.secho(
            "Es ist kein Migrationsordner eingerichtet.\n"
            "Nächster Schritt: in config.toml unter [pfade] den Eintrag migration auf den "
            "Ordner mit den beiden Bestandsdateien setzen, oder --ordner angeben.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    return werte.pfade.migration


def _analyse_ausgeben(analyse, *, ausfuehrlich: bool) -> None:
    from decimal import Decimal

    from app.formate import leistung
    from app.geld import formatiere_euro

    summen = analyse.kontrollsummen()
    auftraege = summen["auftragsliste"]
    projekte = summen["teamliste"]

    typer.echo(f"Auftragsliste:  {auftraege['datei']}")
    typer.echo(f"  Zeilen:       {auftraege['zeilen']}")
    typer.echo(f"  Summe netto:  {formatiere_euro(int(auftraege['summe_netto_cent']))}")
    typer.echo(
        f"  davon gestellt: {formatiere_euro(int(auftraege['summe_gestellt_cent']))} "
        f"in {auftraege['zeilen_gestellt']} Zeilen"
    )
    typer.echo("  Planmonate:")
    for monat, cent in auftraege["summe_je_monat_cent"].items():
        typer.echo(f"    {monat:<14}{formatiere_euro(int(cent)):>16}")

    typer.echo(f"\nTeamliste:      {projekte['datei']}")
    typer.echo(f"  Projekte:     {projekte['projekte']}")
    typer.echo(
        f"  Auftragswert: {formatiere_euro(int(projekte['summe_ab_wert_cent']))} "
        f"({projekte['projekte_mit_ab_wert']} Projekte mit Wert)"
    )
    typer.echo(f"  PV-Leistung:  {leistung(Decimal(str(projekte['summe_pv_kwp'])))}")
    typer.echo(f"  Status:       {projekte['anzahl_je_status']}")
    typer.echo(f"  Meilensteine: {projekte['meilensteine']}")

    zuordnung = summen["zuordnung"]
    typer.echo("\nZuordnung Auftragsliste auf Projekte:")
    typer.echo(f"  Kunden je Art: {zuordnung['kunden_je_art']}")
    typer.echo(f"  Zeilen je Art: {zuordnung['zeilen_je_art']}")
    typer.echo(
        f"  offen:         {zuordnung['offen']} Kunden, "
        f"{formatiere_euro(int(zuordnung['offen_betrag_cent']))}"
    )

    befunde = summen["befunde"]
    typer.echo(f"\nBefunde: {befunde['warnung']} Warnung(en), {befunde['hinweis']} Hinweis(e)")
    zu_zeigen = [b for b in analyse.befunde if ausfuehrlich or b.schwere == "warnung"]
    for befund in zu_zeigen:
        farbe = typer.colors.YELLOW if befund.schwere == "warnung" else None
        typer.secho(f"  {befund.als_text()}", fg=farbe)

    typer.secho(
        "\nHinweis: die Summenzellen der Quelldateien rechnen falsch. Gerechnet wird über die "
        "Datenzeilen; Einzelheiten im Importprotokoll.",
        fg=typer.colors.YELLOW,
    )
    for eintrag in summen["summenfehler_der_quelldateien"]:
        typer.echo(f"  {eintrag['datei']} {eintrag['zelle']}: {eintrag['fehler']}")


def _bericht_ausgeben(bericht) -> None:
    from app.geld import formatiere_euro

    typer.echo("\nÜbernommen:")
    typer.echo(f"  Kunden:            {bericht.kunden}")
    typer.echo(f"  Projekte:          {bericht.projekte}")
    typer.echo(f"  Meilensteine:      {bericht.meilensteine}")
    typer.echo(
        f"  Zahlungsplan:      {bericht.zahlungsplan} Positionen, "
        f"{formatiere_euro(bericht.zahlungsplan_summe_cent)}"
    )
    typer.echo(f"  davon gestellt:    {bericht.zahlungsplan_gestellt}")
    if bericht.projekte_ohne_auftragsjahr:
        typer.echo(
            f"  ohne Auftragsjahr: {bericht.projekte_ohne_auftragsjahr} "
            "(Projektnummer im laufenden Jahr)"
        )
    if bericht.ab_luecken:
        typer.echo(
            f"\n{len(bericht.ab_luecken)} Projekte, deren Zahlungsplan nicht zum Auftragswert "
            f"passt (gesamt {formatiere_euro(bericht.luecke_gesamt_cent)}):"
        )
        for eintrag in bericht.ab_luecken[:10]:
            typer.echo(
                f"  Projekt {eintrag['projekt_nr']}: Auftrag "
                f"{formatiere_euro(int(eintrag['ab_wert_cent']))}, Plan "
                f"{formatiere_euro(int(eintrag['zahlungsplan_cent']))}, Differenz "
                f"{formatiere_euro(int(eintrag['differenz_cent']))}"
            )
        if len(bericht.ab_luecken) > 10:
            typer.echo(f"  ... und {len(bericht.ab_luecken) - 10} weitere, siehe Importprotokoll")
        typer.echo(
            "  Die Auftragsliste führt nur die offenen Positionen; bei Altprojekten ist der "
            "Rest in früheren Jahren berechnet worden."
        )
    if bericht.gewerk_abgeleitet:
        typer.echo(
            f"\n{len(bericht.gewerk_abgeleitet)} Positionen ohne Gewerk im Text – aus den "
            "Anlagendaten abgeleitet, bitte in der Projektmaske nachsehen."
        )
    if bericht.gleiche_bezeichnung:
        typer.echo(
            f"\n{len(bericht.gleiche_bezeichnung)} Projekte mit mehreren Positionen gleichen "
            "Namens – der Text kommt unverändert aus der Auftragsliste:"
        )
        for eintrag in bericht.gleiche_bezeichnung[:10]:
            zeilen = ", ".join(str(z) for z in eintrag["zeilen"])  # type: ignore[union-attr]
            typer.echo(
                f"  Projekt {eintrag['projekt_nr']}: "
                f"\u201e{eintrag['bezeichnung']}\u201c in den Zeilen {zeilen}"
            )
        if len(bericht.gleiche_bezeichnung) > 10:
            typer.echo(
                f"  ... und {len(bericht.gleiche_bezeichnung) - 10} weitere, siehe Importprotokoll"
            )
        typer.echo(
            "  Gemeint sind meist der erste, zweite, dritte Abschlag. Ab Phase 3 steht dieser "
            "Text auf der Rechnung – im Zahlungsplan des Projekts nachziehen."
        )
    typer.echo(f"\nImportprotokoll: importlaeufe Nr. {bericht.importlauf_id}")


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
