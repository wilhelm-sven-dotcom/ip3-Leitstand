/**
 * Startseite (design/Start.dc.html).
 *
 * Die Startseite ist der Arbeitsvorrat: was heute zu tun ist. Die Vorgänge selbst entstehen ab
 * Phase 3 – ein Rechnungsvorschlag braucht einen Zahlungsplan **und** eine Fakturierung.
 * Statt einer leeren Fläche stehen hier Leerzustände, die den nächsten Schritt benennen, und
 * der **Datenstand**: wann die Sicherung zuletzt lief und wann Daten zuletzt eingelesen wurden.
 *
 * Der Datenstand ist der Grund, warum diese Seite in Phase 0 überhaupt etwas zeigt: PLAN §2
 * verlangt, dass ein ausgefallener nächtlicher Lauf auffällt. Ein Werkzeug, das seine eigenen
 * Störungen verschweigt, ist im Ernstfall wertlos.
 */

import { useQuery } from "@tanstack/react-query";
import { PageTitle } from "@/komponenten/PageTitle";
import { EmptyState } from "@/komponenten/EmptyState";
import { Datenstand } from "@/seiten/Datenstand";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { api } from "@/api/client";
import { begruessung, vorname, wochentagDatum } from "@/format/formate";

export function Start() {
  const { nutzer, darf } = useSitzung();

  const status = useQuery({
    queryKey: ["systemstatus"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/systemstatus");
      if (error) throw error;
      return data;
    },
    enabled: darf("systemstatus.lesen"),
    // Der Datenstand ändert sich nachts, nicht im Minutentakt.
    staleTime: 5 * 60 * 1000,
  });

  const heute = new Date();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--abstand-6)",
      }}
    >
      <div>
        <div className="seitentitel__meta" style={{ marginBottom: 6 }}>
          {wochentagDatum(heute)}
        </div>
        <PageTitle
          meta={nutzer ? begruessung(vorname(nutzer.name), heute) : undefined}
        >
          Start
        </PageTitle>
      </div>

      <section>
        <h2
          className="karte__titel"
          style={{ marginBottom: "var(--abstand-3)" }}
        >
          Heute wichtig
        </h2>
        {/* Der Text darf keinen Schritt nennen, der schon getan sein kann: nach der Übernahme
            der Bestandsdaten stünde hier sonst eine Aufforderung zu etwas Erledigtem. Was hier
            erscheinen wird, hängt an den Phasen 2 und 3 – bis dahin führen die Menüpunkte zu
            den Daten. */}
        <EmptyState
          titel="Noch keine Vorgänge."
          text={
            "Rechnungsvorschläge, Fristen und überfällige Beträge erscheinen hier ab Phase 3, " +
            "sobald ein Projekt einen Auslöser des Zahlungsplans erreicht. Projekte und " +
            "Stammdaten sind über das Menü erreichbar."
          }
        />
      </section>

      {darf("systemstatus.lesen") ? (
        <Datenstand
          status={status.data ?? null}
          laedt={status.isLoading}
          fehler={status.isError}
          darfStarten={darf("admin.jobs")}
          neuLaden={() => void status.refetch()}
        />
      ) : null}
    </div>
  );
}
