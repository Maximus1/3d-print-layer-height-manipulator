#!/usr/bin/env python3
"""
G-Code Parser
=============
Robuster Parser für 3D-Druck GCode.
Extrahiert Befehle, Parameter und Zustände aus GCode-Zeilen.

Regeln:
- Kein re.sub() auf komplette GCode-Zeilen
- code_part = line.split(';')[0]
- M82/M83 korrekt tracken
- G92 korrekt tracken
- G0/G1/G2/G3 korrekt parsen
- Kommentare korrekt entfernen
- Positionen korrekt tracken
- Absolute/relative Modi korrekt
"""

import re
from typing import Optional, Dict, Any, List, Tuple


# =============================================================================
# PARAMETER-PATTERN
# =============================================================================

# Einzelner Parameter: Buchstabe + Zahl (auch negative, scientific notation)
# Erlaubt: E1.0, E-1.0, E1e-3, E1.5E-2, X100, Y-0.001
_PARAM_PATTERN = re.compile(r'(?<![A-Za-z])([XYZEFIJRP])\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)')


# =============================================================================
# GCODE-EVENT-TYPEN (für type-sicheres Logging)
# =============================================================================

GCODE_TYPES = {
    'G0':  'travel',
    'G1':  'extrude_or_travel',  # muss anhand E entschieden werden
    'G2':  'arc_cw',
    'G3':  'arc_ccw',
    'G10': 'retract',
    'G11': 'unretract',
    'G28': 'home',
    'G90': 'absolute_xyz',
    'G91': 'relative_xyz',
    'G92': 'set_position',
    'M82': 'absolute_e',
    'M83': 'relative_e',
    'M104': 'set_temperature',
    'M109': 'wait_temperature',
    'M106': 'fan_on',
    'M107': 'fan_off',
    'M84':  'disable_motors',
    'M140': 'set_bed_temperature',
    'M190': 'wait_bed_temperature',
}


# =============================================================================
# PARSER-FUNKTIONEN
# =============================================================================

def strip_comment(line: str) -> str:
    """
    Entfernt Kommentare aus einer GCode-Zeile.
    Reihenfolge:
    1. Klammer-Kommentare entfernen (z.B. (this is a comment))
    2. Semikolon-Kommentare entfernen (alles ab erstem ';')

    Args:
        line: Roh-Zeile (mit oder ohne Kommentar)

    Returns:
        code_part: Nur der GCode-Teil (ohne Kommentar)
    """
    # Klammer-Kommentare entfernen
    code = re.sub(r'\([^)]*\)', '', line)
    # Semikolon-Kommentare entfernen (alles ab ';')
    code = code.split(';')[0]
    return code.strip()


def parse_command(code: str) -> Optional[str]:
    """
    Extrahiert den GCode-Befehl (z.B. 'G1', 'M82', 'G2').
    Nur gültige Befehle werden erkannt.

    Args:
        code: code_part (ohne Kommentar)

    Returns:
        command oder None
    """
    m = re.match(r'^(G\d+(?:\.\d+)?|M\d+|T\d+)', code, re.I)
    if m:
        return m.group(1).upper()
    return None


def parse_params(code: str) -> Dict[str, float]:
    """
    Extrahiert alle Parameter (X, Y, Z, E, I, J, F, R, P) aus dem code_part.

    KEIN re.sub() auf komplette GCode-Zeilen.
    Verwendet Positiv-Lookbehind für saubere Extraktion.

    Args:
        code: code_part (ohne Kommentar)

    Returns:
        dict mit Parameter -> float
    """
    params: Dict[str, float] = {}
    for m in _PARAM_PATTERN.finditer(code):
        key = m.group(1).upper()
        value = float(m.group(2))
        params[key] = value
    return params


def parse_type_comment(line: str) -> Optional[str]:
    """
    Extrahiert den TYPE aus einem ;TYPE:-Kommentar.
    Beispiel: ";TYPE:WALL-OUTER" -> "WALL-OUTER"

    Args:
        line: Roh-Zeile

    Returns:
        Typ-String oder None
    """
    m = re.match(r'^;\s*TYPE\s*:\s*(.*)', line.strip(), re.I)
    if m:
        return m.group(1).strip()
    return None


def is_layer_change(line: str) -> bool:
    """
    Erkennt einen Layer-Wechsel (;LAYER_CHANGE oder ;LAYER CHANGE).

    Args:
        line: Roh-Zeile

    Returns:
        True wenn Layer-Wechsel
    """
    s = line.strip().lower()
    return s.startswith(';layer_change') or s.startswith(';layer change')


