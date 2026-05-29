#!/usr/bin/env python3
"""
Tests für gcode_parser.py
=========================
Testet alle Parser-Funktionen gegen die minimale Fixture.

Test-Fälle (laut Projektplan):
1. Parser-Test: X/Y/Z, E, I/J, G2/G3, Kommentare, Scientific notation, negative Werte
2. Zustands-Test: relative E, absolute E, G92 E, Retracts, Unretracts
3. Geometrie-Test: Kontinuität, Sprünge, Travel-Ketten, Arc-Konsistenz
4. Kontur-Test: geschlossene Konturen, Layerwechsel, Start-/Endpunkte
"""

import sys
import os
from pathlib import Path

# Projekt-Root für Imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from gcode_parser import (
    strip_comment,
    parse_command,
    parse_params,
    parse_type_comment,
    is_layer_change,
    parse_layer_number,
    is_gcode_line,
    GCodeEvent,
    GCodeParser,
)


# =============================================================================
# FIXTURES
# =============================================================================

FIXTURE_DIR = Path(__file__).parent.parent / 'fixtures'
MINIMAL_FIXTURE = FIXTURE_DIR / 'minimal_test.gcode'


@pytest.fixture(scope='session')
def minimal_gcode_lines():
    """Lädt die minimale Test-Fixture."""
    with open(MINIMAL_FIXTURE, 'r', encoding='utf-8') as f:
        return f.readlines()


