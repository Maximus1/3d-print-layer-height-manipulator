#!/usr/bin/env python3
"""
Sublayer Processor – Kontrollierte Extrusions-Skalierung
=========================================================
Darf NUR auf validierte Konturen angewendet werden.

Darf:
* Extrusionsmengen skalieren
* Z-Höhen aufteilen
* Feedrates anpassen

Darf NICHT:
* Konturen neu interpretieren
* Wipes erkennen
* Travel klassifizieren
* Arcs reparieren
* Zustände korrigieren

INPUT: Nur bereits validierte Konturen.
OUTPUT: Transformierte GCode-Events.
"""

import sys
import math
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeEvent
from logging_system import get_logger, snapshot_from_state, close_all


# =============================================================================
# SUBLAYER-KONFIGURATION
# =============================================================================

class SublayerConfig:
    """
    Konfiguration der Sublayer-Aufteilung.
    Alle Werte sind parametrisierbar und dokumentiert.
    """

    __slots__ = (
        'base_layer_height', 'sublayer_height',
        'num_sublayers', 'scale_extrusion',
        'scale_feedrate', 'target_types',
    )

    def __init__(self):
        self.base_layer_height: float = 0.1   # mm
        self.sublayer_height: float = 0.05    # mm
        self.num_sublayers: int = 2
        self.scale_extrusion: bool = True
        self.scale_feedrate: bool = False
        self.target_types: List[str] = ['WALL-OUTER', 'WALL-INNER']


# =============================================================================
# SUBLAYER-PROZESSOR
# =============================================================================

