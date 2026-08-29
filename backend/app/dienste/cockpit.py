"""Firmen-Cockpit: vom Umsatz zur Über-/Unterdeckung (PLAN §7 Phase 5).

Die Steuerungssicht der Geschäftsführung – **keine handelsrechtliche BWA.** Der Unterschied ist
kein Kleingedrucktes, sondern die Rechenweise: hier stehen Auftragswerte, kalkulatorische Sätze
und Planzahlen neben Buchhaltungswerten. Die Oberfläche sagt es an jeder Ansicht.

Der Rechenweg je Monat:

    Umsatz
    − variable Kosten (Material, Fremdleistung, Lagerentnahme)
    = Deckungsbeitrag
    − Fixkosten (SuSa, für Zukunftsmonate der Plan)
    = Über-/Unterdeckung

Vier Festlegungen, ohne die die Zahlen nicht stimmen:

* **Eigenleistung wird auf Firmenebene neutralisiert** (PLAN §6.6). Im Projekt-Ist zählen
  TimeTac-Stunden mal Verrechnungssatz; auf Firmenebene stehen die echten Personalkosten im
  Fixkostenblock. Beides zu addieren zählte Personal doppelt. Deshalb geht ``quelle='timetac'``
  hier ausdrücklich **nicht** in die variablen Kosten ein.
* **Fixkosten: Ist schlägt Plan.** Liegt für einen Monat eine Summen- und Saldenliste vor, gilt
  sie. Für Monate ohne SuSa – die Zukunft – gilt ``fixkosten_plan``. Nie beides addiert.
* **Der Block ``neutral`` zählt nicht.** Er ist zugeordnet und trotzdem draußen (durchlaufende
  Posten). Ein Konto ganz **ohne** Zuordnung zählt ebenfalls nicht, ist aber etwas anderes: es
  hat noch niemand angesehen, und darauf weist das Cockpit hin.
* **Break-even über die Ist-Marge des laufenden Jahres** (Entscheidung 27). Steht das Jahr erst
  am Anfang, ist die Basis dünn; dann kommt ein Hinweis statt einer Scheingenauigkeit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app import formate, geld
from app.dienste import auswertung
from app.modelle import DatevSaldo, FixkostenPlan, IstKosten, Zahlungsplanposition

# Ist-Quellen, die als variable Kosten in den Deckungsbeitrag eingehen. 'timetac' fehlt
# absichtlich – siehe Modulkopf, PLAN §6.6.
VARIABLE_QUELLEN = ("datev", "stueckliste")

# Blöcke, die im Fixkostenausweis nicht mitzählen.
NICHT_GERECHNET = ("neutral",)

# Ab wie vielen Monaten mit Umsatz die Jahresmarge als belastbar gilt (Entscheidung 27).
BELASTBAR_AB_MONATEN = 3


@dataclass
class Monatszahlen:
    """Ein Monat der Cockpit-Ansicht. Beträge in Cent (CLAUDE.md Regel 3)."""

    monat: str
    umsatz_cent: int = 0
    variable_kosten_cent: int = 0
    fixkosten_cent: int = 0
    # Woher die Fixkosten stammen: 'susa', 'plan' oder 'keine'.
    fixkosten_herkunft: str = "keine"

    @property
    def deckungsbeitrag_cent(self) -> int:
        return self.umsatz_cent - self.variable_kosten_cent

    @property
    def deckung_cent(self) -> int:
        """Über- oder Unterdeckung: was nach den Fixkosten übrig bleibt."""
        return self.deckungsbeitrag_cent - self.fixkosten_cent

    @property
    def db_promille(self) -> int | None:
        """Deckungsbeitrag in Promille des Umsatzes. ``None`` ohne Umsatz."""
        if self.umsatz_cent <= 0:
            return None
        return round(self.deckungsbeitrag_cent * 1000 / self.umsatz_cent)

    @property
    def fixkostendeckung_promille(self) -> int | None:
        """Wie weit der Deckungsbeitrag die Fixkosten trägt. ``None`` ohne Fixkosten."""
        if self.fixkosten_cent <= 0:
            return None
        return round(self.deckungsbeitrag_cent * 1000 / self.fixkosten_cent)


@dataclass
class Fixkostenblock:
    """Fixkosten eines Monats nach Blöcken."""

    monat: str
    herkunft: str
    je_block: dict[str, int] = field(default_factory=dict)

    @property
    def summe_cent(self) -> int:
        return sum(
            betrag for block, betrag in self.je_block.items() if block not in NICHT_GERECHNET
        )


@dataclass
class Reichweite:
    """Wie lange der offene Auftragsbestand trägt – zwei Antworten (Entscheidung 26).

    ``umsatzmonate`` beantwortet „wie lange reicht die Arbeit", ``fixkostenmonate`` „wie lange
    trägt der Bestand die Firma". Beide sind berechtigt und meinen Verschiedenes; die Ansicht
    zeigt die erste groß und die zweite als Unterzeile.
    """

    bestand_cent: int
    durchschnittsumsatz_cent: int
    fixkosten_monat_cent: int
    marge_promille: int | None

    @property
    def umsatzmonate(self) -> float | None:
        if self.durchschnittsumsatz_cent <= 0:
            return None
        return round(self.bestand_cent / self.durchschnittsumsatz_cent, 1)

    @property
    def deckungsbeitrag_cent(self) -> int | None:
        """Welcher Deckungsbeitrag im Bestand steckt, zur Durchschnittsmarge."""
        if self.marge_promille is None:
            return None
        return round(self.bestand_cent * self.marge_promille / 1000)

    @property
    def fixkostenmonate(self) -> float | None:
        db = self.deckungsbeitrag_cent
        if db is None or self.fixkosten_monat_cent <= 0:
            return None
        return round(db / self.fixkosten_monat_cent, 1)


@dataclass
class Kennzahlen:
    """Die Kennzahlen neben der Monatsansicht."""

    marge_promille: int | None
    marge_monate: int
    break_even_cent: int | None
    reichweite: Reichweite


@dataclass
class Cockpit:
    jahr: int
    monat: str
    monate: list[Monatszahlen]
    fixkosten: Fixkostenblock
    kennzahlen: Kennzahlen
    hinweise: list[str] = field(default_factory=list)
    # 'gestellt' oder 'bezahlt' – welche Umsatzbasis gerechnet wurde (Entscheidung 28).
    umsatzbasis: str = "gestellt"

    @property
    def aktueller(self) -> Monatszahlen:
        for eintrag in self.monate:
            if eintrag.monat == self.monat:
                return eintrag
        return Monatszahlen(monat=self.monat)

    def bis_einschliesslich(self) -> list[Monatszahlen]:
        return [m for m in self.monate if m.monat <= self.monat]

    @property
    def kumuliert_cent(self) -> int:
        """Über-/Unterdeckung seit Jahresbeginn bis zum gewählten Monat."""
        return sum(m.deckung_cent for m in self.bis_einschliesslich())


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------


def variable_kosten(sitzung: Session, *, jahr: int) -> dict[str, int]:
    """Variable Kosten je Monat aus ``ist_kosten``, ohne die Eigenleistung (PLAN §6.6)."""
    zeilen = sitzung.execute(
        select(IstKosten.monat, func.sum(IstKosten.betrag))
        .where(IstKosten.quelle.in_(VARIABLE_QUELLEN), IstKosten.monat.startswith(f"{jahr}-"))
        .group_by(IstKosten.monat)
    ).all()
    return {monat: int(summe or 0) for monat, summe in zeilen}


def fixkosten_ist(sitzung: Session, *, monat: str) -> dict[str, int]:
    """Fixkosten eines Monats aus der Summen- und Saldenliste, je Block.

    Konten ohne Zuordnung fehlen hier bewusst: sie zählen nicht mit und erscheinen stattdessen
    als Pflegehinweis (siehe :func:`app.dienste.konten.unzugeordnete`).
    """
    zeilen = sitzung.execute(
        select(DatevSaldo.block, func.sum(DatevSaldo.saldo))
        .where(DatevSaldo.monat == monat, DatevSaldo.block.is_not(None))
        .group_by(DatevSaldo.block)
    ).all()
    return {block: int(summe or 0) for block, summe in zeilen if block}


def fixkosten_plan(sitzung: Session, *, monat: str) -> dict[str, int]:
    """Geplante Fixkosten eines Monats, je Block."""
    zeilen = sitzung.execute(
        select(FixkostenPlan.block, func.sum(FixkostenPlan.betrag))
        .where(FixkostenPlan.monat == monat)
        .group_by(FixkostenPlan.block)
    ).all()
    return {block: int(summe or 0) for block, summe in zeilen}


def fixkosten_fuer(sitzung: Session, *, monat: str) -> Fixkostenblock:
    """Fixkosten eines Monats: die SuSa, sonst der Plan, sonst nichts.

    Nie beides addiert – ein Monat hat entweder eine Buchhaltung oder eine Planung.
    """
    ist = fixkosten_ist(sitzung, monat=monat)
    if ist:
        return Fixkostenblock(monat=monat, herkunft="susa", je_block=ist)
    plan = fixkosten_plan(sitzung, monat=monat)
    if plan:
        return Fixkostenblock(monat=monat, herkunft="plan", je_block=plan)
    return Fixkostenblock(monat=monat, herkunft="keine")


def umsatz_je_monat(
    sitzung: Session,
    sichtbare_projekte: Select,
    *,
    jahr: int,
    basis: str,
    skonto_prozent: float,
) -> dict[str, int]:
    """Umsatz je Monat – gestellt oder bezahlt (Entscheidung 28).

    ``gestellt`` ist der Ist-Umsatz aus Phase 2: festgeschriebene Rechnungen je Monat.
    ``bezahlt`` nimmt davon nur, was laut OPOS beglichen ist – zugeordnet bleibt der
    Rechnungsmonat, weil eine OPOS-Liste keinen Zahltag führt.
    """
    if basis == "bezahlt":
        from app.dienste import zahlungsstatus

        return zahlungsstatus.eingang_je_monat(sitzung, jahr=jahr, skonto_prozent=skonto_prozent)

    verlauf = auswertung.jahresverlauf(sitzung, sichtbare_projekte, jahr)
    return {m.monat: m.ist_cent for m in verlauf.monate}


def jahresmarge(monate: list[Monatszahlen], *, bis_monat: str) -> tuple[int | None, int]:
    """Ist-Marge des laufenden Jahres in Promille und die Anzahl Monate mit Umsatz.

    Entscheidung 27: Basis ist das laufende Jahr bis zum gewählten Monat, nicht rollierend.
    Die zweite Zahl trägt die Belastbarkeit – im Januar steht die Marge auf einem Monat.
    """
    gezaehlt = [m for m in monate if m.monat <= bis_monat and m.umsatz_cent > 0]
    umsatz = sum(m.umsatz_cent for m in gezaehlt)
    if umsatz <= 0:
        return None, 0
    db = sum(m.deckungsbeitrag_cent for m in gezaehlt)
    return round(db * 1000 / umsatz), len(gezaehlt)


def break_even_cent(fixkosten_cent: int, marge_promille: int | None) -> int | None:
    """Monatsumsatz, ab dem die Fixkosten gedeckt sind.

    ``None`` ohne belastbare Marge oder ohne Fixkosten – eine Division durch eine Marge von
    null ergäbe einen unendlichen Break-even, und den auszuweisen hülfe niemandem.
    """
    if marge_promille is None or marge_promille <= 0 or fixkosten_cent <= 0:
        return None
    return round(fixkosten_cent * 1000 / marge_promille)


# ---------------------------------------------------------------------------
# Die Ansicht
# ---------------------------------------------------------------------------


def monatsansicht(
    sitzung: Session,
    sichtbare_projekte: Select,
    *,
    monat: str,
    skonto_prozent: float,
    basis: str = "gestellt",
) -> Cockpit:
    """Das Cockpit für einen Monat, mit dem Jahresverlauf dahinter."""
    jahr = int(monat[:4])

    umsaetze = umsatz_je_monat(
        sitzung, sichtbare_projekte, jahr=jahr, basis=basis, skonto_prozent=skonto_prozent
    )
    kosten = variable_kosten(sitzung, jahr=jahr)

    monate: list[Monatszahlen] = []
    for nummer in range(1, 13):
        schluessel = f"{jahr}-{nummer:02d}"
        block = fixkosten_fuer(sitzung, monat=schluessel)
        monate.append(
            Monatszahlen(
                monat=schluessel,
                umsatz_cent=umsaetze.get(schluessel, 0),
                variable_kosten_cent=kosten.get(schluessel, 0),
                fixkosten_cent=block.summe_cent,
                fixkosten_herkunft=block.herkunft,
            )
        )

    marge, marge_monate = jahresmarge(monate, bis_monat=monat)
    fixkosten = fixkosten_fuer(sitzung, monat=monat)
    bestand = auswertung.auftragsbestand(sitzung, sichtbare_projekte)

    mit_umsatz = [m for m in monate if m.monat <= monat and m.umsatz_cent > 0]
    durchschnitt = (
        round(sum(m.umsatz_cent for m in mit_umsatz) / len(mit_umsatz)) if mit_umsatz else 0
    )

    ergebnis = Cockpit(
        jahr=jahr,
        monat=monat,
        monate=monate,
        fixkosten=fixkosten,
        umsatzbasis=basis,
        kennzahlen=Kennzahlen(
            marge_promille=marge,
            marge_monate=marge_monate,
            break_even_cent=break_even_cent(fixkosten.summe_cent, marge),
            reichweite=Reichweite(
                bestand_cent=bestand.bestand_cent,
                durchschnittsumsatz_cent=durchschnitt,
                fixkosten_monat_cent=fixkosten.summe_cent,
                marge_promille=marge,
            ),
        ),
    )
    ergebnis.hinweise = hinweise_sammeln(sitzung, ergebnis)
    return ergebnis


def hinweise_sammeln(sitzung: Session, cockpit: Cockpit) -> list[str]:
    """Die Fälle, in denen eine Zahl weniger wert ist, als sie aussieht."""
    from app.dienste import konten

    hinweise: list[str] = []
    aktuell = cockpit.aktueller

    if aktuell.fixkosten_herkunft == "keine":
        hinweise.append(
            f"Für {cockpit.monat} sind weder eine Summen- und Saldenliste noch Planwerte "
            "hinterlegt. Ohne Fixkosten ist die Überdeckung nur der Deckungsbeitrag und sagt "
            "nichts über das Ergebnis."
        )
    elif aktuell.fixkosten_herkunft == "plan":
        hinweise.append(
            f"Die Fixkosten für {cockpit.monat} sind Planwerte – für diesen Monat liegt noch "
            "keine Summen- und Saldenliste vor."
        )

    offene = konten.unzugeordnete(sitzung, jahr=cockpit.jahr)
    if offene:
        summe = sum(abs(k.summe_cent) for k in offene)
        hinweise.append(
            f"{len(offene)} Konten aus der Buchhaltung sind keinem Kostenblock zugeordnet "
            f"({formate.mit_einheit(geld.cent_nach_euro(summe), '€')}). Sie fehlen im "
            "Fixkostenblock – die Überdeckung sieht dadurch besser aus, als sie ist."
        )

    if cockpit.kennzahlen.marge_promille is None:
        hinweise.append(
            f"Für {cockpit.jahr} ist noch kein Umsatz erfasst. Ohne Marge gibt es keinen "
            "Break-even und keine Reichweite in Fixkostenmonaten."
        )
    elif cockpit.kennzahlen.marge_monate < BELASTBAR_AB_MONATEN:
        hinweise.append(
            f"Die Durchschnittsmarge steht auf {cockpit.kennzahlen.marge_monate} Monat"
            f"{'en' if cockpit.kennzahlen.marge_monate != 1 else ''} des laufenden Jahres. "
            "Break-even und Reichweite sind damit noch grob."
        )

    if cockpit.umsatzbasis == "bezahlt":
        hinweise.append(
            "Umsatzbasis ist der Zahlungseingang laut OPOS, zugeordnet dem Rechnungsmonat – "
            "eine OPOS-Liste führt keinen Zahltag."
        )
    return hinweise


def letzter_monat_mit_zahlen(sitzung: Session) -> str | None:
    """Jüngster Monat, für den **tatsächliche** Zahlen vorliegen – die Vorbelegung der Ansicht.

    Der laufende Monat wäre die naheliegende Wahl und die schlechtere: die Kanzlei liefert erst
    nach dem Monatsabschluss, also steht Anfang September für September noch nichts da. Wer das
    Cockpit aufruft und vier Nullen sieht, hält es für kaputt, statt zu erkennen, dass er in die
    Zukunft schaut.

    Zwei Abgrenzungen, beide im Abnahmelauf teuer erkauft:

    * **Geplant ist nicht gebucht.** Zahlungsplanpositionen tragen Planmonate weit in die
      Zukunft; nur abgerechnete zählen hier (``auswertung.ist_bedingung``).
    * **Nie über den laufenden Monat hinaus.** Ein Beleg mit Datum im Folgemonat zöge die
      Ansicht sonst in einen Monat, über den noch nichts zu sagen ist.
    """
    heute = f"{date.today():%Y-%m}"
    kandidaten = [
        sitzung.scalar(select(func.max(IstKosten.monat))),
        sitzung.scalar(select(func.max(DatevSaldo.monat))),
        sitzung.scalar(
            select(func.max(Zahlungsplanposition.plan_monat)).where(auswertung.ist_bedingung())
        ),
    ]
    vorhanden = [monat for monat in kandidaten if monat and monat <= heute]
    return max(vorhanden) if vorhanden else None


def monate_mit_daten(sitzung: Session, sichtbare_projekte: Select) -> list[str]:
    """Monate, für die es überhaupt etwas zu zeigen gibt – für die Monatswahl der Ansicht."""
    monate: set[str] = set()
    for jahr in auswertung.jahre_mit_daten(sitzung, sichtbare_projekte):
        monate.update(f"{jahr}-{nummer:02d}" for nummer in range(1, 13))
    monate.update(sitzung.scalars(select(DatevSaldo.monat).distinct()).all())
    monate.update(sitzung.scalars(select(FixkostenPlan.monat).distinct()).all())
    if not monate:
        heute = date.today()
        monate.add(f"{heute:%Y-%m}")
    return sorted(monate)
