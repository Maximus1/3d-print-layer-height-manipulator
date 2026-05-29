#!/usr/bin/env python3
"""
Regression Test Runner – Byte-identität der Pipeline verifizieren
=================================================================
Speichert „golden" Outputs für Test-Fixtures und vergleicht bei
jeder Änderung, dass die Pipeline das exakt gleiche Ergebnis erzeugt.

Verwendung:
    # Golden Files generieren (einmalig):
    python regression_runner.py --generate

    # Regressionstests ausführen:
    python regression_runner.py

    # Einzelner Test:
    python regression_runner.py --test identity_minimal_test

Konventionen:
- Fixtures:   fixtures/*.gcode
- Golden:     regression/golden/<name>.gcode
- Tests sind in TEST_CASES definiert (Liste von Dictionaries)
"""

import sys
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import Pipeline, PipelineConfig
from output_writer import make_output_path


# =============================================================================
# TEST-KONFIGURATION
# =============================================================================

@dataclass
class RegressionTest:
    """Ein einzelner Regressionstest."""
    name: str                    # Eindeutiger Name (kein Leerzeichen)
    fixture_path: str            # Pfad zur Eingabe-GCode-Datei
    description: str = ""        # Beschreibung des Tests

@dataclass
class TestResult:
    """Ergebnis eines einzelnen Tests."""
    test_name: str
    passed: bool
    input_size: int = 0
    output_size: int = 0
    golden_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    error: str = ""

# =============================================================================
# DEFINIERTE TESTFÄLLE
# =============================================================================

