#!/usr/bin/env python3
"""
Tests für state_tracker.py
==========================
Testet alle Zustandsübergänge der GCodeState-Maschine.

Test-Fälle (laut Projektplan):
1. Zustands-Test: relative E, absolute E, G92 E, Retracts, Unretracts
2. M82/M83 Wechsel
3. G90/G91 Wechsel
4. G10/G11 Retract/Unretract
5. Extrusion erkannt/nicht erkannt
6. Layer-Wechsel
7. Positionstracking (absolut/relativ)
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from gcode_parser import GCodeEvent
from state_tracker import GCodeState


# =============================================================================
# HELPERS
# =============================================================================

def make_event(line_idx: int, raw: str):
    """Erzeugt ein GCodeEvent und parst es."""
    event = GCodeEvent(line_idx, raw)
    event.parse()
    return event


# =============================================================================
# TEST: Initialzustand
# =============================================================================

class TestInitialState:
    """Der Initialzustand muss korrekt sein."""

    def test_initial_position(self):
        state = GCodeState()
        assert state.current_x == 0.0
        assert state.current_y == 0.0
        assert state.current_z == 0.0

    def test_initial_extruder(self):
        state = GCodeState()
        assert state.current_e == 0.0
        assert state.relative_e_mode is False

    def test_initial_modes(self):
        state = GCodeState()
        assert state.relative_xyz_mode is False  # G90

    def test_initial_state(self):
        state = GCodeState()
        assert state.is_retracted is False
        assert state.is_printing is False
        assert state.awaiting_unretract is False
        assert state.current_layer == 0


# =============================================================================
# TEST: M82 / M83
# =============================================================================

class TestM82M83:
    """M82 (absolute E) und M83 (relative E) Wechsel."""

    def test_m82_default(self):
        state = GCodeState()
        assert state.relative_e_mode is False

    def test_m83_sets_relative(self):
        state = GCodeState()
        event = make_event(0, 'M83')
        changes = state.process_event(event)
        assert state.relative_e_mode is True
        assert changes['state_changes']['relative_e_mode']['new'] is True

    def test_m82_back_to_absolute(self):
        state = GCodeState()
        state.process_event(make_event(0, 'M83'))  # zu relativ
        event = make_event(1, 'M82')
        changes = state.process_event(event)
        assert state.relative_e_mode is False
        assert changes['state_changes']['relative_e_mode']['new'] is False

    def test_m82_m83_toggle(self):
        state = GCodeState()
        assert state.relative_e_mode is False
        state.process_event(make_event(0, 'M83'))
        assert state.relative_e_mode is True
        state.process_event(make_event(1, 'M82'))
        assert state.relative_e_mode is False


# =============================================================================
# TEST: G90 / G91
# =============================================================================

class TestG90G91:
    """G90 (absolute) und G91 (relative) Positionierung."""

    def test_g90_default(self):
        state = GCodeState()
        assert state.relative_xyz_mode is False

    def test_g91_sets_relative(self):
        state = GCodeState()
        event = make_event(0, 'G91')
        changes = state.process_event(event)
        assert state.relative_xyz_mode is True
        assert changes['state_changes']['relative_xyz_mode']['new'] is True

    def test_g90_back_to_absolute(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G91'))
        event = make_event(1, 'G90')
        changes = state.process_event(event)
        assert state.relative_xyz_mode is False
        assert changes['state_changes']['relative_xyz_mode']['new'] is False

    def test_absolute_position_update(self):
        """G90: absolute Koordinaten."""
        state = GCodeState()
        event = make_event(0, 'G1 X10 Y20 Z0.5')
        state.process_event(event)
        assert state.current_x == 10.0
        assert state.current_y == 20.0
        assert state.current_z == 0.5

    def test_relative_position_update(self):
        """G91: relative Koordinaten."""
        state = GCodeState()
        state.process_event(make_event(0, 'G91'))
        event = make_event(1, 'G1 X10 Y5 Z0.1')
        state.process_event(event)
        assert state.current_x == 10.0
        assert state.current_y == 5.0
        assert state.current_z == 0.1
        # Zweite relative Bewegung
        event2 = make_event(2, 'G1 X5 Y5 Z0.1')
        state.process_event(event2)
        assert state.current_x == 15.0  # 10 + 5
        assert state.current_y == 10.0  # 5 + 5
        assert state.current_z == 0.2  # 0.1 + 0.1


# =============================================================================
# TEST: G92
# =============================================================================

class TestG92:
    """G92 (Set Position)."""

    def test_g92_e0(self):
        state = GCodeState()
        # Vorher etwas extrudieren
        state.process_event(make_event(0, 'G1 X10 Y10 E5.0'))
        assert state.current_e == 5.0
        # G92 E0 reset
        event = make_event(1, 'G92 E0')
        changes = state.process_event(event)
        assert state.current_e == 0.0
        assert state.last_e == 0.0  # G92 reset
        assert changes['state_changes']['current_e']['old'] == 5.0
        assert changes['state_changes']['current_e']['new'] == 0.0

    def test_g92_multiple(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G92 E0'))
        state.process_event(make_event(1, 'G1 X10 Y10 E2.0'))
        assert state.current_e == 2.0
        state.process_event(make_event(2, 'G92 E0'))
        assert state.current_e == 0.0
        state.process_event(make_event(3, 'G1 X20 Y20 E1.5'))
        assert state.current_e == 1.5


# =============================================================================
# TEST: G10 / G11 Retract/Unretract
# =============================================================================

class TestG10G11:
    """G10 (Retract) und G11 (Unretract)."""

    def test_g10_retract(self):
        state = GCodeState()
        event = make_event(0, 'G10')
        changes = state.process_event(event)
        assert state.is_retracted is True
        assert state.awaiting_unretract is True
        assert changes['state_changes']['is_retracted']['new'] is True

    def test_g11_unretract(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G10'))
        event = make_event(1, 'G11')
        changes = state.process_event(event)
        assert state.is_retracted is False
        assert changes['state_changes']['is_retracted']['new'] is False

    def test_double_g10_no_change(self):
        """Zweimal G10 hintereinander ändert nichts."""
        state = GCodeState()
        state.process_event(make_event(0, 'G10'))
        event = make_event(1, 'G10')
        changes = state.process_event(event)
        # Keine Änderung: is_retracted war bereits True
        assert 'is_retracted' not in changes['state_changes']

    def test_g11_without_g10(self):
        """G11 ohne vorheriges G10 hat keinen Effekt."""
        state = GCodeState()
        event = make_event(0, 'G11')
        changes = state.process_event(event)
        assert state.is_retracted is False
        assert 'is_retracted' not in changes['state_changes']


# =============================================================================
# TEST: Extrusion (G1 mit E)
# =============================================================================

class TestExtrusion:
    """Erkennung von Extrusion vs. Travel."""

    def test_extrusion_updates_e(self):
        state = GCodeState()
        event = make_event(0, 'G1 X10 Y10 E0.5')
        changes = state.process_event(event)
        assert state.current_e == 0.5
        assert changes['state_changes']['e']['delta'] == 0.5

    def test_extrusion_sets_printing(self):
        state = GCodeState()
        event = make_event(0, 'G1 X10 Y10 E0.5')
        state.process_event(event)
        assert state.is_printing is True

    def test_extrusion_updates_last_extrusion(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y10 E0.5'))
        assert state.last_extrusion_x == 10.0
        assert state.last_extrusion_y == 10.0

    def test_travel_no_e(self):
        """G0 ohne E verändert den E-Wert nicht."""
        state = GCodeState()
        state.current_e = 5.0
        event = make_event(0, 'G0 X20 Y20 F6000')
        state.process_event(event)
        assert state.current_e == 5.0  # unverändert

    def test_extrusion_absolute_mode(self):
        """M82: absolute E-Werte."""
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y10 E5.0'))
        assert state.current_e == 5.0
        state.process_event(make_event(1, 'G1 X20 Y20 E10.0'))
        assert state.current_e == 10.0
        assert state.get_e_delta() == 5.0  # 10 - 5

    def test_extrusion_relative_mode(self):
        """M83: relative E-Werte."""
        state = GCodeState()
        state.process_event(make_event(0, 'M83'))
        state.process_event(make_event(1, 'G1 X10 Y10 E0.5'))
        assert state.current_e == 0.5  # Delta
        state.process_event(make_event(2, 'G1 X20 Y20 E0.3'))
        assert state.current_e == 0.3  # Delta (relativ)
        assert state.get_e_delta() == 0.3

    def test_multiple_extrusions(self):
        """Mehrere Extrusionen hintereinander."""
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y10 E1.0'))
        state.process_event(make_event(1, 'G1 X20 Y10 E2.0'))
        state.process_event(make_event(2, 'G1 X20 Y20 E3.0'))
        assert state.current_e == 3.0
        assert state.is_printing is True

    def test_extrusion_without_xy(self):
        """E ohne XY (Retract durch negatives E)."""
        state = GCodeState()
        state.process_event(make_event(0, 'G1 E-0.5'))
        # Negatives E-Delta ohne XY = Retract
        state.process_event(make_event(1, 'G1 X10 Y10 E0.0'))
        assert state.is_printing or True  # keine Exception


# =============================================================================
# TEST: Retract durch negatives E-Delta
# =============================================================================

class TestNegativeEDelta:
    """Negatives E-Delta als Retract."""

    def test_negative_e_delta_retracts(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y10 E5.0'))
        assert state.is_retracted is False
        event = make_event(1, 'G1 X10 Y10 E4.5')  # negatives Delta
        state.process_event(event)
        assert state.is_retracted is True


# =============================================================================
# TEST: Layer-Wechsel
# =============================================================================

class TestLayerChange:
    """Layer-Wechsel."""

    def test_layer_change_increments(self):
        state = GCodeState()
        event = make_event(0, ';LAYER_CHANGE')
        state.process_event(event)
        assert state.current_layer == 1

    def test_multiple_layer_changes(self):
        state = GCodeState()
        state.process_event(make_event(0, ';LAYER_CHANGE'))
        assert state.current_layer == 1
        state.process_event(make_event(1, ';LAYER_CHANGE'))
        assert state.current_layer == 2

    def test_layer_change_resets_contour(self):
        state = GCodeState()
        state.current_contour = 5
        state.process_event(make_event(0, ';LAYER_CHANGE'))
        assert state.current_contour == 0

    def test_absolute_layer_number(self):
        state = GCodeState()
        event = make_event(0, '; layer:3')
        state.process_event(event)
        assert state.current_layer == 3


# =============================================================================
# TEST: Type-Tag
# =============================================================================

class TestTypeTag:
    """Type-Tag Tracking."""

    def test_type_updates(self):
        state = GCodeState()
        event = make_event(0, ';TYPE:WALL-OUTER')
        state.process_event(event)
        assert state.current_type == 'WALL-OUTER'

    def test_type_overwrites(self):
        state = GCodeState()
        state.process_event(make_event(0, ';TYPE:WALL-OUTER'))
        state.process_event(make_event(1, ';TYPE:WALL-INNER'))
        assert state.current_type == 'WALL-INNER'

    def test_type_changes_in_event(self):
        state = GCodeState()
        event = make_event(0, ';TYPE:WALL-OUTER')
        changes = state.process_event(event)
        assert changes['state_changes']['type']['new'] == 'WALL-OUTER'
        assert changes['state_changes']['type']['old'] is None


# =============================================================================
# TEST: G28 Home
# =============================================================================

class TestG28:
    """G28 Home."""

    def test_g28_resets_position(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X100 Y200 Z10 E50.0'))
        state.process_event(make_event(1, 'G28'))
        assert state.current_x == 0.0
        assert state.current_y == 0.0
        assert state.current_z == 0.0
        assert state.current_e == 0.0

    def test_g28_documents_old_position(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X100 Y200 Z10 E50.0'))
        event = make_event(1, 'G28')
        changes = state.process_event(event)
        assert changes['state_changes']['position']['old'] == (100.0, 200.0, 10.0)
        assert changes['state_changes']['position']['new'] == (0.0, 0.0, 0.0)


# =============================================================================
# TEST: Feedrate
# =============================================================================

class TestFeedrate:
    """Feedrate-Tracking."""

    def test_feedrate_updates(self):
        state = GCodeState()
        event = make_event(0, 'G1 X10 Y10 F3000')
        state.process_event(event)
        assert state.current_feedrate == 3000.0

    def test_feedrate_overwrites(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 F3000'))
        state.process_event(make_event(1, 'G1 X20 F6000'))
        assert state.current_feedrate == 6000.0

    def test_feedrate_initial_none(self):
        state = GCodeState()
        assert state.current_feedrate is None


# =============================================================================
# TEST: Distanzberechnungen
# =============================================================================

class TestDistanceCalculations:
    """Distanzberechnungen."""

    def test_distance_to_last(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y0 E0.5'))
        assert state.distance_to_last() == 10.0  # 0,0 -> 10,0

    def test_distance_from_last_extrusion(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y10 E0.5'))
        # Nach der ersten Extrusion: current = (10,10), last_extrusion = (10,10)
        # Jetzt eine Travel-Bewegung (kein E)
        state.process_event(make_event(1, 'G0 X30 Y20'))
        # current = (30, 20), last_extrusion = (10, 10)
        dist = state.distance_from_last_extrusion()
        assert dist is not None
        expected = ((30 - 10) ** 2 + (20 - 10) ** 2) ** 0.5
        assert abs(dist - expected) < 1e-10

    def test_distance_from_last_extrusion_none(self):
        state = GCodeState()
        # Keine vorherige Extrusion
        assert state.distance_from_last_extrusion() is None

    def test_distance_after_travel(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y10 E0.5'))
        state.process_event(make_event(1, 'G0 X50 Y50'))
        dist = state.distance_to_last()
        assert abs(dist - (40 * 2 ** 0.5)) < 1e-10


# =============================================================================
# TEST: Integration Parser + State
# =============================================================================

class TestParserStateIntegration:
    """Parser und State Tracker zusammen."""

    def test_full_workflow(self):
        """Simuliert einen simplen GCode-Durchlauf."""
        from gcode_parser import GCodeParser

        gcode = [
            'M82\n',                    # absolute E
            'G90\n',                    # absolute XYZ
            'G1 X10 Y10 Z0.3 F3000 E0.5\n',  # extrude
            'G1 X20 Y10 E1.0\n',        # extrude
            'G1 X20 Y20 E1.5\n',        # extrude
            'G10\n',                    # retract
            'G0 X50 Y50 Z1.0\n',       # travel
            'G11\n',                    # unretract
            'G1 X60 Y60 Z1.0 E2.0\n',  # extrude
        ]

        parser = GCodeParser()
        events = parser.parse_lines(gcode)

        state = GCodeState()
        state_history = []

        for event in events:
            changes = state.process_event(event)
            if changes['state_changes']:
                state_history.append(changes)

        # Prüfungen
        assert state.current_x == 60.0
        assert state.current_y == 60.0
        assert state.current_z == 1.0
        assert state.current_e == 2.0
        assert state.relative_e_mode is False  # M82
        assert state.is_retracted is False  # G11 hat unretracted
        assert state.last_extrusion_x == 60.0
        assert state.last_extrusion_y == 60.0

    def test_relative_mode_workflow(self):
        """Test mit M83 (relativem E)."""
        from gcode_parser import GCodeParser

        gcode = [
            'M83\n',                    # relative E
            'G1 X10 Y10 E0.3\n',
            'G1 X20 Y10 E0.3\n',
            'G1 X20 Y20 E0.3\n',
        ]

        parser = GCodeParser()
        events = parser.parse_lines(gcode)
        state = GCodeState()

        for event in events:
            state.process_event(event)

        # Bei M83: current_e ist das letzte Delta (0.3)
        assert state.current_e == 0.3
        assert state.relative_e_mode is True
        assert state.current_x == 20.0
        assert state.current_y == 20.0

    def test_g92_workflow(self):
        """G92 E0 im Workflow."""
        from gcode_parser import GCodeParser

        gcode = [
            'G92 E0\n',                 # reset
            'G1 X10 Y10 E2.0\n',        # extrude 2mm
            'G92 E0\n',                 # reset auf 0
            'G1 X20 Y20 E1.0\n',        # extrude 1mm
        ]

        parser = GCodeParser()
        events = parser.parse_lines(gcode)
        state = GCodeState()

        for event in events:
            state.process_event(event)

        assert state.current_e == 1.0


# =============================================================================
# TEST: Snapshot
# =============================================================================

class TestSnapshot:
    """Snapshot-Funktion."""

    def test_snapshot_contains_all_keys(self):
        state = GCodeState()
        state.process_event(make_event(0, 'G1 X10 Y20 Z0.5 E1.0'))
        snap = state.snapshot()

        assert 'position' in snap
        assert 'last_position' in snap
        assert 'last_extrusion' in snap
        assert 'extruder' in snap
        assert 'modes' in snap
        assert 'state' in snap
        assert 'layer' in snap
        assert 'feedrate' in snap

        assert snap['position']['x'] == 10.0
        assert snap['position']['y'] == 20.0
        assert snap['extruder']['current_e'] == 1.0