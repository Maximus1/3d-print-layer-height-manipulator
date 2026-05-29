#!/usr/bin/env python3
"""
Debug Tools – Analysewerkzeuge für Geometriedivergenzen
======================================================
Stellt Werkzeuge bereit für:
- Delta-Analyse zwischen Original und Output
- Minimale reproduzierbare Sequenzen
- Divergenz-Visualisierung (als Text)
- State-Dumps zu jedem Zeitpunkt

Jeder Debug-Befehl muss reproduzierbar, datenbasiert und beweisbar sein.
"""

import sys
import json
import math
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeParser, GCodeEvent
from state_tracker import GCodeState


# =============================================================================
# MINIMALE REPRODUZIERBARE SEQUENZ
# =============================================================================

def extract_minimal_sequence(events: List[GCodeEvent],
                             start_line: int,
                             context_before: int = 5,
                             context_after: int = 5) -> List[GCodeEvent]:
    """
    Extrahiert eine minimale reproduzierbare Sequenz um eine Zeile herum.

    Args:
        events: Alle Events
        start_line: Zentrale Zeile
        context_before: Zeilen davor
        context_after: Zeilen danach

    Returns:
        Events um die Problemstelle herum
    """
    start_idx = max(0, start_line - context_before)
    end_idx = min(len(events), start_line + context_after + 1)

    # Rückwärts bis zum letzten M82/M83/G92/G10/G11 suchen
    # für vollständigen Zustandskontext
    for i in range(start_idx - 1, max(0, start_idx - 50), -1):
        e = events[i]
        if e.command in ('M82', 'M83', 'G90', 'G91', 'G92', 'G10', 'G11'):
            start_idx = i
            break

    return events[start_idx:end_idx]


def format_sequence(events: List[GCodeEvent], highlight: int = None) -> str:
    """
    Formatiert eine Event-Sequenz als lesbaren Text.

    Args:
        events: Zu formatierende Events
        highlight: Line-Index zum Hervorheben

    Returns:
        formatierte Sequenz
    """
    lines = []
    for e in events:
        marker = '>>>' if e.line_idx == highlight else '   '
        if e.is_empty:
            lines.append(f"{marker} [{e.line_idx:4d}] (leer)")
        elif e.is_comment:
            lines.append(f"{marker} [{e.line_idx:4d}] ; {e.raw.strip()[:60]}")
        elif e.is_layer_change:
            lines.append(f"{marker} [{e.line_idx:4d}] LAYER_CHANGE")
        elif e.command:
            params = ' '.join(f"{k}{v}" for k, v in e.params.items())
            raw_comment = e.raw.strip()
            # Nur den Kommentarteil anzeigen (nach ';')
            if ';' in raw_comment:
                comment = raw_comment.split(';', 1)[1].strip()
                lines.append(f"{marker} [{e.line_idx:4d}] {e.command:4s} {params:40s} ; {comment}")
            else:
                lines.append(f"{marker} [{e.line_idx:4d}] {e.command:4s} {params}")
        else:
            lines.append(f"{marker} [{e.line_idx:4d}] ? {e.raw.strip()[:60]}")
    return '\n'.join(lines)


# =============================================================================
# STATE-DUMP
# =============================================================================

def dump_state(state: GCodeState, title: str = "") -> str:
    """
    Erzeugt einen vollständigen State-Dump.

    Args:
        state: GCodeState
        title: Optionaler Titel

    Returns:
        formatierter State-Dump
    """
    lines = [f"=== STATE DUMP {title} ==="]
    lines.append(f"  Position:  X={state.current_x:.4f} Y={state.current_y:.4f} Z={state.current_z:.4f}")
    lines.append(f"  Last Pos:  X={state.last_x:.4f} Y={state.last_y:.4f}")
    lines.append(f"  Last Extr: X={state.last_extrusion_x} Y={state.last_extrusion_y}")
    lines.append(f"  Extruder:  E={state.current_e:.5f} Last E={state.last_e:.5f}")
    lines.append(f"  Modes:     rel_E={'M83' if state.relative_e_mode else 'M82'}, "
                 f"rel_XYZ={'G91' if state.relative_xyz_mode else 'G90'}")
    lines.append(f"  State:     retracted={state.is_retracted}, "
                 f"printing={state.is_printing}, "
                 f"await_unretract={state.awaiting_unretract}")
    lines.append(f"  Layer:     {state.current_layer}, "
                 f"Contour: {state.current_contour}, "
                 f"Type: {state.current_type}")
    lines.append(f"  Feedrate:  {state.current_feedrate}")
    lines.append(f"  Distances: to_last={state.distance_to_last():.4f}mm, "
                 f"from_last_extr={state.distance_from_last_extrusion()}")
    return '\n'.join(lines)


