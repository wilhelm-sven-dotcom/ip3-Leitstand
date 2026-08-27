/**
 * Komponentengalerie – nur im Entwicklungsmodus erreichbar (`/entwurf/komponenten`).
 *
 * Zeigt jede Komponente in ihren Zuständen neben der Vorlage aus
 * design/Komponenten.dc.html. Zweck: Abweichungen fallen beim Bauen auf, nicht erst, wenn eine
 * Fachseite fertig ist. Beispieldaten sind erfunden und dieselben wie in der Vorlage, damit
 * sich beides direkt vergleichen lässt.
 */

import { useState } from 'react'
import { PageTitle } from '@/komponenten/PageTitle'
import { StatusBadge, BADGE_ZUSTAENDE } from '@/komponenten/StatusBadge'
import { Knopf } from '@/komponenten/Knopf'
import { KpiTile } from '@/komponenten/KpiTile'
import { ActionCard } from '@/komponenten/ActionCard'
import { DataTable } from '@/komponenten/DataTable'
import type { Spalte } from '@/komponenten/DataTable'
import { MonthBars } from '@/komponenten/MonthBars'
import { FormRow } from '@/komponenten/FormRow'
import { EmptyState } from '@/komponenten/EmptyState'
import { ConfirmDialog } from '@/komponenten/ConfirmDialog'
import { Zusammenfassung } from '@/komponenten/Zusammenfassung'
import { Meldung } from '@/komponenten/Meldung'
import { euro, euroKurz, leistung, prozent } from '@/format/formate'

type Zeile = {
  nr: number
  projekt: string
  kwp: number
  betragCent: number
  zustand: (typeof BADGE_ZUSTAENDE)[number]
}

const ZEILEN: Zeile[] = [
  { nr: 26014, projekt: 'Maschinenbau Köstler GmbH', kwp: 499.2, betragCent: 61250000, zustand: 'gestellt' },
  { nr: 26007, projekt: 'Solarpark Pirk Süd', kwp: 5695, betragCent: 324000000, zustand: 'frist' },
  {
    nr: 25041,
    projekt: 'Autohaus Winkler, Halle 2',
    kwp: 63.4,
    betragCent: -1432000,
    zustand: 'ueberfaellig',
  },
]

const SPALTEN: Spalte<Zeile>[] = [
  { kopf: 'Nr.', zelle: (z) => z.nr, zahl: true },
  { kopf: 'Projekt', zelle: (z) => z.projekt, hervorgehoben: true },
  { kopf: 'Leistung (kWp)', zelle: (z) => leistung(z.kwp), zahl: true },
  {
    kopf: 'Betrag netto (€)',
    zelle: (z) => (
      <span className={z.betragCent < 0 ? 'negativ' : undefined}>{euro(z.betragCent, false)}</span>
    ),
    zahl: true,
  },
  { kopf: 'Status', zelle: (z) => <StatusBadge zustand={z.zustand} /> },
]

function Abschnitt({
  titel,
  hinweis,
  children,
  breit = false,
}: {
  titel: string
  hinweis: string
  children: React.ReactNode
  breit?: boolean
}) {
  return (
    <div style={breit ? { gridColumn: '1 / -1' } : undefined}>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{titel}</div>
      <div style={{ fontSize: 12, color: 'var(--text-sekundaer)', marginTop: 2 }}>{hinweis}</div>
      <div className="karte" style={{ padding: 'var(--abstand-5)', marginTop: 10 }}>
        {children}
      </div>
    </div>
  )
}

