#!/usr/bin/env python3
"""
Wipe Detector – Kontextbasierte Wipe-Erkennung
===============================================
Erkennt Wipe-Bewegungen durch vollständige Kontextanalyse.

Wipe-Definition:
Ein Wipe ist eine Bewegung mit positivem E-Delta, die KEINE
normale Extrusion darstellt.
Typische Eigenschaften (müssen NICHT alle zutreffen):
- Großer XY-Sprung im Vergleich zur vorherigen Extrusion
- Erfolgt nach einem Konturende
- Oft nach Retract
- E-Delta ist klein relativ zur Distanz
- Oder: E-Delta ist ungewöhnlich groß für die Distanz

Regeln:
- Niemals nur auf Distanz basieren
- Niemals nur auf E basieren
- Kontextanalyse Pflicht:
  * vorheriger Zustand
  * Retract-State
  * Konturende
  * Travel-Folge
  * XY-Kontinuität
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
# WIPE-ERKENNUNGSERGEBNIS
# =============================================================================

class WipeCandidate:
    """
    Ein Wipe-Kandidat mit vollständigem Kontext.

    Attribute:
        line_idx: Zeile der Wipe-Bewegung
        from_xy: Startposition
        to_xy: Endposition
        distance: XY-Distanz in mm
        e_delta: E-Delta
        e_ratio: E/Distanz-Verhältnis
        is_retracted: War der Extruder retracted?
        was_contour_end: War die vorherige Bewegung ein Konturende?
        has_travel_before: Gab es einen Travel vor diesem Wipe?
        type_tag: TYPE während der Bewegung
        layer: Layer-Nummer
        raw: Roh-Text der Zeile
        reasons: Liste der Erkennungsgründe
    """

    __slots__ = (
        'line_idx', 'from_xy', 'to_xy', 'distance', 'e_delta',
        'e_ratio', 'is_retracted', 'was_contour_end',
        'has_travel_before', 'type_tag', 'layer', 'raw', 'reasons',
    )

    def __init__(self):
        self.line_idx: int = 0
        self.from_xy: Tuple[float, float] = (0.0, 0.0)
        self.to_xy: Tuple[float, float] = (0.0, 0.0)
        self.distance: float = 0.0
        self.e_delta: float = 0.0
        self.e_ratio: float = 0.0
        self.is_retracted: bool = False
        self.was_contour_end: bool = False
        self.has_travel_before: bool = False
        self.type_tag: Optional[str] = None
        self.layer: int = 0
        self.raw: str = ''
        self.reasons: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'line_idx': self.line_idx,
            'from_xy': self.from_xy,
            'to_xy': self.to_xy,
            'distance_mm': round(self.distance, 3),
            'e_delta': round(self.e_delta, 5),
            'e_ratio': round(self.e_ratio, 5),
            'is_retracted': self.is_retracted,
            'was_contour_end': self.was_contour_end,
            'has_travel_before': self.has_travel_before,
            'type': self.type_tag,
            'layer': self.layer,
            'raw': self.raw,
            'reasons': self.reasons,
        }

    def __repr__(self) -> str:
        return (
            f"Wipe L{self.line_idx:4d}: "
            f"{self.distance:6.1f}mm, "
            f"E={self.e_delta:+.5f}, "
            f"ratio={self.e_ratio:.4f}, "
            f"retr={self.is_retracted}, "
            f"contour_end={self.was_contour_end}, "
            f"travel_before={self.has_travel_before}, "
            f"type={self.type_tag}"
        )


# =============================================================================
# WIPE DETECTOR
# =============================================================================

class WipeDetector:
    """
    Erkennt Wipe-Bewegungen durch Kontextanalyse.
    - Vollständig zustandsbasiert
    - Analysiert vorherige/nachfolgende Bewegungen
    - Dokumentiert alle Erkennungsgründe
    """

    def __init__(self, events: List[GCodeEvent]):
        self.events = events
        self.wipe_candidates: List[WipeCandidate] = []
        self._state = GCodeState()

        # Analysehilfen
        self._last_was_extrusion = False
        self._consecutive_extrusion = 0
        self._contour_ended = False

        # Schwellwerte (dürfen später durch Analyse kalibriert werden)
        self.min_wipe_distance = 5.0  # mm
        self.min_wipe_ratio = 0.5  # E/Distanz (niedrig = Wipe-Verdacht)

    def detect_all(self) -> List[WipeCandidate]:
        """
        Führt die Wipe-Erkennung auf allen Events durch.
        """
        self.wipe_candidates = []
        self._state = GCodeState()
        self._last_was_extrusion = False
        self._consecutive_extrusion = 0
        self._contour_ended = False

        for event in self.events:
            self._state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            was_extrusion = self._is_extrusion(event)
            e_delta = self._state.get_e_delta() if event.has_e else 0.0
            dist = self._state.distance_to_last()

            # Konturende erkennen: Travel nach Extrusion
            if self._last_was_extrusion and not was_extrusion:
                self._contour_ended = True

            # Wipe-Kandidat: Bewegung mit E > 0, die KEINE normale Extrusion ist
            if (event.has_e and e_delta > 0 and dist > 0
                    and not self._state.is_retracted):

                # Prüfe ob es ein Wipe-Kandidat ist
                candidate = self._evaluate_wipe(event, dist, e_delta)
                if candidate is not None:
                    self.wipe_candidates.append(candidate)

            self._last_was_extrusion = was_extrusion
            if was_extrusion:
                self._consecutive_extrusion += 1
            else:
                self._consecutive_extrusion = 0
                # Nach einem einzelnen Travel: contour_ended bleibt True
                # Nach mehreren Travels: contour_ended zurücksetzen
                if self._contour_ended and not was_extrusion:
                    # Bleibt True für den nächsten Check
                    pass

        return self.wipe_candidates

    def _is_extrusion(self, event: GCodeEvent) -> bool:
        """Prüft ob ein Event eine Extrusion ist (gleiche Logik wie TravelClassifier)."""
        if not event.has_e:
            return False
        if self._state.is_retracted or self._state.awaiting_unretract:
            return False
        if not event.has_xy:
            return False
        e_delta = self._state.get_e_delta()
        dist = self._state.distance_to_last()
        return e_delta > 0 and dist > 0

    def _evaluate_wipe(self, event: GCodeEvent,
                       dist: float, e_delta: float) -> Optional[WipeCandidate]:
        """
        Prüft ob eine Bewegung ein Wipe-Kandidat ist.
        Führt mehrere kontextabhängige Prüfungen durch.
        """
        e_ratio = e_delta / dist if dist > 0 else 0.0
        reasons = []

        # === KONTEXT-ANALYSE ===

        # Kriterium 1: Großer Sprung (ungewöhnlich für normale Extrusion)
        if dist > 20.0:
            reasons.append(f'LARGE_JUMP({dist:.1f}mm)')

        # Kriterium 2: Niedriges E/Distanz-Verhältnis (viel Bewegung, wenig Filament)
        if e_ratio < 0.1:
            reasons.append(f'LOW_RATIO({e_ratio:.4f})')

        # Kriterium 3: Hohes E/Distanz-Verhältnis (viel Filament, wenig Bewegung)
        if e_ratio > 0.8:
            reasons.append(f'HIGH_RATIO({e_ratio:.4f})')

        # Kriterium 4: Konturende erkannt
        if self._contour_ended:
            reasons.append('AFTER_CONTOUR_END')

        # Kriterium 5: Nach Travel (Kontur wurde durch Travel getrennt)
        if not self._last_was_extrusion and self._consecutive_extrusion > 0:
            reasons.append('AFTER_TRAVEL')

        # Kriterium 6: Erste Extrusion nach einer Serie (Inselwechsel)
        if self._consecutive_extrusion == 0 and self._last_was_extrusion is False:
            reasons.append('FIRST_EXTRUSION_AFTER_TRAVEL')

        # === ENTSCHEIDUNG ===
        # Ein Wipe-Kandidat muss MINDESTENS 2 Kriterien erfüllen
        # ODER: sehr großer Sprung (> 50mm) mit E
        if len(reasons) >= 2 or (dist > 50.0 and e_delta > 0):
            candidate = WipeCandidate()
            candidate.line_idx = event.line_idx
            candidate.from_xy = (self._state.last_x, self._state.last_y)
            candidate.to_xy = (self._state.current_x, self._state.current_y)
            candidate.distance = dist
            candidate.e_delta = e_delta
            candidate.e_ratio = e_ratio
            candidate.is_retracted = self._state.is_retracted
            candidate.was_contour_end = self._contour_ended
            candidate.has_travel_before = not self._last_was_extrusion
            candidate.type_tag = self._state.current_type
            candidate.layer = self._state.current_layer
            candidate.raw = event.raw.strip()
            candidate.reasons = reasons
            return candidate

        return None

    def get_summary(self) -> Dict[str, Any]:
        """Zusammenfassung der Wipe-Erkennung."""
        reason_stats = defaultdict(int)
        for w in self.wipe_candidates:
            for r in w.reasons:
                reason_stats[r] += 1

        return {
            'total_wipe_candidates': len(self.wipe_candidates),
            'reason_distribution': dict(reason_stats),
            'min_distance_threshold': self.min_wipe_distance,
            'min_ratio_threshold': self.min_wipe_ratio,
        }


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt die Wipe-Erkennung auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Wipe Detector – kontextbasierte Wipe-Erkennung'
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

    detector = WipeDetector(events)
    wipes = detector.detect_all()
    summary = detector.get_summary()

    if args.json:
        import json
        print(json.dumps({
            'summary': summary,
            'wipes': [w.to_dict() for w in wipes],
        }, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"WIPE DETECTOR: {filepath.name}")
        print("=" * 60)
        print(f"\n📊 ZUSAMMENFASSUNG")
        print(f"  Wipe-Kandidaten: {summary['total_wipe_candidates']}")
        print(f"\n  Gründe:")
        for reason, count in sorted(summary['reason_distribution'].items()):
            print(f"    {reason}: {count}")

        if wipes:
            print(f"\n🧹 WIPE-KANDIDATEN:")
            print("-" * 60)
            for w in wipes:
                print(f"  {w}")
                for r in w.reasons:
                    print(f"    → {r}")


if __name__ == '__main__':
    main()