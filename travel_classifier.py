#!/usr/bin/env python3
"""
Travel Classifier – Zustandsbasierte Travel/Extrusion-Klassifikation
====================================================================
Klassifiziert jede Bewegung als Travel oder Extrusion basierend auf
dem vollständigen Zustandskontext.

KERNREGELN:
- Travel != "kein E"
- Extrusion != "hat E"
- relative/absolute E zwingend berücksichtigen (M82/M83)
- G92 zwingend berücksichtigen
- Retracts niemals als Extrusion behandeln
- Niemals direkt gekoppelt mit anderen Modulen
- Niemals implizite Annahmen
- Niemals zustandslos

Klassifikationskriterien für EXTRUSION:
1. Befehl in (G1, G2, G3)
2. Hat E-Parameter
3. E-Delta > 0 (unter Berücksichtigung von M82/M83/G92)
4. XY-Distanz > 0
5. Nicht retracted
6. Nicht G0 (G0 ist immer Travel)

Klassifikationskriterien für TRAVEL:
1. G0 (immer Travel, auch mit E != 0)
2. G1/G2/G3 ohne E
3. G1/G2/G3 mit E-Delta <= 0
4. Jede Bewegung während is_retracted=True
5. Jede Bewegung während awaiting_unretract=True
"""

import sys
import math
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeParser, GCodeEvent
from state_tracker import GCodeState


# =============================================================================
# KLASSIFIKATIONSERGEBNIS
# =============================================================================

class ClassificationResult:
    """
    Ergebnis einer einzelnen Bewegungsklassifikation.
    - Enthält ALLE relevanten Zustandsinformationen
    - Ermöglicht Nachvollziehbarkeit der Entscheidung
    """

    __slots__ = (
        'line_idx', 'command', 'is_extrusion', 'is_travel',
        'e_delta', 'distance', 'is_retracted',
        'relative_e_mode', 'current_type', 'reason',
        'from_xy', 'to_xy',
    )

    def __init__(self, line_idx: int, command: str):
        self.line_idx = line_idx
        self.command = command
        self.is_extrusion: bool = False
        self.is_travel: bool = True  # Default: Travel
        self.e_delta: float = 0.0
        self.distance: float = 0.0
        self.is_retracted: bool = False
        self.relative_e_mode: bool = False
        self.current_type: Optional[str] = None
        self.reason: str = ''
        self.from_xy: Tuple[float, float] = (0.0, 0.0)
        self.to_xy: Tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'line_idx': self.line_idx,
            'command': self.command,
            'is_extrusion': self.is_extrusion,
            'is_travel': self.is_travel,
            'e_delta': round(self.e_delta, 5),
            'distance': round(self.distance, 3),
            'is_retracted': self.is_retracted,
            'relative_e_mode': self.relative_e_mode,
            'type': self.current_type,
            'reason': self.reason,
            'from_xy': self.from_xy,
            'to_xy': self.to_xy,
        }

    def __repr__(self) -> str:
        label = 'EXTRUDE' if self.is_extrusion else 'TRAVEL'
        return (
            f"[{label:7s}] L{self.line_idx:4d} "
            f"{self.command:3s} "
            f"E={self.e_delta:+.5f} "
            f"dist={self.distance:6.1f}mm "
            f"{'RETR' if self.is_retracted else '    '} "
            f"| {self.reason}"
        )


# =============================================================================
# TRAVEL CLASSIFIER
# =============================================================================

