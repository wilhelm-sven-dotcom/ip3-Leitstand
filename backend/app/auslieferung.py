"""Auslieferung der gebauten Oberfläche (PLAN §2: ein Dienst).

Vier Punkte, die im Betrieb Ärger machen, wenn man sie falsch macht:

1. **Der Rückfall auf ``index.html`` wird nach den API-Routern registriert.** Sonst
   verschluckt er ``/api/...``, und ein Tippfehler in einem API-Pfad liefert HTML mit Status
   200 – die Oberfläche meldet dann „unerwartete Antwort" und niemand weiß, warum.

2. **``/api``-Pfade bleiben JSON.** Der Rückfall lässt sie ausdrücklich aus, damit ein
   unbekannter API-Pfad einen Fehlerkörper liefert und keine HTML-Seite.

3. **``index.html`` mit ``no-store``.** Die Datei verweist auf Dateinamen mit Namenshash;
   liegt sie im Browsercache, lädt der Browser nach einem Update alte JavaScript-Dateien gegen
   eine neue Schnittstelle. Dieser Fehler trifft einzelne Nutzer und ist von außen kaum zu
   erkennen – deshalb wird die Datei nie zwischengespeichert, die gehashten Dateien dagegen
   dauerhaft.

4. **Fehlt der Build, startet die Anwendung trotzdem.** Sie protokolliert einen Hinweis, und
   die API bleibt nutzbar. Ein Dienst, der wegen einer fehlenden Oberfläche nicht startet,
   verhindert auch die Fehlersuche.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.protokoll import logger

log = logger(__name__)

# Unterverzeichnis mit den gehashten Dateien, die Vite erzeugt.
ASSETS = "assets"


def _index_antwort(datei: Path) -> FileResponse:
    return FileResponse(
        datei,
        media_type="text/html",
        headers={
            # Siehe Punkt 3 im Modulkommentar.
            "Cache-Control": "no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )


def einrichten(app: FastAPI, verzeichnis: Path | None) -> None:
    """Statische Oberfläche einhängen. Ohne Verzeichnis passiert nichts."""
    if verzeichnis is None:
        log.info(
            "Kein Frontend-Verzeichnis eingerichtet – es wird nur die API ausgeliefert. "
            "Für den Betrieb in config.toml unter [pfade] frontend auf frontend/dist setzen."
        )
        return

    index = verzeichnis / "index.html"
    if not index.exists():
        log.warning(
            "Die Oberfläche fehlt: %s ist nicht vorhanden. Der Leitstand läuft, zeigt aber "
            "keine Seiten. Nächster Schritt: im Ordner frontend 'npm ci && npm run build' "
            "ausführen und [pfade] frontend auf frontend/dist setzen.",
            index,
        )
        return

    assets = verzeichnis / ASSETS
    if assets.is_dir():
        # Gehashte Dateinamen: der Browser darf sie dauerhaft behalten.
        app.mount(
            f"/{ASSETS}",
            StaticFiles(directory=assets),
            name="assets",
        )

    @app.get("/{restpfad:path}", include_in_schema=False)
    async def oberflaeche(restpfad: str, request: Request):
        """Alles, was keine API-Route ist, beantwortet die Oberfläche.

        Damit funktionieren Adressen wie ``/projekte/26014`` auch beim direkten Aufruf und
        nach einem Neuladen – die Zuordnung übernimmt der Router im Browser.
        """
        # Punkt 2 im Modulkommentar: API-Pfade bleiben JSON.
        if restpfad.startswith("api/") or restpfad == "api":
            return JSONResponse(
                status_code=404,
                content={
                    "code": "nicht_gefunden",
                    "meldung": "Diese Schnittstelle gibt es nicht.",
                    "naechster_schritt": "Bitte die Seite neu laden. Tritt es wieder auf, ist "
                    "die Oberfläche älter als der Server – dann hilft ein erneutes Update.",
                },
            )

        # Eine echte Datei ausliefern, wenn es sie gibt (Favicon, robots.txt und Ähnliches).
        kandidat = (verzeichnis / restpfad).resolve()
        try:
            innerhalb = kandidat.is_relative_to(verzeichnis.resolve())
        except ValueError:  # pragma: no cover – unterschiedliche Laufwerke unter Windows
            innerhalb = False
        if restpfad and innerhalb and kandidat.is_file():
            return FileResponse(kandidat)

        return _index_antwort(index)

    log.info("Oberfläche wird ausgeliefert aus %s", verzeichnis)
