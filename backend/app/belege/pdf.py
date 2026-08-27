"""Rechnungs-PDF im ip³-Corporate-Design (PLAN §7 Phase 3, §11, Entscheidung 17).

Die Vorlage liegt als HTML und CSS daneben und wird mit WeasyPrint gesetzt. Drei Punkte, die den
Aufbau bestimmen:

* **Die Vorlage rechnet nicht.** Alle Beträge kommen fertig aus :mod:`app.dienste.belege` und
  werden hier nur in deutsche Schreibweise gebracht. Ein zweiter Rechenweg in der Vorlage würde
  irgendwann von der Datenbank abweichen, und dann stimmte das Papier nicht mit dem Beleg
  überein.
* **Die Schriften werden eingebettet**, nicht über das Netz geladen: der Leitstand läuft ohne
  Internet, und ein Beleg, der auf dem Zielrechner in Arial erscheint, verletzt PLAN §11. Fehlt
  eine Schriftdatei, greift die Fallback-Kette – der Beleg ist dann nicht im Corporate Design,
  aber lesbar. Das ist besser als ein Abbruch beim Festschreiben.
* **Kein Zeichen 3.** Die Corporate-Design-Regel schließt das Wasserzeichen auf zahlen- und
  tabellenlastigen Flächen aus; eine Rechnung ist genau das. Die Marke trägt der Briefkopf.

Der Dateiname folgt PLAN §7: ``RE-JJJJ-NNNN_<projekt_nr>_<kunde>.pdf``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.dienste.belege import SatzAnteil, anschrift_zeilen, steuer_hinweise, zahlungsziel
from app.formate import prozent
from app.geld import formatiere_euro, position_netto
from app.konfiguration import BelegtexteEinstellungen, FirmaEinstellungen, einstellungen
from app.modelle import Rechnung
from app.protokoll import logger

log = logger(__name__)

VORLAGEN = Path(__file__).parent / "vorlagen"
# Corporate-Design-Assets neben der Anwendung; über pfade.cd_assets überschreibbar.
STANDARD_ASSETS = Path(__file__).resolve().parents[3] / "assets" / "cd"

# Schriften aus dem Corporate-Design-Ordner. Reihenfolge: Familie, Gewicht, Dateiname.
SCHRIFTEN: tuple[tuple[str, int, str], ...] = (
    ("Libre Franklin", 400, "LibreFranklin-Regular.ttf"),
    ("Libre Franklin", 600, "LibreFranklin-SemiBold.ttf"),
    ("Libre Franklin", 700, "LibreFranklin-Bold.ttf"),
    ("Libre Franklin", 800, "LibreFranklin-ExtraBold.ttf"),
    ("Space Grotesk", 500, "SpaceGrotesk-Medium.ttf"),
    ("Space Grotesk", 700, "SpaceGrotesk-Bold.ttf"),
)

# Titel und Bezeichnungen je Belegart. „Rechnung Nr." wie in der Word-Vorlage; die AB bekommt
# ihre eigene Bezeichnung, weil sie keine Rechnungsnummer trägt (PLAN §10).
BELEGTITEL: dict[str, str] = {
    "ab": "Auftragsbestätigung",
    "abschlag": "Abschlagsrechnung",
    "schluss": "Schlussrechnung",
    "service": "Servicerechnung",
    "gutschrift": "Gutschrift",
    "storno": "Stornorechnung",
}
NUMMER_BEZEICHNUNG: dict[str, str] = {"ab": "Auftragsbestätigung Nr."}
SUMMEN_BEZEICHNUNG: dict[str, str] = {
    "ab": "Auftragssumme brutto",
    "schluss": "Restbetrag zur Zahlung",
    "gutschrift": "Gutschriftsbetrag",
    "storno": "Stornobetrag",
}


def _datum(wert: date | None) -> str:
    return wert.strftime("%d.%m.%Y") if wert else ""


def _menge(wert: Decimal | float | int) -> str:
    """Menge deutsch, ohne unnötige Nachkommastellen: ``1``, ``2,5``, ``0,75``."""
    zahl = Decimal(str(wert)).normalize()
    text = format(zahl, "f")
    return text.replace(".", ",")


def dateiname(beleg: Rechnung) -> str:
    """``RE-JJJJ-NNNN_<projekt_nr>_<kunde>.pdf`` (PLAN §7).

    Der Kundenname wird auf dateisystemtaugliche Zeichen zurückgeführt: Umlaute werden
    umgeschrieben, alles andere zu Bindestrichen. Der OneDrive-Ordner wird auch von Windows aus
    benutzt, und dort sind ``\\ / : * ? " < > |`` verboten.
    """
    teile = [beleg.rechnung_nr or f"entwurf-{beleg.id}"]
    if beleg.projekt is not None:
        teile.append(str(beleg.projekt.projekt_nr))
    name = (beleg.kunde_snapshot or {}).get("name") or (beleg.kunde.name if beleg.kunde else "")
    if name:
        teile.append(_dateisicher(name))
    return "_".join(teile) + ".pdf"


def _dateisicher(text: str) -> str:
    ersetzt = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ß", "ss")
    )
    ohne_akzente = "".join(
        zeichen
        for zeichen in unicodedata.normalize("NFKD", ersetzt)
        if not unicodedata.combining(zeichen)
    )
    gekuerzt = re.sub(r"[^A-Za-z0-9]+", "-", ohne_akzente).strip("-")
    return gekuerzt[:60] or "kunde"


def _schriften_css(schriftordner: Path) -> str:
    """``@font-face``-Regeln für die vorhandenen Schriftdateien.

    Fehlende Dateien werden übersprungen und einmal protokolliert: der Beleg entsteht dann in der
    Fallback-Schrift. Ein Abbruch beim Festschreiben wegen einer fehlenden Schrift wäre der
    falsche Preis.
    """
    regeln: list[str] = []
    fehlend: list[str] = []
    for familie, gewicht, datei in SCHRIFTEN:
        pfad = schriftordner / datei
        if not pfad.exists():
            fehlend.append(datei)
            continue
        regeln.append(
            f"@font-face{{font-family:'{familie}';font-weight:{gewicht};"
            f"font-style:normal;src:url('{pfad.as_uri()}') format('truetype');}}"
        )
    if fehlend:
        log.warning(
            "Schriftdateien für das Rechnungs-PDF fehlen, es gilt die Fallback-Kette",
            extra={"dateien": ", ".join(fehlend), "ordner": str(schriftordner)},
        )
    return "".join(regeln)


def _bildquelle(pfad: Path) -> str | None:
    return pfad.as_uri() if pfad.exists() else None


@dataclass
class Bausteine:
    """Was die Vorlage braucht, in der Form, in der sie es setzt."""

    firma: dict[str, Any]
    empfaenger: list[str]
    beleg: dict[str, Any]
    positionen: list[dict[str, str]]
    summen: dict[str, Any]
    absetzungen: list[dict[str, str]]
    hinweise: list[str]
    texte: dict[str, str]
    wortmarke: str | None
    schriften: str
    stil: str


def _anteile(beleg: Rechnung) -> list[SatzAnteil]:
    """Steueraufteilung des Belegs, bevorzugt aus dem gespeicherten Stand.

    Für einen festgeschriebenen Beleg ist ``ust_details`` die Wahrheit – auch dann, wenn eine
    künftige Phase anders rundete. Nur ein Entwurf ohne gespeicherte Aufteilung wird gerechnet.
    """
    if beleg.ust_details:
        return [SatzAnteil(**anteil) for anteil in beleg.ust_details]
    from app.dienste.belege import summen_berechnen

    return summen_berechnen(list(beleg.positionen)).je_satz


def _texte(beleg: Rechnung, vorgaben: BelegtexteEinstellungen, tage: int) -> dict[str, str]:
    snapshot = beleg.kunde_snapshot or {}
    anrede = vorgaben.anrede_firma if snapshot.get("typ") == "b2b" else vorgaben.anrede_privat
    einleitung = {
        "ab": vorgaben.einleitung_ab,
        "abschlag": vorgaben.einleitung_abschlag,
        "schluss": vorgaben.einleitung_schluss,
        "service": vorgaben.einleitung_service,
    }.get(beleg.art, vorgaben.einleitung_service)
    # Anschreiben am Beleg schlägt den Baustein: Storno und Gutschrift bringen ihren eigenen Text
    # mit, und der Nutzer darf ihn überschreiben.
    if beleg.anschreiben:
        einleitung = beleg.anschreiben

    bedingung = ""
    if beleg.art not in ("ab", "storno") and beleg.faellig_am:
        bedingung = vorgaben.zahlungsbedingung.format(
            faellig_am=_datum(beleg.faellig_am), zahlungsziel_tage=tage
        )
    return {
        "anrede": anrede,
        "einleitung": einleitung,
        "zahlungsbedingung": bedingung,
        "grussformel": vorgaben.grussformel,
    }


def bausteine(beleg: Rechnung, firma: FirmaEinstellungen | None = None) -> Bausteine:
    """Alle Werte der Vorlage aufbereiten – deutsche Zahlen, Daten und Einheiten (PLAN §6.10)."""
    werte = einstellungen()
    firma = firma if firma is not None else werte.firma
    ordner = werte.pfade.cd_assets or STANDARD_ASSETS

    anteile = _anteile(beleg)
    snapshot = beleg.kunde_snapshot or {}
    tage = zahlungsziel(beleg.kunde)

    return Bausteine(
        firma={
            "firmierung": firma.firmierung,
            "strasse": firma.strasse,
            "plz": firma.plz,
            "ort": firma.ort,
            "ust_id": firma.ust_id,
            "st_nr": firma.st_nr,
            "hrb": firma.hrb,
            "geschaeftsfuehrer": firma.geschaeftsfuehrer,
            "telefon": firma.telefon,
            "telefax": firma.telefax,
            "email": firma.email,
            "web": firma.web,
            "bank_institut": firma.bank.institut,
            "bank_iban": firma.bank.iban,
            "bank_bic": firma.bank.bic,
        },
        empfaenger=anschrift_zeilen(snapshot),
        beleg={
            "nummer": beleg.rechnung_nr,
            "nummer_bezeichnung": NUMMER_BEZEICHNUNG.get(beleg.art, "Rechnung Nr."),
            "art": beleg.art,
            "titel": _titel(beleg),
            "datum": _datum(beleg.datum),
            "leistungszeitraum": beleg.leistungszeitraum,
            "faellig_am": _datum(beleg.faellig_am),
            "projekt_nr": beleg.projekt.projekt_nr if beleg.projekt else None,
            "kunden_nr": snapshot.get("kunden_nr"),
            "objekt": _objekt(beleg),
            "schlusstext": beleg.schlusstext,
            "summenbezeichnung": SUMMEN_BEZEICHNUNG.get(beleg.art, "Rechnungsbetrag brutto"),
        },
        positionen=[
            {
                "pos": position.pos,
                "bezeichnung": position.bezeichnung,
                "menge": _menge(position.menge),
                "einheit": position.einheit,
                "ep": formatiere_euro(position.ep_netto),
                "satz": prozent(position.ust_satz),
                "netto": formatiere_euro(position_netto(position.menge, position.ep_netto)),
            }
            for position in beleg.positionen
        ],
        summen={
            "netto": formatiere_euro(beleg.netto),
            "brutto": formatiere_euro(beleg.brutto),
            "absetzung_netto": formatiere_euro(beleg.absetzung_netto),
            "absetzung_ust": formatiere_euro(beleg.absetzung_ust),
            "zahlbetrag": formatiere_euro(beleg.zahlbetrag),
            "hat_absetzung": bool(beleg.absetzungen),
            "je_satz": [
                {
                    "satz": anteil.prozent_text,
                    "netto": formatiere_euro(anteil.netto),
                    "ust": formatiere_euro(anteil.ust),
                    # Bei mehreren Sätzen gehört die Bemessungsgrundlage dazu, sonst ist nicht
                    # erkennbar, worauf sich der Steuerbetrag bezieht (§ 14 Abs. 4 Nr. 8 UStG).
                    "mehrere": len(anteile) > 1,
                }
                for anteil in anteile
            ],
        },
        absetzungen=[
            {
                "rechnung_nr": eintrag.rechnung_nr,
                "datum": _datum(eintrag.datum),
                "netto": formatiere_euro(eintrag.netto),
                "satz": prozent(eintrag.ust_satz),
                "ust": formatiere_euro(eintrag.ust),
                "brutto": formatiere_euro(eintrag.brutto),
            }
            for eintrag in beleg.absetzungen
        ],
        hinweise=steuer_hinweise(
            beleg.ust_kz, list(beleg.positionen), mit_absetzung=bool(beleg.absetzungen)
        ),
        texte=_texte(beleg, werte.fakturierung.texte, tage),
        wortmarke=_bildquelle(ordner / "logos" / "ip3-energietechnik-farbig.png"),
        schriften=_schriften_css(ordner / "fonts"),
        stil=(VORLAGEN / "beleg.css").read_text(encoding="utf-8"),
    )


def _titel(beleg: Rechnung) -> str:
    """Belegtitel; bei einem Abschlag mit der laufenden Nummer wie in der Word-Vorlage."""
    grund = BELEGTITEL.get(beleg.art, "Rechnung")
    if beleg.art == "abschlag" and beleg.abschlag_nr:
        return f"{beleg.abschlag_nr}. {grund}"
    return grund


def _objekt(beleg: Rechnung) -> str | None:
    """Objektzeile wie in der Word-Vorlage: „Gruber, Bechtsrieth"."""
    if beleg.projekt is None:
        return None
    teile = [beleg.projekt.bezeichnung, beleg.projekt.standort]
    zusammen = ", ".join(teil for teil in teile if teil)
    return zusammen or None


