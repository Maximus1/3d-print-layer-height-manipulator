#!/usr/bin/env python3
"""
Contour Extractor – Nur Zustands- und Sequenzlogik
===================================================
Extrahiert Konturen aus GCode-Daten basierend auf der Bewegungssequenz.

Regeln:
- KEINE Geometrieannahmen (nicht prüfen ob geschlossen, ob sinnvoll)
- KEINE Wipeannahmen
- KEINE Arcannahmen
- NUR Zustands- und Sequenzlogik

Eine Kontur ist definiert als:
- Eine Sequenz von Extrusionsbewegungen
- die durch Travel-Moves getrennt sind
- innerhalb eines Layers

Konturwechsel:
- Travel-Move (G0 ohne E) beendet die aktuelle Kontur
- Nächste Extrusion startet eine neue Kontur
- Layer-Wechsel resetet den Konturzähler
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
# KONTUR-DATENSTRUKTUR
# =============================================================================

class Contour:
    """
    Eine einzelne Kontur: Sequenz von Extrusionsbewegungen.

    Attribute:
        contour_id: Eindeutige ID (layer.contour_number)
        layer: Layer-Nummer
        contour_number: Kontur-Nummer innerhalb des Layers
        events: Liste der GCodeEvents in dieser Kontur
        type_tag: TYPE der Kontur (z.B. 'WALL-OUTER')
        start_xy: Startposition (x, y)
        end_xy: Endposition (x, y)
        total_extrusion: Summe der E-Deltas
        total_distance: Summe der XY-Distanzen
        is_open: Ob die Kontur nicht geschlossen ist (Start != Ende)
    """

    __slots__ = (
        'contour_id', 'layer', 'contour_number',
        'events', 'type_tag',
        'start_xy', 'end_xy',
        'total_extrusion', 'total_distance', 'is_open',
        'start_line_idx', 'end_line_idx',
    )

    def __init__(self, contour_id: str, layer: int, contour_number: int):
        self.contour_id = contour_id
        self.layer = layer
        self.contour_number = contour_number
        self.events: List[GCodeEvent] = []
        self.type_tag: Optional[str] = None
        self.start_xy: Optional[Tuple[float, float]] = None
        self.end_xy: Optional[Tuple[float, float]] = None
        self.total_extrusion: float = 0.0
        self.total_distance: float = 0.0
        self.is_open: bool = False
        self.start_line_idx: Optional[int] = None
        self.end_line_idx: Optional[int] = None

    def add_event(self, event: GCodeEvent, dist: float, e_delta: float,
                  position: Tuple[float, float]):
        """Fügt ein Event zur Kontur hinzu."""
        if not self.events:
            self.start_xy = position
            self.start_line_idx = event.line_idx
            if event.type_tag:
                self.type_tag = event.type_tag

        self.events.append(event)
        self.end_xy = position
        self.end_line_idx = event.line_idx
        self.total_extrusion += e_delta
        self.total_distance += dist

        # Type-Tag kann sich innerhalb der Kontur ändern
        if event.type_tag:
            self.type_tag = event.type_tag

    def finalize(self):
        """Schließt die Kontur ab: berechnet is_open."""
        if self.start_xy and self.end_xy:
            dx = self.end_xy[0] - self.start_xy[0]
            dy = self.end_xy[1] - self.start_xy[1]
            gap = math.sqrt(dx ** 2 + dy ** 2)
            self.is_open = gap > 0.01  # > 10µm gilt als offen

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Kontur in ein Dict (für Analyse/Logging)."""
        return {
            'contour_id': self.contour_id,
            'layer': self.layer,
            'contour_number': self.contour_number,
            'type_tag': self.type_tag,
            'start_xy': self.start_xy,
            'end_xy': self.end_xy,
            'is_open': self.is_open,
            'total_extrusion': round(self.total_extrusion, 5),
            'total_distance': round(self.total_distance, 3),
            'num_events': len(self.events),
            'start_line_idx': self.start_line_idx,
            'end_line_idx': self.end_line_idx,
        }

    def __repr__(self) -> str:
        return (
            f"Contour({self.contour_id}: "
            f"type={self.type_tag}, "
            f"events={len(self.events)}, "
            f"ext={self.total_extrusion:.3f}, "
            f"dist={self.total_distance:.1f}mm, "
            f"{'OPEN' if self.is_open else 'CLOSED'})"
        )


# =============================================================================
# CONTOUR EXTRACTOR
# =============================================================================

