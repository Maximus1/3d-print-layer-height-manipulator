#!/usr/bin/env python3
"""
State Tracker – Zustandsmaschine für GCode-Verarbeitung
======================================================
Trackt exakt alle relevanten Zustände während der GCode-Verarbeitung.

Pflichtvariablen (laut Projektplan):
- current_xy
- last_xy
- last_extrusion_xy
- current_e
- relative_e_mode
- relative_xyz_mode
- is_retracted
- is_printing
- current_layer
- current_feedrate
- awaiting_unretract
- current_contour
"""

from typing import Optional, Tuple
import math


class GCodeState:
    """
    Vollständiger Zustand während der GCode-Verarbeitung.

    Alle Zustandsvariablen werden hier zentral verwaltet.
    Jeder Zustandswechsel wird dokumentiert.
    """

    __slots__ = (
        'current_x', 'current_y', 'current_z',
        'last_x', 'last_y',
        'last_extrusion_x', 'last_extrusion_y',
        'current_e',
        'last_e',
        'relative_e_mode',
        'relative_xyz_mode',
        'is_retracted',
        'is_printing',
        'current_layer',
        'current_feedrate',
        'awaiting_unretract',
        'current_contour',
        'current_type',
        'modifiers',
        '_state_history',
    )

    def __init__(self):
        # Positionen
        self.current_x: float = 0.0
        self.current_y: float = 0.0
        self.current_z: float = 0.0
        self.last_x: float = 0.0
        self.last_y: float = 0.0

        # Letzte Extrusionsposition (für Wipe-Erkennung)
        self.last_extrusion_x: Optional[float] = None
        self.last_extrusion_y: Optional[float] = None

        # Extruder
        self.current_e: float = 0.0
        self.last_e: float = 0.0

        # Modi
        self.relative_e_mode: bool = False    # M82 = False, M83 = True
        self.relative_xyz_mode: bool = False  # G90 = False, G91 = True

        # Zustände
        self.is_retracted: bool = False
        self.is_printing: bool = False
        self.awaiting_unretract: bool = False

        # Layer / Kontur
        self.current_layer: int = 0
        self.current_contour: int = 0
        self.current_type: Optional[str] = None

        # Geschwindigkeit
        self.current_feedrate: Optional[float] = None

        # Modifier (z.B. H, S, P)
        self.modifiers: dict = {}

        # Historie (optional, für Debug)
        self._state_history: list = []

    @property
    def current_xy(self) -> Tuple[float, float]:
        return (self.current_x, self.current_y)

    @property
    def last_xy(self) -> Tuple[float, float]:
        return (self.last_x, self.last_y)

    def distance_to_last(self) -> float:
        """Distanz von letzter zu aktueller Position."""
        return math.sqrt(
            (self.current_x - self.last_x) ** 2 +
            (self.current_y - self.last_y) ** 2
        )

    def distance_from_last_extrusion(self) -> Optional[float]:
        """Distanz von letzter Extrusion zu aktueller Position."""
        if self.last_extrusion_x is None or self.last_extrusion_y is None:
            return None
        return math.sqrt(
            (self.current_x - self.last_extrusion_x) ** 2 +
            (self.current_y - self.last_extrusion_y) ** 2
        )

    def get_e_delta(self) -> float:
        """E-Delta (absolut oder relativ, je nach Modus)."""
        if self.relative_e_mode:
            return self.current_e  # bei M83 ist E direkt das Delta
        else:
            return self.current_e - self.last_e

    def update_position(self, x: Optional[float] = None,
                        y: Optional[float] = None,
                        z: Optional[float] = None):
        """Aktualisiert Positionen unter Berücksichtigung von G91 (relativ)."""
        self.last_x = self.current_x
        self.last_y = self.current_y

        if self.relative_xyz_mode:
            if x is not None:
                self.current_x += x
            if y is not None:
                self.current_y += y
            if z is not None:
                self.current_z += z
        else:
            if x is not None:
                self.current_x = x
            if y is not None:
                self.current_y = y
            if z is not None:
                self.current_z = z

    def update_e(self, e_value: float):
        """
        Aktualisiert E-Wert.
        - Bei M83 (relativ): current_e ist direkt das Delta
        - Bei M82 (absolut): current_e ist absoluter Wert
        """
        self.last_e = self.current_e
        if self.relative_e_mode:
            # Bei M83 ist E das Delta
            self.current_e = e_value  # Delta
        else:
            # Bei M82 ist E absolut
            self.current_e = e_value

    def process_event(self, event) -> dict:
        """
        Verarbeitet ein GCodeEvent und aktualisiert den Zustand.
        Gibt ein Dict mit den Änderungen zurück (für Logging).

        Args:
            event: GCodeEvent aus gcode_parser.py

        Returns:
            changes: Dict mit den vorgenommenen Änderungen
        """
        changes = {
            'line_idx': event.line_idx,
            'command': event.command,
            'state_changes': {},
        }

        # Type-Tag aktualisieren
        if event.type_tag:
            old_type = self.current_type
            self.current_type = event.type_tag
            changes['state_changes']['type'] = {
                'old': old_type,
                'new': self.current_type,
            }

        # Layer-Wechsel
        if event.is_layer_change:
            self.current_layer += 1
            self.current_contour = 0
            changes['state_changes']['layer'] = {
                'new': self.current_layer,
            }
            return changes

        # Layer-Nummer (absolute Angabe)
        if event.layer_number is not None:
            self.current_layer = event.layer_number
            changes['state_changes']['layer'] = {
                'new': self.current_layer,
            }
            return changes

        # Kein Befehl -> nichts zu tun
        if event.command is None:
            return changes

        # ========================================================
        # M-Befehle
        # ========================================================

        if event.command == 'M82':  # Absolute Extrusion
            old_mode = self.relative_e_mode
            self.relative_e_mode = False
            changes['state_changes']['relative_e_mode'] = {
                'old': old_mode,
                'new': False,
            }
            return changes

        if event.command == 'M83':  # Relative Extrusion
            old_mode = self.relative_e_mode
            self.relative_e_mode = True
            changes['state_changes']['relative_e_mode'] = {
                'old': old_mode,
                'new': True,
            }
            return changes

        if event.command == 'G90':  # Absolute Positionierung
            old_mode = self.relative_xyz_mode
            self.relative_xyz_mode = False
            changes['state_changes']['relative_xyz_mode'] = {
                'old': old_mode,
                'new': False,
            }
            return changes

        if event.command == 'G91':  # Relative Positionierung
            old_mode = self.relative_xyz_mode
            self.relative_xyz_mode = True
            changes['state_changes']['relative_xyz_mode'] = {
                'old': old_mode,
                'new': True,
            }
            return changes

        if event.command in ('G10',):  # Retract
            if not self.is_retracted:
                self.is_retracted = True
                self.awaiting_unretract = True
                changes['state_changes']['is_retracted'] = {
                    'old': False,
                    'new': True,
                }
            return changes

        if event.command in ('G11',):  # Unretract
            if self.is_retracted:
                self.is_retracted = False
                changes['state_changes']['is_retracted'] = {
                    'old': True,
                    'new': False,
                }
            return changes

        if event.command == 'G92':  # Set Position
            old_e = self.current_e
            if 'E' in event.params:
                self.current_e = event.params['E']
                self.last_e = self.current_e  # G92 reset
                changes['state_changes']['current_e'] = {
                    'old': old_e,
                    'new': self.current_e,
                }
            return changes

        # ========================================================
        # Bewegungsbefehle (G0, G1, G2, G3)
        # ========================================================

        if event.command in ('G0', 'G1', 'G2', 'G3'):
            # Feedrate
            if 'F' in event.params:
                old_f = self.current_feedrate
                self.current_feedrate = event.params['F']
                changes['state_changes']['feedrate'] = {
                    'old': old_f,
                    'new': self.current_feedrate,
                }

            # Position speichern (vor Bewegung)
            old_x, old_y, old_z = self.current_x, self.current_y, self.current_z

            # Position aktualisieren
            self.update_position(
                x=event.params.get('X'),
                y=event.params.get('Y'),
                z=event.params.get('Z'),
            )

            # E aktualisieren
            if event.has_e:
                old_e = self.current_e
                self.update_e(event.params['E'])

                e_delta = self.get_e_delta()

                # Extrusion erkannt?
                is_extrusion = (
                    event.has_xy and
                    e_delta > 0 and
                    not self.is_retracted
                )

                if is_extrusion:
                    # Letzte Extrusionsposition aktualisieren
                    self.last_extrusion_x = self.current_x
                    self.last_extrusion_y = self.current_y
                    self.is_printing = True

                elif e_delta < 0 and not self.is_retracted:
                    # Negatives E-Delta = Retract
                    self.is_retracted = True
                    self.awaiting_unretract = True
                    changes['state_changes']['is_retracted'] = {
                        'old': False,
                        'new': True,
                    }

                changes['state_changes']['e'] = {
                    'old': old_e,
                    'new': self.current_e,
                    'delta': e_delta,
                }

            # Position-Änderungen loggen
            pos_changed = (
                old_x != self.current_x or
                old_y != self.current_y or
                old_z != self.current_z
            )
            if pos_changed:
                changes['state_changes']['position'] = {
                    'old': (old_x, old_y, old_z),
                    'new': (self.current_x, self.current_y, self.current_z),
                    'distance': self.distance_to_last(),
                }

            return changes

        # ========================================================
        # Alle anderen Befehle (G28, M104, M106, etc.)
        # ========================================================

        # G28: Home - setze Position auf 0
        if event.command == 'G28':
            old_pos = (self.current_x, self.current_y, self.current_z)
            self.current_x = 0.0
            self.current_y = 0.0
            self.current_z = 0.0
            self.last_x = 0.0
            self.last_y = 0.0
            self.current_e = 0.0
            self.last_e = 0.0
            changes['state_changes']['position'] = {
                'old': old_pos,
                'new': (0.0, 0.0, 0.0),
            }
            return changes

        # Änderungen an Modifiern (S, P, etc.)
        for key in ('S', 'P', 'R'):
            if key in event.params:
                self.modifiers[key] = event.params[key]
                changes['state_changes'][f'modifier_{key}'] = event.params[key]

        return changes

    def snapshot(self) -> dict:
        """Erzeugt einen vollständigen Snapshot des aktuellen Zustands."""
        return {
            'position': {
                'x': self.current_x,
                'y': self.current_y,
                'z': self.current_z,
            },
            'last_position': {
                'x': self.last_x,
                'y': self.last_y,
            },
            'last_extrusion': {
                'x': self.last_extrusion_x,
                'y': self.last_extrusion_y,
            },
            'extruder': {
                'current_e': self.current_e,
                'last_e': self.last_e,
                'relative_e_mode': self.relative_e_mode,
            },
            'modes': {
                'relative_xyz_mode': self.relative_xyz_mode,
            },
            'state': {
                'is_retracted': self.is_retracted,
                'is_printing': self.is_printing,
                'awaiting_unretract': self.awaiting_unretract,
            },
            'layer': {
                'current_layer': self.current_layer,
                'current_contour': self.current_contour,
                'current_type': self.current_type,
            },
            'feedrate': self.current_feedrate,
        }

    def __repr__(self) -> str:
        return (
            f"GCodeState(pos=({self.current_x:.2f}, {self.current_y:.2f}, {self.current_z:.2f}), "
            f"E={self.current_e:.4f}, "
            f"rel_E={'M83' if self.relative_e_mode else 'M82'}, "
            f"rel_XYZ={'G91' if self.relative_xyz_mode else 'G90'}, "
            f"retracted={self.is_retracted}, "
            f"printing={self.is_printing}, "
            f"layer={self.current_layer}, "
            f"type={self.current_type})"
        )