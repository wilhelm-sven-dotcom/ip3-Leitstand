"""E-Rechnung nach EN 16931 als Factur-X/ZUGFeRD-XML (PLAN §6.3).

Ab dem 1.1.2027 muss ip³ für inländische B2B-Umsätze E-Rechnungen ausstellen (Vorjahresumsatz
2026 über 800.000 €). Das Tool erzeugt sie deshalb ab sofort: für Kunden mit ``typ='b2b'``
entsteht ein PDF/A-3 mit eingebettetem XML, für ``b2c`` und Kleinbetragsrechnungen ein normales
PDF.

Drei Entscheidungen, die den Aufbau bestimmen:

* **Das XML ist eine Ableitung, keine zweite Wahrheit.** Alle Beträge kommen aus dem
  festgeschriebenen Beleg – aus ``ust_details`` die Steueraufteilung, aus ``absetzung_*`` die
  Anzahlungen. Nichts wird hier nachgerechnet, sonst könnten Papier und XML auseinanderlaufen,
  und der Kunde hätte zwei verschiedene Rechnungen in einer Datei.
* **Der Absetzungsblock einer Schlussrechnung geht als Anzahlung (``prepaid_total``) ein.** EN
  16931 kennt dafür BT-113 „Paid amount"; der ausgewiesene Zahlbetrag (BT-115) ist dann der
  Restbetrag. Damit stimmt das XML mit dem, was auf dem Papier als Restbetrag steht.
* **Profil EN 16931 (Comfort).** MINIMUM und BASIC-WL reichen für eine Rechnung mit Positionen
  nicht; EXTENDED bringt nichts, was hier gebraucht würde.

Die Einbettung ins PDF macht WeasyPrint (PDF/A-3 mit Anhang, siehe :mod:`app.belege.pdf`) – es
braucht dafür kein zweites Werkzeug.
"""

from __future__ import annotations

from decimal import Decimal

from app.formate import prozent
from app.geld import cent_nach_euro, position_netto
from app.konfiguration import FirmaEinstellungen, einstellungen
from app.modelle import Rechnung
from app.protokoll import logger

log = logger(__name__)

# Profil und Dateiname des Anhangs nach Factur-X. Der Name ist vorgeschrieben – ein Prüfprogramm
# sucht die Datei genau so.
PROFIL = "FACTUR-X_EN16931"
ANHANGSNAME = "factur-x.xml"

# Belegarten nach UNTDID 1001. 380 = Rechnung, 381 = Gutschrift (auch für den Vollstorno: er ist
# aus Sicht des Standards eine Gutschrift über den gesamten Betrag), 384 = korrigierte Rechnung.
TYP_CODE: dict[str, str] = {
    "abschlag": "380",
    "schluss": "380",
    "service": "380",
    "gutschrift": "381",
    "storno": "381",
}

# Steuerbefreiungsgründe je Kennzeichen (BT-120/BT-121). Ohne Grund weist EN 16931 einen Umsatz
# mit 0 % zurück – „keine Steuer, kein Grund" ist keine gültige Rechnung.
STEUERKATEGORIE: dict[str, str] = {"19": "S", "0": "Z", "13b": "AE", "gemischt": "S"}
BEFREIUNGSGRUND: dict[str, str] = {
    "0": "Steuersatz 0 % nach § 12 Abs. 3 UStG",
    "13b": "Steuerschuldnerschaft des Leistungsempfängers nach § 13b UStG",
}


class ERechnungFehler(RuntimeError):
    """Das XML lässt sich aus diesem Beleg nicht bilden."""


def braucht_erechnung(beleg: Rechnung) -> bool:
    """Ob für diesen Beleg ein XML entsteht (PLAN §6.3).

    B2B ja, B2C nein. Kleinbetragsrechnungen unter der konfigurierten Grenze (§ 33 UStDV, Default
    250 €) bleiben ohne XML: dort dürfen Angaben fehlen, die EN 16931 verlangt.

    Die Auftragsbestätigung ist keine Rechnung und bekommt kein XML.
    """
    if beleg.art == "ab":
        return False
    snapshot = beleg.kunde_snapshot or {}
    typ = snapshot.get("typ") or (beleg.kunde.typ if beleg.kunde else "b2c")
    if typ != "b2b":
        return False
    grenze = einstellungen().fakturierung.kleinbetrag_grenze_cent
    return abs(beleg.brutto) >= grenze


def _betrag(cent: int) -> Decimal:
    return cent_nach_euro(cent)


