#!/usr/bin/env python3
"""
Identity Processor – Phase 13.5
================================
Beweist: Input == Output wenn keine Transformation aktiv ist.

Die Pipeline MUSS zuerst beweisen, dass sie Daten unverändert
durchreichen kann, bevor irgendeine Transformation aktiviert wird.

Byte-identisch außer erlaubten Metadaten (Logging).
"""

import sys
import hashlib
import filecmp
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeParser
from pipeline import Pipeline, PipelineConfig
from output_writer import make_output_path
from logging_system import get_logger, close_all


class IdentityProcessor:
    """
    Validiert dass die Pipeline ohne Transformation
    byte-identische Outputs produziert.

    Workflow:
    1. Datei in input/ kopieren
    2. Pipeline mit deaktiviertem Sublayer laufen lassen
    3. Byte-für-Byte-Vergleich
    4. Bei Abweichung: detaillierten Report erzeugen
    """

    def __init__(self):
        self.log = get_logger('identity_processor')
        self.input_dir = Path('input')
        self.output_dir = Path('output')
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, filepath: str) -> Dict[str, Any]:
        """
        Führt den Identity-Test für eine Datei aus.

        Args:
            filepath: Pfad zur GCode-Datei

        Returns:
            Dict mit Testergebnis
        """
        src = Path(filepath)
        if not src.exists():
            return {
                'file': filepath,
                'passed': False,
                'error': 'Datei nicht gefunden',
            }

        # Dateinamen bereinigen und in input/ kopieren
        dest_name = src.name
        input_path = self.input_dir / dest_name
        shutil.copy2(str(src), str(input_path))

        input_hash_before = self._hash_file(str(input_path))

        self.log.info('identity_test_start',
                     decision='testing',
                     reason=f'input={input_path.name}',
                     geometry={'hash_before': input_hash_before})

        # Pipeline MIT deaktiviertem Sublayer
        config = PipelineConfig()
        config.run_sublayer_processing = False
        config.abort_on_validation_error = False  # Identity geht auch bei Befunden

        pipeline = Pipeline(config)
        output_path = str(self.output_dir / f'identity_{dest_name}')
        result = pipeline.run(str(input_path), output_path)

        # Byte-Vergleich
        input_hash_after = self._hash_file(str(input_path))
        output_hash = self._hash_file(output_path)

        files_identical = filecmp.cmp(str(input_path), output_path, shallow=False)
        hashes_match = input_hash_after == output_hash

        identity_result = {
            'file': filepath,
            'input_file': str(input_path),
            'output_file': output_path,
            'passed': files_identical and hashes_match,
            'input_hash_before': input_hash_before,
            'input_hash_after': input_hash_after,
            'output_hash': output_hash,
            'files_identical': files_identical,
            'hashes_match': hashes_match,
            'input_size_bytes': input_path.stat().st_size,
            'output_size_bytes': Path(output_path).stat().st_size,
            'pipeline_aborted': result.aborted,
            'pipeline_errors': result.errors,
        }

        if identity_result['passed']:
            self.log.info('identity_test_passed',
                         decision='identity_confirmed',
                         reason=f'{input_path.name}: Input == Output (byte-identisch)',
                         geometry=identity_result)
        else:
            self.log.error('identity_test_failed',
                          decision='identity_violated',
                          reason=f'{input_path.name}: Input != Output',
                          geometry=identity_result)
            # Detaillierte Analyse bei Abweichung
            self._analyze_divergence(str(input_path), output_path)

        return identity_result

    def run_all(self, directory: str = 'fixtures') -> Dict[str, Any]:
        """
        Führt Identity-Tests für alle .gcode-Dateien in einem Verzeichnis aus.

        Args:
            directory: Verzeichnis mit Testdateien

        Returns:
            Dict mit Gesamtergebnis
        """
        pattern = Path(directory)
        gcode_files = list(pattern.glob('**/*.gcode'))

        self.log.info('identity_batch_start',
                     decision='batch_testing',
                     reason=f'{len(gcode_files)} files in {directory}')

        results = []
        passed = 0
        failed = 0

        for f in gcode_files:
            res = self.run(str(f))
            results.append(res)
            if res['passed']:
                passed += 1
            else:
                failed += 1
                self.log.error('identity_file_failed',
                              decision='failed',
                              reason=f'{f.name}: Input != Output')

        summary = {
            'directory': directory,
            'total_files': len(gcode_files),
            'passed': passed,
            'failed': failed,
            'results': results,
            'all_passed': failed == 0,
        }

        self.log.info('identity_batch_complete',
                     decision='batch_complete',
                     reason=f'{passed}/{len(gcode_files)} passed',
                     geometry=summary)

        return summary

    def _hash_file(self, filepath: str) -> str:
        """SHA256-Hash einer Datei."""
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    def _analyze_divergence(self, file_a: str, file_b: str):
        """Detaillierte Divergenzanalyse bei fehlgeschlagenem Identity-Test."""
        from debug_tools import compare_geometric_sequences

        analysis = compare_geometric_sequences(file_a, file_b)
        divergence = analysis.get('divergence')

        if divergence:
            self.log.error('divergence_detail',
                          decision='analyzing',
                          reason=f"Erste Divergenz in Zeile {divergence['line_idx']}",
                          geometry=divergence)
        else:
            self.log.warning('no_geometric_divergence',
                            decision='analyzing',
                            reason='Keine geometrische Divergenz, aber Dateien unterschiedlich')


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Führt Identity-Tests aus."""
    import argparse

    parser_arg = argparse.ArgumentParser(
        description='Identity Processor – Phase 13.5'
    )
    parser_arg.add_argument('file', nargs='?', default=None,
                           help='Einzelne Datei testen')
    parser_arg.add_argument('--dir', '-d', default='fixtures',
                           help='Verzeichnis mit Testdateien (default: fixtures)')
    parser_arg.add_argument('--copy-fixture', '-c',
                           help='Fixture in input/ kopieren und testen')

    args = parser_arg.parse_args()

    processor = IdentityProcessor()

    if args.file:
        result = processor.run(args.file)
        _print_result(result)
    elif args.copy_fixture:
        # Fixture kopieren und testen
        src = Path(args.copy_fixture)
        if src.exists():
            result = processor.run(str(src))
            _print_result(result)
        else:
            print(f"Datei nicht gefunden: {args.copy_fixture}")
    else:
        summary = processor.run_all(args.dir)
        _print_summary(summary)

    close_all()


def _print_result(result: Dict[str, Any]):
    """Gibt ein einzelnes Identity-Ergebnis aus."""
    print("=" * 60)
    print(f"IDENTITY TEST: {Path(result['file']).name}")
    print("=" * 60)
    print(f"  Status: {'✅ PASSED' if result['passed'] else '❌ FAILED'}")
    print(f"  Input:  {result['input_file']}")
    print(f"  Output: {result['output_file']}")
    print(f"  Input Size:  {result.get('input_size_bytes', 0)} bytes")
    print(f"  Output Size: {result.get('output_size_bytes', 0)} bytes")
    print(f"  Byte-identisch: {result.get('files_identical', False)}")
    print(f"  Hashes gleich:  {result.get('hashes_match', False)}")
    if result.get('pipeline_errors'):
        print(f"  Pipeline-Fehler: {result['pipeline_errors']}")


def _print_summary(summary: Dict[str, Any]):
    """Gibt eine Zusammenfassung aus."""
    print("=" * 60)
    print(f"IDENTITY BATCH: {summary['directory']}")
    print("=" * 60)
    print(f"  Gesamt: {summary['total_files']}")
    print(f"  Passed: {summary['passed']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Alle bestanden: {'✅' if summary['all_passed'] else '❌'}")
    if not summary['all_passed']:
        print(f"\n  Fehlgeschlagen:")
        for r in summary['results']:
            if not r['passed']:
                print(f"    ❌ {Path(r['file']).name}: "
                      f"{'nicht byte-identisch' if not r.get('files_identical') else 'Hash-Mismatch'}")


if __name__ == '__main__':
    main()