"""Grundschema: alle Tabellen aus PLAN §5

Erzeugt mit Alembic-Autogenerate aus app/modelle/. Das Schema ist von Anfang an vollständig,
auch wenn Phase 0 nur Anmeldung und Systemstatus braucht – so bringen die späteren Phasen
Funktionen statt Schemaumbauten mit.

Die Tabellen `sitzungen` und `job_laeufe` stehen nicht in PLAN §5: die erste trägt die
serverseitigen Sitzungen, die zweite die Läufe der Hintergrundjobs für den Systemstatus.

Revision: 0001
Vorgänger: 
Erstellt: 2026-08-27 08:07:20.549872
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Eigene Spaltentypen (UtcDateTime, Cent) werden mit vollem Modulpfad geschrieben.
import app.modelle.basis  # noqa: F401

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('anlagen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id_ursprung', sa.Integer(), nullable=True),
    sa.Column('kunde_id', sa.Integer(), nullable=False),
    sa.Column('standort', sa.String(length=200), nullable=True),
    sa.Column('pv_kwp', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('speicher_kwh', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('inbetriebnahme', sa.Date(), nullable=True),
    sa.Column('abnahme_datum', sa.Date(), nullable=True),
    sa.Column('gewaehrleistung_ende', sa.Date(), nullable=True),
    sa.Column('wartungsvertrag', sa.Boolean(), nullable=False),
    sa.Column('mastr_nr', sa.String(length=50), nullable=True),
    sa.Column('bemerkung', sa.String(length=1000), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['kunde_id'], ['kunden.id'], name=op.f('fk_anlagen_kunde_id_kunden')),
    sa.ForeignKeyConstraint(['projekt_id_ursprung'], ['projekte.id'], name=op.f('fk_anlagen_projekt_id_ursprung_projekte')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_anlagen'))
    )
    with op.batch_alter_table('anlagen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_anlagen_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_anlagen_gewaehrleistung_ende'), ['gewaehrleistung_ende'], unique=False)
        batch_op.create_index(batch_op.f('ix_anlagen_inbetriebnahme'), ['inbetriebnahme'], unique=False)
        batch_op.create_index(batch_op.f('ix_anlagen_kunde_id'), ['kunde_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_anlagen_projekt_id_ursprung'), ['projekt_id_ursprung'], unique=False)
        batch_op.create_index(batch_op.f('ix_anlagen_wartungsvertrag'), ['wartungsvertrag'], unique=False)

    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ts', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('user', sa.String(length=200), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('aktion', sa.String(length=50), nullable=False),
    sa.Column('tabelle', sa.String(length=50), nullable=True),
    sa.Column('datensatz_id', sa.Integer(), nullable=True),
    sa.Column('alt', sa.JSON(), nullable=True),
    sa.Column('neu', sa.JSON(), nullable=True),
    sa.Column('ip', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_aktion'), ['aktion'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_tabelle'), ['tabelle'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_ts'), ['ts'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_user'), ['user'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_user_id'), ['user_id'], unique=False)

    op.create_table('berechtigungen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('schluessel', sa.String(length=50), nullable=False),
    sa.Column('scope', sa.String(length=50), nullable=True),
    sa.Column('beschreibung', sa.String(length=200), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(scope IS NULL) OR (scope IN ('alle', 'eigene'))", name=op.f('ck_berechtigungen_scope_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_berechtigungen')),
    sa.UniqueConstraint('schluessel', 'scope', name='uq_berechtigungen_schluessel_scope')
    )
    with op.batch_alter_table('berechtigungen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_berechtigungen_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_berechtigungen_schluessel'), ['schluessel'], unique=False)

    op.create_table('firmen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kuerzel', sa.String(length=50), nullable=False),
    sa.Column('firmierung', sa.String(length=200), nullable=False),
    sa.Column('anschrift', sa.String(length=1000), nullable=True),
    sa.Column('ust_id', sa.String(length=50), nullable=True),
    sa.Column('st_nr', sa.String(length=50), nullable=True),
    sa.Column('hrb', sa.String(length=200), nullable=True),
    sa.Column('bank', sa.JSON(), nullable=True),
    sa.Column('aktiv', sa.Boolean(), nullable=False),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_firmen')),
    sa.UniqueConstraint('kuerzel', name=op.f('uq_firmen_kuerzel'))
    )
    with op.batch_alter_table('firmen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_firmen_created_at'), ['created_at'], unique=False)

    op.create_table('fixkosten_plan',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('monat', sa.String(length=7), nullable=False),
    sa.Column('block', sa.String(length=50), nullable=False),
    sa.Column('betrag', app.modelle.basis.Cent(), nullable=False),
    sa.Column('bemerkung', sa.String(length=1000), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(monat IS NULL) OR (length(monat) = 7 AND substr(monat, 5, 1) = '-' AND substr(monat, 6, 2) >= '01' AND substr(monat, 6, 2) <= '12')", name=op.f('ck_fixkosten_plan_monat_format')),
    sa.CheckConstraint("block IN ('personal', 'raum', 'fahrzeuge', 'versicherung', 'werbung', 'zins', 'sonstiges', 'neutral')", name=op.f('ck_fixkosten_plan_block_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fixkosten_plan')),
    sa.UniqueConstraint('monat', 'block', name='uq_fixkosten_plan_monat_block')
    )
    with op.batch_alter_table('fixkosten_plan', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fixkosten_plan_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_fixkosten_plan_monat'), ['monat'], unique=False)

    op.create_table('fristen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bezug', sa.String(length=50), nullable=False),
    sa.Column('bezug_id', sa.Integer(), nullable=False),
    sa.Column('typ', sa.String(length=50), nullable=False),
    sa.Column('bezeichnung', sa.String(length=200), nullable=False),
    sa.Column('faellig_am', sa.Date(), nullable=False),
    sa.Column('vorlauf_tage', sa.Integer(), nullable=False),
    sa.Column('erledigt_am', sa.Date(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("bezug IN ('projekt', 'anlage')", name=op.f('ck_fristen_bezug_wert')),
    sa.CheckConstraint("typ IN ('mastr', 'fertigmeldung', 'reservierung', 'gewaehrleistung', 'sonstig')", name=op.f('ck_fristen_typ_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fristen'))
    )
    with op.batch_alter_table('fristen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fristen_bezug'), ['bezug'], unique=False)
        batch_op.create_index(batch_op.f('ix_fristen_bezug_id'), ['bezug_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_fristen_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_fristen_erledigt_am'), ['erledigt_am'], unique=False)
        batch_op.create_index(batch_op.f('ix_fristen_faellig_am'), ['faellig_am'], unique=False)
        batch_op.create_index(batch_op.f('ix_fristen_typ'), ['typ'], unique=False)

    op.create_table('importlaeufe',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('quelle', sa.String(length=50), nullable=False),
    sa.Column('datei', sa.String(length=1000), nullable=True),
    sa.Column('zeitraum', sa.String(length=50), nullable=True),
    sa.Column('gestartet', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('beendet', app.modelle.basis.UtcDateTime(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('ergebnis', sa.JSON(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("status IN ('laeuft', 'erfolg', 'warnung', 'fehler')", name=op.f('ck_importlaeufe_status_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_importlaeufe'))
    )
    with op.batch_alter_table('importlaeufe', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_importlaeufe_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_importlaeufe_quelle'), ['quelle'], unique=False)
        batch_op.create_index(batch_op.f('ix_importlaeufe_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_importlaeufe_zeitraum'), ['zeitraum'], unique=False)

    op.create_table('job_laeufe',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job', sa.String(length=50), nullable=False),
    sa.Column('gestartet', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('beendet', app.modelle.basis.UtcDateTime(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('ausgeloest_von', sa.String(length=50), nullable=False),
    sa.Column('meldung', sa.Text(), nullable=True),
    sa.Column('dauer_ms', sa.Integer(), nullable=True),
    sa.Column('kennzahlen', sa.JSON(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("ausgeloest_von IN ('zeitplan', 'manuell', 'start')", name=op.f('ck_job_laeufe_ausgeloest_von_wert')),
    sa.CheckConstraint("status IN ('laeuft', 'erfolg', 'warnung', 'fehler')", name=op.f('ck_job_laeufe_status_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_laeufe'))
    )
    with op.batch_alter_table('job_laeufe', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_laeufe_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_laeufe_gestartet'), ['gestartet'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_laeufe_job'), ['job'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_laeufe_status'), ['status'], unique=False)

    op.create_table('konten_mapping',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('konto_von', sa.String(length=50), nullable=False),
    sa.Column('konto_bis', sa.String(length=50), nullable=False),
    sa.Column('block', sa.String(length=50), nullable=False),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("block IN ('personal', 'raum', 'fahrzeuge', 'versicherung', 'werbung', 'zins', 'sonstiges', 'neutral')", name=op.f('ck_konten_mapping_block_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_konten_mapping')),
    sa.UniqueConstraint('konto_von', 'konto_bis', name='uq_konten_mapping_konto_von_konto_bis')
    )
    with op.batch_alter_table('konten_mapping', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_konten_mapping_block'), ['block'], unique=False)
        batch_op.create_index(batch_op.f('ix_konten_mapping_created_at'), ['created_at'], unique=False)

    op.create_table('kunden',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kunden_nr', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('zusatz', sa.String(length=200), nullable=True),
    sa.Column('strasse', sa.String(length=200), nullable=True),
    sa.Column('plz', sa.String(length=10), nullable=True),
    sa.Column('ort', sa.String(length=200), nullable=True),
    sa.Column('ust_id', sa.String(length=50), nullable=True),
    sa.Column('typ', sa.String(length=50), nullable=False),
    sa.Column('zahlungsziel_tage', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=200), nullable=True),
    sa.Column('telefon', sa.String(length=50), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('bemerkung', sa.String(length=1000), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("status IN ('aktiv', 'inaktiv')", name=op.f('ck_kunden_status_wert')),
    sa.CheckConstraint("typ IN ('b2b', 'b2c')", name=op.f('ck_kunden_typ_wert')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kunden'))
    )
    with op.batch_alter_table('kunden', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_kunden_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_kunden_kunden_nr'), ['kunden_nr'], unique=True)
        batch_op.create_index(batch_op.f('ix_kunden_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_kunden_ort'), ['ort'], unique=False)
        batch_op.create_index(batch_op.f('ix_kunden_status'), ['status'], unique=False)

    op.create_table('projekte',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_nr', sa.Integer(), nullable=False),
    sa.Column('firma_id', sa.Integer(), nullable=False),
    sa.Column('typ', sa.String(length=50), nullable=False),
    sa.Column('kunde_id', sa.Integer(), nullable=False),
    sa.Column('standort', sa.String(length=200), nullable=True),
    sa.Column('pv_kwp', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('wr_typ', sa.String(length=200), nullable=True),
    sa.Column('speicher_kwh', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('ladestation', sa.String(length=200), nullable=True),
    sa.Column('auftrag_vom', sa.Date(), nullable=True),
    sa.Column('ab_wert_netto', app.modelle.basis.Cent(), nullable=True),
    sa.Column('pl_user_id', sa.Integer(), nullable=True),
    sa.Column('pl_name', sa.String(length=200), nullable=True),
    sa.Column('vertriebsweg', sa.String(length=200), nullable=True),
    sa.Column('ust_kz', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('anlage_id', sa.Integer(), nullable=True),
    sa.Column('quelle_migration', sa.String(length=200), nullable=True),
    sa.Column('bemerkung', sa.String(length=1000), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("status IN ('angebot', 'beauftragt', 'in_bau', 'abgeschlossen', 'storniert')", name=op.f('ck_projekte_status_wert')),
    sa.CheckConstraint("typ IN ('projekt', 'service')", name=op.f('ck_projekte_typ_wert')),
    sa.CheckConstraint("ust_kz IN ('19', '0', '13b', 'gemischt')", name=op.f('ck_projekte_ust_kz_wert')),
    sa.CheckConstraint('(projekt_nr IS NULL) OR (projekt_nr >= 0)', name=op.f('ck_projekte_projekt_nr_positiv')),
    sa.ForeignKeyConstraint(['anlage_id'], ['anlagen.id'], name=op.f('fk_projekte_anlage_id_anlagen')),
    sa.ForeignKeyConstraint(['firma_id'], ['firmen.id'], name=op.f('fk_projekte_firma_id_firmen')),
    sa.ForeignKeyConstraint(['kunde_id'], ['kunden.id'], name=op.f('fk_projekte_kunde_id_kunden')),
    sa.ForeignKeyConstraint(['pl_user_id'], ['users.id'], name=op.f('fk_projekte_pl_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projekte'))
    )
    with op.batch_alter_table('projekte', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_projekte_anlage_id'), ['anlage_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_auftrag_vom'), ['auftrag_vom'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_firma_id'), ['firma_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_kunde_id'), ['kunde_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_pl_user_id'), ['pl_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_projekt_nr'), ['projekt_nr'], unique=True)
        batch_op.create_index(batch_op.f('ix_projekte_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_projekte_typ'), ['typ'], unique=False)

    op.create_table('rollen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('beschreibung', sa.String(length=200), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rollen')),
    sa.UniqueConstraint('name', name=op.f('uq_rollen_name'))
    )
    with op.batch_alter_table('rollen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rollen_created_at'), ['created_at'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('pw_hash', sa.String(length=128), nullable=False),
    sa.Column('aktiv', sa.Boolean(), nullable=False),
    sa.Column('muss_passwort_wechseln', sa.Boolean(), nullable=False),
    sa.Column('letzte_anmeldung', app.modelle.basis.UtcDateTime(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_aktiv'), ['aktiv'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('ansprechpartner',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kunde_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('funktion', sa.String(length=50), nullable=True),
    sa.Column('telefon', sa.String(length=50), nullable=True),
    sa.Column('email', sa.String(length=200), nullable=True),
    sa.Column('bemerkung', sa.String(length=1000), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(funktion IS NULL) OR (funktion IN ('technik', 'kaufmaennisch', 'sonstig'))", name=op.f('ck_ansprechpartner_funktion_wert')),
    sa.ForeignKeyConstraint(['kunde_id'], ['kunden.id'], name=op.f('fk_ansprechpartner_kunde_id_kunden'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ansprechpartner')),
    sa.UniqueConstraint('kunde_id', 'name', name='uq_ansprechpartner_kunde_id_name')
    )
    with op.batch_alter_table('ansprechpartner', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ansprechpartner_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_ansprechpartner_kunde_id'), ['kunde_id'], unique=False)

    op.create_table('datev_salden',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('monat', sa.String(length=7), nullable=False),
    sa.Column('konto', sa.String(length=50), nullable=False),
    sa.Column('bezeichnung', sa.String(length=200), nullable=True),
    sa.Column('saldo', app.modelle.basis.Cent(), nullable=False),
    sa.Column('block', sa.String(length=50), nullable=True),
    sa.Column('importlauf_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(monat IS NULL) OR (length(monat) = 7 AND substr(monat, 5, 1) = '-' AND substr(monat, 6, 2) >= '01' AND substr(monat, 6, 2) <= '12')", name=op.f('ck_datev_salden_monat_format')),
    sa.ForeignKeyConstraint(['importlauf_id'], ['importlaeufe.id'], name=op.f('fk_datev_salden_importlauf_id_importlaeufe')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_datev_salden')),
    sa.UniqueConstraint('monat', 'konto', name='uq_datev_salden_monat_konto')
    )
    with op.batch_alter_table('datev_salden', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_datev_salden_block'), ['block'], unique=False)
        batch_op.create_index(batch_op.f('ix_datev_salden_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_datev_salden_importlauf_id'), ['importlauf_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_datev_salden_konto'), ['konto'], unique=False)
        batch_op.create_index(batch_op.f('ix_datev_salden_monat'), ['monat'], unique=False)

    op.create_table('dokumente',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('typ', sa.String(length=50), nullable=False),
    sa.Column('pfad', sa.String(length=1000), nullable=False),
    sa.Column('vorhanden', sa.Boolean(), nullable=False),
    sa.Column('geprueft_am', sa.Date(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("typ IN ('ab', 'abnahme', 'anlagendoku', 'konformitaet', 'messkonzept', 'sonstig')", name=op.f('ck_dokumente_typ_wert')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_dokumente_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dokumente'))
    )
    with op.batch_alter_table('dokumente', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dokumente_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_dokumente_projekt_id'), ['projekt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dokumente_typ'), ['typ'], unique=False)

    op.create_table('ist_kosten',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('quelle', sa.String(length=50), nullable=False),
    sa.Column('monat', sa.String(length=7), nullable=False),
    sa.Column('betrag', app.modelle.basis.Cent(), nullable=False),
    sa.Column('referenz', sa.String(length=200), nullable=True),
    sa.Column('importlauf_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(monat IS NULL) OR (length(monat) = 7 AND substr(monat, 5, 1) = '-' AND substr(monat, 6, 2) >= '01' AND substr(monat, 6, 2) <= '12')", name=op.f('ck_ist_kosten_monat_format')),
    sa.CheckConstraint("quelle IN ('datev', 'stueckliste', 'timetac')", name=op.f('ck_ist_kosten_quelle_wert')),
    sa.ForeignKeyConstraint(['importlauf_id'], ['importlaeufe.id'], name=op.f('fk_ist_kosten_importlauf_id_importlaeufe')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_ist_kosten_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ist_kosten'))
    )
    with op.batch_alter_table('ist_kosten', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ist_kosten_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_ist_kosten_importlauf_id'), ['importlauf_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ist_kosten_monat'), ['monat'], unique=False)
        batch_op.create_index(batch_op.f('ix_ist_kosten_projekt_id'), ['projekt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ist_kosten_quelle'), ['quelle'], unique=False)

    op.create_table('meilensteine',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('typ', sa.String(length=50), nullable=False),
    sa.Column('geplant_kw', sa.String(length=50), nullable=True),
    sa.Column('erledigt_am', sa.Date(), nullable=True),
    sa.Column('bemerkung', sa.String(length=1000), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("typ IN ('uebergabetermin', 'freigabe_planung', 'plan_erstellt', 'anmeldung_nb', 'mastr', 'lieferung', 'montage', 'fertigmeldung', 'zaehler', 'abnahme', 'inbetriebnahme')", name=op.f('ck_meilensteine_typ_wert')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_meilensteine_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_meilensteine')),
    sa.UniqueConstraint('projekt_id', 'typ', name='uq_meilensteine_projekt_id_typ')
    )
    with op.batch_alter_table('meilensteine', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_meilensteine_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_meilensteine_erledigt_am'), ['erledigt_am'], unique=False)
        batch_op.create_index(batch_op.f('ix_meilensteine_projekt_id'), ['projekt_id'], unique=False)

    op.create_table('nachtraege',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('bezeichnung', sa.String(length=200), nullable=False),
    sa.Column('betrag_netto', app.modelle.basis.Cent(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('datum', sa.Date(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("status IN ('angeboten', 'beauftragt', 'berechnet')", name=op.f('ck_nachtraege_status_wert')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_nachtraege_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_nachtraege'))
    )
    with op.batch_alter_table('nachtraege', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nachtraege_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_nachtraege_projekt_id'), ['projekt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_nachtraege_status'), ['status'], unique=False)

    op.create_table('nummernkreise',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('firma_id', sa.Integer(), nullable=False),
    sa.Column('kreis', sa.String(length=50), nullable=False),
    sa.Column('jahr', sa.Integer(), nullable=False),
    sa.Column('letzter_wert', sa.Integer(), nullable=False),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint('(letzter_wert IS NULL) OR (letzter_wert >= 0)', name=op.f('ck_nummernkreise_letzter_wert_positiv')),
    sa.ForeignKeyConstraint(['firma_id'], ['firmen.id'], name=op.f('fk_nummernkreise_firma_id_firmen')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_nummernkreise')),
    sa.UniqueConstraint('firma_id', 'kreis', 'jahr', name='uq_nummernkreise_firma_id_kreis_jahr')
    )
    with op.batch_alter_table('nummernkreise', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_nummernkreise_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_nummernkreise_firma_id'), ['firma_id'], unique=False)

    op.create_table('opos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rechnung_nr', sa.String(length=50), nullable=False),
    sa.Column('kunde', sa.String(length=200), nullable=True),
    sa.Column('betrag', app.modelle.basis.Cent(), nullable=False),
    sa.Column('faellig_am', sa.Date(), nullable=True),
    sa.Column('offen_betrag', app.modelle.basis.Cent(), nullable=False),
    sa.Column('stand_datum', sa.Date(), nullable=False),
    sa.Column('importlauf_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['importlauf_id'], ['importlaeufe.id'], name=op.f('fk_opos_importlauf_id_importlaeufe')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_opos')),
    sa.UniqueConstraint('rechnung_nr', 'stand_datum', name='uq_opos_rechnung_nr_stand_datum')
    )
    with op.batch_alter_table('opos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_opos_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_opos_faellig_am'), ['faellig_am'], unique=False)
        batch_op.create_index(batch_op.f('ix_opos_importlauf_id'), ['importlauf_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_opos_rechnung_nr'), ['rechnung_nr'], unique=False)
        batch_op.create_index(batch_op.f('ix_opos_stand_datum'), ['stand_datum'], unique=False)

    op.create_table('rechnungen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rechnung_nr', sa.String(length=50), nullable=True),
    sa.Column('firma_id', sa.Integer(), nullable=False),
    sa.Column('art', sa.String(length=50), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=True),
    sa.Column('kunde_snapshot', sa.JSON(), nullable=True),
    sa.Column('datum', sa.Date(), nullable=False),
    sa.Column('leistungszeitraum', sa.String(length=200), nullable=True),
    sa.Column('faellig_am', sa.Date(), nullable=True),
    sa.Column('netto', app.modelle.basis.Cent(), nullable=False),
    sa.Column('ust', app.modelle.basis.Cent(), nullable=False),
    sa.Column('brutto', app.modelle.basis.Cent(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('storno_ref', sa.Integer(), nullable=True),
    sa.Column('pdf_pfad', sa.String(length=1000), nullable=True),
    sa.Column('xml_pfad', sa.String(length=1000), nullable=True),
    sa.Column('hash', sa.String(length=64), nullable=True),
    sa.Column('festgeschrieben_am', app.modelle.basis.UtcDateTime(), nullable=True),
    sa.Column('erstellt_von', sa.String(length=50), nullable=True),
    sa.Column('quelle_migration', sa.String(length=200), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("art IN ('ab', 'abschlag', 'schluss', 'service', 'gutschrift', 'storno')", name=op.f('ck_rechnungen_art_wert')),
    sa.CheckConstraint("status IN ('entwurf', 'festgeschrieben', 'storniert')", name=op.f('ck_rechnungen_status_wert')),
    sa.ForeignKeyConstraint(['firma_id'], ['firmen.id'], name=op.f('fk_rechnungen_firma_id_firmen')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_rechnungen_projekt_id_projekte')),
    sa.ForeignKeyConstraint(['storno_ref'], ['rechnungen.id'], name=op.f('fk_rechnungen_storno_ref_rechnungen')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rechnungen')),
    sa.UniqueConstraint('firma_id', 'rechnung_nr', name='uq_rechnungen_firma_id_rechnung_nr')
    )
    with op.batch_alter_table('rechnungen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rechnungen_art'), ['art'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_datum'), ['datum'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_faellig_am'), ['faellig_am'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_firma_id'), ['firma_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_projekt_id'), ['projekt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_rechnung_nr'), ['rechnung_nr'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungen_storno_ref'), ['storno_ref'], unique=False)

    op.create_table('rollen_berechtigungen',
    sa.Column('rolle_id', sa.Integer(), nullable=False),
    sa.Column('berechtigung_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['berechtigung_id'], ['berechtigungen.id'], name=op.f('fk_rollen_berechtigungen_berechtigung_id_berechtigungen'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rolle_id'], ['rollen.id'], name=op.f('fk_rollen_berechtigungen_rolle_id_rollen'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('rolle_id', 'berechtigung_id', name=op.f('pk_rollen_berechtigungen'))
    )
    with op.batch_alter_table('rollen_berechtigungen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rollen_berechtigungen_berechtigung_id'), ['berechtigung_id'], unique=False)

    op.create_table('sitzungen',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('laeuft_ab', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('letzte_aktivitaet', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('angemeldet_bleiben', sa.Boolean(), nullable=False),
    sa.Column('ip', sa.String(length=50), nullable=True),
    sa.Column('browser', sa.String(length=200), nullable=True),
    sa.Column('beendet_am', app.modelle.basis.UtcDateTime(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sitzungen_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sitzungen'))
    )
    with op.batch_alter_table('sitzungen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sitzungen_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sitzungen_laeuft_ab'), ['laeuft_ab'], unique=False)
        batch_op.create_index(batch_op.f('ix_sitzungen_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_sitzungen_user_id'), ['user_id'], unique=False)

    op.create_table('soll_kalkulation',
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('material_soll', app.modelle.basis.Cent(), nullable=True),
    sa.Column('dl_soll', app.modelle.basis.Cent(), nullable=True),
    sa.Column('stunden_soll', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('marge_soll', sa.Integer(), nullable=True),
    sa.Column('quelle_datei', sa.String(length=1000), nullable=True),
    sa.Column('eingelesen_am', app.modelle.basis.UtcDateTime(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_soll_kalkulation_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('projekt_id', name=op.f('pk_soll_kalkulation'))
    )
    with op.batch_alter_table('soll_kalkulation', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_soll_kalkulation_created_at'), ['created_at'], unique=False)

    op.create_table('stueckliste',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('artikel_nr', sa.String(length=50), nullable=True),
    sa.Column('bezeichnung', sa.String(length=200), nullable=False),
    sa.Column('menge_soll', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('menge_ist', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('ek_preis', app.modelle.basis.Cent(), nullable=True),
    sa.Column('quelle', sa.String(length=50), nullable=False),
    sa.Column('gewerk', sa.String(length=50), nullable=True),
    sa.Column('bewertet_betrag', app.modelle.basis.Cent(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(gewerk IS NULL) OR (gewerk IN ('pv', 'speicher', 'ls'))", name=op.f('ck_stueckliste_gewerk_wert')),
    sa.CheckConstraint("quelle IN ('projektbestellt', 'lager')", name=op.f('ck_stueckliste_quelle_wert')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_stueckliste_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stueckliste'))
    )
    with op.batch_alter_table('stueckliste', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stueckliste_artikel_nr'), ['artikel_nr'], unique=False)
        batch_op.create_index(batch_op.f('ix_stueckliste_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_stueckliste_projekt_id'), ['projekt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stueckliste_quelle'), ['quelle'], unique=False)

    op.create_table('stunden',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('monat', sa.String(length=7), nullable=False),
    sa.Column('mitarbeiter', sa.String(length=200), nullable=False),
    sa.Column('stunden', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('satz', app.modelle.basis.Cent(), nullable=False),
    sa.Column('quelle', sa.String(length=50), nullable=False),
    sa.Column('importlauf_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(monat IS NULL) OR (length(monat) = 7 AND substr(monat, 5, 1) = '-' AND substr(monat, 6, 2) >= '01' AND substr(monat, 6, 2) <= '12')", name=op.f('ck_stunden_monat_format')),
    sa.ForeignKeyConstraint(['importlauf_id'], ['importlaeufe.id'], name=op.f('fk_stunden_importlauf_id_importlaeufe')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_stunden_projekt_id_projekte'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stunden'))
    )
    with op.batch_alter_table('stunden', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stunden_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_stunden_importlauf_id'), ['importlauf_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stunden_monat'), ['monat'], unique=False)
        batch_op.create_index(batch_op.f('ix_stunden_projekt_id'), ['projekt_id'], unique=False)

    op.create_table('user_rollen',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('rolle_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['rolle_id'], ['rollen.id'], name=op.f('fk_user_rollen_rolle_id_rollen'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_rollen_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'rolle_id', name=op.f('pk_user_rollen'))
    )
    with op.batch_alter_table('user_rollen', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_rollen_rolle_id'), ['rolle_id'], unique=False)

    op.create_table('zahlungsplan',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('projekt_id', sa.Integer(), nullable=False),
    sa.Column('pos_nr', sa.Integer(), nullable=False),
    sa.Column('bezeichnung', sa.String(length=200), nullable=False),
    sa.Column('gewerk', sa.String(length=50), nullable=False),
    sa.Column('art', sa.String(length=50), nullable=False),
    sa.Column('betrag_netto', app.modelle.basis.Cent(), nullable=False),
    sa.Column('plan_monat', sa.String(length=7), nullable=True),
    sa.Column('trigger_status', sa.String(length=50), nullable=True),
    sa.Column('rechnung_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint("(plan_monat IS NULL) OR (length(plan_monat) = 7 AND substr(plan_monat, 5, 1) = '-' AND substr(plan_monat, 6, 2) >= '01' AND substr(plan_monat, 6, 2) <= '12')", name=op.f('ck_zahlungsplan_plan_monat_format')),
    sa.CheckConstraint("art IN ('abschlag', 'schluss', 'einmal')", name=op.f('ck_zahlungsplan_art_wert')),
    sa.CheckConstraint("gewerk IN ('pv', 'speicher', 'ls', 'service', 'nachtrag')", name=op.f('ck_zahlungsplan_gewerk_wert')),
    sa.ForeignKeyConstraint(['projekt_id'], ['projekte.id'], name=op.f('fk_zahlungsplan_projekt_id_projekte'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rechnung_id'], ['rechnungen.id'], name=op.f('fk_zahlungsplan_rechnung_id_rechnungen')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_zahlungsplan')),
    sa.UniqueConstraint('projekt_id', 'pos_nr', name='uq_zahlungsplan_projekt_id_pos_nr')
    )
    with op.batch_alter_table('zahlungsplan', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_zahlungsplan_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_zahlungsplan_gewerk'), ['gewerk'], unique=False)
        batch_op.create_index(batch_op.f('ix_zahlungsplan_plan_monat'), ['plan_monat'], unique=False)
        batch_op.create_index(batch_op.f('ix_zahlungsplan_projekt_id'), ['projekt_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_zahlungsplan_rechnung_id'), ['rechnung_id'], unique=False)

    op.create_table('rechnungspos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rechnung_id', sa.Integer(), nullable=False),
    sa.Column('pos', sa.Integer(), nullable=False),
    sa.Column('bezeichnung', sa.String(length=1000), nullable=False),
    sa.Column('menge', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('einheit', sa.String(length=50), nullable=True),
    sa.Column('ep_netto', app.modelle.basis.Cent(), nullable=False),
    sa.Column('ust_satz', sa.Integer(), nullable=False),
    sa.Column('zahlungsplan_id', sa.Integer(), nullable=True),
    sa.Column('created_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('updated_at', app.modelle.basis.UtcDateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=50), nullable=True),
    sa.CheckConstraint('(ust_satz IS NULL) OR (ust_satz >= 0)', name=op.f('ck_rechnungspos_ust_satz_positiv')),
    sa.ForeignKeyConstraint(['rechnung_id'], ['rechnungen.id'], name=op.f('fk_rechnungspos_rechnung_id_rechnungen'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['zahlungsplan_id'], ['zahlungsplan.id'], name=op.f('fk_rechnungspos_zahlungsplan_id_zahlungsplan')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rechnungspos')),
    sa.UniqueConstraint('rechnung_id', 'pos', name='uq_rechnungspos_rechnung_id_pos')
    )
    with op.batch_alter_table('rechnungspos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rechnungspos_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungspos_rechnung_id'), ['rechnung_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rechnungspos_zahlungsplan_id'), ['zahlungsplan_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('rechnungspos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rechnungspos_zahlungsplan_id'))
        batch_op.drop_index(batch_op.f('ix_rechnungspos_rechnung_id'))
        batch_op.drop_index(batch_op.f('ix_rechnungspos_created_at'))

    op.drop_table('rechnungspos')
    with op.batch_alter_table('zahlungsplan', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_zahlungsplan_rechnung_id'))
        batch_op.drop_index(batch_op.f('ix_zahlungsplan_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_zahlungsplan_plan_monat'))
        batch_op.drop_index(batch_op.f('ix_zahlungsplan_gewerk'))
        batch_op.drop_index(batch_op.f('ix_zahlungsplan_created_at'))

    op.drop_table('zahlungsplan')
    with op.batch_alter_table('user_rollen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_rollen_rolle_id'))

    op.drop_table('user_rollen')
    with op.batch_alter_table('stunden', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stunden_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_stunden_monat'))
        batch_op.drop_index(batch_op.f('ix_stunden_importlauf_id'))
        batch_op.drop_index(batch_op.f('ix_stunden_created_at'))

    op.drop_table('stunden')
    with op.batch_alter_table('stueckliste', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stueckliste_quelle'))
        batch_op.drop_index(batch_op.f('ix_stueckliste_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_stueckliste_created_at'))
        batch_op.drop_index(batch_op.f('ix_stueckliste_artikel_nr'))

    op.drop_table('stueckliste')
    with op.batch_alter_table('soll_kalkulation', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_soll_kalkulation_created_at'))

    op.drop_table('soll_kalkulation')
    with op.batch_alter_table('sitzungen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sitzungen_user_id'))
        batch_op.drop_index(batch_op.f('ix_sitzungen_token_hash'))
        batch_op.drop_index(batch_op.f('ix_sitzungen_laeuft_ab'))
        batch_op.drop_index(batch_op.f('ix_sitzungen_created_at'))

    op.drop_table('sitzungen')
    with op.batch_alter_table('rollen_berechtigungen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rollen_berechtigungen_berechtigung_id'))

    op.drop_table('rollen_berechtigungen')
    with op.batch_alter_table('rechnungen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rechnungen_storno_ref'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_status'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_rechnung_nr'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_firma_id'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_faellig_am'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_datum'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_created_at'))
        batch_op.drop_index(batch_op.f('ix_rechnungen_art'))

    op.drop_table('rechnungen')
    with op.batch_alter_table('opos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_opos_stand_datum'))
        batch_op.drop_index(batch_op.f('ix_opos_rechnung_nr'))
        batch_op.drop_index(batch_op.f('ix_opos_importlauf_id'))
        batch_op.drop_index(batch_op.f('ix_opos_faellig_am'))
        batch_op.drop_index(batch_op.f('ix_opos_created_at'))

    op.drop_table('opos')
    with op.batch_alter_table('nummernkreise', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nummernkreise_firma_id'))
        batch_op.drop_index(batch_op.f('ix_nummernkreise_created_at'))

    op.drop_table('nummernkreise')
    with op.batch_alter_table('nachtraege', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_nachtraege_status'))
        batch_op.drop_index(batch_op.f('ix_nachtraege_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_nachtraege_created_at'))

    op.drop_table('nachtraege')
    with op.batch_alter_table('meilensteine', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_meilensteine_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_meilensteine_erledigt_am'))
        batch_op.drop_index(batch_op.f('ix_meilensteine_created_at'))

    op.drop_table('meilensteine')
    with op.batch_alter_table('ist_kosten', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ist_kosten_quelle'))
        batch_op.drop_index(batch_op.f('ix_ist_kosten_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_ist_kosten_monat'))
        batch_op.drop_index(batch_op.f('ix_ist_kosten_importlauf_id'))
        batch_op.drop_index(batch_op.f('ix_ist_kosten_created_at'))

    op.drop_table('ist_kosten')
    with op.batch_alter_table('dokumente', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dokumente_typ'))
        batch_op.drop_index(batch_op.f('ix_dokumente_projekt_id'))
        batch_op.drop_index(batch_op.f('ix_dokumente_created_at'))

    op.drop_table('dokumente')
    with op.batch_alter_table('datev_salden', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_datev_salden_monat'))
        batch_op.drop_index(batch_op.f('ix_datev_salden_konto'))
        batch_op.drop_index(batch_op.f('ix_datev_salden_importlauf_id'))
        batch_op.drop_index(batch_op.f('ix_datev_salden_created_at'))
        batch_op.drop_index(batch_op.f('ix_datev_salden_block'))

    op.drop_table('datev_salden')
    with op.batch_alter_table('ansprechpartner', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ansprechpartner_kunde_id'))
        batch_op.drop_index(batch_op.f('ix_ansprechpartner_created_at'))

    op.drop_table('ansprechpartner')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))
        batch_op.drop_index(batch_op.f('ix_users_created_at'))
        batch_op.drop_index(batch_op.f('ix_users_aktiv'))

    op.drop_table('users')
    with op.batch_alter_table('rollen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rollen_created_at'))

    op.drop_table('rollen')
    with op.batch_alter_table('projekte', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_projekte_typ'))
        batch_op.drop_index(batch_op.f('ix_projekte_status'))
        batch_op.drop_index(batch_op.f('ix_projekte_projekt_nr'))
        batch_op.drop_index(batch_op.f('ix_projekte_pl_user_id'))
        batch_op.drop_index(batch_op.f('ix_projekte_kunde_id'))
        batch_op.drop_index(batch_op.f('ix_projekte_firma_id'))
        batch_op.drop_index(batch_op.f('ix_projekte_created_at'))
        batch_op.drop_index(batch_op.f('ix_projekte_auftrag_vom'))
        batch_op.drop_index(batch_op.f('ix_projekte_anlage_id'))

    op.drop_table('projekte')
    with op.batch_alter_table('kunden', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_kunden_status'))
        batch_op.drop_index(batch_op.f('ix_kunden_ort'))
        batch_op.drop_index(batch_op.f('ix_kunden_name'))
        batch_op.drop_index(batch_op.f('ix_kunden_kunden_nr'))
        batch_op.drop_index(batch_op.f('ix_kunden_created_at'))

    op.drop_table('kunden')
    with op.batch_alter_table('konten_mapping', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_konten_mapping_created_at'))
        batch_op.drop_index(batch_op.f('ix_konten_mapping_block'))

    op.drop_table('konten_mapping')
    with op.batch_alter_table('job_laeufe', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_laeufe_status'))
        batch_op.drop_index(batch_op.f('ix_job_laeufe_job'))
        batch_op.drop_index(batch_op.f('ix_job_laeufe_gestartet'))
        batch_op.drop_index(batch_op.f('ix_job_laeufe_created_at'))

    op.drop_table('job_laeufe')
    with op.batch_alter_table('importlaeufe', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_importlaeufe_zeitraum'))
        batch_op.drop_index(batch_op.f('ix_importlaeufe_status'))
        batch_op.drop_index(batch_op.f('ix_importlaeufe_quelle'))
        batch_op.drop_index(batch_op.f('ix_importlaeufe_created_at'))

    op.drop_table('importlaeufe')
    with op.batch_alter_table('fristen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fristen_typ'))
        batch_op.drop_index(batch_op.f('ix_fristen_faellig_am'))
        batch_op.drop_index(batch_op.f('ix_fristen_erledigt_am'))
        batch_op.drop_index(batch_op.f('ix_fristen_created_at'))
        batch_op.drop_index(batch_op.f('ix_fristen_bezug_id'))
        batch_op.drop_index(batch_op.f('ix_fristen_bezug'))

    op.drop_table('fristen')
    with op.batch_alter_table('fixkosten_plan', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fixkosten_plan_monat'))
        batch_op.drop_index(batch_op.f('ix_fixkosten_plan_created_at'))

    op.drop_table('fixkosten_plan')
    with op.batch_alter_table('firmen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_firmen_created_at'))

    op.drop_table('firmen')
    with op.batch_alter_table('berechtigungen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_berechtigungen_schluessel'))
        batch_op.drop_index(batch_op.f('ix_berechtigungen_created_at'))

    op.drop_table('berechtigungen')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_user_id'))
        batch_op.drop_index(batch_op.f('ix_audit_log_user'))
        batch_op.drop_index(batch_op.f('ix_audit_log_ts'))
        batch_op.drop_index(batch_op.f('ix_audit_log_tabelle'))
        batch_op.drop_index(batch_op.f('ix_audit_log_aktion'))

    op.drop_table('audit_log')
    with op.batch_alter_table('anlagen', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_anlagen_wartungsvertrag'))
        batch_op.drop_index(batch_op.f('ix_anlagen_projekt_id_ursprung'))
        batch_op.drop_index(batch_op.f('ix_anlagen_kunde_id'))
        batch_op.drop_index(batch_op.f('ix_anlagen_inbetriebnahme'))
        batch_op.drop_index(batch_op.f('ix_anlagen_gewaehrleistung_ende'))
        batch_op.drop_index(batch_op.f('ix_anlagen_created_at'))

    op.drop_table('anlagen')