# =============================================================================
# DELTA-ANALYSE
# =============================================================================

def delta_analysis(events_a: List[GCodeEvent],
                   events_b: List[GCodeEvent]) -> List[Dict[str, Any]]:
    """
    Vergleicht zwei Event-Listen zeilenweise und dokumentiert alle Abweichungen.

    Args:
        events_a: Original-Events
        events_b: Verarbeitete Events

    Returns:
        Liste der Abweichungen
    """
    deltas = []
    min_len = min(len(events_a), len(events_b))

    for i in range(min_len):
        ea = events_a[i]
        eb = events_b[i]
        delta = {'line_idx': i}

        # Befehl geändert?
        if ea.command != eb.command:
            delta['type'] = 'command_changed'
            delta['expected'] = ea.command
            delta['actual'] = eb.command
            delta['raw_a'] = ea.raw.strip()
            delta['raw_b'] = eb.raw.strip()
            deltas.append(delta)
            continue

        # Nur G0/G1/G2/G3 mit Parametern vergleichen
        if ea.command not in ('G0', 'G1', 'G2', 'G3'):
            continue

        param_deltas = {}
        for param in ('X', 'Y', 'Z', 'E', 'I', 'J', 'F'):
            va = ea.params.get(param)
            vb = eb.params.get(param)
            if va is not None or vb is not None:
                if va != vb:
                    param_deltas[param] = {
                        'expected': va,
                        'actual': vb,
                    }

        if param_deltas:
            delta['type'] = 'param_changed'
            delta['params'] = param_deltas
            delta['raw_a'] = ea.raw.strip()
            delta['raw_b'] = eb.raw.strip()
            deltas.append(delta)

    # Längenunterschied
    if len(events_a) != len(events_b):
        deltas.append({
            'type': 'length_mismatch',
            'expected': len(events_a),
            'actual': len(events_b),
        })

    return deltas


# =============================================================================
# SEQUENZ-VERGLEICH (geometrisch)
# =============================================================================

