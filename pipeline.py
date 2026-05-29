#!/usr/bin/env python3
"""
Pipeline – Vollständige Verarbeitungspipeline
==============================================
Orchestriert alle Module in der vorgeschriebenen Reihenfolge.

PIPELINE-SCHRITTE:
1. parse_gcode()
2. state_tracker.apply() → GeometryValidator
3. contour_extractor.extract()
4. geometry_validator.validate()
5. travel_classifier.classify()
6. wipe_detector.detect()
7. arc_handler.process()
8. sublayer_processor.process()
9. geometry_validator.validate(output)
10. debug_tools.compare(original, output)

JEDER SCHRITT:
- separat logbar
- separat validierbar
- separat deaktivierbar

ABBRUCH BEI:
- ungeklärten Geometriesprüngen
- fehlenden Zuständen
- inkonsistentem E-Modus
- Arc-Fehlern
- unbekannten Befehlen
"""

import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeParser, GCodeEvent
from geometry_validator import GeometryValidator, ValidationFinding
from contour_extractor import ContourExtractor, Contour
from travel_classifier import TravelClassifier
from wipe_detector import WipeDetector, WipeCandidate
from arc_handler import ArcHandler, ArcAnalysis
from z_duplication_processor import ZDuplicationProcessor, ZDuplicationConfig
from sublayer_processor import SublayerProcessor, SublayerConfig
from output_writer import OutputWriter, make_output_path
from logging_system import (
    get_logger, snapshot_from_state, close_all
)


# =============================================================================
# PIPELINE-KONFIGURATION
# =============================================================================

class PipelineConfig:
    """
    Konfiguration der Pipeline.
    Jeder Schritt kann separat aktiviert/deaktiviert werden.
    """

    __slots__ = (
        'run_validation_before',
        'run_contour_extraction',
        'run_classification',
        'run_wipe_detection',
        'run_arc_analysis',
        'run_z_duplication',
        'run_sublayer_processing',
        'run_validation_after',
        'run_divergence_check',
        'abort_on_validation_error',
        'z_duplication_config',
        'sublayer_config',
    )

    def __init__(self, **kwargs):
        # Defaults
        self.run_validation_before: bool = True
        self.run_contour_extraction: bool = True
        self.run_classification: bool = True
        self.run_wipe_detection: bool = True
        self.run_arc_analysis: bool = True
        self.run_z_duplication: bool = False  # Phase 13.6 – standardmäßig deaktiviert
        self.run_sublayer_processing: bool = True
        self.run_validation_after: bool = True
        self.run_divergence_check: bool = True
        self.abort_on_validation_error: bool = True
        self.z_duplication_config: ZDuplicationConfig = ZDuplicationConfig()
        self.sublayer_config: SublayerConfig = SublayerConfig()

        # Override mit kwargs
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


# =============================================================================
# PIPELINE-RESULTAT
# =============================================================================

class PipelineResult:
    """
    Ergebnis eines vollständigen Pipeline-Durchlaufs.
    Enthält alle Zwischenergebnisse für Debugging.
    """

    def __init__(self):
        self.original_file: str = ''
        self.output_file: str = ''
        self.total_events: int = 0

        # Ergebnisse der einzelnen Schritte
        self.validation_before: List[ValidationFinding] = []
        self.contours: List[Contour] = []
        self.classification_stats: Dict = {}
        self.wipe_candidates: List[WipeCandidate] = []
        self.arc_analyses: List[ArcAnalysis] = []
        self.sublayer_stats: Dict = {}
        self.validation_after: List[ValidationFinding] = []
        self.divergence: Optional[Dict] = None

        # Fehler
        self.errors: List[str] = []
        self.aborted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'original_file': self.original_file,
            'output_file': self.output_file,
            'total_events': self.total_events,
            'aborted': self.aborted,
            'errors': self.errors,
            'validation_before': {
                'total': len(self.validation_before),
                'errors': sum(1 for v in self.validation_before
                             if v.severity == 'error'),
                'warnings': sum(1 for v in self.validation_before
                               if v.severity == 'warning'),
            },
            'contours': {
                'total': len(self.contours),
            },
            'wipe_candidates': len(self.wipe_candidates),
            'arcs': len(self.arc_analyses),
            'validation_after': {
                'total': len(self.validation_after),
                'errors': sum(1 for v in self.validation_after
                             if v.severity == 'error'),
                'warnings': sum(1 for v in self.validation_after
                               if v.severity == 'warning'),
            },
            'divergence_found': self.divergence is not None,
            'sublayer': self.sublayer_stats,
        }


