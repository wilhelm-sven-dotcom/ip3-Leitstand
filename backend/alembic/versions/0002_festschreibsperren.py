"""Festschreib- und Zahlungsplansperren als Datenbank-Trigger

Setzt PLAN §5 und §6.4 (GoBD) um: ein festgeschriebener Beleg ist unveränderbar. Die Sperre sitzt
in der Datenbank, nicht nur in der Anwendung – ein Programmierfehler in einer künftigen Phase, ein
Importskript oder ein direkter Zugriff mit einem SQLite-Werkzeug darf einen festgeschriebenen
Beleg nicht ändern können. Genau das will eine Betriebsprüfung wissen.

Erlaubt bleibt der eine Weg, den die Korrektur braucht (PLAN §6.4): der Statuswechsel von
``festgeschrieben`` auf ``storniert`` mit gesetztem ``storno_ref``. Die eigentliche Korrektur
entsteht als neuer Beleg (``storno`` oder ``gutschrift``), nicht durch Ändern des alten.

Zahlungsplanpositionen mit gesetzter ``rechnung_id`` sind ebenfalls gesperrt. Sonst ließe sich der
Betrag einer bereits berechneten Position nachträglich verändern, und Zahlungsplan und Beleg
würden auseinanderlaufen.

Die Trigger melden sich mit deutschen Texten; ``app.datenbank_sperren`` bildet sie auf
HTTP 409 mit einem Satz ab, der auf dem Bildschirm stehen darf.

Revision: 0002
Vorgänger: 0001
Erstellt: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Die Meldungstexte stehen auch in app/datenbank_sperren.py. Bei einer Änderung beide Stellen
# anpassen – der Test test_trigger.py prüft, dass sie übereinstimmen.
MELDUNG_RECHNUNG_UPDATE = "festgeschriebene Rechnung nicht aenderbar"
MELDUNG_RECHNUNG_DELETE = "festgeschriebene Rechnung nicht loeschbar"
MELDUNG_POSITION_UPDATE = "Position einer festgeschriebenen Rechnung nicht aenderbar"
MELDUNG_POSITION_DELETE = "Position einer festgeschriebenen Rechnung nicht loeschbar"
MELDUNG_POSITION_NEU = "keine Position an einer festgeschriebenen Rechnung"
MELDUNG_ZAHLUNGSPLAN = "berechnete Zahlungsplanposition nicht aenderbar"
MELDUNG_ZAHLUNGSPLAN_DELETE = "berechnete Zahlungsplanposition nicht loeschbar"

TRIGGER = {
    # Änderungen an einem festgeschriebenen Beleg: nur der Weg in den Storno ist offen.
    "trg_rechnungen_festgeschrieben_update": f"""
        CREATE TRIGGER trg_rechnungen_festgeschrieben_update
        BEFORE UPDATE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status = 'festgeschrieben'
             AND NOT (NEW.status = 'storniert' AND NEW.storno_ref IS NOT NULL)
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_RECHNUNG_UPDATE}');
        END
    """,
    "trg_rechnungen_festgeschrieben_delete": f"""
        CREATE TRIGGER trg_rechnungen_festgeschrieben_delete
        BEFORE DELETE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_RECHNUNG_DELETE}');
        END
    """,
    # Der Storno darf den Status wechseln, aber keine Beträge, Nummern oder Hashes verändern.
    # Ohne diese Prüfung wäre der Storno ein Schlupfloch, um den Beleg umzuschreiben.
    "trg_rechnungen_storno_nur_status": f"""
        CREATE TRIGGER trg_rechnungen_storno_nur_status
        BEFORE UPDATE ON rechnungen
        FOR EACH ROW
        WHEN OLD.status = 'festgeschrieben'
             AND NEW.status = 'storniert'
             AND (NEW.rechnung_nr IS NOT OLD.rechnung_nr
                  OR NEW.netto IS NOT OLD.netto
                  OR NEW.ust IS NOT OLD.ust
                  OR NEW.brutto IS NOT OLD.brutto
                  OR NEW.datum IS NOT OLD.datum
                  OR NEW.hash IS NOT OLD.hash
                  OR NEW.festgeschrieben_am IS NOT OLD.festgeschrieben_am
                  OR NEW.art IS NOT OLD.art
                  OR NEW.firma_id IS NOT OLD.firma_id
                  OR NEW.projekt_id IS NOT OLD.projekt_id
                  OR NEW.kunde_snapshot IS NOT OLD.kunde_snapshot)
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_RECHNUNG_UPDATE}');
        END
    """,
    # Positionen eines festgeschriebenen Belegs: unveränderbar, unlöschbar, nicht erweiterbar.
    "trg_rechnungspos_update": f"""
        CREATE TRIGGER trg_rechnungspos_update
        BEFORE UPDATE ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_POSITION_UPDATE}');
        END
    """,
    "trg_rechnungspos_delete": f"""
        CREATE TRIGGER trg_rechnungspos_delete
        BEFORE DELETE ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = OLD.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_POSITION_DELETE}');
        END
    """,
    "trg_rechnungspos_insert": f"""
        CREATE TRIGGER trg_rechnungspos_insert
        BEFORE INSERT ON rechnungspos
        FOR EACH ROW
        WHEN (SELECT status FROM rechnungen WHERE id = NEW.rechnung_id)
             IN ('festgeschrieben', 'storniert')
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_POSITION_NEU}');
        END
    """,
    # Berechnete Zahlungsplanposition: gesperrt, solange sie an einem Beleg hängt. Die Freigabe
    # erfolgt durch den Storno, der rechnung_id auf NULL zurücksetzt – das ist erlaubt.
    "trg_zahlungsplan_berechnet_update": f"""
        CREATE TRIGGER trg_zahlungsplan_berechnet_update
        BEFORE UPDATE ON zahlungsplan
        FOR EACH ROW
        WHEN OLD.rechnung_id IS NOT NULL
             AND NEW.rechnung_id IS NOT NULL
             AND (NEW.betrag_netto IS NOT OLD.betrag_netto
                  OR NEW.bezeichnung IS NOT OLD.bezeichnung
                  OR NEW.art IS NOT OLD.art
                  OR NEW.gewerk IS NOT OLD.gewerk
                  OR NEW.pos_nr IS NOT OLD.pos_nr
                  OR NEW.projekt_id IS NOT OLD.projekt_id
                  OR NEW.rechnung_id IS NOT OLD.rechnung_id)
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_ZAHLUNGSPLAN}');
        END
    """,
    "trg_zahlungsplan_berechnet_delete": f"""
        CREATE TRIGGER trg_zahlungsplan_berechnet_delete
        BEFORE DELETE ON zahlungsplan
        FOR EACH ROW
        WHEN OLD.rechnung_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, '{MELDUNG_ZAHLUNGSPLAN_DELETE}');
        END
    """,
}


def upgrade() -> None:
    for anweisung in TRIGGER.values():
        op.execute(anweisung.strip())


def downgrade() -> None:
    for name in TRIGGER:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
