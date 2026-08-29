# Anforderung an die Steuerkanzlei: Kostenträgerauswertung für den ip³ Leitstand

*Stand 29.08.2026. Dieses Blatt ist zum Weiterleiten an die Kanzlei gedacht.*

## Worum es geht

Die ip³ Energietechnik GmbH führt seit 2026 ein eigenes Projekt- und Finanzcockpit (den
„Leitstand"). Es rechnet je Projekt nach, was es eingebracht und was es gekostet hat. Die
Kostenseite kommt aus der Finanzbuchhaltung.

**Der Leitstand schreibt nichts nach DATEV zurück.** Er liest ausschließlich eine monatliche
Auswertung. An den Abläufen in der Kanzlei ändert sich dadurch nichts außer den beiden Punkten
unten.

---

## 1. Der Kostenträger: KOST2 trägt die Projektnummer

Der Leitstand ordnet jede Buchung über das Feld **KOST2 (Kostenträger)** einem Projekt zu. Dort
muss die Projektnummer stehen, die auch ip³ verwendet.

**Format der Projektnummer:** rein numerisch, fünfstellig, Schema `JJNNN` — die ersten beiden
Stellen sind das Auftragsjahr, danach eine laufende Nummer. Beispiele: `26001`, `26057`, `22141`.
Serviceaufträge tragen eine führende 9 und sind damit sechsstellig (`926001`). Buchstaben,
Bindestriche oder Leerzeichen kommen darin nicht vor.

**Was zu tun ist:**

- Buchungen, die zu einem Projekt gehören, bekommen die Projektnummer in KOST2.
- Buchungen ohne Projektbezug (Miete, Versicherungen, allgemeine Verwaltung) bleiben **ohne**
  KOST2. Der Leitstand übergeht sie bewusst — sie gehören in den Gemeinkostenblock und werden
  dort ab der nächsten Ausbaustufe ausgewertet.
- KOST1 (Kostenstelle) spielt für den Leitstand keine Rolle und kann bleiben, wie es ist.

**Was ip³ dafür tut:** Die Projektnummer wird auf den Eingangsrechnungen vermerkt, bevor sie zur
Buchung gehen. Ohne diesen Vermerk kann die Kanzlei sie nicht zuordnen.

> **Wenn KOST2 fehlt:** Der Leitstand meldet die Buchung im Importprotokoll als „ohne
> Kostenträger" und lässt sie außen vor. Es geht nichts verloren, aber die Kosten fehlen am
> Projekt — und die Marge des Projekts sieht dann besser aus, als sie ist.

---

## 2. Der monatliche Export

**Welche Auswertung:** eine **Kostenträgerauswertung mit Einzelbuchungen** (je nach
DATEV-Programmstand „Kostenträger-Einzelnachweis" oder „Einzelkostennachweis"). Wichtig ist, dass
die **einzelnen Buchungszeilen** enthalten sind, nicht nur Summen je Kostenträger — der Leitstand
soll jeden Betrag bis auf den Beleg zurückverfolgen können.

**Format:** CSV.

**Zeitraum:** ein Kalendermonat je Datei.

**Dateiname:** `kostentraeger_JJJJ-MM.csv`, also z. B. `kostentraeger_2026-07.csv` für den Juli
2026. Der Monat im Dateinamen entscheidet, welchen Zeitraum der Leitstand ersetzt — er muss
deshalb stimmen.

**Ablage:** im Firmen-OneDrive der ip³ im Ordner `02_DATEV`. Alternativ per Mail an ip³; die
Ablage übernimmt dann ip³ selbst.

**Wann:** nach dem Monatsabschluss. Ein nachgelieferter oder korrigierter Monat ist unkritisch:
der Leitstand ersetzt den Monat vollständig, es verdoppelt sich nichts.

### Diese Felder werden gebraucht

| Feld | Zwingend | Wofür |
|---|---|---|
| **KOST2 / Kostenträger** | ja | Zuordnung zum Projekt |
| **Konto** (Sachkonto) | ja | Entscheidet, ob die Buchung als Projektkosten zählt (siehe Punkt 3) |
| **Umsatz / Betrag** | ja | Der Betrag |
| **Soll/Haben-Kennzeichen** | ja | Soll = Kosten, Haben = Minderung (z. B. Gutschrift eines Lieferanten) |
| Belegdatum | sehr erwünscht | Gegenprobe, ob die Datei wirklich den Monat enthält, der im Dateinamen steht |
| Belegfeld 1 / Belegnummer | erwünscht | Rückverfolgung bis zum Beleg |
| Buchungstext | erwünscht | Rückverfolgung, Lesbarkeit des Protokolls |
| Kontobezeichnung | erwünscht | Beschriftung in der Auswertung |

### Was **nicht** abgestimmt werden muss

Um diese drei Dinge muss sich die Kanzlei nicht kümmern — der Leitstand kommt mit allen üblichen
Varianten zurecht:

- **Spaltenüberschriften.** Weichen sie ab, werden sie einmalig in der Konfiguration des
  Leitstands hinterlegt. Bitte die Spaltennamen nicht extra anpassen.
- **Zeichensatz.** ANSI/Windows-1252 und UTF-8 werden beide erkannt.
- **Trennzeichen.** Semikolon, Komma oder Tabulator — alles wird erkannt.
- **Zahlenformat.** `1.234,56`, `1234.56` und das nachgestellte Minus (`1.234,56-`) werden
  richtig gelesen.

---

## 3. Welche Konten als Projektkosten zählen — **hier ist eine Entscheidung nötig**

Eine Kostenträgerauswertung führt in der Regel **auch Erlöse**, die auf den Kostenträger gebucht
sind. Würde der Leitstand sie als Kosten übernehmen, drehte sich die Marge ins Gegenteil.
Deshalb übernimmt er nur Buchungen aus einem festgelegten Kontenbereich.

**Frage an die Kanzlei / Buchhaltung:**

1. **Welcher Kontenrahmen wird geführt — SKR03 oder SKR04?**
2. **Welche Kontennummernbereiche sollen als Projektkosten in die Nachkalkulation eingehen?**

Zur Orientierung, ohne Anspruch auf Vollständigkeit — maßgeblich ist die Auskunft der Kanzlei:

| Kontenrahmen | Aufwand (Projektkosten) | Erlöse (dürfen **nicht** hinein) |
|---|---|---|
| SKR03 | Klasse 3 (Wareneingang/Material) und Klasse 4 (Betriebsausgaben), also etwa 3000–4999 | 8000–8999 |
| SKR04 | Klasse 5 (Materialaufwand) und Klasse 6 (betriebliche Aufwendungen), also etwa 5000–6999 | **4000–4999** |

> ⚠️ **Der wichtigste Punkt dieses Blattes:** Bei **SKR04 sind die 4000er die Erlöskonten**,
> bei SKR03 dagegen Betriebsausgaben. Wird der Bereich falsch eingestellt, wandern Umsatzerlöse
> als Kosten in die Nachkalkulation. Die Zahlen sähen plausibel aus und wären grob falsch.
> Deshalb bitte den Kontenrahmen ausdrücklich benennen.

**Weitere Fragen, die sich dabei meist stellen:**

- Sollen **Fremdleistungen / Nachunternehmer** in die Projektkosten? (Aus ip³-Sicht: ja.)
- Sollen **Reisekosten und Fahrzeugkosten**, sofern sie auf einen Kostenträger gebucht sind,
  mitzählen? (Entscheidung der Geschäftsführung; technisch beides möglich.)
- Gibt es einzelne Konten innerhalb des Aufwandsbereichs, die ausdrücklich **nicht** hinein
  sollen? Dann bitte nennen — der Bereich lässt sich aus mehreren Abschnitten zusammensetzen.

Die Antwort wird in der Konfiguration des Leitstands hinterlegt (`[datev.kostentraeger]`,
Eintrag `kostenkonten`). Eine spätere Änderung ist jederzeit möglich; die betroffenen Monate
werden dann einmal neu eingelesen.

---

## 4. Zwei weitere monatliche Exporte

Das Firmen-Cockpit ist inzwischen gebaut und braucht zusätzlich zur Kostenträgerauswertung zwei
Exporte. Sie kommen in denselben Ordner, im selben Rhythmus, im selben Format (CSV).

### 4.1 Summen- und Saldenliste — `susa_JJJJ-MM.csv`

Für den Fixkostenblock: was hat die Firma diesen Monat an laufenden Kosten getragen.

| Feld | Zwingend | Wofür |
|---|---|---|
| **Konto** (Sachkonto) | ja | Zuordnung zum Kostenblock (Personal, Raum, Fahrzeuge …) |
| **Saldo** | ja | Der Betrag |
| **Monatssaldo / Periodensaldo** | **sehr wichtig, siehe unten** | Der Wert des Monats |
| Kontobezeichnung | erwünscht | Beschriftung, Nachpflege unbekannter Konten |
| Soll/Haben-Kennzeichen | erwünscht | Vorzeichen; ohne Angabe entscheidet das Vorzeichen des Betrags |

> ⚠️ **Bitte je Periode, nicht kumuliert.** Viele SuSa-Auswertungen führen den Saldo seit
> Jahresbeginn. Der Leitstand braucht den **Monatswert**. Enthält die Datei beide Spalten,
> nimmt er automatisch die Periode. Enthält sie nur den kumulierten Saldo, rechnet er damit und
> vermerkt es im Protokoll — die Fixkosten wären dann ab Februar zu hoch, ohne dass es jemandem
> auffällt.

### 4.2 Offene Posten Debitoren — `opos_JJJJ-MM-TT.csv`

Für den Zahlungsstatus der Ausgangsrechnungen. **Der Dateiname trägt einen vollen Stichtag**
(z. B. `opos_2026-07-31.csv`), nicht nur den Monat: eine OPOS-Liste gilt für einen Tag, und der
Leitstand führt die Stände nebeneinander.

| Feld | Zwingend | Wofür |
|---|---|---|
| **Rechnungsnummer / Belegfeld 1** | ja | Zuordnung zur Rechnung des Leitstands |
| **Offener Betrag** | ja | Was noch aussteht |
| Rechnungsbetrag | erwünscht | Gegenprobe |
| Fälligkeit | erwünscht | Unterscheidung offen / überfällig |
| Kunde / Debitor | erwünscht | Lesbarkeit der Liste |

**Was ip³ damit tut:** Der Leitstand leitet den Zahlungsstatus ausschließlich hieraus ab. Eine
Rechnung, die nicht mehr in der Liste steht, gilt als bezahlt; ein Restbetrag innerhalb der
Skonto-Toleranz als „bezahlt mit Abzug". Rechnungen aus der Zeit vor der Einführung des
Leitstands sind unkritisch — sie stehen im Protokoll und werden übergangen.

### 4.3 Und noch eine Frage zur Kontenzuordnung

Für den Fixkostenblock ordnet der Leitstand Kontenbereiche diesen Blöcken zu: **Personal, Raum,
Fahrzeuge, Versicherungen, Werbung, Zinsen, Sonstiges** und **neutral** (durchlaufende Posten,
die nicht in die Fixkosten gehören).

Bitte einmalig eine Liste der Kontenbereiche mit ihrer Zuordnung — das ist dieselbe Frage wie
unter Punkt 3, nur für die Aufwandsseite im Detail. Konten ohne Zuordnung werden eingelesen,
zählen aber nicht mit und erscheinen im Leitstand als Pflegehinweis.

Außerdem bittet ip³ um eine **Durchsicht der Verfahrensdokumentation** (`VERFAHRENSDOKU.md`) im
Hinblick auf die GoBD, sobald der Leitstand im Regelbetrieb ist. Die Ausgangsrechnungen werden
seit 2026 im Leitstand erstellt, festgeschrieben und als PDF (bei Geschäftskunden zusätzlich als
ZUGFeRD/Factur-X) abgelegt.

---

## Ansprechpartner

ip³ Energietechnik GmbH · Sven Wilhelm · Theisseil
