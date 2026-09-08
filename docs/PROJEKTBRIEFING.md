# Projektbriefing ip³ Leitstand

Für jeden – Mensch oder Agent –, der dieses Projekt neu übernimmt und eigenständig daran
arbeiten soll. Es sagt, **was das Ziel ist, was damit erreicht werden soll, was frei
entscheidbar ist und was nicht** – und bei den unfreien Punkten jeweils, warum.

Verbindliche Langfassungen: [`PLAN.md`](../PLAN.md) (Bauvorlage: Datenmodell, Geschäftsregeln,
Phasen) und [`CLAUDE.md`](../CLAUDE.md) (Arbeitsregeln). Dieses Briefing ersetzt sie nicht, es
macht sie in zehn Minuten lesbar.

---

## 1. Wer

**ip³ Energietechnik GmbH**, Theisseil bei Weiden in der Oberpfalz. Plant, baut und installiert
Photovoltaik-Anlagen und Batteriespeicher – von Aufdach über Gewerbe bis Freifläche und
Großspeicher. Geschäftsführer: Sven Wilhelm und Michael Bäumler.

Nutzer des Werkzeugs: die zwei Geschäftsführer, eine Buchhaltungskraft, lesender Zugriff fürs
Team. Vier bis sechs Personen, alle im Firmennetz, Zugriff über den Browser.

## 2. Das Ziel

Auftragsliste, Umsatzplanung, Abschlagsverfolgung und Nachkalkulation liefen bisher verteilt
über **zwei gewachsene Excel-Dateien, einen Ordner voll Rechnungs-PDFs und Kopfwissen**. Der
Leitstand ersetzt das durch eine zentrale Anwendung mit eigener Datenhaltung.

Sechs Kernfunktionen:

1. **Projektverwaltung** mit Zahlungsplan je Projekt (Abschläge, Schlussrechnung)
2. **Umsatz-Ist und Forecast** je Monat, offener Auftragsbestand
3. **Fakturierung**: Auftragsbestätigung, Abschlags-, Schluss- und Servicerechnung im
   Corporate Design, inklusive E-Rechnung (ZUGFeRD) und GoBD-konformer Festschreibung
4. **Nachkalkulation je Projekt**: Soll aus dem Kalkulationsblatt gegen Ist aus
   DATEV-Kostenträgern, bewerteter Stückliste und TimeTac-Stunden
5. **Firmen-Cockpit**: Deckungsbeitrag gegen Fixkosten, Break-even, Reichweite des
   Auftragsbestands, Zahlungslage über offene Posten
6. **Anlagenregister** mit Serviceaufträgen sowie Fristen- und Gewährleistungswächter

## 3. Was damit erreicht werden soll

Nicht „Digitalisierung". Vier konkrete Fragen, die vorher niemand schnell beantworten konnte:

* **Ist ein Abschlag fällig oder schon gestellt?** Der Zahlungsplan stand in einer anderen
  Datei als die Rechnungen. Geld blieb liegen, weil es niemandem auffiel.
* **Verdient dieses Projekt Geld?** Vorher wusste man das erst nach der Buchung durch die
  Kanzlei – und dann nur als Summe über alles, nicht je Projekt.
* **Wie sieht der Umsatz der nächsten Monate aus?** Der Forecast war eine Momentaufnahme, deren
  Erneuerung einen halben Tag kostete.
* **Reißt uns eine Frist?** Gewährleistung und die Registrierung im Marktstammdatenregister
  hingen an Erinnerung.

Dazu **Kapazität** (reichen die Mannstunden für das, was verkauft ist?), **Pipeline** (was ist
angeboten, gewichtet nach Wahrscheinlichkeit) und ein **Vergütungs-Controlling** für die eigenen
Anlagen (stimmt die Abrechnung des Netzbetreibers?).

## 4. Stand

**Alle sieben Phasen aus PLAN §7 sind gebaut.** Letzter Commit `e34c5fe` auf Branch
`claude/new-session-9oqvjg`. Backend-Suite grün, `ruff` grün, Frontend-Tests und Build grün.

Größenordnung: 104 Python-Module, 55 Test-Dateien, 9 Alembic-Migrationen, 19 Routenmodule,
37 Frontend-Seiten.

**Was noch fehlt, ist keine Software, sondern Einrichtung und Zulieferung.** Der Weg dorthin
steht in [`docs/INBETRIEBNAHME.md`](INBETRIEBNAHME.md); den Stand stellt jederzeit dieser Befehl
fest, der nichts ändert:

```bash
cd backend && uv run ip3-leitstand bereitschaft
```

## 5. Stack

| Ebene | Technik |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, APScheduler, pydantic-settings; `uv` |
| Datenbank | SQLite (WAL, `busy_timeout`, Fremdschlüssel an), lokal auf dem Host |
| Frontend | React 19, Vite, TypeScript, React Router, TanStack Query; eigene Komponenten, **keine UI-Bibliothek** |
| API-Vertrag | OpenAPI → `openapi-typescript`/`openapi-fetch`, generierter Client |
| PDF | WeasyPrint; E-Rechnung Factur-X/ZUGFeRD 2.x, Profil EN 16931 |
| Betrieb | ein Uvicorn-Prozess als Dienst, Caddy davor mit TLS; Frontend-Build vom Backend ausgeliefert |

Verzeichnisse: `backend/`, `frontend/`, `design/` (Designsystem und Mockups, Vorlage – wird
nicht importiert), `assets/cd/` (Schriften, Logos, Zeichen 3), `deploy/`, `docs/`.

---

## 6. Frei entscheidbar

Hier ist eigenes Urteil ausdrücklich erwünscht – die bisherigen Lösungen sind Vorschläge, keine
Vorgaben:

* Innere Struktur der Dienste und Module, Schnitt der Funktionen, Refactorings
* Testaufbau und Fixtures
* Namen und Zuschnitt der API-Routen, solange der Vertrag generiert bleibt
* Aufbau und Bedienung der Oberfläche innerhalb des Corporate Designs
* Wahl der Bibliotheken für neue Aufgaben (sparsam, erst wenn gebraucht, Versionen gepinnt)
* Performance, Indizes, Caching
* Ob es weitere Auswertungen gibt und wie sie aussehen

## 7. Nicht frei – und warum

Diese Punkte sehen wie Geschmack aus, sind aber jeweils ein gelöstes Problem. Wer sie
„aufräumt", bringt einen Fehler zurück, der schon dagewesen ist.

**Fachlich/rechtlich**

| Regel | Warum |
|---|---|
| **Geldbeträge sind Integer in Cent.** Kein Gleitkomma, Umrechnung nur in der Anzeige | Fließkomma-Cent führt zu Summen, die um Cent abweichen und in einer Rechnung nicht erklärbar sind |
| **Umsatzsteuer je Steuersatz auf die Nettosumme des Belegs runden**, nicht je Position | PLAN §6.11; anders ergibt die Summe der Positionen einen anderen Betrag als der Belegausweis |
| **Rundung ist ROUND_HALF_UP.** Ausdrücklich, überall | `Decimal.quantize` rundet ohne Angabe **zur geraden Zahl** – das hat hier schon einen Betrag um einen Cent verschoben, obwohl der Kommentar daneben etwas anderes behauptete |
| **Festgeschriebene Belege sind unveränderbar**, erzwungen per Datenbank-Trigger | GoBD. Eine Prüfung nur in der Anwendungsschicht ist keine Unveränderbarkeit |
| **§ 14 UStG:** vollständige Anschrift des Empfängers, Steuernummer **oder** USt-IdNr. (nicht beides) | Ohne das ist die Rechnung formal fehlerhaft; die Festschreibung weist solche Belege deshalb ab |
| **E-Rechnung** ist für inländische B2B-Umsätze ab 1.1.2027 Pflicht – daher das Kennzeichen Privat/Gewerbe je Kunde | Davon hängt ab, ob überhaupt ein XML entsteht |
| **Nichts löschen, was Bezüge hat.** Belege und Stammdaten wechseln den Status (`inaktiv`, `storniert`), Nutzer werden nur deaktiviert | Aufbewahrungspflicht und Nachvollziehbarkeit |
| **Bei buchführungs- oder steuerrelevanten Unklarheiten nachfragen**, nicht annehmen | Ein falsch angenommener Kontenrahmen bucht Umsatz als Kosten – und die Auswertung sieht dabei plausibel aus |

**Technisch**

