# Änderungsverlauf

Format: neueste Phase oben. Jede Phase endet lauffähig mit grüner Testsuite (PLAN §7).

## 0.1.0 – Phase 0: Fundament

Erste lauffähige Fassung: der Leitstand startet als ein Dienst im ip³-Design, Anmeldung und
serverseitige Berechtigungsprüfung funktionieren, die nächtliche Sicherung läuft und ist
zurückspielbar. Projekt-, Fakturierungs- und Auswertungsfunktionen folgen mit den Phasen 1 bis 6.

### Grundlagen

* **Monorepo** mit `backend/` (FastAPI, SQLAlchemy, Alembic) und `frontend/` (React, Vite,
  TypeScript). Paketverwaltung über uv und npm, Versionen über Lockfiles gepinnt.
* **Konfiguration** aus `config.toml` und `.env`; Umgebungsvariablen überschreiben die Datei,
  sodass sich die Testinstanz allein über `IP3_APP__PORT` auf einen anderen Port legen lässt.
  Fehlerhafte Konfiguration erzeugt eine Meldung in Klartext mit nächstem Schritt.
* **Startsperre für Datenbanken in Sync-Ordnern**: liegt der Datenbankpfad in OneDrive,
  Dropbox oder auf einem Netzlaufwerk, verweigert der Leitstand den Start. SQLite wird dort
  beschädigt; ein Abbruch ist billiger als eine unbemerkt zerstörte Datenbank.
* **Datenbankzugriff** mit den PRAGMAs im Verbindungsereignis (sie gelten je Verbindung),
  WAL-Modus und `BEGIN IMMEDIATE` für Schreibvorgänge.

### Datenmodell

* Alle Tabellen aus PLAN §5 plus zwei technisch nötige: `sitzungen` für die serverseitigen
  Anmeldungen, `job_laeufe` für den Datenstand. Das Schema ist von Anfang an vollständig.
* Geldbeträge als Integer in Cent, Zeitpunkte in UTC über einen eigenen Spaltentyp, der Werte
  ohne Zeitzone abweist. Monate als `'JJJJ-MM'` mit portabler Prüfbedingung.
* Optimistic Locking über `updated_at` für alle von Menschen bearbeiteten Tabellen;
  Importtabellen bewusst ohne.
* Indizes auf allen Fremdschlüsseln sowie auf `projekt_nr`, `kunden_nr`, `rechnung_nr` und den
  Monatsspalten. Ein Test prüft das.

### Buchführungsrelevante Absicherung

* **Datenbank-Trigger** verhindern Änderung und Löschung festgeschriebener Belege, ihrer
  Positionen und berechneter Zahlungsplanpositionen – auch durch Zugriffe an der Anwendung
  vorbei. Erlaubt bleibt allein der Statuswechsel auf `storniert` mit Verweis, wobei Nummer,
  Beträge, Datum und Hash unverändert bleiben müssen.
* **Nummernvergabe** in derselben Transaktion wie der Beleg, damit keine Lücken entstehen. Ein
  Test lässt zehn Threads gleichzeitig Nummern ziehen.
* **Umsatzsteuer je Steuersatz auf die Belegsumme**, nicht je Position aufsummiert (PLAN §6.11);
  kaufmännische Rundung.

### Anmeldung und Berechtigungen

* Server-Sitzungen mit `httpOnly`-Cookie; der Sitzungsschlüssel liegt nur als Hash in der
  Datenbank – die Sicherungskopie im OneDrive enthält keine verwendbaren Zugangsdaten.
* CSRF-Schutz über ein sitzungsgebundenes Token plus Herkunftsprüfung, verankert in der
  Abhängigkeit, die den angemeldeten Nutzer ermittelt: keine Route kann die Prüfung vergessen.
* Sperre nach fünf Fehlanmeldungen für 15 Minuten, gezählt im Änderungsprotokoll; während der
  Sperre wird auch ein richtiges Passwort abgelehnt. Zusätzlich Drosselung je Absenderadresse.
* Die Anmeldung gibt nicht preis, was falsch war – unbekannte Kennung, falsches Passwort und
  deaktiviertes Konto ergeben dieselbe Antwort, auch in der Antwortzeit.