def compare_geometric_sequences(file_a: str, file_b: str,
                                tolerance: float = 0.001) -> Dict[str, Any]:
    """
    Vergleicht zwei GCode-Dateien geometrisch.
    Findet die erste Position, an der sie divergieren.

    Args:
        file_a: Original-Datei
        file_b: Verarbeitete Datei
        tolerance: Toleranz für Positionsvergleiche

    Returns:
        Dict mit Vergleichsergebnis
    """
    parser = GCodeParser()
    events_a = parser.parse_file(file_a)
    events_b = parser.parse_file(file_b)

    state_a = GCodeState()
    state_b = GCodeState()

    result = {
        'file_a': file_a,
        'file_b': file_b,
        'total_lines_a': len(events_a),
        'total_lines_b': len(events_b),
        'divergence': None,
        'stats': {},
    }

    min_len = min(len(events_a), len(events_b))

    for i in range(min_len):
        ea = events_a[i]
        eb = events_b[i]

        state_a.process_event(ea)
        state_b.process_event(eb)

        # Prüfe Positionen
        if ea.has_xy and eb.has_xy:
            dx = abs(state_a.current_x - state_b.current_x)
            dy = abs(state_a.current_y - state_b.current_y)
            if dx > tolerance or dy > tolerance:
                result['divergence'] = {
                    'line_idx': i,
                    'type': 'position',
                    'expected_xy': (state_a.current_x, state_a.current_y),
                    'actual_xy': (state_b.current_x, state_b.current_y),
                    'delta': (dx, dy),
                    'expected_state': dump_state(state_a),
                    'context': format_sequence(
                        extract_minimal_sequence(events_a, i, 3, 3),
                        highlight=i
                    ),
                }
                break

        # Prüfe E-Werte
        if ea.has_e and eb.has_e:
            de = abs(state_a.current_e - state_b.current_e)
            if de > tolerance:
                result['divergence'] = {
                    'line_idx': i,
                    'type': 'extrusion',
                    'expected_e': state_a.current_e,
                    'actual_e': state_b.current_e,
                    'delta': de,
                    'expected_state': dump_state(state_a),
                    'context': format_sequence(
                        extract_minimal_sequence(events_a, i, 3, 3),
                        highlight=i
                    ),
                }
                break

    # Statistiken
    result['stats'] = {
        'same_length': len(events_a) == len(events_b),
        'length_diff': abs(len(events_a) - len(events_b)),
        'has_divergence': result['divergence'] is not None,
    }

    return result


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Debug-Tools Hauptprogramm."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Debug Tools für GCode-Analyse'
    )
    parser_arg.add_argument('file', nargs='?',
                           default='fixtures/minimal_test.gcode',
                           help='GCode-Datei')
    parser_arg.add_argument('--compare', '-c', metavar='FILE',
                           help='Datei zum Vergleichen')
    parser_arg.add_argument('--line', type=int, default=None,
                           help='Zeile für Kontext-Extraktion')
    parser_arg.add_argument('--context', type=int, default=5,
                           help='Kontextzeilen vor/nach')
    parser_arg.add_argument('--json', '-j', action='store_true',
                           help='JSON-Ausgabe')

    args = parser_arg.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Datei nicht gefunden: {filepath}")
        sys.exit(1)

    parser = GCodeParser()
    events = parser.parse_file(str(filepath))

    if args.compare:
        # Vergleichsmodus
        compare_path = Path(args.compare)
        if not compare_path.exists():
            print(f"Vergleichsdatei nicht gefunden: {compare_path}")
            sys.exit(1)

        result = compare_geometric_sequences(str(filepath), str(compare_path))

        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("=" * 60)
            print(f"GEOMETRISCHER VERGLEICH")
            print("=" * 60)
            print(f"  Original:  {result['file_a']} ({result['total_lines_a']} Zeilen)")
            print(f"  Output:    {result['file_b']} ({result['total_lines_b']} Zeilen)")
            print(f"  Gleiche Länge: {result['stats']['same_length']}")
            print(f"  Längen-Diff:   {result['stats']['length_diff']}")

            if result['divergence']:
                d = result['divergence']
                print(f"\n⚠️  DIVERGENZ GEFUNDEN in Zeile {d['line_idx']}:")
                print(f"  Typ: {d['type']}")
                print(f"  Erwartet: {d.get('expected_xy', d.get('expected_e'))}")
                print(f"  Tatsächlich: {d.get('actual_xy', d.get('actual_e'))}")
                print(f"\n  Kontext:\n{d.get('context', '')}")
            else:
                print(f"\n✅ KEINE DIVERGENZ GEFUNDEN.")

    elif args.line is not None:
        # Kontext um eine Zeile
        seq = extract_minimal_sequence(
            events, args.line,
            context_before=args.context,
            context_after=args.context
        )
        print(f"Minimale Sequenz um Zeile {args.line} "
              f"(±{args.context} Zeilen, inkl. vorheriger Zustandswechsel):")
        print("-" * 60)
        print(format_sequence(seq, highlight=args.line))
    else:
        # State-Dump nach komplettem Durchlauf
        state = GCodeState()
        for event in events:
            state.process_event(event)
        print(dump_state(state, f"(nach {len(events)} Events)"))


if __name__ == '__main__':
    main()