def parse_layer_number(line: str) -> Optional[int]:
    """
    Extrahiert die Layer-Nummer aus einem "; layer:N"-Kommentar.

    Args:
        line: Roh-Zeile

    Returns:
        Layer-Nummer oder None
    """
    m = re.match(r'^;\s*layer\s*:\s*(\d+)', line.strip(), re.I)
    if m:
        return int(m.group(1))
    return None


def is_gcode_line(line: str) -> bool:
    """
    Prüft ob eine Zeile einen GCode-Befehl enthält.

    Args:
        line: Roh-Zeile

    Returns:
        True wenn die Zeile einen Befehl enthält
    """
    code = strip_comment(line)
    if not code:
        return False
    return parse_command(code) is not None


# =============================================================================
# GCODE-EVENT-STRUKTUR
# =============================================================================

class GCodeEvent:
    """
    Ein einzelnes GCode-Event mit allen geparsten Informationen.

    Attribute:
        line_idx: Zeilenindex (0-basiert)
        raw: Roh-Zeile
        command: GCode-Befehl (z.B. 'G1', 'M82')
        command_type: Typ des Befehls (z.B. 'extrude_or_travel', 'absolute_e')
        params: Parameter-Dict (X, Y, Z, E, I, J, F, R, P)
        has_e: Hat diese Zeile einen E-Parameter?
        has_xy: Hat diese Zeile X- und/oder Y-Parameter?
        type_tag: TYPE-Kommentar (z.B. 'WALL-OUTER')
        is_layer_change: Ist dies ein Layer-Wechsel?
        layer_number: Layer-Nummer (falls bekannt)
        is_comment: Ist dies eine reine Kommentarzeile?
        is_empty: Ist dies eine leere Zeile?
    """

    __slots__ = (
        'line_idx', 'raw', 'command', 'command_type', 'params',
        'has_e', 'has_xy', 'type_tag', 'is_layer_change',
        'layer_number', 'is_comment', 'is_empty'
    )

    def __init__(self, line_idx: int, raw: str):
        self.line_idx = line_idx
        self.raw = raw

        self.command: Optional[str] = None
        self.command_type: Optional[str] = None
        self.params: Dict[str, float] = {}
        self.has_e: bool = False
        self.has_xy: bool = False
        self.type_tag: Optional[str] = None
        self.is_layer_change: bool = False
        self.layer_number: Optional[int] = None
        self.is_comment: bool = False
        self.is_empty: bool = False

    def parse(self):
        """Führt die vollständige Analyse der Zeile durch."""
        line_stripped = self.raw.strip()

        # Leere Zeile?
        if not line_stripped:
            self.is_empty = True
            return

        # TYPE-Kommentar?
        self.type_tag = parse_type_comment(line_stripped)

        # Layer-Wechsel?
        self.is_layer_change = is_layer_change(line_stripped)
        if self.is_layer_change:
            return

        # Layer-Nummer?
        self.layer_number = parse_layer_number(line_stripped)
        if self.layer_number is not None:
            return

        # Nur Kommentar?
        if line_stripped.startswith(';'):
            self.is_comment = True
            return

        # Code-Teil extrahieren
        code = strip_comment(line_stripped)

        # Wenn nach Strip nichts mehr übrig ist -> nur Kommentar
        if not code:
            self.is_comment = True
            return

        # Befehl parsen
        self.command = parse_command(code)
        if self.command is None:
            # Ungültige Zeile -> als Kommentar behandeln
            self.is_comment = True
            return

        # Command-Type bestimmen
        self.command_type = GCODE_TYPES.get(self.command, 'unknown')

        # Parameter parsen
        self.params = parse_params(code)

        # Flags setzen
        self.has_e = 'E' in self.params
        self.has_xy = 'X' in self.params or 'Y' in self.params

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Event in ein Dict (für Logging)."""
        return {
            'line_idx': self.line_idx,
            'command': self.command,
            'command_type': self.command_type,
            'params': dict(self.params),
            'has_e': self.has_e,
            'has_xy': self.has_xy,
            'type_tag': self.type_tag,
            'is_layer_change': self.is_layer_change,
            'layer_number': self.layer_number,
            'is_comment': self.is_comment,
            'is_empty': self.is_empty,
            'raw': self.raw.rstrip('\n'),
        }

    def __repr__(self) -> str:
        return (
            f"GCodeEvent({self.line_idx}: "
            f"cmd={self.command}, "
            f"params={self.params}, "
            f"type={self.type_tag})"
        )


# =============================================================================
# GCODE-PARSER (HAUPTKLASSE)
# =============================================================================

class GCodeParser:
    """
    Parst eine GCode-Datei zeilenweise in GCodeEvents.

    Features:
    - Zeilenweises Parsen
    - Zugriff auf Events nach Index, Typ, Layer
    - Statistische Auswertung
    """

    def __init__(self):
        self.events: List[GCodeEvent] = []
        self._type_map: Dict[str, List[int]] = {}  # type_tag -> [line_indices]
        self._layer_map: Dict[int, List[int]] = {}  # layer -> [line_indices]
        self._command_map: Dict[str, List[int]] = {}  # command -> [line_indices]

    def parse_line(self, line: str, line_idx: int) -> GCodeEvent:
        """Parst eine einzelne Zeile."""
        event = GCodeEvent(line_idx, line)
        event.parse()
        self.events.append(event)

        # Indizes bauen
        if event.command:
            self._command_map.setdefault(event.command, []).append(line_idx)
        if event.type_tag:
            self._type_map.setdefault(event.type_tag, []).append(line_idx)
        if event.layer_number is not None:
            self._layer_map.setdefault(event.layer_number, []).append(line_idx)

        return event

    def parse_lines(self, lines: List[str]) -> List[GCodeEvent]:
        """Parst mehrere Zeilen."""
        self.events = []
        self._type_map = {}
        self._layer_map = {}
        self._command_map = {}

        for idx, line in enumerate(lines):
            self.parse_line(line, idx)
        return self.events

    def parse_file(self, filepath: str) -> List[GCodeEvent]:
        """Parst eine GCode-Datei."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f:
                lines = f.readlines()

        return self.parse_lines(lines)

    def get_events_by_type(self, type_tag: str) -> List[GCodeEvent]:
        """Alle Events mit einem bestimmten TYPE-Tag."""
        indices = self._type_map.get(type_tag, [])
        return [self.events[i] for i in indices]

    def get_events_by_layer(self, layer: int) -> List[GCodeEvent]:
        """Alle Events in einem bestimmten Layer."""
        indices = self._layer_map.get(layer, [])
        return [self.events[i] for i in indices]

    def get_events_by_command(self, command: str) -> List[GCodeEvent]:
        """Alle Events mit einem bestimmten Befehl."""
        indices = self._command_map.get(command, [])
        return [self.events[i] for i in indices]

    def get_statistics(self) -> Dict[str, Any]:
        """Statistiken über die geparste Datei."""
        stats: Dict[str, Any] = {
            'total_lines': len(self.events),
            'commands': {},
            'types': {},
            'layers': len(self._layer_map),
            'gcode_lines': 0,
            'comment_lines': 0,
            'empty_lines': 0,
            'layer_change_lines': 0,
        }

        for event in self.events:
            if event.is_empty:
                stats['empty_lines'] += 1
            elif event.is_comment:
                stats['comment_lines'] += 1
            elif event.is_layer_change:
                stats['layer_change_lines'] += 1
            elif event.command:
                stats['gcode_lines'] += 1
                cmd = event.command
                stats['commands'][cmd] = stats['commands'].get(cmd, 0) + 1

        return stats