def _umgebung() -> Environment:
    return Environment(
        loader=FileSystemLoader(VORLAGEN),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def html_erzeugen(beleg: Rechnung, firma: FirmaEinstellungen | None = None) -> str:
    """Beleg als HTML – auch die Grundlage der Vorschau in der Oberfläche."""
    daten = bausteine(beleg, firma)
    return _umgebung().get_template("beleg.html").render(**vars(daten))


def pdf_erzeugen(
    beleg: Rechnung,
    firma: FirmaEinstellungen | None = None,
    xml: bytes | None = None,
    xml_name: str = "factur-x.xml",
) -> bytes:
    """Beleg als PDF. Mit ``xml`` als PDF/A-3 mit eingebetteter E-Rechnung (PLAN §6.3).

    Die ``font_config`` ist **nicht** optional: ohne sie ignoriert WeasyPrint die
    ``@font-face``-Regeln stillschweigend und setzt den Beleg in der Systemschrift. Beim Bau kam
    dabei DejaVu Serif heraus – ein Serifensatz, den PLAN §11 ausdrücklich ausschließt, ohne dass
    irgendetwas fehlgeschlagen wäre. Der Test ``test_beleg_pdf.py`` liest deshalb die eingebetteten
    Schriftnamen aus dem fertigen PDF.
    """
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    quelltext = html_erzeugen(beleg, firma)
    optionen: dict[str, Any] = {"font_config": FontConfiguration()}
    if xml is not None:
        from weasyprint import Attachment

        optionen["pdf_variant"] = "pdf/a-3b"
        optionen["attachments"] = [
            Attachment(
                string=xml,
                name=xml_name,
                description="Factur-X/ZUGFeRD-Rechnungsdaten (EN 16931)",
                relationship="Alternative",
            )
        ]
    return HTML(string=quelltext, base_url=str(VORLAGEN)).write_pdf(**optionen)


def seitentexte(beleg: Rechnung, firma: FirmaEinstellungen | None = None) -> list[str]:
    """Text je Seite des gesetzten Belegs – für die Prüfung der Pflichtangaben.

    Der Text im fertigen PDF ist nicht durchsuchbar: WeasyPrint bettet Teilmengen der Schriften
    ein, die Zeichen stehen dort als Glyphennummern. Geprüft wird deshalb auf dem gesetzten
    Dokument, **nach** dem Seitenumbruch – so ist auch die Fußzeile erfasst, die als
    ``running element`` in den Seitenrand läuft und im HTML nur einmal vorkommt.
    """
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    dokument = HTML(string=html_erzeugen(beleg, firma), base_url=str(VORLAGEN)).render(
        font_config=FontConfiguration()
    )

    def sammeln(kasten: Any) -> list[str]:
        gefunden: list[str] = []
        text = getattr(kasten, "text", None)
        if text:
            gefunden.append(text)
        for kind in getattr(kasten, "children", ()):
            gefunden.extend(sammeln(kind))
        return gefunden

    return [" ".join(sammeln(seite._page_box)) for seite in dokument.pages]


def _pdf_klartext(pdf: bytes) -> bytes:
    """PDF samt entpackter Objektströme – nur zum Prüfen, nicht für den Betrieb.

    WeasyPrint legt Fontbeschreibungen, Anhangsverweise und Metadaten in komprimierten
    Objektströmen ab. Eine Suche in den Rohbytes findet sie deshalb nicht und würde einen Test
    vortäuschen, der nichts prüft.
    """
    import re
    import zlib

    teile = [pdf]
    for strom in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            teile.append(zlib.decompress(strom))
        except zlib.error:
            continue
    return b"\n".join(teile)


def eingebettete_schriften(pdf: bytes) -> set[str]:
    """Namen der im PDF eingebetteten Schriften – für die Prüfung des Corporate Designs."""
    import re

    namen = set(re.findall(rb"/BaseFont\s*/([A-Za-z0-9+\-]+)", _pdf_klartext(pdf)))
    # Der Präfix vor dem Plus ist die Kennung der Teilmenge und je Lauf verschieden.
    return {name.decode().split("+")[-1] for name in namen}


def eingebettete_dateien(pdf: bytes) -> set[str]:
    """Namen der im PDF eingebetteten Dateien – für die Prüfung der E-Rechnung."""
    import re

    namen = re.findall(rb"/Type\s*/Filespec/F\s*\(([^)]+)\)", _pdf_klartext(pdf))
    return {name.decode() for name in namen}


def ist_pdf_a3(pdf: bytes) -> bool:
    """Ob das PDF sich als PDF/A-3 ausweist und einen Anhang mit Beziehung trägt.

    Beides gehört zusammen: die Kennung allein macht kein Factur-X, und ein Anhang ohne
    ``AFRelationship`` gilt einem Prüfprogramm nicht als Rechnungsdatensatz.
    """
    klartext = _pdf_klartext(pdf)
    return b"pdfaid" in klartext and b"/AFRelationship" in klartext
