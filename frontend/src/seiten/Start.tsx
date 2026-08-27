/**
 * Startseite (design/Start.dc.html).
 *
 * Die Startseite ist der Arbeitsvorrat: was heute zu tun ist. Seit Phase 3 stehen dort die
 * **Abschlagsvorschläge** (PLAN §6.8): eine Zahlungsplanposition mit gesetztem Auslöser, deren
 * Meilenstein erledigt ist. Nur Vorschlag – der Beleg entsteht erst auf Knopfdruck, und auch dann
 * als Entwurf. Ein Automatikversand ist ausdrücklich nicht vorgesehen.
 *
 * Dazu der **Datenstand**: wann die Sicherung zuletzt lief und wann Daten zuletzt eingelesen
 * wurden.
 *
 * Der Datenstand ist der Grund, warum diese Seite in Phase 0 überhaupt etwas zeigt: PLAN §2
 * verlangt, dass ein ausgefallener nächtlicher Lauf auffällt. Ein Werkzeug, das seine eigenen
 * Störungen verschweigt, ist im Ernstfall wertlos.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ActionCard } from "@/komponenten/ActionCard";
import { PageTitle } from "@/komponenten/PageTitle";
import { EmptyState } from "@/komponenten/EmptyState";
import { Knopf } from "@/komponenten/Knopf";
import { Meldung } from "@/komponenten/Meldung";
import { Datenstand } from "@/seiten/Datenstand";
import { meilensteinText } from "@/seiten/projekte/begriffe";
import { useSitzung } from "@/sitzung/SitzungKontext";
import { api, fehlerAuslesen } from "@/api/client";
import type { ApiFehler } from "@/api/client";
import {
  begruessung,
  datum as datumText,
  euro,
  vorname,
  wochentagDatum,
} from "@/format/formate";
import { useState } from "react";

export function Start() {
  const { nutzer, darf } = useSitzung();
  const navigate = useNavigate();
  const abfragen = useQueryClient();
  const [fehler, setFehler] = useState<ApiFehler | null>(null);

  const vorschlaege = useQuery({
    queryKey: ["rechnungsvorschlaege"],
    enabled: darf("rechnungen.lesen"),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/rechnungen/vorschlaege");
      if (error) throw error;
      return data;
    },
  });

  const abschlagStellen = useMutation({
    mutationFn: async (positionId: number) => {
      setFehler(null);
      const { data, error } = await api.POST(
        "/api/rechnungen/aus-zahlungsplan/{position_id}",
        { params: { path: { position_id: positionId } }, body: {} },
      );
      if (error) throw error;
      return data as { id: number };
    },
    onSuccess: (beleg) => {
      void abfragen.invalidateQueries({ queryKey: ["rechnungsvorschlaege"] });
      navigate(`/fakturierung/${beleg.id}`);
    },
    onError: (f) => setFehler(fehlerAuslesen(f)),
  });

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
        {fehler ? (
          <Meldung
            art="fehler"
            text={fehler.meldung}
            naechsterSchritt={fehler.naechster_schritt}
          />
        ) : null}

        {(vorschlaege.data?.length ?? 0) > 0 ? (
          <div className="vorschlagsliste">
            {(vorschlaege.data ?? []).map((v) => (
              <ActionCard
                key={v.position_id}
                kicker="Rechnungsvorschlag"
                titel={`${v.projekt_nr} · ${v.bezeichnung}`}
                meta={
                  <>
                    {v.projekt_name ? `${v.projekt_name} · ` : ""}
                    Auslöser {meilensteinText(v.ausloeser)} erreicht
                    {v.erledigt_am ? ` am ${datumText(v.erledigt_am)}` : ""}
                  </>
                }
                betrag={euro(v.betrag_netto)}
                aktion={
                  darf("rechnungen.erstellen") ? (
                    <Knopf
                      klein
                      onClick={() => abschlagStellen.mutate(v.position_id)}
                      disabled={abschlagStellen.isPending}
                    >
                      Abschlag stellen
                    </Knopf>
                  ) : null
                }
              />
            ))}
          </div>
        ) : (
          /* Der Text darf keinen Schritt nennen, der schon getan sein kann. Was hier erscheint,
             hängt an den Auslösern im Zahlungsplan: ohne gesetzten Auslöser gibt es nichts
             vorzuschlagen, und das ist keine Störung. */
          <EmptyState
            titel="Noch keine Vorgänge."
            text={
              "Ein Rechnungsvorschlag erscheint, sobald eine Zahlungsplanposition einen " +
              "Auslöser trägt und der zugehörige Meilenstein erledigt ist. Fristen und " +
              "überfällige Beträge folgen mit den Phasen 4 und 6."
            }
          />
        )}
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
