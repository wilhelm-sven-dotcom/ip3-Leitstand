"""TimeTac-Schnittstelle, REST v3 mit Client-Credentials (PLAN §8).

**Diese Tests gehen nie ins Netz.** Sie laufen gegen abgelegte Antworten in
``tests/fixtures/timetac/`` über einen eingehängten ``httpx.MockTransport``. Das ist nicht nur
Testhygiene: die Entwicklungsumgebung erreicht ``api.timetac.com`` gar nicht, die
Netzwerkrichtlinie lehnt die Verbindung ab. Der erste echte Lauf findet auf dem Windows-Host
statt (``ip3-leitstand timetac-test``).

Geprüft wird deshalb vor allem, was auch dann noch stimmen muss, wenn die Antwort im Detail
abweicht: die Anmeldung, der Seitenlauf, jeder Fehlerpfad mit seiner deutschen Meldung – und
dass weder Secret noch Token irgendwo auftauchen.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.importe.timetac_api import (
    AnmeldungAbgelehnt,
    AntwortUnverstaendlich,
    NichtErreichbar,
    TimeTacClient,
    ZugangsdatenFehlen,
    ZugriffAbgelehnt,
    ZuVieleAnfragen,
    abfrage_bauen,
    abholen,
    monate_bestimmen,
)
from app.konfiguration import TimeTacEinstellungen
from app.zeit import jetzt_utc

FIXTURES = Path(__file__).parent / "fixtures" / "timetac"
GEHEIM = "streng-geheimes-secret"
KONTO = "ip3energie"


def antwort_aus(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Aufzeichnung:
    """Merkt sich alle Anfragen und beantwortet sie aus den abgelegten Dateien."""

    def __init__(self, seiten: list[list[dict]] | None = None, **antworten: httpx.Response):
        self.anfragen: list[httpx.Request] = []
        self.seiten = seiten
        self.antworten = antworten

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        self.anfragen.append(anfrage)
        pfad = anfrage.url.path
        if pfad.endswith("/token"):
            return self.antworten.get("token") or httpx.Response(
                200, json=antwort_aus("token.json")
            )
        if self.seiten is not None:
            versatz = int(anfrage.url.params.get("offset", 0))
            grenze = int(anfrage.url.params.get("limit", 200))
            nummer = versatz // grenze if grenze else 0
            eintraege = self.seiten[nummer] if nummer < len(self.seiten) else []
            return httpx.Response(200, json={"Success": True, "Results": eintraege})
        return self.antworten.get("daten") or httpx.Response(
            200, json=antwort_aus("timeTrackings.json")
        )

    @property
    def datenanfragen(self) -> list[httpx.Request]:
        return [a for a in self.anfragen if not a.url.path.endswith("/token")]


def client_bauen(
    aufzeichnung: Aufzeichnung, **abweichend: object
) -> tuple[TimeTacClient, Aufzeichnung]:
    einstellungen = TimeTacEinstellungen(**abweichend)
    return (
        TimeTacClient(
            einstellungen,
            client_id="CLIENT__API_USER_1",
            client_secret=GEHEIM,
            konto=KONTO,
            transport=httpx.MockTransport(aufzeichnung),
        ),
        aufzeichnung,
    )


# ---------------------------------------------------------------------------
# Zugangsdaten und Adressen
# ---------------------------------------------------------------------------


def test_fehlende_zugangsdaten_werden_beim_bauen_gemeldet() -> None:
    with pytest.raises(ZugangsdatenFehlen) as fehler:
        TimeTacClient(TimeTacEinstellungen(), client_id="", client_secret="", konto="")
    assert "IP3_TIMETAC_CLIENT_ID" in str(fehler.value)
    assert ".env" in fehler.value.naechster_schritt
    assert "config.toml" in fehler.value.naechster_schritt


def test_adressen_werden_aus_konto_und_basis_gebildet() -> None:
    client, _ = client_bauen(Aufzeichnung())
    assert client.token_adresse() == "https://api.timetac.com/auth/oauth2/token"
    assert (
        client.ressourcen_adresse("timeTrackings")
        == f"https://api.timetac.com/{KONTO}/api/v3/timeTrackings.json"
    )


def test_eigene_basis_url_wird_benutzt() -> None:
    client, _ = client_bauen(Aufzeichnung(), basis_url="https://test.timetac.com/")
    assert client.token_adresse().startswith("https://test.timetac.com/auth")


# ---------------------------------------------------------------------------
# Anmeldung
# ---------------------------------------------------------------------------


def test_anmeldung_schickt_client_credentials() -> None:
    client, auf = client_bauen(Aufzeichnung())
    client.lesen("timeTrackings")

    anmeldung = auf.anfragen[0]
    inhalt = anmeldung.content.decode()
    assert "grant_type=client_credentials" in inhalt
    assert anmeldung.method == "POST"


def test_token_wird_wiederverwendet_und_vor_ablauf_erneuert() -> None:
    client, auf = client_bauen(Aufzeichnung())
    client.lesen("timeTrackings")
    client.lesen("timeTrackings")
    assert sum(1 for a in auf.anfragen if a.url.path.endswith("/token")) == 1

    # Kurz vor Ablauf wird erneuert, damit kein Seitenlauf mitten hinein läuft.
    client._zugang.gueltig_bis = jetzt_utc() + timedelta(seconds=30)
    client.lesen("timeTrackings")
    assert sum(1 for a in auf.anfragen if a.url.path.endswith("/token")) == 2


def test_datenanfrage_traegt_das_token_als_bearer() -> None:
    client, auf = client_bauen(Aufzeichnung())
    client.lesen("timeTrackings")
    kopf = auf.datenanfragen[0].headers["Authorization"]
    assert kopf.startswith("Bearer ")


@pytest.mark.parametrize("status", [400, 401])
def test_abgelehnte_anmeldung_nennt_das_secret_als_ursache(status: int) -> None:
    client, _ = client_bauen(
        Aufzeichnung(token=httpx.Response(status, json={"error": "invalid_client"}))
    )
    with pytest.raises(AnmeldungAbgelehnt) as fehler:
        client.lesen("timeTrackings")
    assert "Secret" in fehler.value.naechster_schritt


def test_antwort_ohne_token_wird_erklaert() -> None:
    client, _ = client_bauen(Aufzeichnung(token=httpx.Response(200, json={"ok": True})))
    with pytest.raises(AntwortUnverstaendlich, match="access_token"):
        client.lesen("timeTrackings")


# ---------------------------------------------------------------------------
# Seitenlauf
# ---------------------------------------------------------------------------


def test_seitenlauf_ueber_drei_seiten() -> None:
    seiten = [
        [{"id": i} for i in range(2)],
        [{"id": i} for i in range(2, 4)],
        [{"id": 4}],  # kürzer als die Seitengröße: Ende
    ]
    client, auf = client_bauen(Aufzeichnung(seiten=seiten), seitengroesse=2)
    eintraege = client.lesen("timeTrackings")

    assert [e["id"] for e in eintraege] == [0, 1, 2, 3, 4]
    assert [a.url.params.get("offset") for a in auf.datenanfragen] == ["0", "2", "4"]


def test_volle_letzte_seite_wird_durch_eine_leere_beendet() -> None:
    client, auf = client_bauen(Aufzeichnung(seiten=[[{"id": 1}, {"id": 2}], []]), seitengroesse=2)
    assert len(client.lesen("timeTrackings")) == 2
    assert len(auf.datenanfragen) == 2


def test_endloser_seitenlauf_wird_abgebrochen() -> None:
    """Eine Antwort, die immer weiterzählt, darf den nächtlichen Lauf nicht festhalten."""

    def immer_voll(anfrage: httpx.Request) -> httpx.Response:
        if anfrage.url.path.endswith("/token"):
            return httpx.Response(200, json=antwort_aus("token.json"))
        return httpx.Response(200, json={"Results": [{"id": 1}, {"id": 2}]})

    client = TimeTacClient(
        TimeTacEinstellungen(seitengroesse=2),
        client_id="a",
        client_secret="b",
        konto=KONTO,
        transport=httpx.MockTransport(immer_voll),
    )
    with pytest.raises(AntwortUnverstaendlich, match="Seitenlauf endet nicht"):
        client.lesen("timeTrackings")


def test_abfrage_traegt_grenze_versatz_und_filter() -> None:
    abfrage = abfrage_bauen({"date>=": "2026-07-01"}, grenze=200, versatz=400)
    assert abfrage == {"limit": 200, "offset": 400, "filter": "date>=2026-07-01"}


# ---------------------------------------------------------------------------
# Fehlerpfade
# ---------------------------------------------------------------------------


def test_verweigerter_zugriff_nennt_die_berechtigung() -> None:
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(403)))
    with pytest.raises(ZugriffAbgelehnt) as fehler:
        client.lesen("timeTrackings")
    assert "Berechtigungen" in fehler.value.naechster_schritt


def test_zu_viele_anfragen_nennen_die_wartezeit() -> None:
    client, _ = client_bauen(
        Aufzeichnung(daten=httpx.Response(429, headers={"Retry-After": "120"}))
    )
    with pytest.raises(ZuVieleAnfragen) as fehler:
        client.lesen("timeTrackings")
    assert "120" in fehler.value.naechster_schritt


def test_zeitueberschreitung_wird_verstaendlich() -> None:
    def zeitausfall(anfrage: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("zu langsam")

    client = TimeTacClient(
        TimeTacEinstellungen(zeitlimit_sekunden=5),
        client_id="a",
        client_secret="b",
        konto=KONTO,
        transport=httpx.MockTransport(zeitausfall),
    )
    with pytest.raises(NichtErreichbar) as fehler:
        client.lesen("timeTrackings")
    assert "Zeitüberschreitung" in str(fehler.value)
    assert "bleiben unverändert" in fehler.value.naechster_schritt


def test_serverfehler_laesst_die_stunden_stehen() -> None:
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(500)))
    with pytest.raises(NichtErreichbar, match="HTTP 500"):
        client.lesen("timeTrackings")


def test_antwort_ohne_ergebnisliste_verweist_auf_timetac_test() -> None:
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(200, json={"Success": True})))
    with pytest.raises(AntwortUnverstaendlich) as fehler:
        client.lesen("timeTrackings")
    assert "timetac-test" in fehler.value.naechster_schritt


def test_kein_geheimnis_in_meldung_oder_protokoll(caplog: pytest.LogCaptureFixture) -> None:
    """CLAUDE.md Regel 7: Passwörter, Hashes und Token erscheinen nirgends."""
    import logging

    caplog.set_level(logging.DEBUG)
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(500)))
    with pytest.raises(NichtErreichbar) as fehler:
        client.lesen("timeTrackings")

    gesammelt = caplog.text + str(fehler.value) + fehler.value.naechster_schritt
    assert GEHEIM not in gesammelt
    assert "tt-zugangstoken" not in gesammelt


# ---------------------------------------------------------------------------
# Abholen und deuten
# ---------------------------------------------------------------------------


def test_monate_bestimmen() -> None:
    einstellungen = TimeTacEinstellungen()
    assert monate_bestimmen(einstellungen, date(2026, 7, 15)) == ["2026-06", "2026-07"]
    assert monate_bestimmen(einstellungen, date(2026, 1, 3)) == ["2025-12", "2026-01"]
    assert monate_bestimmen(TimeTacEinstellungen(monate_rueckwirkend=0), date(2026, 7, 15)) == [
        "2026-07"
    ]


def test_abholen_uebersetzt_die_antwort_in_zeitbuchungen() -> None:
    client, _ = client_bauen(Aufzeichnung())
    lieferung = abholen(client, ["2026-07"])

    assert lieferung.herkunft == f"TimeTac {KONTO}"
    assert len(lieferung.buchungen) == 4
    erste = lieferung.buchungen[0]
    assert erste.mitarbeiter == "Wilhelm, Sven"
    assert erste.datum == date(2026, 7, 6)
    assert erste.stunden == Decimal("8.00"), "28800 Sekunden sind acht Stunden"
    assert erste.projekt_text.startswith("26001"), "die Nummer wird vorangestellt"


def test_abholen_filtert_auf_den_zeitraum() -> None:
    client, auf = client_bauen(Aufzeichnung())
    abholen(client, ["2026-06", "2026-07"])
    filter_ = auf.datenanfragen[0].url.params.get("filter")
    assert "2026-06-01" in filter_ and "2026-07-31" in filter_


def test_dauer_als_stundenfeld_wird_ebenso_verstanden() -> None:
    """Nicht jede Antwortform liefert Sekunden – die Feldnamen stehen in der config."""
    satz = {
        "user_name": "Wilhelm, Sven",
        "project_name": "26001 Mustermann",
        "date": "2026-07-06",
        "hours": "7,5",
    }
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(200, json={"Results": [satz]})))
    lieferung = abholen(client, ["2026-07"])
    assert lieferung.buchungen[0].stunden == Decimal("7.50")


@pytest.mark.parametrize(
    ("fehlend", "spalte"),
    [
        ("user_name", "mitarbeiter"),
        ("date", "datum"),
        ("duration", "dauer"),
    ],
)
def test_unvollstaendige_buchung_ergibt_befund_statt_abbruch(fehlend: str, spalte: str) -> None:
    saetze = antwort_aus("timeTrackings.json")["Results"]
    kaputt = dict(saetze[0])
    kaputt.pop(fehlend)
    kaputt.pop("start_time", None)
    client, _ = client_bauen(
        Aufzeichnung(daten=httpx.Response(200, json={"Results": [kaputt, saetze[1]]}))
    )
    lieferung = abholen(client, ["2026-07"])

    assert len(lieferung.buchungen) == 1, "die heile Buchung muss durchkommen"
    assert lieferung.befunde[0].spalte == spalte


def test_laufende_buchung_ohne_dauer_wird_still_uebergangen() -> None:
    """Eine begonnene, noch nicht beendete Zeit ist kein Fehler, sondern noch nicht fertig."""
    satz = {
        "user_name": "Wilhelm, Sven",
        "project_name": "26001 Mustermann",
        "date": "2026-07-06",
        "duration": 0,
    }
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(200, json={"Results": [satz]})))
    lieferung = abholen(client, ["2026-07"])
    assert lieferung.buchungen == [] and lieferung.befunde == []


def test_datum_mit_uhrzeit_wird_verstanden() -> None:
    satz = {
        "user_name": "Wilhelm, Sven",
        "project_name": "26001 Mustermann",
        "date": "2026-07-06 07:30:00",
        "duration": 3600,
    }
    client, _ = client_bauen(Aufzeichnung(daten=httpx.Response(200, json={"Results": [satz]})))
    assert abholen(client, ["2026-07"]).buchungen[0].datum == date(2026, 7, 6)
