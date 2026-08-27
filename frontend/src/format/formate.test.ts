/**
 * Zahlen- und Datumsformate (PLAN §6.10, §11).
 *
 * Der wichtigste Prüfpunkt ist das geschützte Leerzeichen vor der Einheit: es ist unsichtbar,
 * fachlich aber verlangt – sonst wird „1.250,00 €" über einen Zeilenumbruch getrennt.
 */

import { describe, expect, it } from 'vitest'
import {
  MINUS,
  NBSP,
  anteil,
  anzahl,
  begruessung,
  datum,
  datumZeit,
  euro,
  euroKurz,
  kapazitaet,
  leistung,
  mitEinheit,
  monat,
  monatKurz,
  prozent,
  vorname,
  wochentagDatum,
  zahl,
} from './formate'

describe('euro', () => {
  it('formatiert Cent-Beträge deutsch', () => {
    expect(euro(125000)).toBe(`1.250,00${NBSP}€`)
    expect(euro(9187500)).toBe(`91.875,00${NBSP}€`)
    expect(euro(5)).toBe(`0,05${NBSP}€`)
    expect(euro(0)).toBe(`0,00${NBSP}€`)
  })

  it('verwendet ein geschütztes Leerzeichen vor dem Währungszeichen', () => {
    // Ohne dieses Zeichen reißt ein Zeilenumbruch Betrag und Währung auseinander.
    expect(euro(125000)).toContain(NBSP)
    expect(euro(125000)).not.toContain(' €')
  })

  it('verwendet das Minuszeichen, nicht den Bindestrich', () => {
    // Das Minuszeichen steht auf Ziffernhöhe; der Bindestrich sitzt zu tief und zu kurz.
    expect(euro(-1432000)).toBe(`${MINUS}14.320,00${NBSP}€`)
    expect(euro(-1432000)).not.toContain('-')
  })

  it('rechnet große Beträge ohne Gleitkommafehler', () => {
    // 12.345.678,91 € – bei einer Division durch 100 in Gleitkomma entstünde hier
    // eine Abweichung im letzten Cent.
    expect(euro(1234567891)).toBe(`12.345.678,91${NBSP}€`)
    expect(euro(999999999999)).toBe(`9.999.999.999,99${NBSP}€`)
  })

  it('kann das Währungszeichen weglassen (für Tabellenspalten mit Einheit im Kopf)', () => {
    expect(euro(125000, false)).toBe('1.250,00')
  })

  it('zeigt für fehlende Werte einen Gedankenstrich', () => {
    expect(euro(null)).toBe('–')
    expect(euro(undefined)).toBe('–')
  })
})

describe('euroKurz', () => {
  it('verkürzt Millionenbeträge', () => {
    expect(euroKurz(794000000)).toBe(`7,94${NBSP}Mio.${NBSP}€`)
  })

  it('verkürzt Tausenderbeträge', () => {
    expect(euroKurz(61240000)).toBe(`612${NBSP}T€`)
  })

  it('zeigt kleine Beträge vollständig', () => {
    expect(euroKurz(125000)).toBe(`1.250,00${NBSP}€`)
  })

  it('behält das Vorzeichen', () => {
    expect(euroKurz(-1240000)).toBe(`${MINUS}12${NBSP}T€`)
  })
})

describe('Einheiten', () => {
  it('setzt ein geschütztes Leerzeichen vor die Einheit', () => {
    expect(mitEinheit(5695, 'kWp', 0)).toBe(`5.695${NBSP}kWp`)
  })

  it('wechselt bei Leistung ab 1000 kWp auf MWp', () => {
    expect(leistung(499.2)).toBe(`499,2${NBSP}kWp`)
    expect(leistung(5695)).toBe(`5,695${NBSP}MWp`)
  })

  it('wechselt bei Kapazität ab 1000 kWh auf MWh', () => {
    expect(kapazitaet(120)).toBe(`120,0${NBSP}kWh`)
    expect(kapazitaet(2500)).toBe(`2,500${NBSP}MWh`)
  })
})

