/**
 * Die Marge gegen die Sollmarge, als Zustand statt als Zahl (PLAN §7 Phase 4, §11).
 *
 * **Kein Grün.** Das Corporate Design verbietet Ampelgrün ausdrücklich; die drei Zustände
 * erscheinen deshalb in den Markenfarben – ip³ Blau für „im Soll", Akzent-Rot als Kontur für
 * „knapp", Akzent-Rot gefüllt für „unter Soll". Ohne Sollmarge bleibt es grau.
 *
 * Kein `StatusBadge`: dessen acht Zustände sind absichtlich abgeschlossen (design/README.md),
 * und „im Soll" ist kein Belegzustand. Die Form ist dieselbe, damit die Seite ruhig bleibt.
 */

import { AMPEL_TEXT, ampelTitel, type Ampel } from "./begriffe";

type Props = {
  ampel: Ampel;
  margeSollPromille?: number | null;
  abweichungPromille?: number | null;
};

export function MargenAmpel({
  ampel,
  margeSollPromille,
  abweichungPromille,
}: Props) {
  return (
    <span
      className={`margen-ampel margen-ampel--${ampel}`}
      title={ampelTitel(ampel, margeSollPromille, abweichungPromille)}
    >
      {AMPEL_TEXT[ampel]}
    </span>
  );
}