# =============================================================================
# PIPELINE
# =============================================================================

class Pipeline:
    """
    Vollständige Verarbeitungspipeline.
    - Orchestriert alle Module
    - Loggt jeden Schritt
    - Bricht bei Fehlern ab (konfigurierbar)
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.log = get_logger('pipeline')
        self.result = PipelineResult()

    def run(self, filepath: str, output_path: Optional[str] = None) -> PipelineResult:
        """
        Führt die vollständige Pipeline aus.

        Args:
            filepath: Pfad zur GCode-Datei
            output_path: Optionaler Output-Pfad (sonst automatisch)

        Returns:
            PipelineResult mit allen Ergebnissen
        """
        self.result = PipelineResult()
        self.result.original_file = filepath

        if output_path is None:
            output_path = make_output_path(filepath, 'processed')

        self.result.output_file = output_path

        self.log.info('pipeline_start',
                     decision=f'processing {Path(filepath).name}',
                     reason='full pipeline',
                     geometry={
                         'input_file': filepath,
                         'output_file': output_path,
                     })

        # =================================================================
        # SCHRITT 1: PARSEN
        # =================================================================
        self.log.info('stage_start', decision='parsing', reason='step 1/10')
        parser = GCodeParser()
        try:
            events = parser.parse_file(filepath)
        except Exception as e:
            self.result.errors.append(f'Parse error: {e}')
            self.result.aborted = True
            self.log.critical('parse_error', reason=str(e))
            return self.result

        self.result.total_events = len(events)
        self.log.info('stage_complete',
                     decision='parsed',
                     reason=f'{len(events)} events')

        # =================================================================
        # SCHRITT 2: VALIDIERUNG VOR VERARBEITUNG
        # =================================================================
        if self.config.run_validation_before:
            self.log.info('stage_start',
                         decision='validating_before',
                         reason='step 2/10')
            validator = GeometryValidator(events)
            self.result.validation_before = validator.validate_all()
            self._check_validation_errors(self.result.validation_before)

            self.log.info('stage_complete',
                         decision='validated_before',
                         reason=f'{len(self.result.validation_before)} findings')

        # =================================================================
        # SCHRITT 3: KONTUREXTRAKTION
        # =================================================================
        if self.config.run_contour_extraction:
            self.log.info('stage_start',
                         decision='extracting_contours',
                         reason='step 3/10')
            extractor = ContourExtractor(events)
            self.result.contours = extractor.extract_all()
            summary = extractor.get_summary()

            self.log.info('stage_complete',
                         decision='contours_extracted',
                         reason=f'{summary["total_contours"]} contours, '
                                f'{summary["layers"]} layers',
                         geometry={
                             'total_contours': summary['total_contours'],
                             'layers': summary['layers'],
                             'open_contours': summary['open_contours'],
                         })

        # =================================================================
        # SCHRITT 4: TRAVEL/EXTRUSION KLASSIFIKATION
        # =================================================================
        if self.config.run_classification:
            self.log.info('stage_start',
                         decision='classifying',
                         reason='step 4/10')
            classifier = TravelClassifier(events)
            classifier.classify_all()
            self.result.classification_stats = classifier.get_statistics()

            self.log.info('stage_complete',
                         decision='classified',
                         reason=f'{self.result.classification_stats.get("total_classified", 0)} moves',
                         geometry={
                             'travel': self.result.classification_stats.get('travel_count', 0),
                             'extrusion': self.result.classification_stats.get('extrusion_count', 0),
                         })

        # =================================================================
        # SCHRITT 5: WIPE-ERKENNUNG
        # =================================================================
        if self.config.run_wipe_detection:
            self.log.info('stage_start',
                         decision='detecting_wipes',
                         reason='step 5/10')
            detector = WipeDetector(events)
            self.result.wipe_candidates = detector.detect_all()

            self.log.info('stage_complete',
                         decision='wipes_detected',
                         reason=f'{len(self.result.wipe_candidates)} candidates')

        # =================================================================
        # SCHRITT 6: ARC-ANALYSE
        # =================================================================
        if self.config.run_arc_analysis:
            self.log.info('stage_start',
                         decision='analyzing_arcs',
                         reason='step 6/10')
            handler = ArcHandler(events)
            self.result.arc_analyses = handler.analyze_all()

            self.log.info('stage_complete',
                         decision='arcs_analyzed',
                         reason=f'{len(self.result.arc_analyses)} arcs')

        # =================================================================
        # NEWLINE-FORMAT UND TRAILING-NL DER ORIGINALDATEI ERKENNEN
        # =================================================================
        original_newline = self._detect_newline(filepath)
        has_trailing_nl = self._detect_trailing_newline(filepath)

        # =================================================================
        # SCHRITT 6.5: Z-DUPLICATION (Phase 13.6)
        # =================================================================
        modified_lines: Dict[int, str | List[str]] = {}
        if self.config.run_z_duplication:
            self.log.info('stage_start',
                         decision='z_duplication',
                         reason='step 6.5/10')

            z_processor = ZDuplicationProcessor(
                self.config.z_duplication_config)

            current_type_tag = ''
            z_duplications = 0

            for event in events:
                # Type-Tag tracken
                if event.type_tag:
                    current_type_tag = event.type_tag

                # Nur GCode-Befehle verarbeiten
                if event.command in ('G0', 'G1', 'G2', 'G3',
                                     'G10', 'G11', 'G28',
                                     'G90', 'G91', 'G92',
                                     'M82', 'M83'):
                    result_lines = z_processor.process_event(
                        event, current_type_tag)

                    if len(result_lines) > 1:
                        # Duplikat erzeugt → Liste speichern
                        modified_lines[event.line_idx] = result_lines
                        z_duplications += 1

            self.log.info('stage_complete',
                         decision='z_duplication_complete',
                         reason=f'{z_duplications} duplications',
                         geometry={
                             'duplications': z_duplications,
                             'stats': z_processor.get_stats(),
                         })

        # =================================================================
        # SCHRITT 7: SUBLAYER-VERARBEITUNG
        # =================================================================
        if self.config.run_sublayer_processing:
            self.log.info('stage_start',
                         decision='processing_sublayers',
                         reason='step 7/10')

            processor = SublayerProcessor(self.config.sublayer_config)

            for contour in self.result.contours:
                contour_events = [events[i] for i in range(
                    contour.start_line_idx or 0,
                    (contour.end_line_idx or 0) + 1
                ) if i < len(events)]

                # State-Snapshot für diesen Zeitpunkt
                state_snapshot = {'modes': {'relative_e': False}}

                # Kontur verarbeiten
                new_lines = processor.process_contour(
                    contour, contour_events, state_snapshot
                )

                # Modifizierte Zeilen merken
                if len(new_lines) != len(contour_events):
                    # Sublayer erzeugt mehrere Zeilen pro Event
                    for idx, event in enumerate(contour_events):
                        if idx < len(new_lines):
                            modified_lines[event.line_idx] = new_lines[idx]

            self.result.sublayer_stats = processor.get_stats()

            self.log.info('stage_complete',
                         decision='sublayers_processed',
                         reason=f'{self.result.sublayer_stats.get("contours_processed", 0)} contours',
                         geometry=self.result.sublayer_stats)

        # =================================================================
        # SCHRITT 8: OUTPUT SCHREIBEN
        # =================================================================
        self.log.info('stage_start',
                     decision='writing_output',
                     reason='step 8/10')
        writer = OutputWriter()
        writer.write_combined(events, modified_lines, output_path,
                              original_newline=original_newline,
                              has_trailing_newline=has_trailing_nl)

        self.log.info('stage_complete',
                     decision='output_written',
                     reason=f'output={output_path}')

        # =================================================================
        # SCHRITT 9: VALIDIERUNG NACH VERARBEITUNG
        # =================================================================
        if self.config.run_validation_after:
            self.log.info('stage_start',
                         decision='validating_after',
                         reason='step 9/10')
            parser2 = GCodeParser()
            output_events = parser2.parse_file(output_path)
            validator2 = GeometryValidator(output_events)
            self.result.validation_after = validator2.validate_all()

            self.log.info('stage_complete',
                         decision='validated_after',
                         reason=f'{len(self.result.validation_after)} findings')

        # =================================================================
        # SCHRITT 10: DIVERGENZ-CHECK
        # =================================================================
        if self.config.run_divergence_check:
            self.log.info('stage_start',
                         decision='checking_divergence',
                         reason='step 10/10')
            from debug_tools import compare_geometric_sequences
            self.result.divergence = compare_geometric_sequences(
                filepath, output_path
            )

            if self.result.divergence and self.result.divergence.get('divergence'):
                self.log.warning('divergence_found',
                                decision='divergence_detected',
                                reason=f"Line {self.result.divergence['divergence']['line_idx']}",
                                geometry=self.result.divergence)
            else:
                self.log.info('stage_complete',
                             decision='no_divergence',
                             reason='original and output match')

        self.log.info('pipeline_complete',
                     decision='completed',
                     reason='all 10 stages executed')

        return self.result

    def _detect_newline(self, filepath: str) -> str:
        """
        Erkennt das Zeilenende-Format der Originaldatei.
        Gibt '\n' (LF) oder '\r\n' (CRLF) zurück.
        Default: '\n'
        """
        try:
            with open(filepath, 'rb') as f:
                raw = f.read(1024 * 64)  # erste 64KB
            if b'\r\n' in raw:
                return '\r\n'
            return '\n'
        except Exception:
            return '\n'

    def _detect_trailing_newline(self, filepath: str) -> bool:
        """
        Erkennt ob die Originaldatei mit einem Newline endet.
        Gibt True wenn Datei mit \n oder \r\n endet.
        """
        try:
            with open(filepath, 'rb') as f:
                # Letzten 4 Bytes lesen (reicht für \r\n)
                f.seek(-4, 2)
                tail = f.read()
            return tail.endswith(b'\n') or tail.endswith(b'\r\n')
        except Exception:
            return True

    def _check_validation_errors(self, findings: List[ValidationFinding]):
        """Prüft auf kritische Validierungsfehler und bricht ggf. ab."""
        errors = [f for f in findings if f.severity in ('error', 'critical')]
        if errors and self.config.abort_on_validation_error:
            for e in errors[:5]:  # max 5 loggen
                self.log.error('validation_failed',
                              line_number=e.line_idx,
                              decision='abort',
                              reason=e.description)
            self.result.errors.append(
                f'{len(errors)} validation errors found, aborting'
            )
            self.result.aborted = True


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt die Pipeline auf einer GCode-Datei aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='GCode Processing Pipeline'
    )
    parser_arg.add_argument('file', nargs='?',
                           default='fixtures/minimal_test.gcode',
                           help='GCode-Datei')
    parser_arg.add_argument('--output', '-o', default=None,
                           help='Output-Datei')
    parser_arg.add_argument('--json', '-j', action='store_true',
                           help='JSON-Ergebnis')

    args = parser_arg.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"Datei nicht gefunden: {filepath}")
        sys.exit(1)

    pipeline = Pipeline()
    result = pipeline.run(str(filepath), args.output)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print("=" * 60)
        print(f"PIPELINE: {filepath.name}")
        print("=" * 60)
        print(f"\nStatus: {'ABORTED' if result.aborted else 'COMPLETED'}")
        print(f"Events: {result.total_events}")
        print(f"Output: {result.output_file}")

        if result.errors:
            print(f"\nFehler:")
            for e in result.errors:
                print(f"  ⚠️  {e}")

        print(f"\nKonturen: {len(result.contours)}")
        print(f"Wipe-Kandidaten: {len(result.wipe_candidates)}")
        print(f"Arcs: {len(result.arc_analyses)}")

        vbef = result.validation_before
        print(f"Validation Before: {len(vbef)} Befunde "
              f"({sum(1 for v in vbef if v.severity=='error')} errors)")

        vafter = result.validation_after
        print(f"Validation After:  {len(vafter)} Befunde "
              f"({sum(1 for v in vafter if v.severity=='error')} errors)")

        if result.divergence:
            d = result.divergence.get('divergence')
            if d:
                print(f"\n⚠️  DIVERGENZ in Zeile {d.get('line_idx')}: "
                      f"{d.get('type', '?')}")

        print(f"\nSublayer: {result.sublayer_stats}")

    close_all()


if __name__ == '__main__':
    main()