def _anteile(beleg: Rechnung) -> list[dict[str, int]]:
    if beleg.ust_details:
        return [dict(anteil) for anteil in beleg.ust_details]
    return [{"satz": 190, "netto": beleg.netto, "ust": beleg.ust}]


def xml_erzeugen(
    beleg: Rechnung, firma: FirmaEinstellungen | None = None, pruefen: bool = True
) -> bytes:
    """Factur-X-XML des Belegs, Profil EN 16931.

    ``pruefen`` validiert gegen das mit drafthorse gelieferte XSD. Im Betrieb bleibt das an: ein
    ungültiges XML im PDF ist schlimmer als kein XML, weil der Empfänger es einliest und daran
    scheitert.
    """
    from drafthorse.models.accounting import ApplicableTradeTax
    from drafthorse.models.document import Document
    from drafthorse.models.note import IncludedNote
    from drafthorse.models.payment import PaymentMeans, PaymentTerms
    from drafthorse.models.tradelines import LineItem

    werte = einstellungen()
    firma = firma if firma is not None else werte.firma
    snapshot = beleg.kunde_snapshot or {}

    if beleg.rechnung_nr is None:
        raise ERechnungFehler(
            "Ein Entwurf hat noch keine Rechnungsnummer; ohne sie ist kein gültiges "
            "EN-16931-XML möglich."
        )

    doc = Document()
    doc.context.guideline_parameter.id = "urn:cen.eu:en16931:2017"
    doc.header.id = beleg.rechnung_nr
    doc.header.type_code = TYP_CODE.get(beleg.art, "380")
    doc.header.issue_date_time = beleg.datum
    if beleg.leistungszeitraum:
        note = IncludedNote()
        note.content = f"Leistungszeitraum: {beleg.leistungszeitraum}"
        doc.header.notes.add(note)
    for hinweis in _hinweise(beleg):
        note = IncludedNote()
        note.content = hinweis
        doc.header.notes.add(note)

    verkaeufer = doc.trade.agreement.seller
    verkaeufer.name = firma.firmierung
    verkaeufer.address.line_one = firma.strasse
    verkaeufer.address.postcode = firma.plz
    verkaeufer.address.city_name = firma.ort
    verkaeufer.address.country_id = "DE"
    if firma.ust_id:
        verkaeufer.tax_registrations.add(_steuernummer(firma.ust_id, "VA"))
    if firma.st_nr:
        verkaeufer.tax_registrations.add(_steuernummer(firma.st_nr, "FC"))

    kaeufer = doc.trade.agreement.buyer
    kaeufer.name = snapshot.get("name") or ""
    kaeufer.address.line_one = snapshot.get("strasse") or ""
    kaeufer.address.postcode = snapshot.get("plz") or ""
    kaeufer.address.city_name = snapshot.get("ort") or ""
    kaeufer.address.country_id = "DE"
    if snapshot.get("kunden_nr"):
        kaeufer.id = str(snapshot["kunden_nr"])
    if snapshot.get("ust_id"):
        kaeufer.tax_registrations.add(_steuernummer(snapshot["ust_id"], "VA"))

    # Die Lieferung: ohne eigenes Datum gilt das Belegdatum (BT-72).
    doc.trade.delivery.event.occurrence = beleg.datum

    abrechnung = doc.trade.settlement
    abrechnung.currency_code = "EUR"
    abrechnung.payment_reference = beleg.rechnung_nr
    if firma.bank.iban:
        mittel = PaymentMeans()
        # 58 = SEPA-Überweisung.
        mittel.type_code = "58"
        mittel.payee_account.iban = firma.bank.iban.replace(" ", "")
        if firma.bank.institut:
            mittel.payee_account.account_name = firma.bank.institut
        if firma.bank.bic:
            mittel.payee_institution.bic = firma.bank.bic
        abrechnung.payment_means.add(mittel)
    if beleg.faellig_am:
        bedingung = PaymentTerms()
        bedingung.due = beleg.faellig_am
        abrechnung.terms.add(bedingung)

    for anteil in _anteile(beleg):
        steuer = ApplicableTradeTax()
        steuer.calculated_amount = _betrag(int(anteil["ust"]))
        steuer.basis_amount = _betrag(int(anteil["netto"]))
        steuer.type_code = "VAT"
        steuer.category_code = STEUERKATEGORIE.get(beleg.ust_kz, "S")
        steuer.rate_applicable_percent = Decimal(int(anteil["satz"])) / 10
        grund = BEFREIUNGSGRUND.get(beleg.ust_kz)
        if int(anteil["satz"]) == 0 and grund:
            steuer.exemption_reason = grund
            steuer.category_code = STEUERKATEGORIE.get(beleg.ust_kz, "Z")
        abrechnung.trade_tax.add(steuer)

    summe = abrechnung.monetary_summation
    summe.line_total = _betrag(sum(position_netto(p.menge, p.ep_netto) for p in beleg.positionen))
    summe.tax_basis_total = _betrag(beleg.netto)
    summe.tax_total = (_betrag(beleg.ust), "EUR")
    summe.grand_total = _betrag(beleg.brutto)
    # BT-113: schon gezahlt bzw. schon berechnet. Der Absetzungsblock der Schlussrechnung geht
    # hier ein, damit BT-115 (due_amount) der Restbetrag ist – genau wie auf dem Papier.
    summe.prepaid_total = _betrag(beleg.absetzung_netto + beleg.absetzung_ust)
    summe.due_amount = _betrag(beleg.zahlbetrag)

    for position in beleg.positionen:
        zeile = LineItem()
        zeile.document.line_id = str(position.pos)
        zeile.product.name = position.bezeichnung
        zeile.agreement.net.amount = _betrag(position.ep_netto)
        zeile.delivery.billed_quantity = (Decimal(str(position.menge)), _einheit(position.einheit))
        zeile.settlement.trade_tax.type_code = "VAT"
        zeile.settlement.trade_tax.category_code = STEUERKATEGORIE.get(beleg.ust_kz, "S")
        if position.ust_satz == 0 and beleg.ust_kz in BEFREIUNGSGRUND:
            zeile.settlement.trade_tax.category_code = STEUERKATEGORIE[beleg.ust_kz]
        zeile.settlement.trade_tax.rate_applicable_percent = Decimal(position.ust_satz) / 10
        zeile.settlement.monetary_summation.total_amount = _betrag(
            position_netto(position.menge, position.ep_netto)
        )
        doc.trade.items.add(zeile)

    return doc.serialize(schema=PROFIL) if pruefen else doc.serialize()


