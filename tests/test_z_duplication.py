#!/usr/bin/env python3
"""
Tests für Phase 13.6 – Z-Duplication
=====================================
Testet den z_duplication_processor isoliert.

Laut PIPELINE_SPEC.md Phase 13.6:
- Z-Wert einer Bewegung erhöhen und Bewegung duplizieren
- Beispiel: G1 X10 Y10 Z0.2 E0.4 → G1 X10 Y10 Z0.2 E0.4 + G1 X10 Y10 Z0.25
- Keine E-Änderung im duplizierten Move
"""

import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gcode_parser import GCodeParser, GCodeEvent
from z_duplication_processor import ZDuplicationProcessor, ZDuplicationConfig


def make_event(raw: str, line_idx: int = 10, type_tag: str = '',
               layer_number: int = 1) -> GCodeEvent:
    """
    Hilfsfunktion: Erzeugt ein GCodeEvent mit korrekter Initialisierung.
    Erstellt Event, ruft parse() auf, setzt type_tag und layer_number.
    """
    event = GCodeEvent(line_idx=line_idx, raw=raw)
    event.parse()
    event.type_tag = type_tag
    event.layer_number = layer_number
    return event


class TestZDuplicationConfig(unittest.TestCase):
    """Tests für die Konfiguration."""

    def test_default_config(self):
        config = ZDuplicationConfig()
        self.assertEqual(config.z_offset, 0.05)
        self.assertEqual(config.target_types, ['WALL-OUTER'])
        self.assertTrue(config.enabled)

    def test_custom_config(self):
        config = ZDuplicationConfig()
        config.z_offset = 0.1
        config.target_types = ['WALL-OUTER', 'WALL-INNER']
        self.assertEqual(config.z_offset, 0.1)
        self.assertEqual(config.target_types, ['WALL-OUTER', 'WALL-INNER'])


class TestZDuplicationExtrusion(unittest.TestCase):
    """Tests für die Duplizierung von Extrusionsbewegungen."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.config.z_offset = 0.05
        self.processor = ZDuplicationProcessor(self.config)

    def test_g1_with_extrusion_is_duplicated(self):
        """G1 mit E > 0 muss dupliziert werden."""
        event = make_event(
            'G1 X10 Y10 Z0.2 E0.4 F1200',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        # Sollte 2 Zeilen zurückgeben: Original + Duplikat
        self.assertEqual(len(result), 2)
        # Original unverändert
        self.assertIn('G1', result[0])
        self.assertIn('X10', result[0])
        self.assertIn('E0.4', result[0])
        # Duplikat mit erhöhtem Z und ohne E
        self.assertIn('Z0.25', result[1])  # 0.2 + 0.05
        self.assertNotIn('E', result[1].split(';')[0])  # Kein E im Duplikat

    def test_g1_without_extrusion_not_duplicated(self):
        """G1 ohne E (Travel) darf NICHT dupliziert werden."""
        event = make_event(
            'G1 X10 Y10 Z0.2 F3000',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        # Nur 1 Zeile (Original)
        self.assertEqual(len(result), 1)

    def test_g0_not_duplicated(self):
        """G0 (rapid move) darf NICHT dupliziert werden."""
        event = make_event(
            'G0 X10 Y10 Z0.2',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        self.assertEqual(len(result), 1)


class TestZDuplicationNonTargetType(unittest.TestCase):
    """Tests für Nicht-Zieltypen."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.config.z_offset = 0.05
        self.config.target_types = ['WALL-OUTER']
        self.processor = ZDuplicationProcessor(self.config)

    def test_fill_type_not_duplicated(self):
        """FILL-Typ darf NICHT dupliziert werden."""
        event = make_event(
            'G1 X10 Y10 Z0.2 E0.4',
            type_tag='FILL',
        )

        result = self.processor.process_event(event, type_tag='FILL')

        # Nur 1 Zeile
        self.assertEqual(len(result), 1)

    def test_wall_inner_not_duplicated_by_default(self):
        """WALL-INNER wird standardmäßig NICHT dupliziert."""
        event = make_event(
            'G1 X10 Y10 Z0.2 E0.4',
            type_tag='WALL-INNER',
        )

        result = self.processor.process_event(event, type_tag='WALL-INNER')

        self.assertEqual(len(result), 1)