* RBAC mit den drei Rollen aus PLAN §4. Finanzsichtbarkeit ist abgetrennt: `projekte.lesen`
  zeigt Termine und Anlagendaten, `projekte.werte_lesen` erst die Beträge.
* Ein Regressionstest verlangt für jede schreibende `/api`-Route eine Berechtigungsprüfung.
* `docs/BERECHTIGUNGEN.md` wird aus dem Katalog erzeugt, nicht gepflegt.

### Betrieb

* **Nächtliche Sicherung** per `VACUUM INTO` – eine in sich geschlossene Kopie, erzeugt auch
  während gearbeitet wird. 30 Generationen, Rotation ausschließlich nach Namensmuster und ohne
  die Dateien zu öffnen (sonst holt OneDrive alte Sicherungen aus der Cloud zurück). Jede
  Sicherung wird auf Integrität geprüft.
* **Datenstand** auf der Startseite: für jeden Hintergrundlauf, wann er zuletzt erfolgreich war
  und wie alt dieser Stand ist. Läufe späterer Phasen erscheinen als „kommt später" und färben
  den Gesamtstatus nicht. Der Zeitplan läuft in Ortszeit und warnt bei mehreren
  Arbeitsprozessen.
* **Ein Prozess liefert API und Oberfläche.** Tiefe Adressen funktionieren nach einem Neuladen,
  `/api`-Pfade bleiben JSON, die `index.html` wird nie zwischengespeichert. Fehlt der Build,
  startet die Anwendung trotzdem und protokolliert einen Hinweis.
* **Kommandozeile** für alles am Host: `server`, `schema`, `seed`, `backup`, `pruefen`,
  `passwort-setzen`, `nutzer-liste`, `openapi`, `berechtigungen-doku`.
* **Deploy-Unterlagen**: Caddyfile mit interner Zertifizierungsstelle, systemd-Unit,
  NSSM-Anleitung für Windows samt dem Hinweis, dass ein Dienst unter `LocalSystem` das OneDrive
  des angemeldeten Nutzers nicht erreicht.

### Oberfläche

* Designsystem aus `design/` umgesetzt: Tokens unverändert übernommen, Markenschriften selbst
  ausgeliefert statt über Google Fonts, alle Komponenten nach den Rezepten.
* Anmeldeseite in Navy mit dem Zeichen 3, Startseite mit Datenstand, Passwortwechsel.
* Menüpunkte ohne Berechtigung werden ausgeblendet, nicht ausgegraut.
* Deutsche Zahlenformate mit geschütztem Leerzeichen vor der Einheit und Minuszeichen statt
  Bindestrich.
* TypeScript-Client aus der OpenAPI-Spezifikation erzeugt; ein Test hält die Spezifikation
  aktuell.
* Komponentengalerie unter `/entwurf/komponenten`, nur im Entwicklungsmodus.

### Bemerkenswerte Funde beim Bau

Vier Fehler, die ohne die zugehörigen Tests unbemerkt geblieben wären:

* Alembic ruft `fileConfig()` auf, was standardmäßig **alle bestehenden Logger deaktiviert**.
  Nach einer Migration aus dem laufenden Programm protokollierte die Anwendung nichts mehr –
  ein stiller Ausfall genau der Protokollierung, die PLAN §2 verlangt.
* Der Struktur-Regressionstest für Berechtigungen fand in seiner ersten Fassung **gar keine
  Routen**: FastAPI hängt eingebundene Router nicht flach in `app.routes` ein. Der Test wäre
  wirkungslos gewesen, ohne fehlzuschlagen. Er sichert sich jetzt selbst ab.
* Die Routen lasen die globale Konfiguration statt der, mit der die Anwendung erzeugt wurde –
  eine Instanz mit abweichender Konfiguration hätte gegen falsche Werte gearbeitet.
* Die Integritätsprüfung einer Sicherung brach bei einer stark beschädigten Datei mit einer
  Ausnahme ab, statt „nicht in Ordnung" zu melden.

### Offen

Fehlende Zulieferungen und Rückfragen stehen in `docs/OFFENE-PUNKTE.md`. Für den Betrieb
gebraucht werden zuerst: Firmenstammdaten für den Rechnungskopf, Backup-Zielpfad, Host und
Dienstkonto. Für Phase 1 die zwei Excel-Bestandsdateien.

Tests: 371 im Backend, 52 im Frontend.