| Regel | Warum |
|---|---|
| **Berechtigungen ausschließlich serverseitig**, über `benoetigt('ressource.aktion')`, **nie gegen Rollennamen** | Ein Regressionstest (`backend/tests/test_rbac.py`) verlangt das für **jede** schreibende `/api`-Route; seine Ausnahmeliste darf nur mit Begründung wachsen. Das Frontend blendet nur zusätzlich aus |
| **Beträge sind der Rolle `team` entzogen, Stunden nicht** | PLAN §4: Finanzsichtbarkeit ist von der Projektsicht getrennt |
| **Zeitstempel in UTC speichern** (`UtcDateTime`, naive Werte werden abgewiesen), Anzeige und Monatszuordnung in Europe/Berlin | Sonst wandern Buchungen bei der Zeitumstellung in den falschen Monat |
| **Optimistic Locking in allen Bearbeitungsmasken** | Speichern mit veraltetem Stand ergibt eine Konfliktmeldung, kein stilles Überschreiben |
| **Jede schreibende Aktion ins `audit_log`** – nie Passwörter, Hashes oder Token | Nachvollziehbarkeit; Geheimnisse in Protokollen sind ein Datenleck mit Aufbewahrungsfrist |
| **Fehlerkörper `{code, meldung, naechster_schritt}`**, verständlich, deutsch, niemals ein Stacktrace in der Antwort | Fehlerpfade zählen zur Funktion, nicht zum Rand |
| **SQLite-Datei niemals in einem Sync-Ordner** (OneDrive) | Ordnersynchronisation kennt die Dateisperren nicht – die Datei wird beschädigt. Die Anwendung verweigert deshalb den Start bei verdächtigem Pfad |
| **Genau ein Arbeitsprozess**, kein `--workers` | Der Zeitplan der nächtlichen Läufe steckt im Prozess; mehrere Prozesse zählen Kosten doppelt |
| **Die Anwendung schreibt nur in die eigene Datenbank und in den Rechnungs-Ausgabeordner.** Alle externen Quellen werden **nur gelesen** | Sie darf in Fremddaten keinen Schaden anrichten können |
| **Keine Cloud-Dienste.** Alle Daten bleiben lokal bzw. im Firmen-OneDrive | Vorgabe des Auftraggebers |
| **`firma_id` bleibt im Schema**, auch wenn es nur ip³ gibt | PLAN §12: die Firmen-Dimension ist bewusst von Anfang an drin, damit später eine zweite Firma ohne Umbau fakturieren kann. Kein toter Code |
| **Nach jeder Änderung an Routen oder Schemas `npm run api`** | Sonst schlägt der Frische-Test der OpenAPI-Spezifikation fehl, und der generierte Client läuft auseinander |

**Sprache und Gestaltung**

* **Deutsch:** Oberfläche, Fachkommentare, Commit-Nachrichten, Dokumentation. Feldnamen deutsch
  in `snake_case`.
* **Corporate Design ist verbindlich** (PLAN §11, `design/README.md`): Farben nur aus den
  Tokens – ip³ Blau `#2F2482`, Navy `#0C1A3D`, ip³ Rot `#8D0C07`, Akzent-Rot `#C83C30`.
  **Kein Grün, keine Verläufe.** Zahlen in Space Grotesk mit Tabellenziffern. Deutsche
  Zahlenformate (`1.250,00 €`, `5.695 kWp`) mit geschütztem Leerzeichen vor der Einheit.
* Jede Phase endet lauffähig, mit grüner `pytest`-Suite und einem Eintrag in `CHANGELOG.md`.

## 8. Was ausdrücklich nicht dazugehört

Kein ERP, keine Lagerbuchhaltung, keine handelsrechtliche BWA (Abgrenzungen, AfA, teilfertige
Arbeiten bleiben beim Steuerberater), keine DATEV-Direktschnittstelle, kein automatischer Mahn-
oder Mailversand, keine Mobile-App, kein SSO. Der Leitstand ersetzt die Buchhaltung nicht – er
liest sie.

---

## 9. Was offen ist

**Die eine Entscheidung, an der weitere Arbeit hängt:** auf welchem Host der Leitstand läuft –
Rechner im Büro (Windows, NSSM) oder gemieteter Linux-Server (systemd). Beide Wege sind in
`deploy/` vorbereitet. Davon hängen die konkreten Pfade und die Frage ab, ob der nächtliche Lauf
um 01:30 Uhr überhaupt stattfindet.

**Zulieferungen, die nur ip³ liefern kann** – vollständig mit Begründung in
[`docs/OFFENE-PUNKTE.md`](OFFENE-PUNKTE.md):

