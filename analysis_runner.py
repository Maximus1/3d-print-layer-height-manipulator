#!/usr/bin/env python3
"""
Analysis Runner – Erstes Analysewerkzeug
========================================
Führt grundlegende geometrische Analysen auf GCode-Dateien durch,
BEVOR Produktionslogik geschrieben wird.

Analysen:
1. Travel vs Extrusion: Verteilung, Distanzen, Häufigkeit
2. E-Delta-Analyse: Positive/negative Deltas, Min/Max/Mittel
3. Layer-Analyse: Anzahl Layer, Events pro Layer, Typen pro Layer
4. Distanz-Histogramm: XY-Sprünge klassifizieren
5. Wipe-Kandidaten: Große XY-Sprünge mit positivem E
6. Arc-Analyse: Anzahl Arcs, I/J-Werte
7. Erste Divergenz: Vergleich zweier Dateien
"""

import sys
import os
import json
import math
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from collections import Counter, defaultdict

# Projekt-Root
sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeParser, GCodeEvent
from state_tracker import GCodeState


# =============================================================================
# PAKETMANAGEMENT (laut .clinerules)
# =============================================================================

def _ensure_deps():
    """Stellt sicher, dass numpy und matplotlib verfügbar sind."""
    try:
        import numpy
    except ImportError:
        import subprocess
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "numpy"
        ])
        os.execv(sys.executable, [sys.executable] + sys.argv)


# =============================================================================
# ANALYSE-FUNKTIONEN
# =============================================================================