class TravelClassifier:
    """
    Klassifiziert jede Bewegung als Travel oder Extrusion.
    - Vollständig zustandsbasiert
    - Berücksichtigt M82/M83, G92, G10/G11
    - Jede Entscheidung ist nachvollziehbar dokumentiert
    """

    def __init__(self, events: List[GCodeEvent]):
        self.events = events
        self.results: List[ClassificationResult] = []
        self._state = GCodeState()

        # Getrennte Listen
        self.travel_results: List[ClassificationResult] = []
        self.extrusion_results: List[ClassificationResult] = []

    def classify_all(self) -> List[ClassificationResult]:
        """
        Klassifiziert ALLE Bewegungen.
        Nutzt den State Tracker für korrekte Zustände.
        """
        self.results = []
        self.travel_results = []
        self.extrusion_results = []

        for event in self.events:
            self._state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            result = self._classify(event)
            self.results.append(result)

            if result.is_extrusion:
                self.extrusion_results.append(result)
            else:
                self.travel_results.append(result)

        return self.results

    def _classify(self, event: GCodeEvent) -> ClassificationResult:
        """
        Klassifiziert EINE Bewegung.
        Gibt immer ein ClassificationResult mit Begründung zurück.
        """
        result = ClassificationResult(event.line_idx, event.command)

        # Zustandsinformationen sammeln
        result.e_delta = self._state.get_e_delta() if event.has_e else 0.0
        result.distance = self._state.distance_to_last()
        result.is_retracted = self._state.is_retracted
        result.relative_e_mode = self._state.relative_e_mode
        result.current_type = self._state.current_type
        result.from_xy = (self._state.last_x, self._state.last_y)
        result.to_xy = (self._state.current_x, self._state.current_y)

        # ================================================================
        # KLASSIFIKATIONSLOGIK (strikt, deterministisch)
        # ================================================================

        # REGEL 1: G0 ist IMMER Travel
        if event.command == 'G0':
            result.is_travel = True
            result.is_extrusion = False
            if event.has_e and result.e_delta > 0:
                result.reason = 'G0_TRAVEL_WITH_E'
            else:
                result.reason = 'G0_TRAVEL'
            return result

        # REGEL 2: Retracted → IMMER Travel
        if self._state.is_retracted or self._state.awaiting_unretract:
            result.is_travel = True
            result.is_extrusion = False
            if event.has_e and result.e_delta > 0:
                result.reason = 'TRAVEL_WHILE_RETRACTED_WITH_E'
            else:
                result.reason = 'TRAVEL_WHILE_RETRACTED'
            return result

        # REGEL 3: Kein E-Parameter → IMMER Travel
        if not event.has_e:
            result.is_travel = True
            result.is_extrusion = False
            result.reason = 'NO_E'
            return result

        # REGEL 4: E-Delta <= 0 → IMMER Travel
        if result.e_delta <= 0:
            result.is_travel = True
            result.is_extrusion = False
            if result.e_delta < 0:
                result.reason = 'NEGATIVE_E_DELTA'
            else:
                result.reason = 'ZERO_E_DELTA'
            return result

        # REGEL 5: Keine XY-Bewegung → IMMER Travel
        if result.distance <= 0:
            result.is_travel = True
            result.is_extrusion = False
            result.reason = 'ZERO_DISTANCE'
            return result

        # REGEL 6: Alle Kriterien erfüllt → EXTRUSION
        result.is_extrusion = True
        result.is_travel = False
        result.reason = 'EXTRUSION'
        return result

    def get_statistics(self) -> Dict[str, Any]:
        """Statistiken über die Klassifikation."""
        travel_count = len(self.travel_results)
        extrusion_count = len(self.extrusion_results)

        travel_dist = sum(r.distance for r in self.travel_results)
        extrusion_dist = sum(r.distance for r in self.extrusion_results)
        total_dist = travel_dist + extrusion_dist

        reasons = defaultdict(int)
        for r in self.results:
            reasons[r.reason] += 1

        return {
            'total_classified': len(self.results),
            'travel_count': travel_count,
            'extrusion_count': extrusion_count,
            'travel_distance_mm': round(travel_dist, 2),
            'extrusion_distance_mm': round(extrusion_dist, 2),
            'total_distance_mm': round(total_dist, 2),
            'travel_pct': round(travel_dist / total_dist * 100, 1) if total_dist > 0 else 0,
            'extrusion_pct': round(extrusion_dist / total_dist * 100, 1) if total_dist > 0 else 0,
            'reasons': dict(reasons),
        }


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt die Klassifikation auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Travel Classifier – zustandsbasierte Klassifikation'
    )
    parser_arg.add_argument('file', nargs='?',
                           default='fixtures/minimal_test.gcode',
                           help='GCode-Datei')
    parser_arg.add_argument('--json', '-j', action='store_true',
                           help='JSON-Ausgabe')
    parser_arg.add_argument('--travel-only', action='store_true',
                           help='Nur Travel anzeigen')
    parser_arg.add_argument('--extrusion-only', action='store_true',
                           help='Nur Extrusion anzeigen')
    parser_arg.add_argument('--limit', type=int, default=0,
                           help='Maximale Anzahl anzuzeigender Ergebnisse')

    args = parser_arg.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Datei nicht gefunden: {filepath}")
        sys.exit(1)

    gcode_parser = GCodeParser()
    events = gcode_parser.parse_file(str(filepath))

    classifier = TravelClassifier(events)
    results = classifier.classify_all()
    stats = classifier.get_statistics()

    if args.json:
        import json
        output = {
            'statistics': stats,
            'classifications': [r.to_dict() for r in results],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"TRAVEL CLASSIFIER: {filepath.name}")
        print("=" * 60)
        print(f"\n📊 STATISTIK")
        print(f"  Klassifiziert:     {stats['total_classified']}")
        print(f"  Travel:            {stats['travel_count']} ({stats['travel_pct']}%)")
        print(f"  Extrusion:         {stats['extrusion_count']} ({stats['extrusion_pct']}%)")
        print(f"  Travel Distanz:    {stats['travel_distance_mm']:.1f} mm")
        print(f"  Extrusion Distanz: {stats['extrusion_distance_mm']:.1f} mm")
        print(f"  Gesamt Distanz:    {stats['total_distance_mm']:.1f} mm")
        print(f"\n  Gründe:")
        for reason, count in sorted(stats['reasons'].items()):
            print(f"    {reason}: {count}")

        # Auswahl anzeigen
        display = results
        if args.travel_only:
            display = classifier.travel_results
        elif args.extrusion_only:
            display = classifier.extrusion_results

        if args.limit > 0:
            display = display[:args.limit]

        if display:
            print(f"\n📋 DETAILS ({len(display)} Einträge):")
            print("-" * 60)
            for r in display:
                print(f"  {r}")


if __name__ == '__main__':
    main()