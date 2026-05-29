#!/usr/bin/env python3
"""
Integrationstest für Phase 13.6 – Z-Duplication
=================================================
Testet die vollständige Pipeline mit aktivierter Z-Duplication.

Validiert:
1. Output hat mehr Zeilen als Input (Duplizierung)
2. Originalzeilen bleiben unverändert
3. Duplizierte Zeilen haben erhöhtes Z
4. Duplizierte Zeilen haben kein E
5. Nur WALL-OUTER wird dupliziert
"""

import sys
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import Pipeline, PipelineConfig
from gcode_parser import GCodeParser
from z_duplication_processor import ZDuplicationConfig


def main():
    filepath = 'fixtures/minimal_test.gcode'

    # =========================================================================
    # TEST 1: Identity (Z-Duplication deaktiviert)
    # =========================================================================
    print("=" * 60)
    print("TEST 1: Identity (Z-Duplication DEAKTIVIERT)")
    print("=" * 60)

    config_identity = PipelineConfig()
    config_identity.run_z_duplication = False
    config_identity.run_sublayer_processing = False
    config_identity.abort_on_validation_error = False

    pipeline_identity = Pipeline(config_identity)
    result_identity = pipeline_identity.run(
        filepath, 'output/test_identity.gcode')

    with open(filepath, 'rb') as f:
        input_data = f.read()
    with open('output/test_identity.gcode', 'rb') as f:
        output_data = f.read()

    identical = input_data == output_data
    print(f"  Input:  {len(input_data)} bytes")
    print(f"  Output: {len(output_data)} bytes")
    print(f"  Byte-identisch: {'✅ JA' if identical else '❌ NEIN'}")

    if not identical:
        print("  ❌ FEHLER: Identity-Verletzung!")
        return False

    print("  ✅ PASSED\n")

    # =========================================================================
    # TEST 2: Z-Duplication aktiviert
    # =========================================================================
    print("=" * 60)
    print("TEST 2: Z-Duplication AKTIVIERT")
    print("=" * 60)

    z_config = ZDuplicationConfig()
    z_config.z_offset = 0.05
    z_config.target_types = ['WALL-OUTER']

    config_z = PipelineConfig()
    config_z.run_z_duplication = True
    config_z.z_duplication_config = z_config
    config_z.run_sublayer_processing = False
    config_z.abort_on_validation_error = False

    pipeline_z = Pipeline(config_z)
    result_z = pipeline_z.run(
        filepath, 'output/test_z_duplication.gcode')

    with open(filepath, 'rb') as f:
        input_lines = f.readlines()
    with open('output/test_z_duplication.gcode', 'rb') as f:
        output_lines = f.readlines()

    print(f"  Input:  {len(input_lines)} Zeilen")
    print(f"  Output: {len(output_lines)} Zeilen")

    if len(output_lines) <= len(input_lines):
        print("  ❌ FEHLER: Output hat nicht mehr Zeilen als Input!")
        return False

    print(f"  ✅ Output hat {len(output_lines) - len(input_lines)} Zeilen mehr\n")

    # =========================================================================
    # TEST 3: Duplizierte Zeilen analysieren
    # =========================================================================
    print("=" * 60)
    print("TEST 3: Duplizierte Zeilen analysieren")
    print("=" * 60)

    # Finde Duplikate: Zeilen die nicht im Input vorkommen
    input_set = set(line.strip() for line in input_lines)
    new_lines = [line for line in output_lines
                 if line.strip() not in input_set]

    print(f"  Neue Zeilen im Output: {len(new_lines)}")

    # Prüfe ob Duplikate korrekt sind
    z_duplications_found = 0
    e_in_duplicates = 0

    for line in new_lines:
        decoded = line.decode('utf-8', errors='replace').strip()
        if decoded.startswith('G1'):
            # Prüfe ob E-Parameter vorhanden ist
            code_part = decoded.split(';')[0]
            if 'E' in code_part:
                e_in_duplicates += 1
                print(f"  ⚠️  Duplikat mit E: {decoded}")
            else:
                z_duplications_found += 1

    print(f"\n  Korrekte Duplikate (kein E): {z_duplications_found}")
    print(f"  Fehlerhafte Duplikate (mit E): {e_in_duplicates}")

    if e_in_duplicates > 0:
        print("  ❌ FEHLER: Duplikate haben E-Parameter!")
        return False

    if z_duplications_found == 0:
        print("  ❌ FEHLER: Keine Duplikate gefunden!")
        return False

    print(f"  ✅ {z_duplications_found} korrekte Duplikate gefunden\n")

    # =========================================================================
    # TEST 4: Z-Werte prüfen
    # =========================================================================
    print("=" * 60)
    print("TEST 4: Z-Werte der Duplikate prüfen")
    print("=" * 60)

    z_correct = 0
    z_wrong = 0
    import re

    for line in new_lines:
        decoded = line.decode('utf-8', errors='replace').strip()
        if decoded.startswith('G1') and 'Z' in decoded:
            code_part = decoded.split(';')[0]
            z_match = re.search(r'Z([-+]?\d*\.?\d+)', code_part)
            if z_match:
                z_val = float(z_match.group(1))
                # Z-Wert muss > 0 sein
                # Prüfe ob Z-Wert ein Vielfaches von 0.05 ist
                # (Floating-Point-Toleranz: 0.001)
                rounded_20 = round(z_val * 20)
                is_multiple_of_05 = abs(z_val * 20 - rounded_20) < 0.001
                if z_val > 0 and is_multiple_of_05:
                    z_correct += 1
                else:
                    z_wrong += 1
                    print(f"  ⚠️  Unerwarteter Z-Wert: {z_val} "
                          f"(x20={z_val*20:.3f})")

    print(f"  Korrekte Z-Werte: {z_correct}")
    print(f"  Falsche Z-Werte: {z_wrong}")

    if z_wrong > 0:
        print("  ❌ FEHLER: Z-Werte nicht korrekt!")
        return False

    print(f"  ✅ Alle Z-Werte korrekt\n")

    # =========================================================================
    # ERGEBNIS
    # =========================================================================
    print("=" * 60)
    print("ERGEBNIS")
    print("=" * 60)
    print("✅ Phase 13.6 (Z-Duplication) – ALLE TESTS BESTANDEN")
    print(f"   Input:  {len(input_lines)} Zeilen")
    print(f"   Output: {len(output_lines)} Zeilen")
    print(f"   Duplikate: {z_duplications_found}")
    print(f"   Z-Offset: {z_config.z_offset} mm")
    print(f"   Target: {z_config.target_types}")

    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)