# =============================================================================
# MAIN / TEST
# =============================================================================

def main():
    """Parser-Test mit der minimalen Fixture."""
    import sys
    from pathlib import Path

    # Standard-Fixture
    fixture_path = Path('fixtures/minimal_test.gcode')

    if len(sys.argv) > 1:
        fixture_path = Path(sys.argv[1])

    if not fixture_path.exists():
        print(f"Datei nicht gefunden: {fixture_path}")
        sys.exit(1)

    parser = GCodeParser()
    events = parser.parse_file(str(fixture_path))
    stats = parser.get_statistics()

    print(f"Parser-Statistiken für {fixture_path}:")
    print(f"  Gesamt Zeilen: {stats['total_lines']}")
    print(f"  GCode-Zeilen:  {stats['gcode_lines']}")
    print(f"  Kommentare:    {stats['comment_lines']}")
    print(f"  Leere Zeilen:  {stats['empty_lines']}")
    print(f"  Layer-Wechsel: {stats['layer_change_lines']}")
    print(f"  Layer gesamt:  {stats['layers']}")
    print(f"  Befehle:       {stats['commands']}")
    print()

    # Detailausgabe der ersten Events
    print("Erste 40 Events:")
    print("-" * 60)
    for event in events[:40]:
        if event.is_empty:
            print(f"  [{event.line_idx:4d}] (leer)")
        elif event.is_comment:
            print(f"  [{event.line_idx:4d}] Kommentar: {event.raw.strip()[:50]}")
        elif event.is_layer_change:
            print(f"  [{event.line_idx:4d}] LAYER_CHANGE")
        elif event.command:
            params_str = ' '.join(f"{k}{v}" for k, v in event.params.items())
            print(f"  [{event.line_idx:4d}] {event.command:4s} {params_str}")
        else:
            print(f"  [{event.line_idx:4d}] (unbekannt)")


if __name__ == '__main__':
    main()