def _steuernummer(nummer: str, schema: str):
    """Steuerregistrierung des Verkäufers (BT-31 USt-IdNr., BT-32 Steuernummer)."""
    from drafthorse.models.party import TaxRegistration

    eintrag = TaxRegistration()
    eintrag.id = (schema, nummer)
    return eintrag


def _einheit(einheit: str | None) -> str:
    """Mengeneinheit nach UN/ECE Recommendation 20. ``C62`` ist „Stück ohne Einheit"."""
    tabelle = {
        None: "C62",
        "": "C62",
        "stk": "H87",
        "Stk": "H87",
        "Stück": "H87",
        "m": "MTR",
        "m²": "MTK",
        "kWp": "KWP",
        "kWh": "KWH",
        "h": "HUR",
        "Std": "HUR",
        "pauschal": "C62",
    }
    return tabelle.get(einheit, "C62")


def _hinweise(beleg: Rechnung) -> list[str]:
    """Textliche Hinweise, die auch auf dem Papier stehen (BT-22)."""
    from app.dienste.belege import steuer_hinweise

    hinweise = steuer_hinweise(
        beleg.ust_kz, list(beleg.positionen), mit_absetzung=bool(beleg.absetzungen)
    )
    for eintrag in beleg.absetzungen:
        hinweise.append(
            f"Abgesetzt: Abschlagsrechnung {eintrag.rechnung_nr} vom "
            f"{eintrag.datum.strftime('%d.%m.%Y')}, netto "
            f"{_betrag(eintrag.netto)} EUR, Umsatzsteuer {prozent(eintrag.ust_satz)} "
            f"{_betrag(eintrag.ust)} EUR."
        )
    return hinweise


def pruefen_gegen_schema(xml: bytes) -> bytes:
    """XML gegen das EN-16931-XSD prüfen und aufbereitet zurückgeben.

    **Grenze, die benannt gehört:** das XSD prüft die Struktur, nicht die Geschäftsregeln
    (BR-*, BR-DE-*) der EN 16931. Eine vollständige Schematron-Prüfung braucht die KoSIT-Werkzeuge
    und damit Java; sie läuft nicht in der Testsuite. Der RUNBOOK-Abnahmeschritt sieht deshalb
    einmal eine Prüfung von Hand beim KoSIT-Validator vor.
    """
    from drafthorse.utils import validate_xml

    return validate_xml(xml, PROFIL)