class TestZDuplicationCommentPassthrough(unittest.TestCase):
    """Tests für Kommentar-Zeilen."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.processor = ZDuplicationProcessor(self.config)

    def test_comment_not_duplicated(self):
        """Kommentar-Zeilen werden unverändert durchgereicht."""
        event = make_event('; some comment', type_tag='')

        result = self.processor.process_event(event, type_tag='')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], '; some comment')


class TestZDuplicationZCalculation(unittest.TestCase):
    """Tests für die korrekte Z-Berechnung."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.processor = ZDuplicationProcessor(self.config)

    def test_z_offset_added_correctly(self):
        """Z-Offset wird korrekt addiert."""
        event = make_event(
            'G1 X5 Y5 Z0.3 E0.2',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        self.assertEqual(len(result), 2)
        # Duplikat: Z = 0.3 + 0.05 = 0.35
        self.assertIn('Z0.35', result[1])

    def test_custom_z_offset(self):
        """Benutzerdefinierter Z-Offset."""
        self.config.z_offset = 0.1
        processor = ZDuplicationProcessor(self.config)

        event = make_event(
            'G1 X5 Y5 Z0.2 E0.2',
            type_tag='WALL-OUTER',
        )

        result = processor.process_event(event, type_tag='WALL-OUTER')

        self.assertEqual(len(result), 2)
        self.assertIn('Z0.3', result[1])  # 0.2 + 0.1


class TestZDuplicationWithComments(unittest.TestCase):
    """Tests für Extrusion mit Inline-Kommentar."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.processor = ZDuplicationProcessor(self.config)

    def test_inline_comment_preserved_in_duplication(self):
        """Inline-Kommentar wird im Duplikat beibehalten (oder entfernt?)."""
        event = make_event(
            'G1 X10 Y10 Z0.2 E0.4 ; inner wall',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        self.assertEqual(len(result), 2)
        # Original mit Kommentar
        self.assertIn('; inner wall', result[0])
        # Duplikat mit erhöhtem Z, ohne E
        dup_parts = result[1].split(';')
        self.assertIn('Z0.25', dup_parts[0])


class TestZDuplicationPreservesXY(unittest.TestCase):
    """Tests für X/Y-Bewahrung im Duplikat."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.processor = ZDuplicationProcessor(self.config)

    def test_xy_preserved_in_duplication(self):
        """X und Y bleiben im Duplikat identisch."""
        event = make_event(
            'G1 X42.5 Y87.3 Z0.2 E0.4',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        self.assertEqual(len(result), 2)
        self.assertIn('X42.5', result[1])
        self.assertIn('Y87.3', result[1])


class TestZDuplicationDisabled(unittest.TestCase):
    """Tests für deaktivierten Prozessor."""

    def test_disabled_returns_original(self):
        """Deaktivierter Prozessor gibt immer Original zurück."""
        config = ZDuplicationConfig()
        config.enabled = False
        processor = ZDuplicationProcessor(config)

        event = make_event(
            'G1 X10 Y10 Z0.2 E0.4',
            type_tag='WALL-OUTER',
        )

        result = processor.process_event(event, type_tag='WALL-OUTER')
        self.assertEqual(len(result), 1)


class TestZDuplicationFeedrate(unittest.TestCase):
    """Tests für Feedrate-Verhalten im Duplikat."""

    def setUp(self):
        self.config = ZDuplicationConfig()
        self.processor = ZDuplicationProcessor(self.config)

    def test_feedrate_preserved_in_duplication(self):
        """Feedrate wird im Duplikat beibehalten."""
        event = make_event(
            'G1 X10 Y10 Z0.2 E0.4 F1200',
            type_tag='WALL-OUTER',
        )

        result = self.processor.process_event(event, type_tag='WALL-OUTER')

        self.assertEqual(len(result), 2)
        self.assertIn('F1200', result[1])


if __name__ == '__main__':
    unittest.main()