export function KomponentenGalerie() {
  const [dialogOffen, setDialogOffen] = useState(false)
  const [bestaetigt, setBestaetigt] = useState(false)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-6)' }}>
      <PageTitle
        meta={
          'Nur im Entwicklungsmodus. Vergleich mit design/Komponenten.dc.html – ' +
          'Beispieldaten sind erfunden.'
        }
      >
        Komponenten
      </PageTitle>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 420px), 1fr))',
          gap: 'var(--abstand-6) var(--abstand-5)',
          alignItems: 'start',
        }}
      >
        <Abschnitt
          titel="Statusbadge-Set"
          hinweis="Genau diese acht Zustände, überall identisch. Kein Grün."
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {BADGE_ZUSTAENDE.map((zustand) => (
              <StatusBadge key={zustand} zustand={zustand} />
            ))}
          </div>
        </Abschnitt>

        <Abschnitt
          titel="Schaltflächen"
          hinweis="Primär Blau, sekundär weiß mit Linie. Akzent-Rot nur für Festschreiben."
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
            <Knopf>Abschlag stellen</Knopf>
            <Knopf art="sekundaer">Abbrechen</Knopf>
            <Knopf art="festschreiben">Jetzt festschreiben</Knopf>
            <Knopf disabled>Deaktiviert</Knopf>
          </div>
        </Abschnitt>

        <Abschnitt
          titel="KPI-Kachel"
          hinweis="Wert in Space Grotesk mit Tabellenziffern. Negative Werte in Akzent-Rot."
        >
          <div
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--abstand-4)' }}
          >
            <KpiTile
              label="Umsatz"
              wert={euroKurz(61240000)}
              zusatz={`${prozent(7.2)} ggü. Juli`}
              zusatzArt="positiv"
            />
            <KpiTile
              label="Unterdeckung"
              wert={euroKurz(-1240000)}
              zusatz="Fixkosten nicht gedeckt"
              negativ
            />
          </div>
        </Abschnitt>

        <Abschnitt
          titel="Monatsbalken"
          hinweis="Ist gefüllt in ip³ Blau, Plan als Kontur. Werte in der Sprechblase."
        >
          <MonthBars
            werte={[
              { monat: '2026-05', beschriftung: 'Mai', betrag: 59800000, titel: 'Mai · 598 T€' },
              { monat: '2026-06', beschriftung: 'Jun', betrag: 63400000, titel: 'Juni · 634 T€' },
              { monat: '2026-07', beschriftung: 'Jul', betrag: 57100000, titel: 'Juli · 571 T€' },
              {
                monat: '2026-08',
                beschriftung: 'Aug',
                betrag: 61240000,
                aktuell: true,
                titel: 'August · 612 T€',
              },
              {
                monat: '2026-09',
                beschriftung: 'Sep',
                betrag: 64000000,
                plan: true,
                titel: 'September · Plan 640 T€',
              },
              {
                monat: '2026-10',
                beschriftung: 'Okt',
                betrag: 65500000,
                plan: true,
                titel: 'Oktober · Plan 655 T€',
              },
            ]}
          />
        </Abschnitt>

        <Abschnitt
          titel="Datentabelle"
          hinweis="Kopf ip³ Blau und fixiert, Zebrastreifen, Zahlen rechts, Einheit im Spaltenkopf."
          breit
        >
          <DataTable
            spalten={SPALTEN}
            zeilen={ZEILEN}
            schluessel={(z) => z.nr}
            beschriftung="Beispieltabelle mit erfundenen Projekten"
          />
        </Abschnitt>

        <Abschnitt
          titel="Aktionskarte"
          hinweis="Kicker · Titel · Meta links, Betrag und genau eine Aktion rechts."
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-3)' }}>
            <ActionCard
              kicker="Rechnungsvorschlag"
              titel="26014 · Maschinenbau Köstler GmbH"
              meta="Inbetriebnahme erreicht — Abschlag 4 kann gestellt werden"
              betrag={euro(9187500)}
              aktion={
                <Knopf klein>Abschlag stellen</Knopf>
              }
            />
            <ActionCard
              kicker="Überfällig"
              warnung
              titel="25041 · Autohaus Winkler, Halle 2"
              meta="Schlussrechnung RE-2026-0087 · fällig seit 12 Tagen"
              betrag={euro(1432000)}
              betragNegativ
              aktion={
                <Knopf art="sekundaer" klein>
                  Erinnerung senden
                </Knopf>
              }
            />
          </div>
        </Abschnitt>

        <Abschnitt
          titel="Formularzeile"
          hinweis="Label über dem Feld, Hinweis oder Fehler darunter."
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <FormRow
              label="Betrag netto (€)"
              defaultValue="91.875,00"
              zahl
              hinweis="15,0 % vom Auftragswert"
            />
            <FormRow
              label="Fällig am"
              defaultValue="31.02.2026"
              zahl
              fehler="Das Datum gibt es nicht. Format TT.MM.JJJJ."
            />
          </div>
        </Abschnitt>

        <Abschnitt
          titel="Meldung"
          hinweis="Fehler und Hinweise nennen immer den nächsten Schritt (PLAN §14)."
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--abstand-3)' }}>
            <Meldung
              art="fehler"
              text="Der Beleg ist festgeschrieben und kann nicht mehr geändert werden."
              naechsterSchritt="Für eine Korrektur einen Storno oder eine Gutschrift erzeugen."
            />
            <Meldung
              art="hinweis"
              text="Firmenstammdaten unvollständig (Umsatzsteuer-Identifikationsnummer)."
              naechsterSchritt="In config.toml unter [firma] ergänzen."
            />
          </div>
        </Abschnitt>

        <Abschnitt
          titel="Leerzustand"
          hinweis="Erklärt den nächsten Schritt, begleitet vom dezenten Zeichen 3."
        >
          <EmptyState
            titel="Noch kein Zahlungsplan."
            text="Legen Sie den ersten Abschlag an — Vorschlag: 30 % bei Auftrag."
            aktion={<Knopf klein>Ersten Abschlag anlegen</Knopf>}
          />
        </Abschnitt>

        <Abschnitt
          titel="Bestätigungsdialog"
          hinweis="Vollständige Zusammenfassung, Pflicht-Checkbox, Bestätigen in Akzent-Rot."
          breit
        >
          <Knopf art="festschreiben" onClick={() => setDialogOffen(true)}>
            Dialog öffnen
          </Knopf>
          <ConfirmDialog
            offen={dialogOffen}
            titel="Abschlagsrechnung festschreiben"
            meta='Projekt 26014 · Abschlag 4 „Inbetriebnahme"'
            bestaetigungstext="Ich habe die Zusammenfassung geprüft und will die Rechnung festschreiben."
            bestaetigt={bestaetigt}
            onBestaetigtChange={setBestaetigt}
            bestaetigenText="Jetzt festschreiben"
            unwiderruflich
            onBestaetigen={() => {
              setDialogOffen(false)
              setBestaetigt(false)
            }}
            onAbbrechen={() => {
              setDialogOffen(false)
              setBestaetigt(false)
            }}
          >
            <Zusammenfassung
              zeilen={[
                { label: 'Betrag netto', wert: euro(9187500) },
                { label: 'Umsatzsteuer 19 %', wert: euro(1745625) },
                { label: 'Brutto', wert: euro(10933125), summe: true },
              ]}
            />
          </ConfirmDialog>
        </Abschnitt>
      </div>
    </div>
  )
}
