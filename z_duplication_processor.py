#!/usr/bin/env python3
"""
Z-Duplication Processor – Phase 13.6
======================================
Dupliziert Extrusionsbewegungen mit erhöhtem Z-Wert.

Laut PIPELINE_SPEC.md Phase 13.6:
- Z-Wert einer Bewegung erhöhen und Bewegung duplizieren
- Beispiel: G1 X10 Y10 Z0.2 E0.4 → G1 X10 Y10 Z0.2 E0.4 + G1 X10 Y10 Z0.25
- Keine E-Änderung im duplizierten Move

REGELN:
- Nur Extrusionsbewegungen (G1 mit E > 0) werden dupliziert
- Nur konfigurierte Typen (target_types) werden dupliziert
- Travel, Kommentare, andere Befehle bleiben unverändert
- Das Duplikat enthält X/Y des Originals, neues Z, FEEDRATE, aber KEIN E
"""

import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeEvent
from logging_system import get_logger, close_all


# =============================================================================
# KONFIGURATION
# =============================================================================

class ZDuplicationConfig:
    """
    Konfiguration für Z-Duplication.
    """

    __slots__ = ('z_offset', 'target_types', 'enabled')

    def __init__(self):
        self.z_offset: float = 0.05       # mm – Z-Offset für Duplikat
        self.target_types: List[str] = ['WALL-OUTER']
        self.enabled: bool = True


# =============================================================================
# Z-DUPLICATION PROZESSOR
# =============================================================================

class ZDuplicationProcessor:
    """
    Verarbeitet GCodeEvents und dupliziert Extrusionsbewegungen
    mit erhöhtem Z-Wert.

    Jedes Event liefert eine Liste von GCode-Zeilen:
    - 1 Zeile = unverändert (Original)
    - 2 Zeilen = Original + Duplikat (nur beiqualifizierten Extrusionen)
    """

    def __init__(self, config: Optional[ZDuplicationConfig] = None):
        self.config = config or ZDuplicationConfig()
        self.log = get_logger('z_duplication')
        self._stats = {
            'total_events': 0,
            'duplications': 0,
            'skipped': 0,
        }

    def process_event(self, event: GCodeEvent,
                      type_tag: str = '') -> List[str]:
        """
        Verarbeitet ein einzelnes Event.

        Args:
            event: GCodeEvent aus dem Parser
            type_tag: Aktueller Type-Tag (z.B. 'WALL-OUTER')

        Returns:
            Liste von GCode-Zeilen (1 = Original, 2 = Original + Duplikat)
        """
        self._stats['total_events'] += 1

        # Nicht duplizieren wenn deaktiviert
        if not self.config.enabled:
            return [event.raw]

        # Nur qualifizierte Extrusionsbewegungen duplizieren
        if not self._should_duplicate(event, type_tag):
            self._stats['skipped'] += 1
            return [event.raw]

        # Duplikat erzeugen
        dup_line = self._create_duplication(event)

        self._stats['duplications'] += 1

        self.log.info('z_duplication',
                      line_number=event.line_idx,
                      command=event.command,
                      decision='duplicated',
                      reason=f'Z {event.params.get("Z", "?")} → '
                             f'{event.params.get("Z", 0) + self.config.z_offset}',
                      geometry={
                          'original': event.raw.rstrip(),
                          'duplicate': dup_line,
                      })

        return [event.raw, dup_line]

    def _should_duplicate(self, event: GCodeEvent,
                          type_tag: str) -> bool:
        """
        Prüft ob ein Event dupliziert werden soll.

        Kriterien:
        1. Kommando ist G1 (G0 wird nicht dupliziert)
        2. Event hat E-Parameter (Extrusion, kein Travel)
        3. Type-Tag ist in target_types
        """
        # Nur G1 (kein G0, G2, G3)
        if event.command != 'G1':
            return False

        # Extrusion vorhanden?
        if not event.has_e:
            return False

        # Type-Tag in Zielliste?
        if type_tag not in self.config.target_types:
            return False

        return True

    def _create_duplication(self, event: GCodeEvent) -> str:
        """
        Erzeugt die Duplikat-Zeile.

        Regeln:
        - Gleicher Befehl (G1)
        - Gleiche X/Y-Werte
        - Neuer Z-Wert (Original + offset)
        - Gleiche Feedrate (falls vorhanden)
        - KEIN E-Parameter
        - Originaler Kommentar wird NICHT übernommen
        """
        raw = event.raw.rstrip('\n\r')

        # Code-Teil von Kommentar trennen
        code_part = raw.split(';')[0].strip()

        # Parameter aus dem Code-Teil extrahieren und neu aufbauen
        parts = ['G1']

        # X beibehalten
        if 'X' in event.params:
            parts.append(f'X{self._fmt(event.params["X"])}')

        # Y beibehalten
        if 'Y' in event.params:
            parts.append(f'Y{self._fmt(event.params["Y"])}')

        # Z erhöhen
        if 'Z' in event.params:
            new_z = event.params['Z'] + self.config.z_offset
            parts.append(f'Z{self._fmt(new_z)}')

        # F beibehalten
        if 'F' in event.params:
            parts.append(f'F{self._fmt(event.params["F"])}')

        # KEIN E im Duplikat!

        return ' '.join(parts)

    def _fmt(self, value: float) -> str:
        """
        Formatiert einen Float-Wert für GCode.
        Entfernt überflüssige Nullen, behält aber mindestens 1 Nachkommastelle.
        """
        # Bei ganzen Zahlen (z.B. F1200) keine Nachkommastelle
        if value == int(value) and value < 10000:
            return str(int(value))
        # Sonst: bis zu 5 Nachkommastellen, trailing zeros entfernen
        formatted = f'{value:.5f}'.rstrip('0').rstrip('.')
        return formatted

    def get_stats(self) -> Dict[str, Any]:
        """Gibt Statistiken zurück."""
        return dict(self._stats)


# =============================================================================
# MAIN (TEST)
# =============================================================================

def main():
    """Testet den Z-Duplication Processor."""
    from gcode_parser import GCodeParser

    parser = GCodeParser()
    events = parser.parse_file('fixtures/minimal_test.gcode')

    config = ZDuplicationConfig()
    config.z_offset = 0.05
    config.target_types = ['WALL-OUTER']

    processor = ZDuplicationProcessor(config)

    current_type = ''
    for event in events:
        if event.type_tag:
            current_type = event.type_tag

        result = processor.process_event(event, current_type)
        if len(result) > 1:
            print(f"  Line {event.line_idx}: DUPLICATED")
            print(f"    Original:  {result[0].rstrip()}")
            print(f"    Duplicate: {result[1]}")

    print(f"\nStats: {processor.get_stats()}")
    close_all()


if __name__ == '__main__':
    main()