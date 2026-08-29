/**
 * Fristen auf der Startseite (PLAN §7 Phase 6).
 *
 * Das Widget zeigt, was überfällig ist oder im eigenen Vorlauf liegt – nicht alle Fristen.
 * Eine Liste, in der neben zwei dringenden Sachen dreißig ferne stehen, wird nicht gelesen.
 *
 * **Kein Mailversand** (Entscheidung 34): PLAN §12 und CLAUDE.md schließen ihn aus. Diese
 * Fläche ist die Erinnerung – deshalb muss sie stimmen und darf nicht überladen sein.
 *
 * Abhaken geht direkt hier: wer die Frist sieht und erledigt hat, soll nicht erst eine Seite
 * weiter klicken müssen. Die Berechtigung dafür ist `anlagen.schreiben`; ohne sie bleibt die
 * Liste lesbar, aber unveränderlich.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { EmptyState } from "@/komponenten/EmptyState";
import { Knopf } from "@/komponenten/Knopf";
import { StatusBadge } from "@/komponenten/StatusBadge";
import { api } from "@/api/client";
import { datum } from "@/format/formate";
import { useSitzung } from "@/sitzung/SitzungKontext";
import {
  frist as fristText,
  fristBadge,
  fristTyp,
  fristenZusatz,
} from "./begriffe";
import "./service.css";

/** Höchstens so viele Zeilen: darüber ist es kein Widget mehr, sondern eine Liste. */
const GRENZE = 6;

export function FristenWidget() {
  const { darf } = useSitzung();
  const abfragen = useQueryClient();
  const darfSchreiben = darf("anlagen.schreiben");

  const fristen = useQuery({
    queryKey: ["fristen", "widget"],
    enabled: darf("anlagen.lesen"),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/fristen", {
        params: { query: { nur_anstehende: true, grenze: GRENZE } },
      });
      if (error) throw error;
      return data;
    },
    // Fristen ändern sich tageweise, nicht im Minutentakt.
    staleTime: 5 * 60 * 1000,
  });

  const erledigen = useMutation({
    mutationFn: async (fristId: number) => {
      const { error } = await api.POST("/api/fristen/{frist_id}/erledigt", {
        params: { path: { frist_id: fristId }, query: { erledigt: true } },
      });
      if (error) throw error;
    },
    onSuccess: () => void abfragen.invalidateQueries({ queryKey: ["fristen"] }),
  });

  if (!darf("anlagen.lesen")) return null;

  const zeilen = fristen.data?.fristen ?? [];
  const zusatz = fristenZusatz(fristen.data?.zaehlung ?? {});
  const gesamt =
    (fristen.data?.zaehlung?.ueberfaellig ?? 0) +
    (fristen.data?.zaehlung?.faellig ?? 0);

  return (
    <section>
      <div className="fristen__kopf">
        <h2 className="karte__titel">Fristen</h2>
        {zusatz ? <span className="fristen__zusatz">{zusatz}</span> : null}
      </div>

      {fristen.isError ? (
        <EmptyState
          ohneZeichen
          titel="Die Fristen ließen sich nicht laden."
          text="Nächster Schritt: die Seite neu laden. Bleibt es dabei, im Systemstatus nachsehen."
        />
      ) : zeilen.length === 0 ? (
        <EmptyState
          ohneZeichen
          titel="Keine Frist steht an."
          text={
            "Hier erscheinen Gewährleistungen, MaStR-Registrierungen, Fertigmeldungen und " +
            "Reservierungen, sobald sie in ihren Vorlauf kommen."
          }
        />
      ) : (
        <ul className="fristen">
          {zeilen.map((f) => (
            <li key={f.id} className="fristen__zeile">
              <div className="fristen__marke">
                <StatusBadge
                  zustand={fristBadge(f.status)}
                  text={fristText(f.tage_bis)}
                  titel={`fällig am ${datum(f.faellig_am)}`}
                />
              </div>
              <div className="fristen__text">
                <div className="fristen__titel">
                  {fristTyp(f.typ)} · {f.betreff}
                </div>
                <div className="fristen__meta">
                  {f.kunde ? `${f.kunde} · ` : ""}
                  {f.bezeichnung}
                </div>
              </div>
              {darfSchreiben ? (
                <Knopf
                  klein
                  art="sekundaer"
                  onClick={() => erledigen.mutate(f.id)}
                  disabled={erledigen.isPending}
                >
                  Erledigt
                </Knopf>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {gesamt > zeilen.length ? (
        <div className="fristen__mehr">
          <Link to="/service">
            Alle {gesamt} anstehenden Fristen im Anlagenregister
          </Link>
        </div>
      ) : null}
    </section>
  );
}