class GCodeAnalyzer:
    """
    Führt geometrische Analysen auf GCode-Daten durch.
    Arbeitet auf geparsten Events + State für maximale Genauigkeit.
    """

    def __init__(self, events: List[GCodeEvent]):
        self.events = events
        self.stats: Dict[str, Any] = {}

        # Travel/Extrusion-Klassifikation
        self.travel_lines: List[GCodeEvent] = []
        self.extrusion_lines: List[GCodeEvent] = []

        # E-Deltas
        self.e_deltas: List[float] = []
        self.e_positive: List[float] = []
        self.e_negative: List[float] = []

        # Distanzen
        self.xy_distances: List[float] = []
        self.extrusion_distances: List[float] = []
        self.travel_distances: List[float] = []

        # Layer
        self.layer_events: Dict[int, List[int]] = {}
        self.layer_types: Dict[int, set] = {}

        # Wipe-Kandidaten
        self.wipe_candidates: List[Dict] = []

        # Arcs
        self.arc_events: List[GCodeEvent] = []

    def run_all(self) -> Dict[str, Any]:
        """Führt alle Analysen aus und gibt die Ergebnisse zurück."""
        self._classify_moves()
        self._analyze_e_deltas()
        self._analyze_distances()
        self._analyze_layers()
        self._find_wipe_candidates()
        self._analyze_arcs()
        self._compile_statistics()
        return self.stats

    def _classify_moves(self):
        """
        Klassifiziert jede Bewegung als Travel oder Extrusion.
        Nutzt den State Tracker für korrekte E-Delta-Berechnung.
        """
        state = GCodeState()

        for event in self.events:
            state.process_event(event)

            # Nur G0/G1/G2/G3 mit XY-Bewegung
            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            # Distanz berechnen
            dist = state.distance_to_last()

            if event.has_e and not state.is_retracted:
                e_delta = state.get_e_delta()
                if e_delta > 0 and dist > 0:
                    self.extrusion_lines.append(event)
                    self.extrusion_distances.append(dist)
                    self.e_deltas.append(e_delta)
                    self.e_positive.append(e_delta)
                else:
                    self.travel_lines.append(event)
                    self.travel_distances.append(dist)
                    if e_delta < 0:
                        self.e_negative.append(e_delta)
            else:
                self.travel_lines.append(event)
                self.travel_distances.append(dist)

            self.xy_distances.append(dist)

    def _analyze_e_deltas(self):
        """E-Delta-Analyse: Verteilung der positiven/negativen Deltas."""
        self.stats['e_deltas'] = {
            'count_positive': len(self.e_positive),
            'count_negative': len(self.e_negative),
            'sum_positive': sum(self.e_positive) if self.e_positive else 0.0,
            'sum_negative': sum(self.e_negative) if self.e_negative else 0.0,
            'max_positive': max(self.e_positive) if self.e_positive else 0.0,
            'min_positive': min(self.e_positive) if self.e_positive else 0.0,
            'max_negative': min(self.e_negative) if self.e_negative else 0.0,
            'min_negative': max(self.e_negative) if self.e_negative else 0.0,
            'total_extrusion': sum(self.e_positive) if self.e_positive else 0.0,
        }

    def _analyze_distances(self):
        """Distanz-Analyse: Travel vs Extrusion."""
        def _dist_stats(values, label):
            if not values:
                return {
                    'label': label,
                    'count': 0,
                    'total': 0.0,
                    'mean': 0.0,
                    'max': 0.0,
                    'min': 0.0,
                }
            return {
                'label': label,
                'count': len(values),
                'total': sum(values),
                'mean': sum(values) / len(values),
                'max': max(values),
                'min': min(values),
            }

        self.stats['distances'] = {
            'all': _dist_stats(self.xy_distances, 'Alle Bewegungen'),
            'extrusion': _dist_stats(self.extrusion_distances, 'Extrusion'),
            'travel': _dist_stats(self.travel_distances, 'Travel'),
        }

        # Travel/Extrusion-Verhältnis
        total_travel = sum(self.travel_distances) if self.travel_distances else 0.0
        total_extrusion = sum(self.extrusion_distances) if self.extrusion_distances else 0.0
        total_all = total_travel + total_extrusion

        self.stats['travel_extrusion_ratio'] = {
            'travel_mm': total_travel,
            'extrusion_mm': total_extrusion,
            'total_mm': total_all,
            'travel_pct': (total_travel / total_all * 100) if total_all > 0 else 0.0,
            'extrusion_pct': (total_extrusion / total_all * 100) if total_all > 0 else 0.0,
            'travel_moves': len(self.travel_lines),
            'extrusion_moves': len(self.extrusion_lines),
        }

    def _analyze_layers(self):
        """Layer-Analyse: Layer-Zählung, Events pro Layer, Typen."""
        state = GCodeState()
        layer_event_count: Dict[int, int] = defaultdict(int)
        layer_type_set: Dict[int, set] = defaultdict(set)

        for event in self.events:
            old_layer = state.current_layer
            state.process_event(event)

            current_layer = state.current_layer

            if event.command and not event.is_comment and not event.is_empty:
                layer_event_count[current_layer] += 1

            if event.type_tag:
                layer_type_set[current_layer].add(event.type_tag)

        self.stats['layers'] = {
            'count': max(layer_event_count.keys()) if layer_event_count else 0,
            'events_per_layer': dict(layer_event_count),
            'types_per_layer': {
                str(k): sorted(list(v))
                for k, v in sorted(layer_type_set.items())
            },
        }

    def _find_wipe_candidates(self):
        """
        Findet Wipe-Kandidaten: Bewegungen mit
        - großem XY-Sprung (> 5mm)
        - positivem E-Delta
        - innerhalb aktiver Extrusion
        """
        state = GCodeState()
        wipe_threshold = 5.0  # mm

        for event in self.events:
            state.process_event(event)

            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy or not event.has_e:
                continue
            if state.is_retracted:
                continue

            e_delta = state.get_e_delta()
            dist = state.distance_to_last()

            if e_delta > 0 and dist >= wipe_threshold:
                self.wipe_candidates.append({
                    'line_idx': event.line_idx,
                    'command': event.command,
                    'from_xy': (state.last_x, state.last_y),
                    'to_xy': (state.current_x, state.current_y),
                    'distance_mm': round(dist, 3),
                    'e_delta': round(e_delta, 5),
                    'type': state.current_type,
                    'layer': state.current_layer,
                    'raw': event.raw.strip(),
                })

        self.stats['wipe_candidates'] = {
            'count': len(self.wipe_candidates),
            'threshold_mm': wipe_threshold,
            'candidates': self.wipe_candidates[:50],  # max 50 anzeigen
        }

    def _analyze_arcs(self):
        """Arc-Analyse: Anzahl, I/J-Werte, Distanzen."""
        self.arc_events = [e for e in self.events if e.command in ('G2', 'G3')]

        arc_i_values = []
        arc_j_values = []
        arc_distances = []

        state = GCodeState()
        for event in self.arc_events:
            state.process_event(event)
            if 'I' in event.params:
                arc_i_values.append(event.params['I'])
            if 'J' in event.params:
                arc_j_values.append(event.params['J'])
            arc_distances.append(state.distance_to_last())

        self.stats['arcs'] = {
            'count_g2': len([e for e in self.arc_events if e.command == 'G2']),
            'count_g3': len([e for e in self.arc_events if e.command == 'G3']),
            'total': len(self.arc_events),
            'i_values': {
                'min': min(arc_i_values) if arc_i_values else 0,
                'max': max(arc_i_values) if arc_i_values else 0,
                'count': len(arc_i_values),
            },
            'j_values': {
                'min': min(arc_j_values) if arc_j_values else 0,
                'max': max(arc_j_values) if arc_j_values else 0,
                'count': len(arc_j_values),
            },
            'endpoint_distances': {
                'min': min(arc_distances) if arc_distances else 0,
                'max': max(arc_distances) if arc_distances else 0,
                'mean': (sum(arc_distances) / len(arc_distances)) if arc_distances else 0,
            },
        }

    def _compile_statistics(self):
        """Allgemeine Statistiken."""
        stats = {
            'total_events': len(self.events),
            'travel_lines': len(self.travel_lines),
            'extrusion_lines': len(self.extrusion_lines),
        }
        self.stats['overview'] = stats


