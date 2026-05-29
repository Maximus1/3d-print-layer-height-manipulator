#!/usr/bin/env python3
"""
Logging System – Strukturiertes JSONL-Logging für alle Module
==============================================================
Jedes Modul loggt über diese zentrale Schnittstelle.

FORMAT: JSONL (eine JSON-Zeile pro Event)
VERZEICHNIS: logs/
DATEINAMEN: logs/<modulname>.jsonl

PFLICHTFELDER:
- timestamp: ISO-Timestamp
- module: Modulname
- event_type: Event-Typ (laut Vorgabe)
- line_number: Zeilennummer im GCode
- command: GCode-Befehl
- decision: Entscheidung
- reason: Begründung
- geometry: Geometriedaten
- state_snapshot: Zustandsdaten
- severity: info/warning/error/critical
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any


# Log-Verzeichnis
LOG_DIR = Path(__file__).parent / 'logs'


class LogEvent:
    """
    Ein einzelner Log-Eintrag mit allen Pflichtfeldern.
    """

    __slots__ = (
        'timestamp', 'module', 'event_type', 'line_number',
        'command', 'decision', 'reason', 'geometry',
        'state_snapshot', 'severity', 'extra',
    )

    def __init__(self, module: str, event_type: str, **kwargs):
        self.timestamp: str = datetime.now(timezone.utc).isoformat()
        self.module: str = module
        self.event_type: str = event_type
        self.line_number: Optional[int] = kwargs.pop('line_number', None)
        self.command: Optional[str] = kwargs.pop('command', None)
        self.decision: Optional[str] = kwargs.pop('decision', None)
        self.reason: Optional[str] = kwargs.pop('reason', None)
        self.geometry: Optional[Dict] = kwargs.pop('geometry', None)
        self.state_snapshot: Optional[Dict] = kwargs.pop('state_snapshot', None)
        self.severity: str = kwargs.pop('severity', 'info')
        self.extra: Dict = kwargs  # verbleibende Argumente

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'timestamp': self.timestamp,
            'module': self.module,
            'event_type': self.event_type,
            'severity': self.severity,
        }
        if self.line_number is not None:
            result['line_number'] = self.line_number
        if self.command is not None:
            result['command'] = self.command
        if self.decision is not None:
            result['decision'] = self.decision
        if self.reason is not None:
            result['reason'] = self.reason
        if self.geometry is not None:
            result['geometry'] = self.geometry
        if self.state_snapshot is not None:
            result['state_snapshot'] = self.state_snapshot
        if self.extra:
            result.update(self.extra)
        return result


class ModuleLogger:
    """
    Logger für ein einzelnes Modul.
    Schreibt JSONL in logs/<modulname>.jsonl.
    """

    def __init__(self, module_name: str):
        self.module_name = module_name
        self._filepath = LOG_DIR / f'{module_name}.jsonl'
        self._ensure_log_dir()
        self._file = None
        self._event_count = 0

    def _ensure_log_dir(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _open(self):
        if self._file is None:
            self._file = open(self._filepath, 'a', encoding='utf-8')
        return self._file

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def log(self, event_type: str, **kwargs) -> 'ModuleLogger':
        """
        Loggt ein Event.
        Gibt self zurück für Method Chaining.

        Args:
            event_type: Typ des Events (laut Vorgabe)
            **kwargs: Weitere Felder (line_number, command, decision, etc.)
        """
        event = LogEvent(
            module=self.module_name,
            event_type=event_type,
            **kwargs
        )
        line = json.dumps(event.to_dict(), default=str)
        f = self._open()
        f.write(line + '\n')
        f.flush()
        self._event_count += 1
        return self

    def info(self, event_type: str, **kwargs):
        """Loggt ein Info-Event."""
        return self.log(event_type, severity='info', **kwargs)

    def warning(self, event_type: str, **kwargs):
        """Loggt ein Warning-Event."""
        return self.log(event_type, severity='warning', **kwargs)

    def error(self, event_type: str, **kwargs):
        """Loggt ein Error-Event."""
        return self.log(event_type, severity='error', **kwargs)

    def critical(self, event_type: str, **kwargs):
        """Loggt ein Critical-Event."""
        return self.log(event_type, severity='critical', **kwargs)

    def get_log_path(self) -> Path:
        return self._filepath

    @property
    def event_count(self) -> int:
        return self._event_count


# =============================================================================
# SESSION-MANAGEMENT
# =============================================================================

_session_loggers: Dict[str, ModuleLogger] = {}


def get_logger(module_name: str) -> ModuleLogger:
    """Holt oder erzeugt einen Logger für ein Modul."""
    if module_name not in _session_loggers:
        _session_loggers[module_name] = ModuleLogger(module_name)
    return _session_loggers[module_name]


def close_all():
    """Schließt alle offenen Logger."""
    for logger in _session_loggers.values():
        logger.close()
    _session_loggers.clear()


# =============================================================================
# STATE-SNAPSHOT-HELPER
# =============================================================================

def snapshot_from_state(state) -> Dict[str, Any]:
    """
    Erzeugt einen State-Snapshot aus einem GCodeState-Objekt.

    Args:
        state: GCodeState-Instanz

    Returns:
        Dict mit relevanten Zustandswerten
    """
    return {
        'position': {
            'x': round(state.current_x, 4),
            'y': round(state.current_y, 4),
            'z': round(state.current_z, 4),
        },
        'last_position': {
            'x': round(state.last_x, 4),
            'y': round(state.last_y, 4),
        },
        'extruder': {
            'current_e': round(state.current_e, 5),
            'last_e': round(state.last_e, 5),
        },
        'modes': {
            'relative_e': state.relative_e_mode,
            'relative_xyz': state.relative_xyz_mode,
        },
        'state': {
            'retracted': state.is_retracted,
            'printing': state.is_printing,
            'awaiting_unretract': state.awaiting_unretract,
        },
        'layer': state.current_layer,
        'type': state.current_type,
        'feedrate': state.current_feedrate,
    }


def geometry_from_event(event, state) -> Dict[str, Any]:
    """
    Erzeugt einen Geometry-Eintrag aus Event + State.

    Args:
        event: GCodeEvent
        state: GCodeState

    Returns:
        Dict mit Geometriedaten
    """
    geom = {}
    if event.has_xy:
        geom['from'] = (round(state.last_x, 4), round(state.last_y, 4))
        geom['to'] = (round(state.current_x, 4), round(state.current_y, 4))
        geom['distance_mm'] = round(state.distance_to_last(), 4)
    if event.has_e:
        geom['e_delta'] = round(state.get_e_delta(), 5)
    return geom


# =============================================================================
# MAIN (TEST)
# =============================================================================

def main():
    """Testet das Logging-System."""
    log = get_logger('logging_test')
    log.info('test_event',
             line_number=42,
             command='G1 X10 Y20 E0.5',
             decision='classified_as_extrusion',
             reason='e_delta_positive_with_xy',
             geometry={'distance_mm': 10.0, 'e_delta': 0.5},
             )
    print(f"Log geschrieben: {log.get_log_path()}")
    print(f"Events: {log.event_count}")
    close_all()


if __name__ == '__main__':
    main()