/**
 * Statusbadge für Projekte (design/Projektliste.dc.html).
 *
 * Warum nicht `StatusBadge`: dessen acht Zustände beschreiben **Belege** (Entwurf, Gestellt,
 * Bezahlt …) und sind laut design/README.md fest. Ein Projekt hat einen anderen Lebenslauf –
 * Angebot, Beauftragt, In Bau, Abgeschlossen, Storniert – und das Mockup zeichnet ihn mit
 * eigenen Farben. Zwei getrennte Sätze sind hier richtiger als ein aufgeweichter: „Gestellt"
 * an einem Projekt wäre eine Aussage über eine Rechnung, die es nicht gibt.
 *
 * Die Formsprache bleibt dieselbe: Versalien 10,5 px/600, Radius 4, kein Grün.
 */

import { STATUS_TEXT, type ProjektStatus } from "@/seiten/projekte/begriffe";

type Props = {
  status: string;
  titel?: string;
};

export function ProjektStatusBadge({ status, titel }: Props) {
  const text = STATUS_TEXT[status as ProjektStatus];
  if (!text) {
    if (import.meta.env.DEV) {
      throw new Error(
        `Unbekannter Projektstatus: ${status}. Erlaubt sind: ${Object.keys(STATUS_TEXT).join(", ")}.`,
      );
    }
    return null;
  }
  return (
    <span
      className={`badge badge--projekt-${status.replace("_", "-")}`}
      title={titel}
    >
      {text}
    </span>
  );
}
