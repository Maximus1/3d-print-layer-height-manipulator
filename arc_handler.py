#!/usr/bin/env python3
"""
Arc Handler – Korrekte Behandlung von G2/G3 Arcs
=================================================
G2/G3 dürfen NICHT wie lineare G1-Bewegungen behandelt werden.

Regeln:
- I/J definieren die Geometrie, NICHT den Endpunkt
- Arc-Endpunkt-Distanz ist NICHT die Arc-Länge
- I/J dürfen niemals ignoriert werden
- Arcs müssen den State dennoch korrekt aktualisieren (Position, E)

Zentrale Erkenntnis:
Der Arc-Mittelpunkt ist (start_x + I, start_y + J).
Der Radius ist sqrt(I² + J²).
Die tatsächliche Arc-Länge ist abhängig vom Winkel (Start→Mittelpunkt→Ende).
"""

import sys
import math
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeParser, GCodeEvent
from state_tracker import GCodeState


# =============================================================================
# ARC-ANALYSE
# =============================================================================

class ArcAnalysis:
    """
    Analysiert einen einzelnen Arc (G2/G3).
    - Berechnet Mittelpunkt, Radius, Winkel, Länge
    - Dokumentiert alle geometrischen Eigenschaften
    """

    __slots__ = (
        'line_idx', 'command', 'start_xy', 'end_xy',
        'i', 'j',
        'center_xy', 'radius',
        'start_angle', 'end_angle', 'sweep_angle',
        'arc_length', 'chord_length',
        'e_delta', 'type_tag',
    )

    def __init__(self, line_idx: int, command: str):
        self.line_idx = line_idx
        self.command = command  # 'G2' oder 'G3'
        self.start_xy: Tuple[float, float] = (0.0, 0.0)
        self.end_xy: Tuple[float, float] = (0.0, 0.0)
        self.i: float = 0.0
        self.j: float = 0.0
        self.center_xy: Tuple[float, float] = (0.0, 0.0)
        self.radius: float = 0.0
        self.start_angle: float = 0.0
        self.end_angle: float = 0.0
        self.sweep_angle: float = 0.0
        self.arc_length: float = 0.0
        self.chord_length: float = 0.0
        self.e_delta: float = 0.0
        self.type_tag: Optional[str] = None

    def calculate(self, start_x: float, start_y: float,
                  end_x: float, end_y: float,
                  i: float, j: float,
                  e_delta: float = 0.0,
                  type_tag: Optional[str] = None):
        """
        Berechnet alle Arc-Eigenschaften.

        Mittelpunkt: (start_x + I, start_y + J)
        Radius: sqrt(I² + J²)
        """
        self.start_xy = (start_x, start_y)
        self.end_xy = (end_x, end_y)
        self.i = i
        self.j = j
        self.e_delta = e_delta
        self.type_tag = type_tag

        # Mittelpunkt
        cx = start_x + i
        cy = start_y + j
        self.center_xy = (cx, cy)

        # Radius
        self.radius = math.sqrt(i ** 2 + j ** 2)

        # Chord (Sehnenlänge)
        dx = end_x - start_x
        dy = end_y - start_y
        self.chord_length = math.sqrt(dx ** 2 + dy ** 2)

        # Winkel
        self.start_angle = math.atan2(start_y - cy, start_x - cx)
        self.end_angle = math.atan2(end_y - cy, end_x - cx)

        # Sweep-Winkel (berücksichtigt G2=CW, G3=CCW)
        if self.command == 'G2':  # CW
            sweep = self.start_angle - self.end_angle
        else:  # G3 = CCW
            sweep = self.end_angle - self.start_angle

        # Auf [0, 2π] normalisieren
        if sweep < 0:
            sweep += 2 * math.pi

        self.sweep_angle = sweep

        # Arc-Länge = Radius * Winkel (im Bogenmaß)
        self.arc_length = self.radius * self.sweep_angle

    def to_dict(self) -> Dict[str, Any]:
        return {
            'line_idx': self.line_idx,
            'command': self.command,
            'start_xy': self.start_xy,
            'end_xy': self.end_xy,
            'center_xy': self.center_xy,
            'i': self.i,
            'j': self.j,
            'radius': round(self.radius, 4),
            'chord_length': round(self.chord_length, 4),
            'arc_length': round(self.arc_length, 4),
            'sweep_angle_deg': round(math.degrees(self.sweep_angle), 2),
            'e_delta': round(self.e_delta, 5),
            'type': self.type_tag,
        }

    def __repr__(self) -> str:
        return (
            f"Arc({self.command} L{self.line_idx}: "
            f"R={self.radius:.2f}, "
            f"arc={self.arc_length:.2f}mm, "
            f"chord={self.chord_length:.2f}mm, "
            f"sweep={math.degrees(self.sweep_angle):.1f}°, "
            f"E={self.e_delta:.5f})"
        )


# =============================================================================
# ARC HANDLER
# =============================================================================