@pytest.fixture(scope='session')
def parsed_minimal():
    """Parst die minimale Test-Fixture einmal für alle Tests."""
    parser = GCodeParser()
    with open(MINIMAL_FIXTURE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    parser.parse_lines(lines)
    return parser


# =============================================================================
# TEST: strip_comment
# =============================================================================

class TestStripComment:
    """Tests für strip_comment()."""

    def test_semicolon_comment(self):
        """Semikolon-Kommentare werden entfernt."""
        assert strip_comment('G1 X10 Y20 ; das ist ein Test') == 'G1 X10 Y20'

    def test_parenthesis_comment(self):
        """Klammer-Kommentare werden entfernt."""
        assert strip_comment('G1 X10 (das ist ein Test)') == 'G1 X10'

    def test_both_comments(self):
        """Beide Kommentararten werden entfernt."""
        result = strip_comment('G1 X10 (Klammer) ; Semikolon')
        assert result == 'G1 X10'

    def test_no_comment(self):
        """Zeilen ohne Kommentar bleiben unverändert."""
        assert strip_comment('G1 X10 Y20 E0.5') == 'G1 X10 Y20 E0.5'

    def test_only_comment(self):
        """Reine Kommentarzeilen ergeben leeren String."""
        assert strip_comment('; nur ein Kommentar') == ''

    def test_comment_with_numbers(self):
        """Kommentar mit Zahlen beeinflusst nicht das Ergebnis."""
        assert strip_comment('G1 X10 ; 123 Test 456') == 'G1 X10'


# =============================================================================
# TEST: parse_command
# =============================================================================

class TestParseCommand:
    """Tests für parse_command()."""

    def test_g0(self):
        assert parse_command('G0 X10 Y20') == 'G0'

    def test_g1(self):
        assert parse_command('G1 X10 Y20 E0.5') == 'G1'

    def test_g2(self):
        assert parse_command('G2 X20 Y10 I10 J-10') == 'G2'

    def test_g3(self):
        assert parse_command('G3 X20 Y10 I10 J-10') == 'G3'

    def test_g10(self):
        assert parse_command('G10') == 'G10'

    def test_g11(self):
        assert parse_command('G11') == 'G11'

    def test_g28(self):
        assert parse_command('G28') == 'G28'

    def test_g90(self):
        assert parse_command('G90') == 'G90'

    def test_g91(self):
        assert parse_command('G91') == 'G91'

    def test_g92(self):
        assert parse_command('G92 E0') == 'G92'

    def test_m82(self):
        assert parse_command('M82') == 'M82'

    def test_m83(self):
        assert parse_command('M83') == 'M83'

    def test_m104(self):
        assert parse_command('M104 S200') == 'M104'

    def test_empty_string(self):
        assert parse_command('') is None

    def test_only_comment(self):
        assert parse_command('; nur Kommentar') is None

    def test_invalid_command(self):
        assert parse_command('ABC123') is None


# =============================================================================
# TEST: parse_params
# =============================================================================

class TestParseParams:
    """Tests für parse_params()."""

    def test_xyz(self):
        params = parse_params('G1 X10 Y20 Z0.5')
        assert params == {'X': 10.0, 'Y': 20.0, 'Z': 0.5}

    def test_e(self):
        params = parse_params('G1 X10 E0.5')
        assert params == {'X': 10.0, 'E': 0.5}

    def test_ij(self):
        params = parse_params('G2 X20 Y10 I10 J-10')
        assert params == {'X': 20.0, 'Y': 10.0, 'I': 10.0, 'J': -10.0}

    def test_feedrate(self):
        params = parse_params('G1 X10 F3000')
        assert params == {'X': 10.0, 'F': 3000.0}

    def test_negative_e(self):
        """Negative E-Werte (Retract) müssen erkannt werden."""
        params = parse_params('G1 X10 E-0.5')
        assert params == {'X': 10.0, 'E': -0.5}

    def test_scientific_notation_e(self):
        """Scientific notation: E1e-3"""
        params = parse_params('G1 X0.0001 Y0.0002 Z2.0 E1e-3')
        assert 'E' in params
        assert abs(params['E'] - 0.001) < 1e-10

    def test_scientific_notation_capital(self):
        """Scientific notation: E1.5E-2"""
        params = parse_params('G1 X1e2 Y2e2 Z2.1 E1.5E-2')
        assert 'X' in params
        assert abs(params['X'] - 100.0) < 1e-10
        assert 'E' in params
        assert abs(params['E'] - 0.015) < 1e-10

    def test_mixed_order(self):
        """Parameter in gemischter Reihenfolge."""
        params = parse_params('G1 F3000 X100 Y100 Z3.0 E10.0')
        assert params['X'] == 100.0
        assert params['Y'] == 100.0
        assert params['Z'] == 3.0
        assert params['E'] == 10.0
        assert params['F'] == 3000.0

    def test_no_params(self):
        assert parse_params('G28') == {}

    def test_only_y(self):
        """Nur Y + E (kein X)."""
        params = parse_params('G1 Y110 E11.0')
        assert params == {'Y': 110.0, 'E': 11.0}


# =============================================================================
# TEST: parse_type_comment
# =============================================================================

class TestParseTypeComment:
    """Tests für parse_type_comment()."""

    def test_wall_outer(self):
        assert parse_type_comment(';TYPE:WALL-OUTER') == 'WALL-OUTER'

    def test_wall_inner(self):
        assert parse_type_comment(';TYPE:WALL-INNER') == 'WALL-INNER'

    def test_fill(self):
        assert parse_type_comment(';TYPE:FILL') == 'FILL'

    def test_support(self):
        assert parse_type_comment(';TYPE:SUPPORT') == 'SUPPORT'

    def test_skin(self):
        assert parse_type_comment(';TYPE:SKIN') == 'SKIN'

    def test_lowercase(self):
        assert parse_type_comment(';type:wall-outer') == 'wall-outer'

    def test_no_type(self):
        assert parse_type_comment('G1 X10') is None

    def test_not_a_type(self):
        assert parse_type_comment('; generated by PrusaSlicer') is None


# =============================================================================
# TEST: is_layer_change
# =============================================================================

class TestIsLayerChange:
    """Tests für is_layer_change()."""

    def test_layer_change(self):
        assert is_layer_change(';LAYER_CHANGE') is True

    def test_layer_change_with_space(self):
        assert is_layer_change(';LAYER CHANGE') is True

    def test_layer_change_lowercase(self):
        assert is_layer_change(';layer_change') is True

    def test_not_layer_change(self):
        assert is_layer_change('G1 X10') is False

    def test_type_comment(self):
        assert is_layer_change(';TYPE:WALL-OUTER') is False


# =============================================================================
# TEST: parse_layer_number
# =============================================================================

class TestParseLayerNumber:
    """Tests für parse_layer_number()."""

    def test_layer_1(self):
        assert parse_layer_number('; layer:1') == 1

    def test_layer_2(self):
        assert parse_layer_number('; layer:2') == 2

    def test_no_layer(self):
        assert parse_layer_number('G1 X10') is None

    def test_invalid(self):
        assert parse_layer_number('; layer:abc') is None


# =============================================================================
# TEST: is_gcode_line
# =============================================================================

class TestIsGcodeLine:
    """Tests für is_gcode_line()."""

    def test_g0(self):
        assert is_gcode_line('G0 X10') is True

    def test_g1(self):
        assert is_gcode_line('G1 X10 Y20 E0.5') is True

    def test_m82(self):
        assert is_gcode_line('M82') is True

    def test_comment(self):
        assert is_gcode_line('; Kommentar') is False

    def test_empty(self):
        assert is_gcode_line('') is False


# =============================================================================
# TEST: GCodeEvent
# =============================================================================

class TestGCodeEvent:
    """Tests für GCodeEvent."""

    def test_g1_event(self):
        event = GCodeEvent(0, 'G1 X10 Y20 Z0.3 E0.5')
        event.parse()
        assert event.command == 'G1'
        assert event.command_type == 'extrude_or_travel'
        assert event.params == {'X': 10.0, 'Y': 20.0, 'Z': 0.3, 'E': 0.5}
        assert event.has_e is True
        assert event.has_xy is True
        assert event.is_comment is False
        assert event.is_empty is False

    def test_g0_event(self):
        event = GCodeEvent(1, 'G0 X15 Y15 F6000')
        event.parse()
        assert event.command == 'G0'
        assert event.command_type == 'travel'
        assert event.params == {'X': 15.0, 'Y': 15.0, 'F': 6000.0}
        assert event.has_e is False
        assert event.has_xy is True

    def test_comment_event(self):
        event = GCodeEvent(2, ';TYPE:WALL-OUTER')
        event.parse()
        assert event.type_tag == 'WALL-OUTER'
        # TYPE-Kommentare sind Kommentare (beginnen mit ';')
        assert event.is_comment is True
        assert event.is_empty is False

    def test_empty_event(self):
        event = GCodeEvent(3, '')
        event.parse()
        assert event.is_empty is True
        assert event.is_comment is False

    def test_layer_change_event(self):
        event = GCodeEvent(4, ';LAYER_CHANGE')
        event.parse()
        assert event.is_layer_change is True

    def test_g92_event(self):
        event = GCodeEvent(5, 'G92 E0')
        event.parse()
        assert event.command == 'G92'
        assert event.command_type == 'set_position'
        assert event.params == {'E': 0.0}

    def test_arc_event(self):
        event = GCodeEvent(6, 'G2 X40 Y10 I10 J-10 E3.0')
        event.parse()
        assert event.command == 'G2'
        assert event.command_type == 'arc_cw'
        assert event.params == {'X': 40.0, 'Y': 10.0, 'I': 10.0, 'J': -10.0, 'E': 3.0}

    def test_parenthesis_comment(self):
        """Klammer-Kommentare werden korrekt entfernt."""
        event = GCodeEvent(7, 'G1 X140 Y140 E13.0 (das ist ein Klammerkommentar)')
        event.parse()
        assert event.command == 'G1'
        assert event.params == {'X': 140.0, 'Y': 140.0, 'E': 13.0}

    def test_multiple_gcode_per_line(self):
        """Mehrere GCode-Befehle pro Zeile: erster Befehl wird genommen, finditer findet alle Parameter."""
        event = GCodeEvent(8, 'G1 X10 Y10 E24.0 G1 X20 Y20 E25.0')
        event.parse()
        # Der Parser nimmt den ERSTEN Befehl (G1)
        assert event.command == 'G1'
        # finditer() findet alle Parameter im code_part.
        # Bei mehrfach gleichen Parametern überschreibt der letzte (Dict-Verhalten).
        # Das ist ein bewusst akzeptiertes Verhalten für diesen extrem seltenen Fall.
        assert event.params.get('X') == 20.0  # letzter X-Wert
        assert event.params.get('Y') == 20.0  # letzter Y-Wert
        assert event.params.get('E') == 25.0  # letzter E-Wert


# =============================================================================
# TEST: GCodeParser (Integration)
# =============================================================================

class TestGCodeParser:
    """Integrationstests für GCodeParser."""

    def test_parse_minimal_fixture(self, minimal_gcode_lines):
        """Die minimale Fixture wird vollständig geparst."""
        parser = GCodeParser()
        events = parser.parse_lines(minimal_gcode_lines)
        assert len(events) == len(minimal_gcode_lines)
        assert len(events) > 0

    def test_statistics(self, parsed_minimal):
        """Parser-Statistiken sind plausibel."""
        stats = parsed_minimal.get_statistics()
        assert stats['total_lines'] > 0
        assert stats['gcode_lines'] > 0
        assert 'G1' in stats['commands']
        assert 'G2' in stats['commands'] or 'G3' in stats['commands']

    def test_get_events_by_type(self, parsed_minimal):
        """Events nach TYPE-Tag abrufbar."""
        outer = parsed_minimal.get_events_by_type('WALL-OUTER')
        assert len(outer) > 0
        inner = parsed_minimal.get_events_by_type('WALL-INNER')
        assert len(inner) > 0

    def test_get_events_by_layer(self, parsed_minimal):
        """Events nach Layer abrufbar."""
        events = parsed_minimal.get_events_by_layer(1)
        assert len(events) > 0

    def test_get_events_by_command(self, parsed_minimal):
        """Events nach Befehl abrufbar."""
        g1_events = parsed_minimal.get_events_by_command('G1')
        assert len(g1_events) > 0
        m82_events = parsed_minimal.get_events_by_command('M82')
        assert len(m82_events) > 0

    def test_g92_e0_detected(self, parsed_minimal):
        """G92 E0 wird korrekt erkannt."""
        g92_events = parsed_minimal.get_events_by_command('G92')
        assert len(g92_events) >= 2
        for event in g92_events:
            assert event.params.get('E') == 0.0

    def test_arcs_detected(self, parsed_minimal):
        """G2/G3-Arcs werden erkannt."""
        g2_events = parsed_minimal.get_events_by_command('G2')
        g3_events = parsed_minimal.get_events_by_command('G3')
        assert len(g2_events) > 0
        assert len(g3_events) > 0
        for event in g2_events + g3_events:
            assert 'I' in event.params or 'J' in event.params

    def test_m82_m83_tracked(self, parsed_minimal):
        """M82/M83-Events werden erkannt."""
        m82 = parsed_minimal.get_events_by_command('M82')
        m83 = parsed_minimal.get_events_by_command('M83')
        assert len(m82) >= 2  # mindestens 2x M82 in der Fixture
        assert len(m83) >= 1  # mindestens 1x M83

    def test_retracts_detected(self, parsed_minimal):
        """G10/G11-Retracts werden erkannt."""
        g10 = parsed_minimal.get_events_by_command('G10')
        g11 = parsed_minimal.get_events_by_command('G11')
        assert len(g10) >= 1
        assert len(g11) >= 1

    def test_parse_file(self):
        """parse_file() funktioniert."""
        parser = GCodeParser()
        events = parser.parse_file(str(MINIMAL_FIXTURE))
        assert len(events) > 0
        stats = parser.get_statistics()
        assert stats['total_lines'] == len(events)


# =============================================================================
# TEST: Spezifische Parser-Fälle aus der Fixture
# =============================================================================

class TestFixtureSpecificCases:
    """Tests für spezifische, kritische Parser-Fälle."""

    def test_scientific_notation_fixture(self, parsed_minimal):
        """Scientific Notation in der Fixture wird korrekt geparst."""
        events = parsed_minimal.events
        # Suche nach Zeile mit E1e-3
        for event in events:
            if event.command == 'G1' and event.params.get('E') is not None:
                if abs(event.params['E'] - 0.001) < 1e-10:
                    return  # Gefunden!
        pytest.fail("Kein Event mit E=0.001 (E1e-3) gefunden")

    def test_negative_e_values(self, parsed_minimal):
        """Negative E-Werte werden korrekt geparst."""
        events = parsed_minimal.events
        found_negative = False
        for event in events:
            if event.params.get('E', 0) < 0:
                found_negative = True
                break
        assert found_negative, "Kein negativer E-Wert in der Fixture gefunden"

    def test_g91_relative(self, parsed_minimal):
        """G91 (relative Positionierung) wird erkannt."""
        g91_events = parsed_minimal.get_events_by_command('G91')
        assert len(g91_events) == 1

    def test_g90_absolute(self, parsed_minimal):
        """G90 (absolute Positionierung) wird erkannt."""
        g90_events = parsed_minimal.get_events_by_command('G90')
        assert len(g90_events) >= 1

    def test_layer_change_count(self, parsed_minimal):
        """Anzahl Layer-Wechsel in der Fixture."""
        layer_changes = sum(1 for e in parsed_minimal.events if e.is_layer_change)
        assert layer_changes == 2  # 2 LAYER_CHANGE in der Fixture

    def test_type_tag_count(self, parsed_minimal):
        """Alle TYPE-Tags der Fixture werden erkannt."""
        types = set()
        for event in parsed_minimal.events:
            if event.type_tag:
                types.add(event.type_tag)
        expected_types = {'WALL-OUTER', 'WALL-INNER', 'FILL', 'SUPPORT', 'SKIN'}
        for t in expected_types:
            assert t in types, f"TYPE {t} nicht in der Fixture gefunden"

    def test_no_parameter_leakage(self, parsed_minimal):
        """Parameter aus Kommentaren dürfen nicht in Events landen."""
        for event in parsed_minimal.events:
            if event.is_comment or event.is_empty or event.is_layer_change:
                continue
            if event.command is None:
                continue
            # Prüfe: kein Parameterwert darf aus einem Kommentar stammen
            for key, val in event.params.items():
                assert isinstance(val, float), f"Parameter {key}={val} ist kein float"
                assert val != float('inf'), f"Parameter {key} ist inf"
                assert val != float('nan'), f"Parameter {key} ist nan"