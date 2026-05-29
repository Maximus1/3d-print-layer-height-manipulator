#!/usr/bin/env python3
"""
Extrusion Scaling Processor – Phase 13.7
==========================================
Isolierte mathematische Skalierung von E-Werten.

Laut PIPELINE_SPEC.md Phase 13.7:
- E-Werte mathematisch skalieren (M82/M83 korrekt)
- Keine Änderung an X/Y/Z
- Keine Änderung an G2/G3 I/J

MODI:
- M83 (relativ): E-Wert direkt skalieren (E_delta * scale_factor)
- M82 (absolut): Delta berechnen, skalieren, neues absolutes E

REGELN:
- Nur Zeilen mit E-Parameter werden transformiert
- X/Y/Z bleiben unverändert
- I/J bleiben unverändert
- Feedrate bleibt unverändert
- Kommentare bleiben unverändert
- G0 wird nicht transformiert (kein E)
"""

import re
import sys
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeEvent
from logging_system import get_logger, close_all


# =============================================================================
# KONFIGURATION
# =============================================================================

class ExtrusionScalingConfig:
    """Konfiguration für Extrusion Scaling."""

    __slots__ = ('scale_factor', 'enabled')

    def __init__(self):
        self.scale_factor: float = 1.0  # Skalierungsfaktor (0.0 – ∞)
        self.enabled: bool = True


# =============================================================================
# EXTRUSION SCALING PROZESSOR
# =============================================================================

class ExtrusionScalingProcessor:
    """
    Skaliert E-Werte mathematisch korrekt.

    - M83 (relativ): E_delta * scale_factor
    - M82 (absolut): Delta berechnen, skalieren, neues absolutes E
    """

    def __init__(self, config: Optional[ExtrusionScalingConfig] = None):
        self.config = config or ExtrusionScalingConfig()
        self.log = get_logger('extrusion_scaling')
        self._current_e: float = 0.0  # Nur für absoluten Modus
        self._stats = {
            'total_events': 0,
            'scaled': 0,
            'skipped': 0,
        }

    def set_current_e(self, e_value: float):
        """Setzt den aktuellen E-Wert (für absoluten Modus)."""
        self._current_e = e_value

    def process_event(self, event: GCodeEvent,
                      relative_e: bool = True) -> str:
        """
        Verarbeitet ein einzelnes Event.

        Args:
            event: GCodeEvent aus dem Parser
            relative_e: True wenn M83 (relativ), False wenn M82 (absolut)

        Returns:
            Transformierte GCode-Zeile (oder Original)
        """
        self._stats['total_events'] += 1

        # Nicht transformieren wenn deaktiviert
        if not self.config.enabled:
            return event.raw

        # Nur Zeilen mit E-Parameter transformieren
        if not event.has_e:
            self._stats['skipped'] += 1
            return event.raw

        # E-Wert transformieren
        if relative_e:
            new_line = self._scale_relative(event)
        else:
            new_line = self._scale_absolute(event)

        self._stats['scaled'] += 1

        return new_line

    def _scale_relative(self, event: GCodeEvent) -> str:
        """
        Skaliert E-Wert im relativen Modus (M83).
        E_delta * scale_factor
        """
        raw = event.raw.rstrip('\n\r')
        code_part = raw.split(';')[0].strip()
        comment = ''
        if ';' in raw:
            comment = ';' + raw.split(';', 1)[1]

        # E-Wert im Code-Teil ersetzen
        e_value = event.params['E']
        new_e = e_value * self.config.scale_factor
        new_code = self._replace_e_in_code(code_part, new_e)

        self.log.info('extrusion_scaled_relative',
                      line_number=event.line_idx,
                      command=event.command,
                      decision='scaled',
                      reason=f'E {e_value} → {new_e} '
                             f'(factor={self.config.scale_factor})',
                      geometry={
                          'original_e': e_value,
                          'scaled_e': new_e,
                          'scale_factor': self.config.scale_factor,
                      })

        return new_code + comment

    def _scale_absolute(self, event: GCodeEvent) -> str:
        """
        Skaliert E-Wert im absoluten Modus (M82).
        Delta = E_neu - E_aktuell
        Skalierter Delta = Delta * scale_factor
        Neues absolutes E = E_aktuell + skalierter Delta
        """
        raw = event.raw.rstrip('\n\r')
        code_part = raw.split(';')[0].strip()
        comment = ''
        if ';' in raw:
            comment = ';' + raw.split(';', 1)[1]

        # Delta berechnen
        e_neu = event.params['E']
        delta = e_neu - self._current_e
        scaled_delta = delta * self.config.scale_factor
        new_absolute_e = self._current_e + scaled_delta

        # Aktuellen E-Wert aktualisieren
        self._current_e = new_absolute_e

        # E-Wert im Code-Teil ersetzen
        new_code = self._replace_e_in_code(code_part, new_absolute_e)

        self.log.info('extrusion_scaled_absolute',
                      line_number=event.line_idx,
                      command=event.command,
                      decision='scaled',
                      reason=f'E {e_neu} → {new_absolute_e} '
                             f'(delta={delta}, '
                             f'scaled_delta={scaled_delta})',
                      geometry={
                          'original_e': e_neu,
                          'new_absolute_e': new_absolute_e,
                          'delta': delta,
                          'scaled_delta': scaled_delta,
                          'scale_factor': self.config.scale_factor,
                      })

        return new_code + comment

    def _replace_e_in_code(self, code: str, new_e: float) -> str:
        """Ersetzt den E-Wert im Code-Teil."""
        fmt = self._fmt_e(new_e)
        # Pattern: E gefolgt von Zahl (auch negativ, scientific)
        pattern = r'(?<![A-Za-z0-9.])E[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?'
        if re.search(pattern, code, re.I):
            return re.sub(pattern, f'E{fmt}', code, flags=re.I)
        return code

    def _fmt_e(self, value: float) -> str:
        """
        Formatiert einen E-Wert für GCode.
        Behält bis zu 5 Nachkommastellen, entfernt trailing zeros.
        """
        if abs(value) < 1e-10:
            return '0'
        formatted = f'{value:.5f}'.rstrip('0').rstrip('.')
        return formatted

    def get_stats(self) -> Dict[str, Any]:
        """Gibt Statistiken zurück."""
        return dict(self._stats)


# =============================================================================
# MAIN (TEST)
# =============================================================================

def main():
    """Testet den Extrusion Scaling Processor."""
    from gcode_parser import GCodeParser

    parser = GCodeParser()
    events = parser.parse_file('fixtures/minimal_test.gcode')

    config = ExtrusionScalingConfig()
    config.scale_factor = 0.5

    processor = ExtrusionScalingProcessor(config)

    relative_e = True
    for event in events:
        # M82/M83 tracken
        if event.command == 'M82':
            relative_e = False
        elif event.command == 'M83':
            relative_e = True

        if event.has_e:
            result = processor.process_event(event, relative_e)
            if result != event.raw:
                print(f"  Line {event.line_idx}: SCALED")
                print(f"    Original: {event.raw.rstrip()}")
                print(f"    Skaliert: {result}")

    print(f"\nStats: {processor.get_stats()}")
    close_all()


if __name__ == '__main__':
    main()