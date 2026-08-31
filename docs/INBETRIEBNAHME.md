# Inbetriebnahme des ip³ Leitstands

Der Weg von „gebaut" zu „läuft produktiv". Alle sieben Phasen aus [PLAN §7](../PLAN.md) sind
fertig; was jetzt noch fehlt, ist keine Software mehr, sondern **Einrichtung und Zulieferung**.

Diese Datei ist die Reihenfolge. Für den täglichen Betrieb danach – Start, Stopp, Update,
Restore – gilt weiter das [RUNBOOK](../RUNBOOK.md).

Wer das Projekt zum ersten Mal sieht – etwa eine beauftragte IT – liest vorher
[`UEBERGABE-IT.md`](UEBERGABE-IT.md): Zweck, Aufbau, Datenflüsse und die Regeln, die man
nicht verletzen darf.

> **Der eine Befehl, der alles prüft:**
> ```bash
> cd backend && uv run ip3-leitstand bereitschaft
> ```
> Er ändert nichts. Er sagt zu jedem Punkt, ob er erledigt ist, was fehlt und was der nächste
> Schritt ist. Nach jedem Abschnitt hier lohnt es sich, ihn erneut laufen zu lassen.

---

## Was zuerst passieren muss, weil es am längsten dauert

Zwei Dinge hängen nicht an dir und sollten deshalb **heute** rausgehen, nicht am Tag der
Umstellung:

### 1. Die Anfrage an die Kanzlei

[`docs/KANZLEI-ANFORDERUNG.md`](KANZLEI-ANFORDERUNG.md) liegt fertig zum Weiterleiten. Darin
stehen drei Fragen; die dritte ist die gefährlichste:

* **KOST2 = Projektnummer** in der Buchhaltung. Ohne sie lässt sich keine Buchung einem Projekt
  zuordnen, und die ganze Nachkalkulation bleibt leer.
* **Drei monatliche CSV-Exporte** nach `02_DATEV`: Kostenträger, Summen- und Saldenliste,
  offene Posten.
* **Welcher Kontenrahmen geführt wird.** Bei SKR04 sind die 4000er **Erlöse**, bei SKR03
  Betriebsausgaben. Ein falsch eingestellter Bereich bucht Umsatz als Kosten – und die
  Nachkalkulation sieht dabei völlig plausibel aus. Genau deshalb ist das keine Frage, die man
  nebenbei beantwortet.

### 2. Die Entscheidung, wo der Leitstand läuft

Danach richtet sich alles Weitere. Zwei Wege, beide vorbereitet:

| | Rechner im Büro (Windows) | Gemieteter Linux-Server |
|---|---|---|
| Dienst | `deploy/windows/` | `deploy/systemd/` |
| TLS | Caddy, `deploy/Caddyfile` | Caddy, `deploy/Caddyfile` |
| Rechnungs-PDF | **GTK-Runtime nachinstallieren**, sonst kein PDF | liegt in der Regel vor |
| OneDrive | direkt eingebunden | Zugriff muss eingerichtet werden |
| Läuft nachts | nur wenn der Rechner an bleibt | immer |

Der nächtliche Lauf – Sicherung, Importe, Fristen, Doku-Scan – braucht einen Rechner, der um
01:30 Uhr läuft. Auf einem Bürorechner, der abends ausgeht, holt der Leitstand einen verpassten
Lauf beim nächsten Start **einmal** nach; er stapelt sie nicht.

---

## Schritt für Schritt

### Schritt 1: Host vorbereiten

`git`, `node`, `uv` installieren, Quelltext holen, Frontend bauen – wie in
[`AUF-DEN-EIGENEN-RECHNER.md`](AUF-DEN-EIGENEN-RECHNER.md) beschrieben, nur eben auf dem
Rechner, der ihn später betreibt.

**Auf Windows zusätzlich das GTK-Runtime-Paket.** Ohne die Bibliotheken wirft der erste Klick
auf „PDF-Vorschau" einen unerwarteten Fehler – und zwar genau dann, wenn eine Rechnung
rausgehen soll. `ip3-leitstand bereitschaft` prüft das im Voraus.

### Schritt 2: Ordner anlegen

Der Leitstand legt **keine Ordner an**. Das ist Absicht: ein Werkzeug, das ungefragt
Verzeichnisse im Firmen-OneDrive anlegt, wäre schlimmer als eines, das sie vermisst.

