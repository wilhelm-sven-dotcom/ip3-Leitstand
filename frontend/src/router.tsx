/**
 * Routen der Oberfläche.
 *
 * `GeschuetzteRoute` führt zur Anmeldung, wenn keine Sitzung besteht, und zur
 * Passwortmaske, wenn ein Wechsel aussteht. Das ist Bequemlichkeit, keine Sperre: wer die
 * Adresse einer Seite kennt, kommt hier vorbei – die API dahinter lässt ihn trotzdem nicht
 * an die Daten (PLAN §14).
 */

import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { AppShell } from "@/komponenten/AppShell";
import { Anmelden } from "@/seiten/Anmelden";
import { Start } from "@/seiten/Start";
import { PasswortAendern } from "@/seiten/PasswortAendern";
import { NichtGefunden } from "@/seiten/Fehlerseite";
import { KomponentenGalerie } from "@/seiten/KomponentenGalerie";
import { Importe } from "@/seiten/importe/Importe";
import { MigrationZuordnung } from "@/seiten/migration/Zuordnung";
import { Kunden } from "@/seiten/stammdaten/Kunden";
import { Projekte } from "@/seiten/projekte/Projekte";
import { ProjektDetail } from "@/seiten/projekte/ProjektDetail";
import { ProjektNeu } from "@/seiten/projekte/ProjektNeu";
import { Projektleiter } from "@/seiten/projekte/Projektleiter";
import { Rechnungen } from "@/seiten/rechnungen/Rechnungen";
import { RechnungDetail } from "@/seiten/rechnungen/RechnungDetail";
import { Cockpit } from "@/seiten/cockpit/Cockpit";
import { Nachkalkulation } from "@/seiten/nachkalkulation/Nachkalkulation";
import { Umsatz } from "@/seiten/umsatz/Umsatz";
import { Anlagen } from "@/seiten/service/Anlagen";
import { Planung } from "@/seiten/planung/Planung";
import { Unterlagen } from "@/seiten/unterlagen/Unterlagen";
import { useSitzung } from "@/sitzung/SitzungKontext";

function Ladeflaeche() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--text-sekundaer)",
        fontSize: 13,
      }}
    >
      wird geladen …
    </div>
  );
}

function GeschuetzteRoute({ children }: { children: ReactNode }) {
  const { nutzer, laedt } = useSitzung();
  const ort = useLocation();

  // Solange nicht bekannt ist, ob eine Sitzung besteht, keine Entscheidung treffen –
  // sonst blitzt die Anmeldeseite bei jedem Neuladen kurz auf.
  if (laedt) return <Ladeflaeche />;

  if (!nutzer) {
    return <Navigate to="/anmelden" replace state={{ von: ort.pathname }} />;
  }

  if (nutzer.muss_passwort_wechseln && ort.pathname !== "/passwort") {
    return <Navigate to="/passwort" replace />;
  }

  return <AppShell>{children}</AppShell>;
}

export function AppRouten() {
  const { nutzer, laedt } = useSitzung();

  return (
    <Routes>
      <Route
        path="/anmelden"
        element={
          laedt ? (
            <Ladeflaeche />
          ) : nutzer ? (
            <Navigate to="/" replace />
          ) : (
            <Anmelden />
          )
        }
      />

      <Route
        path="/"
        element={
          <GeschuetzteRoute>
            <Start />
          </GeschuetzteRoute>
        }
      />

      {/* Reihenfolge egal: React Router bewertet feste Pfadteile höher als `:projektNr`,
          „/projekte/neu" landet also nicht im Detail. */}
      <Route
        path="/projekte"
        element={
          <GeschuetzteRoute>
            <Projekte />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/projekte/neu"
        element={
          <GeschuetzteRoute>
            <ProjektNeu />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/projekte/projektleiter"
        element={
          <GeschuetzteRoute>
            <Projektleiter />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/projekte/:projektNr"
        element={
          <GeschuetzteRoute>
            <ProjektDetail />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/fakturierung"
        element={
          <GeschuetzteRoute>
            <Rechnungen />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/fakturierung/:belegId"
        element={
          <GeschuetzteRoute>
            <RechnungDetail />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/nachkalkulation"
        element={
          <GeschuetzteRoute>
            <Nachkalkulation />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/cockpit"
        element={
          <GeschuetzteRoute>
            <Cockpit />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/umsatz"
        element={
          <GeschuetzteRoute>
            <Umsatz />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/service"
        element={
          <GeschuetzteRoute>
            <Anlagen />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/planung"
        element={
          <GeschuetzteRoute>
            <Planung />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/unterlagen"
        element={
          <GeschuetzteRoute>
            <Unterlagen />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/importe"
        element={
          <GeschuetzteRoute>
            <Importe />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/importe/migration"
        element={
          <GeschuetzteRoute>
            <MigrationZuordnung />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/stammdaten"
        element={
          <GeschuetzteRoute>
            <Kunden />
          </GeschuetzteRoute>
        }
      />

      <Route
        path="/passwort"
        element={
          <GeschuetzteRoute>
            <PasswortAendern />
          </GeschuetzteRoute>
        }
      />

      {/* Die Galerie gibt es nur im Entwicklungsmodus – sie zeigt erfundene Daten und
          gehört nicht in den Betrieb. */}
      {import.meta.env.DEV ? (
        <Route
          path="/entwurf/komponenten"
          element={
            <GeschuetzteRoute>
              <KomponentenGalerie />
            </GeschuetzteRoute>
          }
        />
      ) : null}

      <Route
        path="*"
        element={
          <GeschuetzteRoute>
            <NichtGefunden />
          </GeschuetzteRoute>
        }
      />
    </Routes>
  );
}