class SublayerProcessor:
    """
    Verarbeitet Konturen in Sublayer.
    - NUR Transformation
    - KEINE Analyse
    - KEINE Entscheidungen
    """

    def __init__(self, config: Optional[SublayerConfig] = None):
        self.config = config or SublayerConfig()
        self.log = get_logger('sublayer_processor')
        self._current_e: float = 0.0  # Für absolute E-Skalierung
        self._global_e: float = 0.0   # Über Konturen hinweg
        self._stats = {
            'contours_processed': 0,
            'events_generated': 0,
            'extrusion_scaled': 0.0,
        }

    def process_contour(self, contour, events: List[GCodeEvent],
                        state_snapshot: dict) -> List[str]:
        """
        Verarbeitet eine einzelne Kontur in Sublayer.

        Args:
            contour: Contour-Objekt (aus contour_extractor)
            events: Original-Events dieser Kontur
            state_snapshot: Zustandssnapshot der umgebenden Pipeline

        Returns:
            Liste neuer GCode-Events (oder None wenn nicht verarbeitet)
        """
        # Nur konfigurierte Typen verarbeiten
        if contour.type_tag not in self.config.target_types:
            self.log.info('contour_skipped',
                         line_number=contour.start_line_idx or 0,
                         command=f'contour {contour.contour_id}',
                         decision='skipped',
                         reason=f'type {contour.type_tag} not in target_types')
            return events

        # Aktuellen E-Wert: Aus dem State-Snapshot übernehmen
        # oder aus Events berechnen
        if not state_snapshot.get('modes', {}).get('relative_e', False):
            # State-Snapshot enthält den aktuellen E-Wert
            self._current_e = state_snapshot.get('current_e', self._global_e)
            # Prüfe ob Events einen G92 Reset haben
            for prev_event in events:
                if prev_event.command in ('G92',) and 'E' in prev_event.params:
                    self._current_e = prev_event.params['E']
            self._global_e = self._current_e

        self.log.info('contour_processing_start',
                     line_number=contour.start_line_idx or 0,
                     command=f'contour {contour.contour_id}',
                     decision='processing',
                     reason=f'type={contour.type_tag}, events={len(events)}, '
                            f'start_e={self._current_e:.3f}',
                     geometry={
                         'distance_mm': contour.total_distance,
                         'extrusion_mm': contour.total_extrusion,
                     },
                     state_snapshot=state_snapshot)

        result = self._split_contour(contour, events, state_snapshot)

        # Globalen E-Wert nach Kontur aktualisieren
        if not state_snapshot.get('modes', {}).get('relative_e', False):
            self._global_e = self._current_e

        self._stats['contours_processed'] += 1
        self._stats['events_generated'] += len(result) - len(events)
        self._stats['extrusion_scaled'] += contour.total_extrusion * (
            self.config.num_sublayers - 1
        )

        self.log.info('contour_processing_end',
                     line_number=contour.end_line_idx or 0,
                     command=f'contour {contour.contour_id}',
                     decision='completed',
                     reason=f'generated {len(result)} events from {len(events)}')

        return result

    def _split_contour(self, contour, events: List[GCodeEvent],
                       state_snapshot: dict) -> List[GCodeEvent]:
        """
        Teilt eine Kontur in Sublayer auf.
        """
        result = []

        for sublayer_idx in range(self.config.num_sublayers):
            z_offset = sublayer_idx * self.config.sublayer_height
            scale = 1.0 / self.config.num_sublayers

            for event in events:
                new_event = self._transform_event(
                    event, sublayer_idx, z_offset, scale, state_snapshot
                )
                if new_event is not None:
                    result.append(new_event)

        return result

    def _transform_event(self, event: GCodeEvent,
                         sublayer_idx: int,
                         z_offset: float,
                         scale: float,
                         state_snapshot: dict) -> Optional[str]:
        """
        Transformiert ein einzelnes Event.
        - Skaliert E-Werte
        - Passt Z-Höhen an
        - Gibt modifizierte Roh-Zeile zurück oder None

        Args:
            event: Original-Event
            sublayer_idx: Index des Sublayers (0-basiert)
            z_offset: Z-Offset für diesen Sublayer
            scale: Skalierungsfaktor für E
            state_snapshot: Zustand zum Zeitpunkt der Kontur

        Returns:
            Modifizierte GCode-Zeile oder None (für Nicht-Bewegungen)
        """
        if event.command not in ('G0', 'G1', 'G2', 'G3'):
            return event.raw

        raw = event.raw.rstrip('\n')
        code_part = raw.split(';')[0]
        comment = ''
        if ';' in raw:
            comment = ';' + raw.split(';', 1)[1]

        modified = code_part

        # Z-Höhe anpassen
        if 'Z' in event.params:
            new_z = event.params['Z'] + z_offset
            # Z im code_part ersetzen
            modified = self._replace_param(modified, 'Z', new_z)

        # E-Wert skalieren
        # ACHTUNG: Im absoluten Modus (M82) ist E-Skalierung NICHT möglich,
        # weil absolute E-Werte aufsteigend sein müssen und Skalierung
        # nicht-aufsteigende Werte erzeugt.
        # Nur im relativen Modus (M83) ist E-Skalierung sicher.
        if event.has_e and self.config.scale_extrusion:
            e_value = event.params['E']
            if state_snapshot.get('modes', {}).get('relative_e', False):
                # Relativer Modus: E-Wert direkt skalieren
                scaled_e = e_value * scale
                modified = self._replace_param(modified, 'E', scaled_e)
            # Im absoluten Modus: E-Wert NICHT ändern

        return modified + comment + '\n'

    def _replace_param(self, code: str, param: str, value: float) -> str:
        """Ersetzt einen Parameter im code_part."""
        import re
        fmt = f'{value:.5f}'.rstrip('0').rstrip('.')
        pattern = rf'(?<![A-Za-z0-9.]){param}[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?'
        if re.search(pattern, code, re.I):
            return re.sub(pattern, f'{param}{fmt}', code, flags=re.I)
        return code

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._stats)


# =============================================================================
# MAIN (TEST)
# =============================================================================

def main():
    """Testet den Sublayer-Prozessor."""
    from gcode_parser import GCodeParser
    from contour_extractor import ContourExtractor

    parser = GCodeParser()
    events = parser.parse_file('fixtures/minimal_test.gcode')

    extractor = ContourExtractor(events)
    contours = extractor.extract_all()

    config = SublayerConfig()
    config.target_types = ['SKIN', 'WALL-OUTER']

    processor = SublayerProcessor(config)

    for contour in contours:
        if contour.type_tag not in config.target_types:
            continue
        contour_events = [events[i] for i in range(
            contour.start_line_idx or 0,
            (contour.end_line_idx or 0) + 1
        ) if i < len(events)]
        result = processor.process_contour(
            contour, contour_events,
            {'modes': {'relative_e': False}}
        )
        print(f"  {contour.contour_id}: {len(contour_events)} → {len(result)} Events")

    print(f"\nStats: {processor.get_stats()}")
    close_all()


if __name__ == '__main__':
    main()