class ContourExtractor:
    """
    Extrahiert Konturen aus GCode-Events.
    - NUR Zustands- und Sequenzlogik
    - KEINE Geometrieannahmen
    - KEINE Wipe/Arc-Annahmen
    """

    def __init__(self, events: List[GCodeEvent]):
        self.events = events
        self.contours: List[Contour] = []
        self._state = GCodeState()

        # Mapping: layer -> [contours]
        self._layer_contours: Dict[int, List[Contour]] = defaultdict(list)

    def extract_all(self) -> List[Contour]:
        """
        Extrahiert alle Konturen aus der Event-Liste.
        Konturwechsel bei:
        1. Travel-Move (G0 ohne E oder Bewegung während Retract)
        2. Layer-Wechsel
        3. Extrusion nach Travel = neue Kontur
        """
        self.contours = []
        self._layer_contours = defaultdict(list)

        current_contour: Optional[Contour] = None
        was_travel = True  # Start: kein aktiver Kontur

        for event in self.events:
            self._state.process_event(event)

            # Layer-Wechsel: aktuelle Kontur abschließen
            if event.is_layer_change:
                if current_contour is not None:
                    current_contour.finalize()
                    self.contours.append(current_contour)
                    current_contour = None
                was_travel = True
                continue

            # Nur Bewegungsbefehle mit XY
            if event.command not in ('G0', 'G1', 'G2', 'G3'):
                continue
            if not event.has_xy:
                continue

            dist = self._state.distance_to_last()
            is_extrusion = self._is_extrusion(event)

            if is_extrusion:
                e_delta = self._state.get_e_delta() if event.has_e else 0.0

                # Travel beendet die alte Kontur
                if was_travel and current_contour is not None:
                    current_contour.finalize()
                    self.contours.append(current_contour)
                    current_contour = None

                # Neue Kontur starten
                if current_contour is None:
                    contour_num = len(self._layer_contours[self._state.current_layer]) + 1
                    contour_id = f"L{self._state.current_layer}.C{contour_num}"
                    current_contour = Contour(
                        contour_id=contour_id,
                        layer=self._state.current_layer,
                        contour_number=contour_num,
                    )
                    self._layer_contours[self._state.current_layer].append(current_contour)

                    # Type-Tag vom aktuellen State übernehmen
                    # (TYPE ist ein separater Kommentar, nicht im Bewegungs-Event)
                    if self._state.current_type and current_contour.type_tag is None:
                        current_contour.type_tag = self._state.current_type

                current_contour.add_event(
                    event=event,
                    dist=dist,
                    e_delta=e_delta,
                    position=(self._state.current_x, self._state.current_y),
                )
                was_travel = False

            else:
                # Travel: wenn wir in einer Kontur waren, schließen
                was_travel = True

        # Letzte Kontur abschließen
        if current_contour is not None:
            current_contour.finalize()
            self.contours.append(current_contour)

        return self.contours

    def _is_extrusion(self, event: GCodeEvent) -> bool:
        """
        Prüft ob ein Event eine Extrusion ist.
        Verwendet den aktuellen State für korrekte Entscheidung.

        Kriterien:
        - hat E-Parameter
        - nicht retracted
        - XY-Bewegung vorhanden
        - E-Delta > 0
        """
        if not event.has_e:
            return False
        if self._state.is_retracted:
            return False
        if not event.has_xy:
            return False

        e_delta = self._state.get_e_delta()
        dist = self._state.distance_to_last()

        return e_delta > 0 and dist > 0

    def get_contours_by_layer(self, layer: int) -> List[Contour]:
        """Alle Konturen eines Layers."""
        return list(self._layer_contours.get(layer, []))

    def get_contours_by_type(self, type_tag: str) -> List[Contour]:
        """Alle Konturen mit einem bestimmten TYPE-Tag."""
        return [c for c in self.contours if c.type_tag == type_tag]

    def get_summary(self) -> Dict[str, Any]:
        """Zusammenfassung der extrahierten Konturen."""
        by_type = defaultdict(int)
        open_count = 0
        total_extrusion = 0.0
        total_distance = 0.0

        for c in self.contours:
            by_type[c.type_tag or 'unknown'] += 1
            if c.is_open:
                open_count += 1
            total_extrusion += c.total_extrusion
            total_distance += c.total_distance

        return {
            'total_contours': len(self.contours),
            'layers': len(self._layer_contours),
            'by_type': dict(by_type),
            'open_contours': open_count,
            'closed_contours': len(self.contours) - open_count,
            'total_extrusion': round(total_extrusion, 5),
            'total_distance': round(total_distance, 3),
            'contours_per_layer': {
                str(k): len(v)
                for k, v in sorted(self._layer_contours.items())
            },
        }


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt die Konturextraktion auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Contour Extractor – Zustands- und Sequenzlogik'
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

    extractor = ContourExtractor(events)
    contours = extractor.extract_all()
    summary = extractor.get_summary()

    if args.json:
        import json
        print(json.dumps({
            'summary': summary,
            'contours': [c.to_dict() for c in contours],
        }, indent=2, default=str))
    else:
        print("=" * 60)
        print(f"CONTOUR EXTRACTOR: {filepath.name}")
        print("=" * 60)
        print(f"\n📊 ZUSAMMENFASSUNG")
        print(f"  Konturen gesamt: {summary['total_contours']}")
        print(f"  Layer:           {summary['layers']}")
        print(f"  Geschlossen:     {summary['closed_contours']}")
        print(f"  Offen:           {summary['open_contours']}")
        print(f"  Extrusion total: {summary['total_extrusion']:.4f} mm")
        print(f"  Distanz total:   {summary['total_distance']:.1f} mm")
        if summary['by_type']:
            print(f"\n  Typen:")
            for t, c in sorted(summary['by_type'].items()):
                print(f"    {t}: {c}x")

        if contours:
            print(f"\n📋 KONTUREN:")
            print("-" * 60)
            for c in contours:
                print(f"  {c}")


if __name__ == '__main__':
    main()