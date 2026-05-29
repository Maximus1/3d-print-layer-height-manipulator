#!/usr/bin/env python3
"""
Tests für Phase 13.7 – Extrusion Scaling
==========================================
Isolierte mathematische Tests für E-Wert-Skalierung.

Laut PIPELINE_SPEC.md Phase 13.7:
- E-Werte mathematisch skalieren (M82/M83 korrekt)
- Keine Änderung an X/Y/Z
- Keine Änderung an G2/G3 I/J
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gcode_parser import GCodeEvent
from extrusion_scaling_processor import (
    ExtrusionScalingProcessor, ExtrusionScalingConfig
)


def make_event(raw: str, line_idx: int = 10) -> GCodeEvent:
    """Hilfsfunktion: Erzeugt ein GCodeEvent mit korrekter Initialisierung."""
    event = GCodeEvent(line_idx=line_idx, raw=raw)
    event.parse()
    return event


# =============================================================================
# KONFIGURATION
# =============================================================================

class TestExtrusionScalingConfig(unittest.TestCase):
    """Tests für die Konfiguration."""

    def test_default_config(self):
        config = ExtrusionScalingConfig()
        self.assertEqual(config.scale_factor, 1.0)
        self.assertTrue(config.enabled)

    def test_custom_config(self):
        config = ExtrusionScalingConfig()
        config.scale_factor = 0.5
        self.assertEqual(config.scale_factor, 0.5)


# =============================================================================
# RELATIVER MODUS (M83)
# =============================================================================

class TestExtrusionScalingRelativeMode(unittest.TestCase):
    """Tests für E-Skalierung im relativen Modus (M83)."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_relative_e_halved(self):
        """Relativer E-Wert wird halbiert."""
        event = make_event('G1 X10 Y10 Z0.2 E0.4 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('E0.2', result)

    def test_relative_e_scaled(self):
        """Relativer E-Wert wird skaliert."""
        self.config.scale_factor = 0.75
        processor = ExtrusionScalingProcessor(self.config)

        event = make_event('G1 X10 Y10 Z0.2 E1.0 F1200')
        result = processor.process_event(event, relative_e=True)

        self.assertIn('E0.75', result)

    def test_relative_e_zero(self):
        """E=0 bleibt E=0."""
        event = make_event('G1 X10 Y10 Z0.2 E0.0 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('E0', result)

    def test_relative_e_negative(self):
        """Negativer E (Retract) wird skaliert."""
        event = make_event('G1 E-1.0 F2400')
        result = self.processor.process_event(
            event, relative_e=True)

        # -1.0 * 0.5 = -0.5
        self.assertIn('E-0.5', result)


# =============================================================================
# ABSOLUTER MODUS (M82)
# =============================================================================

class TestExtrusionScalingAbsoluteMode(unittest.TestCase):
    """Tests für E-Skalierung im absoluten Modus (M82)."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_absolute_e_from_zero(self):
        """Absolutes E ab 0 wird skaliert."""
        # Startpunkt: E=0, aktuelles E=1.0, Delta=1.0
        self.processor.set_current_e(0.0)
        event = make_event('G1 X10 Y10 Z0.2 E1.0 F1200')
        result = self.processor.process_event(
            event, relative_e=False)

        # Delta = 1.0 - 0.0 = 1.0, skaliert = 0.5
        # Neues absolutes E = 0.0 + 0.5 = 0.5
        self.assertIn('E0.5', result)

    def test_absolute_e_from_nonzero(self):
        """Absolutes E ab nicht-Null Startpunkt."""
        self.processor.set_current_e(1.0)
        event = make_event('G1 X10 Y10 Z0.2 E2.0 F1200')
        result = self.processor.process_event(
            event, relative_e=False)

        # Delta = 2.0 - 1.0 = 1.0, skaliert = 0.5
        # Neues absolutes E = 1.0 + 0.5 = 1.5
        self.assertIn('E1.5', result)

    def test_absolute_e_multiple_steps(self):
        """Mehrere Schritte im absoluten Modus."""
        self.processor.set_current_e(0.0)

        event1 = make_event('G1 X10 Y10 Z0.2 E1.0 F1200')
        result1 = self.processor.process_event(
            event1, relative_e=False)
        self.assertIn('E0.5', result1)

        # Aktuelles E jetzt 0.5
        event2 = make_event('G1 X20 Y20 Z0.2 E2.0 F1200')
        result2 = self.processor.process_event(
            event2, relative_e=False)

        # Delta = 2.0 - 0.5 = 1.5, skaliert = 0.75
        # Neues absolutes E = 0.5 + 0.75 = 1.25
        self.assertIn('E1.25', result2)


# =============================================================================
# KEIN E (TRAVEL)
# =============================================================================

class TestExtrusionScalingNoE(unittest.TestCase):
    """Tests für Zeilen ohne E-Parameter."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_travel_unchanged(self):
        """Travel-Zeile bleibt unverändert."""
        event = make_event('G1 X10 Y10 Z0.2 F3000')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertEqual(result, event.raw)

    def test_g0_unchanged(self):
        """G0-Zeile bleibt unverändert."""
        event = make_event('G0 X10 Y10 Z0.2')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertEqual(result, event.raw)

    def test_comment_unchanged(self):
        """Kommentar bleibt unverändert."""
        event = make_event('; some comment')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertEqual(result, event.raw)


# =============================================================================
# X/Y/Z UNVERÄNDERT
# =============================================================================

class TestExtrusionScalingPreservesXYZ(unittest.TestCase):
    """Tests dass X/Y/Z unverändert bleiben."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_xyz_preserved_relative(self):
        """X/Y/Z bleiben im relativen Modus unverändert."""
        event = make_event('G1 X42.5 Y87.3 Z0.3 E0.4 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('X42.5', result)
        self.assertIn('Y87.3', result)
        self.assertIn('Z0.3', result)

    def test_xyz_preserved_absolute(self):
        """X/Y/Z bleiben im absoluten Modus unverändert."""
        self.processor.set_current_e(0.0)
        event = make_event('G1 X42.5 Y87.3 Z0.3 E0.4 F1200')
        result = self.processor.process_event(
            event, relative_e=False)

        self.assertIn('X42.5', result)
        self.assertIn('Y87.3', result)
        self.assertIn('Z0.3', result)


# =============================================================================
# FEEDRATE
# =============================================================================

class TestExtrusionScalingFeedrate(unittest.TestCase):
    """Tests für Feedrate-Verhalten."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_feedrate_preserved(self):
        """Feedrate bleibt unverändert."""
        event = make_event('G1 X10 Y10 Z0.2 E0.4 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('F1200', result)


# =============================================================================
# DEAKTIVIERT
# =============================================================================

class TestExtrusionScalingDisabled(unittest.TestCase):
    """Tests für deaktivierten Prozessor."""

    def test_disabled_returns_original(self):
        """Deaktivierter Prozessor gibt Original zurück."""
        config = ExtrusionScalingConfig()
        config.enabled = False
        processor = ExtrusionScalingProcessor(config)

        event = make_event('G1 X10 Y10 Z0.2 E0.4')
        result = processor.process_event(event, relative_e=True)

        self.assertEqual(result, event.raw)


# =============================================================================
# ARC (G2/G3)
# =============================================================================

class TestExtrusionScalingArc(unittest.TestCase):
    """Tests für Arc-Verhalten."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_arc_e_scaled_relative(self):
        """G2 mit E wird im relativen Modus skaliert."""
        event = make_event('G2 X10 Y10 I5 J0 E0.4 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('E0.2', result)
        # I/J bleiben unverändert
        self.assertIn('I5', result)

    def test_arc_ij_preserved(self):
        """G2 I/J Parameter bleiben unverändert."""
        event = make_event('G3 X10 Y10 I5 J3 E0.4 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('I5', result)
        self.assertIn('J3', result)


# =============================================================================
# FEHLERFÄLLE
# =============================================================================

class TestExtrusionScalingEdgeCases(unittest.TestCase):
    """Tests für Randfälle."""

    def setUp(self):
        self.config = ExtrusionScalingConfig()
        self.config.scale_factor = 0.5
        self.processor = ExtrusionScalingProcessor(self.config)

    def test_very_small_e(self):
        """Sehr kleiner E-Wert."""
        event = make_event('G1 X10 Y10 Z0.2 E0.001 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('E0.0005', result)

    def test_large_e(self):
        """Großer E-Wert."""
        event = make_event('G1 X10 Y10 Z0.2 E100.0 F1200')
        result = self.processor.process_event(
            event, relative_e=True)

        self.assertIn('E50', result)

    def test_scale_factor_one(self):
        """Skalierungsfaktor 1.0 = unverändert."""
        self.config.scale_factor = 1.0
        processor = ExtrusionScalingProcessor(self.config)

        event = make_event('G1 X10 Y10 Z0.2 E0.4 F1200')
        result = processor.process_event(event, relative_e=True)

        self.assertIn('E0.4', result)

    def test_scale_factor_zero(self):
        """Skalierungsfaktor 0.0 = kein E."""
        self.config.scale_factor = 0.0
        processor = ExtrusionScalingProcessor(self.config)

        event = make_event('G1 X10 Y10 Z0.2 E0.4 F1200')
        result = processor.process_event(event, relative_e=True)

        self.assertIn('E0', result)


if __name__ == '__main__':
    unittest.main()