Antwort der Kanzlei (Kontenrahmen SKR03/SKR04, KOST2 = Projektnummer, drei Monatsexporte) ·
Bankverbindung, HRB, Steuernummer · vier Verrechnungssätze bestätigen · Zahlungsziel und Skonto
bestätigen · Anschriften der 484 übernommenen Bestandskunden (keiner hat Straße und PLZ) ·
Privat/Gewerbe-Kennzeichen · TimeTac-Zugangsdaten · je eine echte Beispieldatei aus dem
Angebots-Tool und vom Netzbetreiber · eigene Anlagen erfassen · Mitarbeiter mit Wochenstunden in
TimeTac-Schreibweise · Eintrag ins Verzeichnis der Verarbeitungstätigkeiten nach Art. 30 DSGVO.

**Noch nie in Echt gelaufen:** der TimeTac-Abruf. Endpunkte und Feldnamen sind nach der
v3-Dokumentation vorbelegt und in der `config.toml` nachziehbar; `ip3-leitstand timetac-test`
prüft es.

## 10. Vertrauliches

Nichts davon liegt im Repository, und nichts davon gehört in einen Chat oder einen externen
Dienst:

* **`.env`** – Sitzungsschlüssel und TimeTac-Zugang. Gehört ausschließlich auf den Host.
* **`config.toml`** – Pfade und Firmenstammdaten.
* **`migration-quellen/`** – die echten Bestandsdateien mit Kundennamen, Auftragswerten und
  Rechnungen. Versionsignoriert.

Für Entwicklung und Prüfung reichen Demodaten: `ip3-leitstand seed --demodaten`. Eine echte
Rechnung oder eine echte Kundenliste braucht dafür niemand.

## 11. Wo was steht

| Datei | Inhalt |
|---|---|
| [`PLAN.md`](../PLAN.md) | **Verbindliche Bauvorlage.** Architekturentscheidungen mit Begründung, Datenmodell (§5), Geschäftsregeln (§6), Phasenplan (§7), Integrationen (§8), Corporate Design (§11), Nichtziele (§12) |
| [`CLAUDE.md`](../CLAUDE.md) | Arbeitsregeln, Stack, häufige Befehle |
| [`docs/UEBERGABE-IT.md`](UEBERGABE-IT.md) | Übergabe an eine beauftragte IT: Zweck, Aufbau, Datenflüsse, Anbindungen |
| [`docs/INBETRIEBNAHME.md`](INBETRIEBNAHME.md) | Der Weg zum Echtbetrieb, Schritt für Schritt |
| [`RUNBOOK.md`](../RUNBOOK.md) | Betrieb: Start, Update über die Testinstanz, Sicherung, Restore, Störungen |
| [`docs/AUF-DEN-EIGENEN-RECHNER.md`](AUF-DEN-EIGENEN-RECHNER.md) | Probeinstallation mit Demodaten auf einem beliebigen Rechner, zum Wegwerfen |
| [`docs/BERECHTIGUNGEN.md`](BERECHTIGUNGEN.md) | Wer darf was – **erzeugt** aus dem Katalog im Code, Änderungen von Hand gehen verloren |
| [`NUTZERHANDBUCH.md`](../NUTZERHANDBUCH.md) | Bedienung je Rolle |
| [`VERFAHRENSDOKU.md`](../VERFAHRENSDOKU.md) | Verfahrensdokumentation nach GoBD (Abstimmung mit dem Steuerberater offen) |
| [`docs/OFFENE-PUNKTE.md`](OFFENE-PUNKTE.md) | Rückfragen, getroffene Zwischenentscheidungen, Befunde der Abnahmeläufe |
| [`CHANGELOG.md`](../CHANGELOG.md) | Was in welcher Phase entstanden ist |
| [`design/README.md`](../design/README.md) | Designsystem, Komponentenschnitt, Screen-Mockups |

## 12. Befehle

```bash
# Backend
cd backend
uv sync                                  # Abhängigkeiten
uv run alembic upgrade head              # Schema anlegen/aktualisieren
uv run ip3-leitstand seed --demodaten    # Stammdaten + Demodaten (nur Entwicklung)
uv run ip3-leitstand server              # API auf :8000
uv run ip3-leitstand bereitschaft        # prüft, was zur Inbetriebnahme fehlt
uv run pytest
uv run ruff check . && uv run ruff format --check .

# Frontend
cd frontend
npm ci
npm run api                              # OpenAPI-Client neu generieren (nach API-Änderungen!)
npm run dev                              # Vite auf :5173, /api wird auf :8000 gespiegelt
npm run typecheck && npm test && npm run build
```

**Einstieg zum Kennenlernen:** `docs/AUF-DEN-EIGENEN-RECHNER.md` – Probeinstallation mit
Demodaten, eine Stunde, ohne Server, ohne echte Daten. Danach ist klar, worum es geht.
