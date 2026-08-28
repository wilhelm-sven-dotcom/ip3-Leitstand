"""Wiederkehrende Importe: DATEV, TimeTac und Kalkulationsblätter (PLAN §8, Phase 4).

Abgegrenzt von ``app/migration/``: dort steht die **einmalige** Übernahme der beiden
Excel-Bestandsdateien, die genau einmal läuft und danach nie wieder. Hier stehen die Importe,
die monatlich bzw. nächtlich laufen. Beide teilen sich die Bausteine in :mod:`.befunde` und
:mod:`.werte`.

Die Regel, die alle drei Importe verbindet (PLAN §8): **jeder Lauf ersetzt seinen Zeitraum,
statt anzuhängen.** Ein Monat wird nachgeliefert und korrigiert, ohne dass Beträge sich
verdoppeln – deshalb steht vor jedem Einfügen ein Löschen des Zeitraums, in derselben
Schreibtransaktion.
"""

from app.importe.befunde import Befund

__all__ = ["Befund"]
