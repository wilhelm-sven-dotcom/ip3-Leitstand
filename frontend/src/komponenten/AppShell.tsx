/**
 * Rahmen der Anwendung: Sidebar, Topbar, Inhaltsbereich (design/Start.dc.html).
 *
 * Der Menüpunkte-Katalog steht hier und nicht in jeder Seite. Jeder Punkt nennt die
 * Berechtigung, die ihn sichtbar macht: **fehlt sie, verschwindet der Punkt** – ausgegraute
 * Menüpunkte gibt es nicht (design/README.md). Das ist eine Anzeigeentscheidung; die Sperre
 * sitzt im Backend, an jeder einzelnen Route.
 *
 * Punkte für spätere Phasen sind vorhanden, aber als „kommt noch" gekennzeichnet: so ist von
 * Anfang an sichtbar, wohin der Leitstand wächst, ohne dass jemand ins Leere klickt.
 */

import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import wortmarke from "@cd/logos/ip3-energietechnik-farbig.svg";
import { useSitzung } from "@/sitzung/SitzungKontext";
import "./appshell.css";

type Menuepunkt = {
  pfad: string;
  beschriftung: string;
  /** Ohne diese Berechtigung ist der Punkt nicht sichtbar. */
  recht?: string;
  /** Ab welcher Phase es die Seite gibt; bis dahin ohne Verweis. */
  abPhase?: number;
};

const AKTUELLE_PHASE = 7;

export const MENUE: Menuepunkt[] = [
  { pfad: "/", beschriftung: "Start" },
  {
    pfad: "/projekte",
    beschriftung: "Projekte",
    recht: "projekte.lesen",
    abPhase: 1,
  },
  // Abweichung von den Mockups: dort gibt es keinen Punkt für Kunden, PLAN §7 verlangt für
  // Phase 1 aber eine Maske dafür. Siehe design/UMSETZUNG.md.
  {
    pfad: "/stammdaten",
    beschriftung: "Stammdaten",
    recht: "kunden.lesen",
    abPhase: 1,
  },
  {
    pfad: "/fakturierung",
    beschriftung: "Fakturierung",
    recht: "rechnungen.lesen",
    abPhase: 3,
  },
  {
    pfad: "/umsatz",
    beschriftung: "Umsatz & Forecast",
    recht: "umsatz.lesen",
    abPhase: 2,
  },
  {
    pfad: "/nachkalkulation",
    beschriftung: "Nachkalkulation",
    recht: "nachkalkulation.lesen",
    abPhase: 4,
  },
  {
    pfad: "/cockpit",
    beschriftung: "Firmen-Cockpit",
    recht: "cockpit.lesen",
    abPhase: 5,
  },
  {
    pfad: "/service",
    beschriftung: "Service & Anlagen",
    recht: "anlagen.lesen",
    abPhase: 6,
  },
  {
    pfad: "/planung",
    beschriftung: "Kapazität & Pipeline",
    // Das breitere der beiden Rechte: der Pipeline-Reiter braucht zusätzlich angebote.lesen
    // und erscheint ohne es gar nicht.
    recht: "kapazitaet.lesen",
    abPhase: 7,
  },
  {
    pfad: "/unterlagen",
    beschriftung: "Unterlagen",
    // Der Ordnerbefund ist Projektsicht, kein Betrag (PLAN §4) – deshalb sieht ihn auch das
    // Team, das die Protokolle ablegt. Nur der Scan von Hand braucht importe.ausfuehren.
    recht: "projekte.lesen",
    abPhase: 7,
  },
  {
    pfad: "/importe",
    beschriftung: "Importe & Daten",
    recht: "importe.ausfuehren",
    abPhase: 1,
  },
  // Nutzerverwaltung in der Oberfläche kommt später; in Phase 1 legt die Kommandozeile
  // die Konten an (RUNBOOK, Schritt 8a).
  {
    pfad: "/administration",
    beschriftung: "Administration",
    recht: "admin.nutzer",
    abPhase: 7,
  },
];

type Props = {
  children: ReactNode;
};

export function AppShell({ children }: Props) {
  const { nutzer, darf, abmelden } = useSitzung();

  const sichtbar = MENUE.filter((punkt) => !punkt.recht || darf(punkt.recht));

  return (
    <div className="huelle">
      <aside className="sidebar">
        <div className="sidebar__marke">
          <img src={wortmarke} alt="ip³ Energietechnik GmbH" />
        </div>

        <nav className="sidebar__menue" aria-label="Hauptmenü">
          {sichtbar.map((punkt) => {
            const kommtNoch =
              punkt.abPhase !== undefined && punkt.abPhase > AKTUELLE_PHASE;
            if (kommtNoch) {
              return (
                <span
                  key={punkt.pfad}
                  className="sidebar__punkt sidebar__punkt--spaeter"
                  title={`Kommt mit Phase ${punkt.abPhase}`}
                >
                  {punkt.beschriftung}
                </span>
              );
            }
            return (
              <NavLink
                key={punkt.pfad}
                to={punkt.pfad}
                end={punkt.pfad === "/"}
                className={({ isActive }) =>
                  isActive
                    ? "sidebar__punkt sidebar__punkt--aktiv"
                    : "sidebar__punkt"
                }
              >
                {punkt.beschriftung}
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar__fuss">
          <div className="sidebar__nutzer">{nutzer?.name}</div>
          <div className="sidebar__rolle">{nutzer?.rollen.join(", ")}</div>
          <button
            type="button"
            className="sidebar__abmelden"
            onClick={() => void abmelden()}
          >
            Abmelden
          </button>
        </div>
      </aside>

      <div className="inhalt">
        <header className="topbar">
          {/* Die übergreifende Suche aus dem Mockup (Strg K) kommt später. Projekte und
              Kunden haben je eine eigene Suche in ihrer Liste; eine zweite, die überall
              gleichzeitig sucht, gehört in die Phase, in der es mehr zu finden gibt als
              Projekte und Kunden. Siehe design/UMSETZUNG.md. */}
          <div
            className="topbar__suche"
            title="Übergreifende Suche kommt mit Phase 3"
          >
            <span>Suchen …</span>
            <kbd>Strg K</kbd>
          </div>
        </header>
        <main className="inhalt__flaeche">{children}</main>
      </div>
    </div>
  );
}