# =============================================================================
# DIVERGENZANALYSE
# =============================================================================

def find_first_divergence(file_a: str, file_b: str, tolerance: float = 0.001):
    """
    Findet die erste geometrische Divergenz zwischen zwei GCode-Dateien.

    Vergleicht:
    - Positionen (X, Y, Z)
    - Extruder-Werte (E)
    - Befehls-Typen

    Args:
        file_a: Pfad zur ersten Datei (Original)
        file_b: Pfad zur zweiten Datei (Verarbeitet)
        tolerance: Toleranz für Positionsvergleiche

    Returns:
        Dict mit Divergenz-Information oder None
    """
    parser = GCodeParser()
    events_a = parser.parse_file(file_a)
    events_b = parser.parse_file(file_b)

    state_a = GCodeState()
    state_b = GCodeState()

    min_len = min(len(events_a), len(events_b))

    for i in range(min_len):
        event_a = events_a[i]
        event_b = events_b[i]

        state_a.process_event(event_a)
        state_b.process_event(event_b)

        # Prüfe: Gleicher Befehl?
        if event_a.command != event_b.command:
            return {
                'type': 'command_mismatch',
                'line_idx': i,
                'expected': event_a.command,
                'actual': event_b.command,
                'raw_a': event_a.raw.strip(),
                'raw_b': event_b.raw.strip(),
            }

        # Prüfe: Positionen (wenn beide XY haben)
        if event_a.has_xy and event_b.has_xy:
            if (abs(state_a.current_x - state_b.current_x) > tolerance or
                abs(state_a.current_y - state_b.current_y) > tolerance):
                return {
                    'type': 'position_divergence',
                    'line_idx': i,
                    'expected': (state_a.current_x, state_a.current_y),
                    'actual': (state_b.current_x, state_b.current_y),
                    'delta_x': state_a.current_x - state_b.current_x,
                    'delta_y': state_a.current_y - state_b.current_y,
                    'raw_a': event_a.raw.strip(),
                    'raw_b': event_b.raw.strip(),
                }

        # Prüfe: E-Werte (wenn beide E haben)
        if event_a.has_e and event_b.has_e:
            if abs(state_a.current_e - state_b.current_e) > tolerance:
                return {
                    'type': 'extrusion_divergence',
                    'line_idx': i,
                    'expected': state_a.current_e,
                    'actual': state_b.current_e,
                    'delta': state_a.current_e - state_b.current_e,
                    'raw_a': event_a.raw.strip(),
                    'raw_b': event_b.raw.strip(),
                }

    return None  # Keine Divergenz gefunden


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt die Analyse auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='GCode Analysis Runner'
    )
    parser_arg.add_argument('file', nargs='?',
                           default='fixtures/minimal_test.gcode',
                           help='GCode-Datei für die Analyse')
    parser_arg.add_argument('--compare', '-c', metavar='FILE',
                           help='Zweite Datei für Divergenzanalyse')
    parser_arg.add_argument('--json', '-j', action='store_true',
                           help='Ausgabe als JSON')
    parser_arg.add_argument('--output', '-o',
                           help='Analyse in Datei speichern')

    args = parser_arg.parse_args()

    # Parser
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Datei nicht gefunden: {filepath}")
        sys.exit(1)

    parser = GCodeParser()
    events = parser.parse_file(str(filepath))

    # Analyse
    analyzer = GCodeAnalyzer(events)
    stats = analyzer.run_all()

    # Ausgabe
    if args.json:
        output = json.dumps(stats, indent=2, default=str)
        print(output)
    else:
        _print_pretty(stats, filepath.name)

    # Speichern
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, default=str)
        print(f"\nAnalyse gespeichert: {args.output}")

    # Divergenzanalyse
    if args.compare:
        compare_path = Path(args.compare)
        if not compare_path.exists():
            print(f"Vergleichsdatei nicht gefunden: {compare_path}")
        else:
            print("\n" + "=" * 60)
            print(f"DIVERGENZANALYSE: {filepath.name} vs {compare_path.name}")
            print("=" * 60)
            div = find_first_divergence(str(filepath), str(compare_path))
            if div is None:
                print("KEINE DIVERGENZ GEFUNDEN.")
            else:
                print(f"ERSTE DIVERGENZ in Zeile {div['line_idx']}:")
                print(f"  Typ: {div['type']}")
                for k, v in div.items():
                    if k != 'type':
                        print(f"  {k}: {v}")


