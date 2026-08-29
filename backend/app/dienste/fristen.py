"""Fristenwächter: was demnächst abläuft (PLAN §6.9, §7 Phase 6).

Fristen sind der einzige Teil des Leitstands, der von selbst etwas anstößt. Alles andere
antwortet auf eine Frage; hier meldet sich die Anwendung. Damit das trägt, gelten drei
Festlegungen:

* **Der Vorlauf steht an der Frist, nicht an der Liste.** Die Gewährleistung meldet sich drei
  Monate vorher, eine MaStR-Registrierung nach zwei Wochen. Beides in einer Liste mit einem
  gemeinsamen Vorlauf zu zeigen hieße, entweder zu früh zu lärmen oder zu spät zu warnen.
* **Erledigt bleibt erledigt.** Der nächtliche Lauf legt Fristen an und hakt sie ab, wenn die
  Voraussetzung erfüllt ist – aber er macht nie eine wieder auf, die jemand von Hand
  geschlossen hat.
* **Kein Mailversand** (Entscheidung 34). PLAN §12 und CLAUDE.md schließen ihn aus; die Fristen
  stehen auf der Startseite und in der Fristenliste. Eine Erinnerung, die im Postfach
  untergeht, ist keine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dienste.anlagen import frist_setzen
from app.modelle import Anlage, Frist, Kunde, Projekt

# Ab wann eine Frist als „läuft ab" gilt: sie liegt im eigenen Vorlauf.
STATUS_UEBERFAELLIG = "ueberfaellig"
STATUS_FAELLIG = "faellig"
STATUS_OFFEN = "offen"

FRIST_MASTR = "mastr"

# Reihenfolge für die Anzeige: das Dringendste zuerst.
_RANG = {STATUS_UEBERFAELLIG: 0, STATUS_FAELLIG: 1, STATUS_OFFEN: 2}


def status_fuer(faellig_am: date, vorlauf_tage: int, stichtag: date) -> str:
    """Überfällig, fällig (im Vorlauf) oder noch offen."""
    if faellig_am < stichtag:
        return STATUS_UEBERFAELLIG
    if faellig_am - timedelta(days=max(vorlauf_tage, 0)) <= stichtag:
        return STATUS_FAELLIG
    return STATUS_OFFEN


@dataclass
class Fristzeile:
    """Eine Frist mit aufgelöstem Bezug – so, wie sie auf der Startseite steht."""

    id: int
    typ: str
    bezeichnung: str
    faellig_am: date
    vorlauf_tage: int
    status: str
    # Negativ heißt überfällig: „seit 12 Tagen" ist die Auskunft, die zählt.
    tage_bis: int
    bezug: str
    bezug_id: int
    betreff: str
    kunde: str | None = None
    erledigt_am: date | None = None
    # Für die Konfliktprüfung beim Speichern (CLAUDE.md Regel 6). Steht hier, damit die Route
    # nicht alle Fristen ein zweites Mal laden muss, nur um an ``updated_at`` zu kommen.
    stand: datetime | None = None


def _betreffe(
    sitzung: Session, fristen: list[Frist]
) -> dict[tuple[str, int], tuple[str, str | None]]:
    """Bezug je Frist auflösen: Anlagenstandort bzw. Projektnummer, dazu der Kunde.

    In zwei Abfragen statt einer je Frist – die Startseite lädt sonst bei jedem Aufruf ein
    Dutzend Einzelabfragen.
    """
    anlagen_ids = {f.bezug_id for f in fristen if f.bezug == "anlage"}
    projekt_ids = {f.bezug_id for f in fristen if f.bezug == "projekt"}
    betreffe: dict[tuple[str, int], tuple[str, str | None]] = {}

    if anlagen_ids:
        zeilen = sitzung.execute(
            select(Anlage.id, Anlage.standort, Kunde.name)
            .join(Kunde, Kunde.id == Anlage.kunde_id)
            .where(Anlage.id.in_(anlagen_ids))
        ).all()
        for anlage_id, standort, kunde in zeilen:
            betreffe[("anlage", anlage_id)] = (standort or f"Anlage {anlage_id}", kunde)

    if projekt_ids:
        zeilen = sitzung.execute(
            select(Projekt.id, Projekt.projekt_nr, Projekt.bezeichnung, Kunde.name)
            .join(Kunde, Kunde.id == Projekt.kunde_id)
            .where(Projekt.id.in_(projekt_ids))
        ).all()
        for projekt_id, projekt_nr, bezeichnung, kunde in zeilen:
            beschriftung = f"{projekt_nr}" + (f" – {bezeichnung}" if bezeichnung else "")
            betreffe[("projekt", projekt_id)] = (beschriftung, kunde)

    return betreffe


def liste(
    sitzung: Session,
    *,
    stichtag: date | None = None,
    nur_anstehende: bool = False,
    mit_erledigten: bool = False,
    grenze: int | None = None,
    bezug: str | None = None,
    bezug_id: int | None = None,
    frist_id: int | None = None,
) -> list[Fristzeile]:
    """Fristen mit aufgelöstem Bezug, das Dringendste zuerst.

    ``nur_anstehende`` liefert, was das Startseiten-Widget zeigt: überfällig oder im eigenen
    Vorlauf. Ohne die Einschränkung kommt die vollständige Liste – dieselben Daten, nur ohne
    Filter, damit die Fristenseite nicht eine zweite Abfrage braucht.

    ``bezug``/``bezug_id`` schränken auf einen Datensatz ein (das Anlagenblatt), ``frist_id`` auf
    eine einzelne Frist (die Antwort nach dem Speichern). Ohne diese Einschränkung würde jedes
    Anlagenblatt sämtliche Fristen der Firma laden.
    """
    heute = stichtag or date.today()
    abfrage = select(Frist)
    if not mit_erledigten:
        abfrage = abfrage.where(Frist.erledigt_am.is_(None))
    if bezug is not None:
        abfrage = abfrage.where(Frist.bezug == bezug)
    if bezug_id is not None:
        abfrage = abfrage.where(Frist.bezug_id == bezug_id)
    if frist_id is not None:
        abfrage = abfrage.where(Frist.id == frist_id)
    fristen = list(sitzung.scalars(abfrage.order_by(Frist.faellig_am, Frist.id)))

    betreffe = _betreffe(sitzung, fristen)
    zeilen: list[Fristzeile] = []
    for frist in fristen:
        zustand = status_fuer(frist.faellig_am, frist.vorlauf_tage, heute)
        if nur_anstehende and zustand == STATUS_OFFEN:
            continue
        betreff, kunde = betreffe.get(
            (frist.bezug, frist.bezug_id), (f"{frist.bezug} {frist.bezug_id}", None)
        )
        zeilen.append(
            Fristzeile(
                id=frist.id,
                typ=frist.typ,
                bezeichnung=frist.bezeichnung,
                faellig_am=frist.faellig_am,
                vorlauf_tage=frist.vorlauf_tage,
                status=zustand,
                tage_bis=(frist.faellig_am - heute).days,
                bezug=frist.bezug,
                bezug_id=frist.bezug_id,
                betreff=betreff,
                kunde=kunde,
                erledigt_am=frist.erledigt_am,
                stand=frist.updated_at,
            )
        )

    zeilen.sort(key=lambda z: (_RANG[z.status], z.faellig_am, z.id))
    return zeilen[:grenze] if grenze else zeilen


def zaehlung(zeilen: list[Fristzeile]) -> dict[str, int]:
    """Wie viele je Zustand – die Zahl über dem Widget."""
    gezaehlt = {STATUS_UEBERFAELLIG: 0, STATUS_FAELLIG: 0, STATUS_OFFEN: 0}
    for zeile in zeilen:
        gezaehlt[zeile.status] += 1
    return gezaehlt


@dataclass
class Wachergebnis:
    """Was der nächtliche Lauf getan hat."""

    # Nur neu entstandene Fristen. Ein Lauf, der nur bestätigt, was schon dasteht, meldet 0 –
    # sonst stünde jede Nacht dieselbe Zahl im Protokoll und sagte nichts mehr.
    gesetzt: int = 0
    erledigt: int = 0
    ueberfaellig: int = 0
    faellig: int = 0
    hinweise: list[str] = field(default_factory=list)


def mastr_pflegen(sitzung: Session, *, tage: int, stichtag: date | None = None) -> Wachergebnis:
    """MaStR-Fristen aus den Inbetriebnahmedaten ableiten (§ 5 Abs. 1 MaStRV).

    Das Marktstammdatenregister verlangt die Registrierung binnen eines Monats nach
    Inbetriebnahme. Die Frist entsteht also nicht durch Eingabe, sondern aus einer Tatsache –
    und sie erledigt sich selbst, sobald die Nummer im Anlagenregister steht. Genau deshalb
    darf der Lauf beliebig oft laufen: er rechnet jedes Mal denselben Stand aus.
    """
    ergebnis = Wachergebnis()

    offen = sitzung.scalars(
        select(Anlage).where(Anlage.inbetriebnahme.is_not(None), _ohne_mastr_nummer())
    )
    for anlage in offen:
        assert anlage.inbetriebnahme is not None  # von der Abfrage garantiert
        _, ist_neu = frist_setzen(
            sitzung,
            bezug="anlage",
            bezug_id=anlage.id,
            typ=FRIST_MASTR,
            bezeichnung=(
                "Registrierung im Marktstammdatenregister "
                f"(Inbetriebnahme {anlage.inbetriebnahme:%d.%m.%Y})"
            ),
            faellig_am=anlage.inbetriebnahme + timedelta(days=tage),
            # Die Frist ist kurz; ein Vorlauf über die halbe Laufzeit wäre Dauerlärm.
            vorlauf_tage=max(tage // 2, 1),
        )
        if ist_neu:
            ergebnis.gesetzt += 1

    # Nummer nachgetragen: die Frist ist erfüllt, nicht verfallen.
    heute = stichtag or date.today()
    erledigte = sitzung.scalars(
        select(Frist)
        .join(Anlage, Anlage.id == Frist.bezug_id)
        .where(
            Frist.bezug == "anlage",
            Frist.typ == FRIST_MASTR,
            Frist.erledigt_am.is_(None),
            ~_ohne_mastr_nummer(),
        )
    )
    for frist in erledigte:
        frist.erledigt_am = heute
        ergebnis.erledigt += 1

    sitzung.flush()
    return ergebnis


def _ohne_mastr_nummer():
    """Keine MaStR-Nummer: NULL oder leer. Ein Leerstring ist keine Registrierung."""
    return (Anlage.mastr_nr.is_(None)) | (Anlage.mastr_nr == "")


def wachen(sitzung: Session, *, mastr_tage: int, stichtag: date | None = None) -> Wachergebnis:
    """Der nächtliche Lauf: Fristen ableiten, abhaken, zählen.

    Es wird nichts verschickt (Entscheidung 34) – das Ergebnis ist die Zahl im Job-Protokoll
    und der Stand, den die Startseite am nächsten Morgen zeigt.
    """
    heute = stichtag or date.today()
    ergebnis = mastr_pflegen(sitzung, tage=mastr_tage, stichtag=heute)

    anstehend = liste(sitzung, stichtag=heute, nur_anstehende=True)
    gezaehlt = zaehlung(anstehend)
    ergebnis.ueberfaellig = gezaehlt[STATUS_UEBERFAELLIG]
    ergebnis.faellig = gezaehlt[STATUS_FAELLIG]

    for zeile in anstehend:
        if zeile.status == STATUS_UEBERFAELLIG:
            ergebnis.hinweise.append(
                f"{zeile.betreff}: {zeile.bezeichnung} war am {zeile.faellig_am:%d.%m.%Y} fällig."
            )
    return ergebnis