| Ordner | Wofür | Zugriff |
|---|---|---|
| `01_Rechnungen` | Ablage der festgeschriebenen Belege (PDF + XML) | **schreibend** |
| `02_DATEV` | die drei Monatsexporte der Kanzlei | lesend |
| `03_Kalkulation` | die Kalkulationsblätter | lesend |
| `04_Backup` | nächtliche Sicherung, 30 Generationen | **schreibend** |
| `05_Projekte` | ein Ordner je Projekt, Nummer im Namen | lesend |
| Abrechnungen | Netzbetreiber-Abrechnungen der eigenen Anlagen | lesend |

Die **Datenbank gehört nicht dorthin.** Sie liegt lokal auf dem Host, niemals in einem
synchronisierten Ordner – SQLite und Ordnersynchronisation zerstören sich gegenseitig. Der
Leitstand verweigert in dem Fall den Start.

### Schritt 3: `config.toml` und `.env`

`config.example.toml` als Vorlage nehmen. Beide Dateien bleiben auf dem Host und wandern nie
ins Repository.

In die **`.env`** gehören ausschließlich Geheimnisse:

```
IP3_SITZUNG_SCHLUESSEL=...
IP3_TIMETAC_CLIENT_ID=...
IP3_TIMETAC_CLIENT_SECRET=...
IP3_TIMETAC_KONTO=...
```

Den Sitzungsschlüssel erzeugen mit:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

In die **`config.toml`** gehört alles andere. Vier Blöcke sind noch offen und brauchen deine
Angaben:

* `[firma]` – Bankverbindung, HRB, Geschäftsführer. § 14 UStG verlangt sie; ohne sie weist die
  Festschreibung **jeden** Beleg ab.
* `[pfade]` – die Ordner aus Schritt 2.
* `[stundensaetze.saetze]` – die vier Verrechnungssätze. Sie stehen noch auf der Vorbelegung;
  bis sie bestätigt sind, ist jede Eigenleistung in der Nachkalkulation geschätzt.
* `[datev.kostentraeger] kostenkonten` – der Kontenbereich, sobald die Kanzlei geantwortet hat.

Für den Echtbetrieb außerdem `[app] umgebung = "produktion"`. Erst dann greifen die
Sicherheitsprüfungen für Cookies und Herkunft – und der Leitstand startet dann **nicht** mehr
ohne Sitzungsschlüssel, ohne TLS-Cookie und ohne erlaubte Herkunft.

### Schritt 4: Datenbank anlegen

```bash
cd backend
uv run ip3-leitstand schema        # Tabellen und Trigger
uv run ip3-leitstand seed          # Rollen, Berechtigungen, Administrator
```

**Ohne `--demodaten`.** Die Demoprojekte gehören in die Probeinstallation, nicht in den
Echtbetrieb.

Das Startpasswort erscheint genau einmal. Es muss bei der ersten Anmeldung gewechselt werden.

### Schritt 5: Bestandsdaten übernehmen

Der einmalige Vorgang aus [RUNBOOK §9](../RUNBOOK.md): 539 Projekte und rund 290
Zahlungsplanpositionen aus den beiden Excel-Dateien. Erst ansehen, dann übernehmen – die
Kontrollsummen stehen im Importprotokoll.

Danach: **Projektleiter den Nutzerkonten zuordnen.** Ohne diese Zuordnung greift der
Sichtbarkeits-Scope „eigene" nicht, und die betroffenen Nutzer sehen nichts.

### Schritt 6: Bevor die erste echte Rechnung rausgeht

Das ist der Abschnitt mit der meisten Handarbeit, und er lässt sich nicht überspringen:

| Was | Stand aus dem Abnahmelauf |
|---|---|
| **Anschriften nachtragen** | Von 484 migrierten Kunden hat **keiner** Straße und PLZ; 454 haben einen Ort. Die Teamliste führte keine Anschriften. § 14 UStG verlangt die vollständige Anschrift, der Leitstand weist einen solchen Beleg ab. Mindestens für die Kunden, die als Nächstes eine Rechnung bekommen. |
| **Privat oder Gewerbe setzen** | Alle 484 stehen auf „Privatkunde", weil die Quelldateien nichts dazu sagten. Davon hängt ab, ob eine E-Rechnung entsteht – ab 1.1.2027 Pflicht für inländische B2B-Umsätze. |
| **Zahlungsziel und Skonto bestätigen** | Vorbelegung 14 Tage, 3 %. Die Fälligkeit steht auf jedem festgeschriebenen Beleg, und **danach ist eine Änderung nicht mehr rückwirkend möglich.** |
| **12 Projekte ohne Auftragswert** | 10 aus der Teamliste (unlesbare Zelle), 2 bewusst leer. Ohne Auftragswert lässt sich keine Schlussrechnung vorbelegen. Die Liste steht auf der Umsatzseite. |

