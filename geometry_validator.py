#!/usr/bin/env python3
"""
Geometry Validator – Rein analytische Geometrieprüfung
======================================================
Diese Datei ist NIEMALS korrigierend oder patchend.
Sie ist NUR beweisend: sie analysiert Geometriedaten und dokumentiert
Abweichungen, Anomalien und Konsistenzverletzungen.

Prüfungen:
1. Kontinuität: Sind die XY-Pfade stetig?
2. Extrusionskonsistenz: Ist E zu XY proportional?
3. Travel/Extrusion-Trennung: Werden Travel und Extrusion sauber getrennt?
4. Arc-Konsistenz: Sind G2/G3-Endpunkte geometrisch plausibel?
5. Layer-Konsistenz: Sind Layer-Wechsel sauber?
6. Retract-Konsistenz: Werden Retracts korrekt eingehalten?
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
# VALIDIERUNGSERGEBNIS
# =============================================================================

class ValidationFinding:
    """
    Ein einzelner Validierungsbefund.
    - KEINE Korrektur
    - KEIN Patch
    - NUR Dokumentation
    """

    __slots__ = (
        'finding_type', 'severity', 'line_idx', 'description',
        'expected', 'actual', 'delta', 'context',
    )

    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_ERROR = 'error'
    SEVERITY_CRITICAL = 'critical'

    def __init__(
        self,
        finding_type: str,
        severity: str,
        line_idx: int,
        description: str,
        expected: Any = None,
        actual: Any = None,
        delta: Any = None,
        context: dict = None,
    ):
        self.finding_type = finding_type
        self.severity = severity
        self.line_idx = line_idx
        self.description = description
        self.expected = expected
        self.actual = actual
        self.delta = delta
        self.context = context or {}

    def to_dict(self) -> Dict:
        return {
            'type': self.finding_type,
            'severity': self.severity,
            'line_idx': self.line_idx,
            'description': self.description,
            'expected': self.expected,
            'actual': self.actual,
            'delta': self.delta,
            'context': self.context,
        }

    def __repr__(self) -> str:
        return (
            f"[{self.severity.upper():8s}] {self.finding_type:30s} "
            f"L{self.line_idx}: {self.description}"
        )


# =============================================================================
# GEOMETRY VALIDATOR
# =============================================================================

class GeometryValidator:
    """
    Führt geometrische Validierung auf GCode-Events durch.
    - NUR analysierend
    - NIEMALS korrigierend
    - ALLE Befunde werden dokumentiert
    """

    def __init__(self, events: List[GCodeEvent]):
        self.events = events
        self.findings: List[ValidationFinding] = []
        self.state = GCodeState()

        # Klassifikationslisten (für Analyse)
        self.extrusion_moves: List[Tuple[int, GCodeEvent, float, float]] = []
        """(line_idx, event, dist, e_delta)"""
        self.travel_moves: List[Tuple[int, GCodeEvent, float]] = []
        """(line_idx, event, dist)"""
        self.arc_moves: List[Tuple[int, GCodeEvent, float]] = []
        """(line_idx, event, endpoint_dist)"""

    # ======================================================================
    # VALIDIERUNGSLÄUFE
    # ======================================================================

    def validate_all(self) -> List[ValidationFinding]:
        """Führt alle Validierungsläufe aus."""
        self.findings = []
        self._classify_all_moves()
        self._validate_continuity()
        self._validate_extrusion_consistency()
        self._validate_travel_extrusion_separation()
        self._validate_arc_consistency()
        self._validate_layer_consistency()
        self._validate_retract_consistency()
        self._validate_jump_detection()
        return self.findings

    def _classify_all_moves(self):
        """
        Klassifiziert ALLE Bewegungen mittels Zustandsmaschine.
        Dies ist die EINZIGE Stelle, an der Travel/Extrusion unterschieden wird.

        Kriterien für Extrusion:
        - Befehl in (G0, G1, G2, G3)
        - hat XY-Bewegung
        - hat E-Parameter
        - E-Delta > 0 (unter Berücksichtigung von M82/M83/G92)
        - nicht retracted
        - Distanz > 0

        Kriterien für Travel:
        - G0 ohne E
        - G1/G2/G3 mit E <= 0
        - Jede Bewegung während Retract
        """
        self.extrusion_moves = []
        self.travel_moves = []
        self.arc_moves = []

        for event in self.events:
            self.state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            dist = self.state.distance_to_last()
            is_arc = event.command in ('G2', 'G3')

            if is_arc:
                self.arc_moves.append((event.line_idx, event, dist))

            e_delta = 0.0
            if event.has_e and not self.state.is_retracted:
                e_delta = self.state.get_e_delta()

            is_extrusion = (
                event.has_e
                and e_delta > 0
                and dist > 0
                and not self.state.is_retracted
            )

            if is_extrusion:
                self.extrusion_moves.append((event.line_idx, event, dist, e_delta))
            else:
                self.travel_moves.append((event.line_idx, event, dist))

    # ======================================================================
    # 1. KONTINUITÄT
    # ======================================================================

    def _validate_continuity(self):
        """
        Prüft Kontinuität der XY-Pfade:
        - Große XY-Sprünge ohne vorherigen Retract
        - Unterbrochene Extrusionspfade
        - Positionen, die weit auseinander liegen
        """
        state = GCodeState()
        last_extrusion_end = None
        extrusion_active = False

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            dist = state.distance_to_last()
            e_delta = state.get_e_delta() if event.has_e else 0.0

            # Prüfe: Extrusion mit extrem großem Sprung (> 50mm)
            if (event.has_e and e_delta > 0
                    and not state.is_retracted
                    and dist > 50.0):
                self.findings.append(ValidationFinding(
                    finding_type='large_extrusion_jump',
                    severity='warning',
                    line_idx=event.line_idx,
                    description=f'Extrusion mit {dist:.1f}mm Sprung',
                    expected=f'Sprung < 50mm',
                    actual=f'{dist:.1f}mm',
                    context={
                        'from_xy': (state.last_x, state.last_y),
                        'to_xy': (state.current_x, state.current_y),
                        'e_delta': e_delta,
                        'type': state.current_type,
                    },
                ))

            # Prüfe: Extrusion ohne vorherige Extrusion im Layer
            if event.has_e and e_delta > 0 and not state.is_retracted:
                if last_extrusion_end is not None and extrusion_active:
                    gap = math.sqrt(
                        (state.last_x - last_extrusion_end[0]) ** 2 +
                        (state.last_y - last_extrusion_end[1]) ** 2
                    )
                    if gap > 1.0:
                        self.findings.append(ValidationFinding(
                            finding_type='extrusion_gap',
                            severity='info',
                            line_idx=event.line_idx,
                            description=f'Lücke in Extrusion: {gap:.2f}mm',
                            expected='lückenlose Extrusion',
                            actual=f'{gap:.2f}mm Lücke',
                            context={
                                'last_end': last_extrusion_end,
                                'new_start': (state.last_x, state.last_y),
                                'type': state.current_type,
                            },
                        ))
                last_extrusion_end = (state.current_x, state.current_y)
                extrusion_active = True

    # ======================================================================
    # 2. EXTRUSIONSKONSISTENZ
    # ======================================================================

    def _validate_extrusion_consistency(self):
        """
        Prüft Konsistenz der Extrusion:
        - Ist E zu XY proportional?
        - Gibt es Extrusion ohne XY-Bewegung?
        - Gibt es XY-Bewegung ohne E (anormal)?
        """
        state = GCodeState()

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue

            e_delta = state.get_e_delta() if event.has_e else 0.0
            dist = state.distance_to_last()

            # Extrusion mit E > 0 aber Distanz = 0
            if (event.has_e and e_delta > 0
                    and not state.is_retracted
                    and dist == 0):
                self.findings.append(ValidationFinding(
                    finding_type='zero_distance_extrusion',
                    severity='error',
                    line_idx=event.line_idx,
                    description=f'Extrusion ohne Bewegung: E={e_delta:.5f}',
                    expected='E > 0 mit XY-Bewegung',
                    actual=f'E={e_delta:.5f}, Distanz=0',
                ))

            # Extrusion mit extremem E/Distanz-Verhältnis (Wipe-Verdacht)
            if (event.has_e and e_delta > 0
                    and not state.is_retracted
                    and dist > 0):
                ratio = e_delta / dist
                if ratio > 0.5:
                    self.findings.append(ValidationFinding(
                        finding_type='high_extrusion_ratio',
                        severity='info',
                        line_idx=event.line_idx,
                        description=f'Hohes E/Distanz-Verhältnis: {ratio:.4f}',
                        expected=f'ratio < 0.5',
                        actual=f'{ratio:.4f}',
                        context={
                            'dist': dist,
                            'e_delta': e_delta,
                            'type': state.current_type,
                        },
                    ))

    # ======================================================================
    # 3. TRAVEL/EXTRUSION-TRENNUNG
    # ======================================================================

    def _validate_travel_extrusion_separation(self):
        """
        Prüft ob Travel und Extrusion sauber getrennt sind.
        - Travel mit E > 0 (Kandidat für Wipe oder Fehler)
        - G1 ohne E aber mit XY (reiner Travel auf G1)
        """
        state = GCodeState()

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            e_delta = state.get_e_delta() if event.has_e else 0.0

            # G0 mit E > 0 (ungewöhnlich, aber möglich)
            if event.command == 'G0' and event.has_e and e_delta > 0:
                self.findings.append(ValidationFinding(
                    finding_type='travel_with_extrusion',
                    severity='warning',
                    line_idx=event.line_idx,
                    description=f'G0 (Travel) mit E={e_delta:.5f}',
                    expected='G0 ohne E',
                    actual=f'E={e_delta:.5f}',
                    context={
                        'dist': state.distance_to_last(),
                        'type': state.current_type,
                    },
                ))

            # G1 ohne E aber mit XY (reiner Travel auf G1)
            if (event.command == 'G1'
                    and not event.has_e
                    and event.has_xy
                    and not state.is_retracted):
                self.findings.append(ValidationFinding(
                    finding_type='g1_travel_without_e',
                    severity='info',
                    line_idx=event.line_idx,
                    description=f'G1 Travel ohne E: {state.distance_to_last():.1f}mm',
                    expected='G1 mit E oder G0',
                    actual='G1 ohne E',
                    context={
                        'dist': state.distance_to_last(),
                    },
                ))

    # ======================================================================
    # 4. ARC-KONSISTENZ
    # ======================================================================

    def _validate_arc_consistency(self):
        """
        Prüft Konsistenz von Arcs (G2/G3):
        - Haben Arcs I/J Parameter?
        - Sind Arc-Endpunkte plausibel?
        """
        state = GCodeState()

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G2', 'G3'):
                continue

            has_ij = 'I' in event.params and 'J' in event.params
            i_val = event.params.get('I', 0.0)
            j_val = event.params.get('J', 0.0)

            # Arc ohne I/J
            if not has_ij:
                self.findings.append(ValidationFinding(
                    finding_type='arc_without_ij',
                    severity='error',
                    line_idx=event.line_idx,
                    description=f'{event.command} ohne I/J Parameter',
                    expected='I/J für Arc',
                    actual='Kein I/J',
                ))

            # Arc mit I=0 und J=0 (degenerierter Arc)
            if has_ij and abs(i_val) < 0.001 and abs(j_val) < 0.001:
                self.findings.append(ValidationFinding(
                    finding_type='degenerate_arc',
                    severity='warning',
                    line_idx=event.line_idx,
                    description=f'{event.command} mit I=0, J=0 (degeneriert)',
                    expected='I oder J ≠ 0',
                    actual='I=0, J=0',
                ))

            # Arc-Endpunkt-Distanz (KEINE tatsächliche Arc-Länge)
            dist = state.distance_to_last()
            if dist < 0.001:
                self.findings.append(ValidationFinding(
                    finding_type='zero_length_arc',
                    severity='error',
                    line_idx=event.line_idx,
                    description=f'{event.command} mit Endpunkt-Distanz=0',
                    expected='Bewegung > 0',
                    actual='Endpunkt-Distanz = 0',
                    context={'i': i_val, 'j': j_val},
                ))

    # ======================================================================
    # 5. LAYER-KONSISTENZ
    # ======================================================================

    def _validate_layer_consistency(self):
        """
        Prüft Layer-Konsistenz:
        - Layer-Wechsel erkennbar?
        - Layer haben sinnvolle Extrusion?
        """
        state = GCodeState()
        layer_extrusion: Dict[int, float] = defaultdict(float)
        layer_moves: Dict[int, int] = defaultdict(int)

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue

            e_delta = state.get_e_delta() if event.has_e else 0.0
            if e_delta > 0 and not state.is_retracted:
                layer_extrusion[state.current_layer] += e_delta
                layer_moves[state.current_layer] += 1

        # Prüfe: Layer ohne Extrusion
        for layer, ext in sorted(layer_extrusion.items()):
            if ext < 0.001:
                self.findings.append(ValidationFinding(
                    finding_type='empty_layer',
                    severity='warning',
                    line_idx=0,
                    description=f'Layer {layer} hat keine Extrusion',
                    expected='E > 0',
                    actual=f'E={ext:.4f}',
                ))

    # ======================================================================
    # 6. RETRACT-KONSISTENZ
    # ======================================================================

    def _validate_retract_consistency(self):
        """
        Prüft Retract-Konsistenz:
        - Extrusion während Retract?
        - Fehlendes Unretract vor Extrusion?
        """
        state = GCodeState()
        last_retract_line = -1

        for event in self.events:
            # process_event MUSS für ALLE Events aufgerufen werden,
            # damit G10/G11 den Retract-State korrekt aktualisieren
            old_retracted = state.is_retracted
            changes = state.process_event(event)

            # G10 Retract gefunden
            if event.command == 'G10':
                last_retract_line = event.line_idx

            # Nur Bewegungsbefehle auf Extrusion während Retract prüfen
            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_e:
                continue
            if not old_retracted:
                continue

            e_delta = state.get_e_delta()
            if e_delta > 0:
                self.findings.append(ValidationFinding(
                    finding_type='extrusion_while_retracted',
                    severity='error',
                    line_idx=event.line_idx,
                    description=f'Extrusion während Retract: E={e_delta:.5f}',
                    expected='Keine Extrusion während Retract',
                    actual=f'E={e_delta:.5f}',
                    context={
                        'last_retract_line': last_retract_line,
                    },
                ))

    # ======================================================================
    # 7. SPRUNGERKENNUNG
    # ======================================================================

    def _validate_jump_detection(self):
        """
        Erkennt große XY-Sprünge.
        Diese können sein:
        - Normale Travel-Moves (nach Retract)
        - Wipe-Bewegungen (mit E)
        - Anomalien
        """
        state = GCodeState()

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            dist = state.distance_to_last()

            # Großer Sprung (> 100mm)
            if dist > 100.0:
                e_delta = state.get_e_delta() if event.has_e else 0.0
                self.findings.append(ValidationFinding(
                    finding_type='large_jump',
                    severity='info',
                    line_idx=event.line_idx,
                    description=f'Großer Sprung: {dist:.1f}mm',
                    expected='',
                    actual=f'{dist:.1f}mm',
                    context={
                        'from_xy': (state.last_x, state.last_y),
                        'to_xy': (state.current_x, state.current_y),
                        'e_delta': e_delta,
                        'is_retracted': state.is_retracted,
                        'type': state.current_type,
                    },
                ))

    # ======================================================================
    # AUSGABE
    # ======================================================================

    def get_summary(self) -> Dict[str, Any]:
        """Erzeugt eine Zusammenfassung aller Befunde."""
        by_severity = defaultdict(int)
        by_type = defaultdict(int)

        for f in self.findings:
            by_severity[f.severity] += 1
            by_type[f.finding_type] += 1

        return {
            'total_findings': len(self.findings),
            'by_severity': dict(by_severity),
            'by_type': dict(by_type),
            'extrusion_moves': len(self.extrusion_moves),
            'travel_moves': len(self.travel_moves),
            'arc_moves': len(self.arc_moves),
        }


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt Validierung auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Geometry Validator – rein analysierend'
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

    validator = GeometryValidator(events)
    findings = validator.validate_all()
    summary = validator.get_summary()

    if args.json:
        import json
        print(json.dumps({
            'summary': summary,
            'findings': [f.to_dict() for f in findings],
        }, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"GEOMETRY VALIDATOR: {filepath.name}")
        print("=" * 60)
        print(f"\n📊 ZUSAMMENFASSUNG")
        print(f"  Befunde gesamt: {summary['total_findings']}")
        for sev, cnt in sorted(summary['by_severity'].items()):
            print(f"    {sev}: {cnt}")
        print(f"  Extrusion Moves: {summary['extrusion_moves']}")
        print(f"  Travel Moves:    {summary['travel_moves']}")
        print(f"  Arc Moves:       {summary['arc_moves']}")

        if findings:
            print(f"\n📋 BEFUNDE (Details):")
            print("-" * 60)
            for f in findings:
                print(f"  {f}")


if __name__ == '__main__':
    main()