class ArcHandler:
    """
    Analysiert und dokumentiert Arcs.
    - Berechnet geometrische Arc-Eigenschaften
    - Dokumentiert Abweichungen
    - NIEMALS korrigierend
    """

    def __init__(self, events: List[GCodeEvent]):
        self.events = events
        self.arc_analyses: List[ArcAnalysis] = []
        self._state = GCodeState()

    def analyze_all(self) -> List[ArcAnalysis]:
        """Analysiert alle Arcs in der Event-Liste."""
        self.arc_analyses = []
        self._state = GCodeState()

        for event in self.events:
            old_x, old_y = self._state.current_x, self._state.current_y
            old_e = self._state.current_e

            self._state.process_event(event)

            if event.command in ('G2', 'G3'):
                # Arc gefunden
                if 'I' in event.params and 'J' in event.params:
                    i = event.params['I']
                    j = event.params['J']
                    e_delta = self._state.get_e_delta() if event.has_e else 0.0

                    analysis = ArcAnalysis(event.line_idx, event.command)
                    analysis.calculate(
                        start_x=old_x,
                        start_y=old_y,
                        end_x=self._state.current_x,
                        end_y=self._state.current_y,
                        i=i, j=j,
                        e_delta=e_delta,
                        type_tag=self._state.current_type,
                    )
                    self.arc_analyses.append(analysis)

        return self.arc_analyses

    def get_summary(self) -> Dict[str, Any]:
        """Zusammenfassung der Arc-Analyse."""
        if not self.arc_analyses:
            return {'total': 0}

        radii = [a.radius for a in self.arc_analyses]
        arc_lengths = [a.arc_length for a in self.arc_analyses]
        chord_lengths = [a.chord_length for a in self.arc_analyses]
        sweeps = [math.degrees(a.sweep_angle) for a in self.arc_analyses]

        return {
            'total_arcs': len(self.arc_analyses),
            'g2_count': sum(1 for a in self.arc_analyses if a.command == 'G2'),
            'g3_count': sum(1 for a in self.arc_analyses if a.command == 'G3'),
            'radii': {
                'min': round(min(radii), 4),
                'max': round(max(radii), 4),
                'mean': round(sum(radii) / len(radii), 4),
            },
            'arc_lengths': {
                'min': round(min(arc_lengths), 4),
                'max': round(max(arc_lengths), 4),
                'mean': round(sum(arc_lengths) / len(arc_lengths), 4),
            },
            'chord_vs_arc_ratio': round(
                sum(chord_lengths) / sum(arc_lengths) * 100, 2
            ) if sum(arc_lengths) > 0 else 0,
            'sweep_angles_deg': {
                'min': round(min(sweeps), 2),
                'max': round(max(sweeps), 2),
                'mean': round(sum(sweeps) / len(sweeps), 2),
            },
        }


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt die Arc-Analyse auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Arc Handler – Geometrische Arc-Analyse'
    )
    parser_arg.add_argument('file', nargs='?',
                           default='fixtures/minimal_test.gcode',
                           help='GCode-Datei')
    parser_arg.add_argument('--json', '-j', action='store_true',
                           help='JSON-Ausgabe')

    args = parser_arg.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Datei nicht gefunden: {filepath}")
        sys.exit(1)

    gcode_parser = GCodeParser()
    events = gcode_parser.parse_file(str(filepath))

    handler = ArcHandler(events)
    analyses = handler.analyze_all()
    summary = handler.get_summary()

    if args.json:
        import json
        print(json.dumps({
            'summary': summary,
            'arcs': [a.to_dict() for a in analyses],
        }, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"ARC HANDLER: {filepath.name}")
        print("=" * 60)
        print(f"\n📊 ZUSAMMENFASSUNG")
        print(f"  Arcs gesamt:  {summary.get('total_arcs', 0)}")
        print(f"  G2 (CW):     {summary.get('g2_count', 0)}")
        print(f"  G3 (CCW):    {summary.get('g3_count', 0)}")

        if 'radii' in summary:
            r = summary['radii']
            print(f"\n  Radien: {r['min']} – {r['max']}mm (Ø {r['mean']}mm)")

        if 'arc_lengths' in summary:
            al = summary['arc_lengths']
            print(f"  Arc-Längen: {al['min']} – {al['max']}mm (Ø {al['mean']}mm)")

        if 'sweep_angles_deg' in summary:
            sa = summary['sweep_angles_deg']
            print(f"  Sweep-Winkel: {sa['min']}° – {sa['max']}° (Ø {sa['mean']}°)")

        if 'chord_vs_arc_ratio' in summary:
            print(f"  Chord/Arc-Verhältnis: {summary['chord_vs_arc_ratio']}%")

        if analyses:
            print(f"\n🌀 ARC-DETAILS:")
            print("-" * 60)
            for a in analyses:
                print(f"  {a}")


if __name__ == '__main__':
    main()