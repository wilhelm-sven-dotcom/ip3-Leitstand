"""Zuordnung der Auftragsliste zu den Projekten der Teamliste (PLAN §9).

Beide Dateien führen den Kunden als Freitext, unabhängig voneinander gepflegt. Der Abgleich muss
also unscharf arbeiten – und genau dort liegt die Gefahr. Im echten Bestand liefert ein
Ähnlichkeitsmaß von 0,80 den Treffer **„Nachtmann, Weiden" → „Hubmann, Weiden"**: zwei
verschiedene Kunden, 550.000 € am falschen Projekt. Deshalb die harte Regel dieses Moduls:

    **Nur der exakte Treffer auf der Vergleichsform wird automatisch übernommen.
    Jeder unscharfe Treffer geht in die Zuordnungsmaske und braucht eine Bestätigung.**

Das ist keine Vorsicht auf Vorrat, sondern die Antwort auf einen belegten Fehltreffer. Der Test
``test_falschtreffer_wird_nicht_automatisch_uebernommen`` hält den Fall fest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz

from app.migration.quellen import AuftragsZeile, ProjektZeile
from app.migration.vokabular import vergleichsform

# Ab dieser Güte wird ein Vorschlag überhaupt angezeigt. Darunter ist er Rauschen und kostet in
# der Maske nur Zeit. Übernommen wird ein Vorschlag nie von allein.
VORSCHLAG_AB = 80.0

# Name und Ort werden getrennt bewertet und gewichtet zusammengezogen. Ohne diese Trennung
# genügt ein gemeinsamer Ort für 85 Punkte: 'Nachtmann, Weiden' und 'Lackierfachbetrieb Birkner,
# Weiden' sehen dann ähnlich aus, obwohl nur der Ort gleich ist. Der Name muss deshalb für sich
# passen, sonst gibt es überhaupt keinen Vorschlag.
NAME_MINDESTGUETE = 72.0
GEWICHT_NAME = 0.75
GEWICHT_ORT = 0.25

# Fehlt auf einer Seite der Ort, gibt es nur ein Signal – dann muss der Name deutlicher passen.
# 'Volksfestplatz Weiden 1' und 'Winter, Weiden' kommen sonst auf 86 Punkte, allein weil beide
# das Wort Weiden enthalten; im Bestand teilen sich 60 Projekte diesen Ort.
VORSCHLAG_AB_OHNE_ORT = 90.0

# Wie viele Vorschläge je unzugeordnetem Kunden angeboten werden.
VORSCHLAEGE_JE_KUNDE = 3


class Art(StrEnum):
    """Wie eine Zuordnung entstanden ist."""

    EXAKT = "exakt"
    VORSCHLAG = "vorschlag"
    OHNE = "ohne"
    BESTAETIGT = "bestaetigt"
    NEUES_PROJEKT = "neues_projekt"

    @property
    def braucht_bestaetigung(self) -> bool:
        return self in (Art.VORSCHLAG, Art.OHNE)


@dataclass(frozen=True)
class Vorschlag:
    """Ein möglicher Treffer mit seiner Ähnlichkeit."""

    projekt_zeile: int
    kunde: str
    guete: float


@dataclass
class Zuordnung:
    """Ein Kunde der Auftragsliste und das Projekt, zu dem seine Zeilen gehören."""

    kundenteil: str
    vergleichsform: str
    auftrags_zeilen: list[int]
    betrag_cent: int
    art: Art
    projekt_zeile: int | None = None
    vorschlaege: list[Vorschlag] = field(default_factory=list)

    @property
    def zugeordnet(self) -> bool:
        return self.projekt_zeile is not None

    @property
    def offen(self) -> bool:
        """Braucht eine Entscheidung in der Maske."""
        return self.art.braucht_bestaetigung


@dataclass
class Zuordnungsvorschau:
    """Gesamtbild vor der Übernahme."""

    zuordnungen: list[Zuordnung] = field(default_factory=list)
    # Projekte der Teamliste, deren Kundenname mehrfach vorkommt. Ein exakter Treffer wäre dort
    # nicht eindeutig, deshalb entscheidet auch hier ein Mensch.
    mehrdeutige_kunden: dict[str, list[int]] = field(default_factory=dict)

    def je_art(self) -> dict[str, int]:
        zaehler: dict[str, int] = {}
        for zuordnung in self.zuordnungen:
            zaehler[zuordnung.art.value] = zaehler.get(zuordnung.art.value, 0) + 1
        return dict(sorted(zaehler.items()))

    def zeilen_je_art(self) -> dict[str, int]:
        zaehler: dict[str, int] = {}
        for zuordnung in self.zuordnungen:
            schluessel = zuordnung.art.value
            zaehler[schluessel] = zaehler.get(schluessel, 0) + len(zuordnung.auftrags_zeilen)
        return dict(sorted(zaehler.items()))

    @property
    def offene(self) -> list[Zuordnung]:
        return [z for z in self.zuordnungen if z.offen]

    @property
    def betrag_offen_cent(self) -> int:
        return sum(z.betrag_cent for z in self.offene)


def vorschau_erstellen(
    auftragszeilen: list[AuftragsZeile], projektzeilen: list[ProjektZeile]
) -> Zuordnungsvorschau:
    """Ordnet die Auftragszeilen den Projekten zu, ohne etwas zu schreiben.

    Gruppiert wird je Kunde: die acht Abschlagszeilen eines Projekts gehören zusammen und werden
    gemeinsam entschieden, nicht achtmal einzeln.
    """
    vorschau = Zuordnungsvorschau()
    formen = _projektformen(projektzeilen)
    vorschau.mehrdeutige_kunden = {
        form: zeilen for form, zeilen in formen.items() if len(zeilen) > 1
    }
    for kundenteil, zeilen in _nach_kunde(auftragszeilen).items():
        form = vergleichsform(kundenteil)
        betrag = sum(z.betrag_cent for z in zeilen)
        nummern = [z.zeile for z in zeilen]
        eindeutig = formen.get(form, [])

        if len(eindeutig) == 1:
            vorschau.zuordnungen.append(
                Zuordnung(
                    kundenteil=kundenteil,
                    vergleichsform=form,
                    auftrags_zeilen=nummern,
                    betrag_cent=betrag,
                    art=Art.EXAKT,
                    projekt_zeile=eindeutig[0],
                )
            )
            continue

        erste = zeilen[0]
        vorschlaege = _vorschlaege(erste.kunde, erste.ort, projektzeilen)
        # Ein mehrfach vorkommender Kundenname ist ein exakter Treffer ohne Eindeutigkeit: die
        # Vorschläge sind dann genau diese Projekte, entscheiden muss sie ein Mensch.
        vorschau.zuordnungen.append(
            Zuordnung(
                kundenteil=kundenteil,
                vergleichsform=form,
                auftrags_zeilen=nummern,
                betrag_cent=betrag,
                art=Art.VORSCHLAG if vorschlaege else Art.OHNE,
                vorschlaege=vorschlaege,
            )
        )
    vorschau.zuordnungen.sort(key=lambda z: (-z.betrag_cent, z.kundenteil))
    return vorschau


def _nach_kunde(auftragszeilen: list[AuftragsZeile]) -> dict[str, list[AuftragsZeile]]:
    """Zeilen der Auftragsliste je Kundenteil, Reihenfolge der Datei bleibt erhalten."""
    gruppen: dict[str, list[AuftragsZeile]] = {}
    for zeile in auftragszeilen:
        gruppen.setdefault(zeile.kundenteil, []).append(zeile)
    return gruppen


def _projektformen(projektzeilen: list[ProjektZeile]) -> dict[str, list[int]]:
    """Vergleichsformen der Teamliste auf Zeilennummern.

    Neben dem vollen Kundentext wird die Form ohne Projektzusatz aufgenommen: die Teamliste
    schreibt Varianten wie 'Ammann, Weiherhammer - Wallbox', die Auftragsliste nur den Kunden.
    """
    formen: dict[str, list[int]] = {}
    for projekt in projektzeilen:
        for text in _varianten(projekt.kundenteil):
            form = vergleichsform(text)
            if not form:
                continue
            if projekt.zeile not in formen.setdefault(form, []):
                formen[form].append(projekt.zeile)
    return formen


def _varianten(kundentext: str) -> list[str]:
    varianten = [kundentext]
    if " - " in kundentext:
        varianten.append(kundentext.split(" - ")[0])
    return varianten


def guete(kunde: str, ort: str | None, projekt_kunde: str, projekt_ort: str | None) -> float:
    """Ähnlichkeit zweier Kundenangaben, Name und Ort getrennt gewichtet.

    Ergibt 0, wenn schon der Name nicht passt. Der Ort verstärkt oder dämpft nur – er kann einen
    fremden Namen nicht zum Treffer machen. Genau daran wäre der Abgleich sonst gescheitert:
    im echten Bestand teilen sich 60 Projekte den Ort Weiden.
    """
    namensguete = fuzz.WRatio(vergleichsform(kunde), vergleichsform(projekt_kunde))
    if namensguete < NAME_MINDESTGUETE:
        return 0.0
    if not ort or not projekt_ort:
        return float(namensguete)
    ortsguete = fuzz.WRatio(vergleichsform(ort), vergleichsform(projekt_ort))
    return GEWICHT_NAME * float(namensguete) + GEWICHT_ORT * float(ortsguete)


def _vorschlaege(kunde: str, ort: str | None, projektzeilen: list[ProjektZeile]) -> list[Vorschlag]:
    """Bis zu drei ähnlichste Projekte, absteigend nach Güte."""
    bewertet: list[Vorschlag] = []
    for projekt in projektzeilen:
        punkte = max(
            guete(kunde, ort, projekt.kunde, projekt.ort),
            # Auch gegen den vollen Kundentext prüfen: dort steht bei manchen Projekten der
            # Zusatz, der den Ausschlag gibt ('Haas, Waldershof - Batteriespeicher').
            guete(kunde, ort, projekt.kundenteil, projekt.ort),
        )
        schwelle = VORSCHLAG_AB if (ort and projekt.ort) else VORSCHLAG_AB_OHNE_ORT
        if punkte >= schwelle:
            bewertet.append(
                Vorschlag(
                    projekt_zeile=projekt.zeile,
                    kunde=projekt.kundenteil,
                    guete=round(punkte, 1),
                )
            )
    bewertet.sort(key=lambda v: (-v.guete, v.projekt_zeile))
    return bewertet[:VORSCHLAEGE_JE_KUNDE]


def bestaetigen(vorschau: Zuordnungsvorschau, entscheidungen: dict[str, int | None]) -> None:
    """Übernimmt die Entscheidungen aus der Maske in die Vorschau.

    ``entscheidungen`` bildet den Kundenteil auf eine Projektzeile ab; ``None`` heißt „als
    eigenes Projekt anlegen". Ein Kunde, der in der Vorschau nicht vorkommt, wird abgewiesen –
    stiller Leerlauf wäre die schlechtere Antwort.
    """
    nach_kunde = {z.kundenteil: z for z in vorschau.zuordnungen}
    unbekannt = sorted(set(entscheidungen) - set(nach_kunde))
    if unbekannt:
        raise UnbekannterKunde(unbekannt)

    for kundenteil, projekt_zeile in entscheidungen.items():
        zuordnung = nach_kunde[kundenteil]
        if projekt_zeile is None:
            zuordnung.art = Art.NEUES_PROJEKT
            zuordnung.projekt_zeile = None
        else:
            zuordnung.art = Art.BESTAETIGT
            zuordnung.projekt_zeile = projekt_zeile


class UnbekannterKunde(Exception):
    """Eine Entscheidung nennt einen Kunden, den die Vorschau nicht kennt."""

    def __init__(self, kunden: list[str]) -> None:
        super().__init__(", ".join(kunden))
        self.kunden = kunden