def _print_pretty(stats: Dict, filename: str):
    """Formatierte Ausgabe der Analyseergebnisse."""
    print("=" * 60)
    print(f"GCODE-ANALYSE: {filename}")
    print("=" * 60)

    # Übersicht
    ov = stats.get('overview', {})
    print(f"\n📊 ÜBERSICHT")
    print(f"  Events:      {ov.get('total_events', 0)}")
    print(f"  Extrusion:   {ov.get('extrusion_lines', 0)}")
    print(f"  Travel:      {ov.get('travel_lines', 0)}")

    # Travel/Extrusion
    te = stats.get('travel_extrusion_ratio', {})
    print(f"\n📏 TRAVEL vs EXTRUSION")
    print(f"  Travel gesamt:      {te.get('travel_mm', 0):.2f} mm ({te.get('travel_pct', 0):.1f}%)")
    print(f"  Extrusion gesamt:   {te.get('extrusion_mm', 0):.2f} mm ({te.get('extrusion_pct', 0):.1f}%)")
    print(f"  Travel Moves:       {te.get('travel_moves', 0)}")
    print(f"  Extrusion Moves:    {te.get('extrusion_moves', 0)}")

    # E-Deltas
    ed = stats.get('e_deltas', {})
    print(f"\n🧵 E-DELTAS")
    print(f"  Positive Deltas:    {ed.get('count_positive', 0)}")
    print(f"  Negative Deltas:    {ed.get('count_negative', 0)}")
    print(f"  Extrusion gesamt:   {ed.get('total_extrusion', 0):.4f} mm")
    print(f"  Max positives Delta: {ed.get('max_positive', 0):.5f}")
    print(f"  Min negatives Delta: {ed.get('max_negative', 0):.5f}")

    # Distanzen
    dist = stats.get('distances', {})
    for key, label in [('extrusion', 'Extrusion'), ('travel', 'Travel')]:
        d = dist.get(key, {})
        if d and d.get('count', 0) > 0:
            print(f"\n📐 {label}-DISTANZEN")
            print(f"  Anzahl:  {d.get('count', 0)}")
            print(f"  Gesamt:  {d.get('total', 0):.2f} mm")
            print(f"  Mittel:  {d.get('mean', 0):.2f} mm")
            print(f"  Max:     {d.get('max', 0):.2f} mm")
            print(f"  Min:     {d.get('min', 0):.2f} mm")

    # Layer
    layers = stats.get('layers', {})
    layer_count = layers.get('count', 0)
    print(f"\n🗂️  LAYER")
    print(f"  Layer gesamt: {layer_count}")
    if 'types_per_layer' in layers:
        types = layers['types_per_layer']
        type_counts = Counter()
        for layer_types in types.values():
            for t in layer_types:
                type_counts[t] += 1
        if type_counts:
            print(f"  Typen-Verteilung:")
            for t, c in type_counts.most_common():
                print(f"    {t}: {c}x")

    # Wipe-Kandidaten
    wipes = stats.get('wipe_candidates', {})
    wipe_count = wipes.get('count', 0)
    print(f"\n🧹 WIPE-KANDIDATEN (>{wipes.get('threshold_mm', 5)}mm + E>0)")
    print(f"  Gefunden: {wipe_count}")
    for w in wipes.get('candidates', [])[:10]:
        print(f"  [{w.get('line_idx')}] {w.get('distance_mm', 0):.1f}mm, "
              f"E={w.get('e_delta', 0):.4f}, "
              f"Typ={w.get('type')}, "
              f"Layer={w.get('layer')}")

    # Arcs
    arcs = stats.get('arcs', {})
    if arcs.get('total', 0) > 0:
        print(f"\n🌀 ARCS")
        print(f"  G2 (CW): {arcs.get('count_g2', 0)}")
        print(f"  G3 (CCW): {arcs.get('count_g3', 0)}")
        print(f"  Gesamt: {arcs.get('total', 0)}")

    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()