describe('Prozent', () => {
  it('setzt bei Veränderungen ein Pluszeichen', () => {
    expect(prozent(7.2)).toBe(`+7,2${NBSP}%`)
    expect(prozent(-3.5)).toBe(`${MINUS}3,5${NBSP}%`)
  })

  it('rechnet Promille aus der Schnittstelle um', () => {
    // Steuersätze und Sollmargen kommen als Promille, damit sie ohne Gleitkomma darstellbar sind.
    expect(prozent(190, 0, true)).toBe(`+19${NBSP}%`)
    expect(prozent(0, 0, true)).toBe(`0${NBSP}%`)
  })

  it('lässt bei Anteilen das Pluszeichen weg', () => {
    expect(anteil(15)).toBe(`15,0${NBSP}%`)
  })
})

describe('Zahlen', () => {
  it('setzt Tausenderpunkte', () => {
    expect(zahl(5695)).toBe('5.695')
    expect(zahl(1234567)).toBe('1.234.567')
  })

  it('rundet auf die angegebenen Nachkommastellen', () => {
    expect(zahl(45.678, 1)).toBe('45,7')
  })
})

describe('Datum', () => {
  it('formatiert als TT.MM.JJJJ', () => {
    expect(datum('2026-08-27')).toBe('27.08.2026')
    expect(datum(new Date(2026, 0, 5))).toBe('05.01.2026')
  })

  it('formatiert Zeitpunkte mit Uhrzeit', () => {
    const text = datumZeit('2026-08-27T12:30:00Z')
    expect(text).toContain('27.08.2026')
    expect(text).toMatch(/\d{2}:\d{2}/)
  })

  it('nennt den Wochentag für den Kopf der Startseite', () => {
    expect(wochentagDatum('2026-08-27')).toBe('Donnerstag, 27.08.2026')
  })

  it('behandelt fehlende und unlesbare Werte', () => {
    expect(datum(null)).toBe('–')
    expect(datum('kein Datum')).toBe('–')
    expect(datumZeit(undefined)).toBe('–')
  })
})

describe('Monat', () => {
  it('schreibt den Monatsnamen aus', () => {
    expect(monat('2026-09')).toBe('September 2026')
    expect(monat('2026-03')).toBe('März 2026')
  })

  it('nennt fehlende Planmonate „unterminiert"', () => {
    // PLAN §7, Phase 2: Positionen ohne Planmonat werden gesondert ausgewiesen.
    expect(monat(null)).toBe('unterminiert')
    expect(monat('')).toBe('unterminiert')
  })

  it('kürzt für Diagrammbeschriftungen', () => {
    expect(monatKurz('2026-08')).toBe('Aug')
    expect(monatKurz('2026-12')).toBe('Dez')
  })
})

describe('Texte', () => {
  it('grüßt nach Tageszeit', () => {
    expect(begruessung('Sven', new Date(2026, 7, 27, 8, 0))).toBe('Guten Morgen, Sven.')
    expect(begruessung('Sven', new Date(2026, 7, 27, 14, 0))).toBe('Guten Tag, Sven.')
    expect(begruessung('Sven', new Date(2026, 7, 27, 20, 0))).toBe('Guten Abend, Sven.')
  })

  it('holt den Vornamen aus dem vollständigen Namen', () => {
    expect(vorname('Sven Wilhelm')).toBe('Sven')
    expect(vorname('Michael Bäumler')).toBe('Michael')
    expect(vorname('Sven')).toBe('Sven')
  })

  it('beugt Substantive nach Anzahl', () => {
    // „1 Projekte" fällt in einer deutschen Oberfläche sofort auf.
    expect(anzahl(1, 'Projekt', 'Projekte')).toBe('1 Projekt')
    expect(anzahl(23, 'Projekt', 'Projekte')).toBe('23 Projekte')
    expect(anzahl(0, 'Projekt', 'Projekte')).toBe('0 Projekte')
  })
})