**Dann eine Probe-Rechnung schreiben und wieder stornieren.** Nummernkreis, PDF, Ablage und
E-Rechnung einmal im Echtbetrieb gesehen zu haben ist mehr wert als jede Zusicherung – und ein
Storno ist genau dafür da.

### Schritt 7: Die Datenquellen anschließen

Jede einzeln, jede prüfbar:

```bash
uv run ip3-leitstand timetac-test        # Zugang, Konto, ein Testabruf
```

Der erste echte TimeTac-Lauf ist noch nie gefahren – die Entwicklungsumgebung erreicht
`api.timetac.com` nicht. Endpunkte und Feldnamen sind nach der v3-Dokumentation vorbelegt und in
der `config.toml` nachziehbar. Geht der Test durch, stimmt beides.

Danach über **Importe & Daten** in der Oberfläche: DATEV, Kalkulationsblätter, SuSa, OPOS. Jeder
Import hat eine Vorschau, die nichts schreibt.

Für die zwei Phase-7-Funktionen:

* **Angebots-Tool:** eine Beispieldatei liefern, `[pfade] angebote` setzen. Die Spaltennamen in
  `[angebote.spalten]` sind gegen erfundene Namen entwickelt – erst die echte Datei zeigt, ob
  sie passen.
* **Netzbetreiber-Abrechnung:** eine echte Abrechnung liefern, `[pfade] einspeisung` setzen,
  die eigenen Anlagen mit Vergütungssatz und Zählernummer erfassen. Als `.csv` oder `.xlsx`,
  **nicht als PDF**.
* **Mitarbeiter mit Wochenstunden erfassen.** Die Schreibweise der Namen muss der in TimeTac
  entsprechen, sonst zählen die Stunden in der Nachkalkulation und die Person fehlt in der
  Kapazität. Der Leitstand nennt solche Namen.

### Schritt 8: Als Dienst einrichten

`deploy/systemd/` bzw. `deploy/windows/` und `deploy/Caddyfile`. Danach:

* **Autostart prüfen:** Rechner neu starten, Leitstand muss von selbst wieder da sein.
* **Eine Sicherung testweise zurückspielen** – nach [RUNBOOK §7](../RUNBOOK.md), Schritt für
  Schritt. Eine Sicherung, die nie zurückgespielt wurde, ist eine Vermutung.
* **Systemstatus ansehen.** Er zeigt jeden nächtlichen Lauf mit seinem Alter. Ein Lauf, der
  still fehlt, ist schlimmer als einer, der als „noch nicht eingerichtet" dasteht.

### Schritt 9: Nutzer und Schulung

```bash
uv run ip3-leitstand nutzer-anlegen
```

Drei Rollen sind vorbereitet: `admin`, `buchhaltung`, `team`. Wer was sieht, steht in
[`BERECHTIGUNGEN.md`](BERECHTIGUNGEN.md) – die Datei wird aus dem Katalog erzeugt und ist damit
immer aktuell.

**Beträge sind dem Team entzogen** (PLAN §4): Auftragswerte, Margen, Cockpit und Angebotssummen
sieht es nicht, Stunden und Termine schon. Bei der Kapazitätsansicht ist noch zu bestätigen, ob
das Team sie sehen soll – zurzeit ja; sie zeigt Stunden und Projektnummern, keine Beträge.

---

## Was noch offen ist

Der vollständige Stand steht in [`OFFENE-PUNKTE.md`](OFFENE-PUNKTE.md). Kurz:

**Nur von dir zu liefern:**
Kanzlei-Antwort (Kontenrahmen, KOST2, Exporte) · Bankverbindung und HRB · Verrechnungssätze ·
Zahlungsziel bestätigen · Kundenanschriften · Privat/Gewerbe · TimeTac-`.env` · Beispieldatei
des Angebots-Tools · eine Netzbetreiber-Abrechnung · Host-Entscheidung

**Formal, ohne Eile:**
Das Werkzeug ins Verzeichnis der Verarbeitungstätigkeiten nach Art. 30 DSGVO aufnehmen. Zweck
der TimeTac-Stunden ist Kostenrechnung, ausdrücklich keine Leistungskontrolle.

---

## Was der Leitstand nicht tut

Kein ERP, keine Lagerbuchhaltung, keine BWA, keine DATEV-Direktschnittstelle, kein
automatischer Mail- oder Mahnversand, keine Mobile-App (PLAN §12).

Er schreibt **nur** in die eigene Datenbank und in den Rechnungs-Ausgabeordner. Alle anderen
Quellen – DATEV, Kalkulationsblätter, TimeTac, Projektordner, Abrechnungen – werden
ausschließlich gelesen.
