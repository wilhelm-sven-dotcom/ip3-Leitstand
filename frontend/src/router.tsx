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
import { MigrationZuordnung } from "@/seiten/migration/Zuordnung";
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

      <Route
        path="/importe/migration"
        element={
          <GeschuetzteRoute>
            <MigrationZuordnung />
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