TEST_CASES: List[RegressionTest] = [
    # --- Identitätstests (Pipeline mit allen Schritten deaktiviert) ---
    RegressionTest(
        name="identity_minimal_test",
        fixture_path="fixtures/minimal_test.gcode",
        description="Byte-identische Reproduktion von minimal_test.gcode ohne Änderungen"
    ),
    RegressionTest(
        name="identity_sublayer_clean",
        fixture_path="fixtures/sublayer_clean.gcode",
        description="Byte-identische Reproduktion von sublayer_clean.gcode ohne Änderungen"
    ),
    # Hier können weitere Tests hinzugefügt werden:
    # RegressionTest(
    #     name="sublayer_splitting",
    #     fixture_path="fixtures/sublayer_fixture.gcode",
    #     description="Sublayer-Splitting erzeugt korrekte Ausgabe"
    # ),
    # RegressionTest(
    #     name="arc_handling",
    #     fixture_path="fixtures/arc_test.gcode",
    #     description="Arc-Verarbeitung korrekt"
    # ),
]


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def compute_hash(filepath: str) -> str:
    """SHA256 Hash einer Datei."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def run_identity_pipeline(fixture_path: str, output_dir: Path) -> str:
    """
    Führt die Pipeline im Identitätsmodus aus (alle Schritte deaktiviert).
    Gibt den Pfad der Output-Datei zurück.
    """
    config = PipelineConfig()
    # Alle Verarbeitungsschritte deaktivieren → reine Kopie
    for attr in ('run_validation_before', 'run_contour_extraction',
                 'run_classification', 'run_wipe_detection',
                 'run_arc_analysis', 'run_sublayer_processing',
                 'run_validation_after', 'run_divergence_check'):
        setattr(config, attr, False)

    pipeline = Pipeline(config)

    # Output-Pfad im output-Verzeichnis
    out_name = f"identity_{Path(fixture_path).stem}.gcode"
    output_path = str(output_dir / out_name)

    result = pipeline.run(fixture_path, output_path)
    return output_path


# =============================================================================
# GENERIEREN VON GOLDEN FILES
# =============================================================================

def generate_golden(golden_dir: Path):
    """Erzeugt golden files für alle Testfälle."""
    golden_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("GOLDEN FILE GENERATION")
    print("=" * 60)

    for tc in TEST_CASES:
        golden_path = golden_dir / f"{tc.name}.gcode"
        print(f"\n[{tc.name}] {tc.description}")

        # Pipeline ausführen (Identity-Modus)
        out_path = run_identity_pipeline(tc.fixture_path, output_dir)

        if not Path(out_path).exists():
            print(f"  ❌ Kein Output erstellt!")
            continue

        # Nach golden/ kopieren
        import shutil
        shutil.copy2(out_path, str(golden_path))

        h = compute_hash(str(golden_path))
        size = Path(golden_path).stat().st_size
        print(f"  ✅ Golden file: {golden_path.name} ({size} bytes, sha256={h[:16]}...)")


# =============================================================================
# REGRESSIONSTESTS AUSFÜHREN
# =============================================================================

def run_tests(golden_dir: Path) -> List[TestResult]:
    """Führt alle Regressionstests aus und vergleicht mit golden files."""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    results: List[TestResult] = []

    print("=" * 60)
    print("REGRESSION TESTS")
    print("=" * 60)

    for tc in TEST_CASES:
        golden_path = golden_dir / f"{tc.name}.gcode"
        result = TestResult(test_name=tc.name, passed=False)

        # Golden file existiert?
        if not golden_path.exists():
            result.error = f"No golden file at {golden_path}"
            results.append(result)
            print(f"\n❌ [{tc.name}] No golden file")
            continue

        golden_hash = compute_hash(str(golden_path))

        # Pipeline ausführen (Identity-Modus)
        try:
            out_path = run_identity_pipeline(tc.fixture_path, output_dir)
        except Exception as e:
            result.error = f"Pipeline error: {e}"
            results.append(result)
            print(f"\n❌ [{tc.name}] Pipeline failed: {e}")
            continue

        if not Path(out_path).exists():
            result.error = "No output file created"
            results.append(result)
            print(f"\n❌ [{tc.name}] No output")
            continue

        actual_hash = compute_hash(str(out_path))
        result.input_size = Path(tc.fixture_path).stat().st_size
        result.output_size = Path(out_path).stat().st_size
        result.golden_hash = golden_hash[:16]
        result.actual_hash = actual_hash[:16]

        # Byte-Identität prüfen
        with open(str(golden_path), 'rb') as gf:
            golden_data = gf.read()
        with open(out_path, 'rb') as af:
            actual_data = af.read()

        if golden_data == actual_data:
            result.passed = True
            print(f"\n✅ [{tc.name}] PASSED (sha256={actual_hash[:16]}...)")
        else:
            # Diff suchen
            min_len = min(len(golden_data), len(actual_data))
            first_diff = -1
            for i in range(min_len):
                if golden_data[i] != actual_data[i]:
                    first_diff = i
                    break

            if first_diff >= 0:
                result.error = f"First diff at byte {first_diff}: " \
                              f"golden=0x{golden_data[first_diff]:02x} vs " \
                              f"actual=0x{actual_data[first_diff]:02x}"
            elif len(golden_data) != len(actual_data):
                result.error = (f"Size mismatch: golden={len(golden_data)}b vs "
                               f"actual={len(actual_data)}b")

            print(f"\n❌ [{tc.name}] FAILED")
            print(f"   {result.error}")
            print(f"   Golden hash:  {golden_hash[:32]}...")
            print(f"   Actual hash:  {actual_hash[:32]}...")

        results.append(result)

    return results


# =============================================================================
# HAUPTPROGRAMM
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="GCode Regression Test Runner")
    parser.add_argument('--generate', action='store_true',
                       help="Golden files generieren (einmalig)")
    parser.add_argument('--test', type=str, default=None,
                       help="Nur einen bestimmten Test ausführen")

    args = parser.parse_args()
    golden_dir = Path("regression/golden")

    if args.generate:
        generate_golden(golden_dir)
        print("\n✅ Golden file generation complete.")
        return

    # Tests ausführen
    results = run_tests(golden_dir)

    # Zusammenfassung
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print(f"\n{'=' * 60}")
    print(f"ERGEBNIS: {passed}/{len(results)} bestanden, {failed} fehlgeschlagen")
    print(f"{'=' * 60}")

    if failed > 0:
        print("\nFehler:")
        for r in results:
            if not r.passed:
                print(f"  ❌ [{r.test_name}] {r.error}")
        sys.exit(1)
    else:
        print("\n🎉 Alle Tests bestanden!")
        sys.exit(0)


if __name__ == '__main__':
    main()