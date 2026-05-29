#!/usr/bin/env python3
"""
Output Writer – Erzeugt GCode-Output aus verarbeiteten Events
==============================================================
Wandelt GCodeEvents wieder in GCode-Zeilen um.
Erzeugt neue .gcode-Dateien.

Regeln:
- Originaldatei wird NIEMALS überschrieben
- Output geht immer in eine neue Datei
- Formatierung bleibt originaltreu (Kommentare, Leerzeilen)
"""

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from gcode_parser import GCodeEvent
from logging_system import get_logger, close_all


class OutputWriter:
    """
    Schreibt verarbeitete GCode-Events in eine Ausgabedatei.
    - Originaltreue Formatierung
    - Kein Überschreiben von Originalen
    """

    def __init__(self):
        self.log = get_logger('output_writer')

    def write(self, events: List[GCodeEvent], output_path: str,
              original_newline: str = '\n',
              has_trailing_newline: bool = True) -> str:
        """
        Schreibt Events in eine GCode-Datei.

        Args:
            events: Liste der GCodeEvents (originals + transformierte)
            output_path: Pfad für die Ausgabedatei
            original_newline: Zeilenende der Originaldatei ('\n' oder '\r\n')
            has_trailing_newline: Ob die Originaldatei mit Newline endet

        Returns:
            Pfad der geschriebenen Datei
        """
        path = Path(output_path)

        self.log.info('write_start',
                     decision='writing',
                     reason=f'output={path.name}, events={len(events)}')

        lines = []
        passed_through = 0
        modified = 0

        for event in events:
            # Roh-Zeile (wenn unverändert)
            if event.raw is not None:
                raw_stripped = event.raw.rstrip('\n\r')
                lines.append(raw_stripped + original_newline)
                passed_through += 1
            else:
                lines.append(self._event_to_gcode(event))
                modified += 1

        with open(str(path), 'w', encoding='utf-8', newline='') as f:
            f.writelines(lines)

        # Trailing-newline Korrektur: Original ohne trailing NL?
        if not has_trailing_newline and lines:
            # Letztes Newline entfernen (das extra Byte)
            offset = len(original_newline)
            with open(str(path), 'rb') as f:
                data = f.read()
            if data[-offset:] == original_newline.encode('utf-8'):
                data = data[:-offset]
            with open(str(path), 'wb') as f:
                f.write(data)

        self.log.info('write_complete',
                     decision='completed',
                     reason=f'{len(lines)} lines written',
                     geometry={
                         'passed_through': passed_through,
                         'modified': modified,
                         'output_file': str(path),
                         'size_bytes': path.stat().st_size,
                     })

        return str(path)

    def _event_to_gcode(self, event: GCodeEvent) -> str:
        """Konvertiert ein Event zurück in eine GCode-Zeile."""
        return event.raw if hasattr(event, 'raw') and event.raw else ''

    def write_combined(self, original_events: List, modified_lines: dict,
                       output_path: str,
                       original_newline: str = '\n',
                       has_trailing_newline: bool = True) -> str:
        """
        Erzeugt einen Output aus originalen Events + modifizierten Zeilen.
        modified_lines: Dict {line_idx: neue_zeile}

        Args:
            original_events: Alle Original-Events
            modified_lines: Dict mit line_idx -> neuer GCode-String
            output_path: Ausgabepfad
            original_newline: Zeilenende der Originaldatei ('\n' oder '\r\n')
            has_trailing_newline: Ob die Originaldatei mit Newline endet

        Returns:
            Pfad der geschriebenen Datei
        """
        path = Path(output_path)

        self.log.info('write_combined_start',
                     decision='writing_combined',
                     reason=f'output={path.name}, modifications={len(modified_lines)}')

        lines = []
        modifications_applied = 0

        for event in original_events:
            if event.line_idx in modified_lines:
                mod = modified_lines[event.line_idx]
                if isinstance(mod, list):
                    # Mehrere Zeilen: Ersetzt Original durch Liste
                    for sub_line in mod:
                        sub_stripped = sub_line.rstrip('\n\r')
                        lines.append(sub_stripped + original_newline)
                        modifications_applied += 1
                else:
                    mod_line = mod.rstrip('\n\r')
                    lines.append(mod_line + original_newline)
                    modifications_applied += 1
            else:
                raw_stripped = event.raw.rstrip('\n\r')
                lines.append(raw_stripped + original_newline)

        with open(str(path), 'w', encoding='utf-8', newline='') as f:
            f.writelines(lines)

        # Trailing-newline Korrektur
        if not has_trailing_newline and lines:
            offset = len(original_newline)
            with open(str(path), 'rb') as f:
                data = f.read()
            if data[-offset:] == original_newline.encode('utf-8'):
                data = data[:-offset]
            with open(str(path), 'wb') as f:
                f.write(data)

        self.log.info('write_combined_complete',
                     decision='completed',
                     reason=f'{len(lines)} lines, {modifications_applied} modifications',
                     geometry={
                         'modifications': modifications_applied,
                         'output_file': str(path),
                     })

        return str(path)


# =============================================================================
# NAMENSKONVENTION FÜR OUTPUT-DATEIEN
# =============================================================================

def make_output_path(original_path: str, suffix: str = 'processed') -> str:
    """
    Erzeugt einen Output-Pfad nach Namenskonvention.

    original.gcode -> original_processed.gcode

    Args:
        original_path: Pfad zur Original-Datei
        suffix: Suffix für die Output-Datei

    Returns:
        Neuer Pfad
    """
    p = Path(original_path)
    return str(p.parent / f'{suffix}_{p.name}')


def main():
    """Testet den Output Writer."""
    from gcode_parser import GCodeParser

    parser = GCodeParser()
    events = parser.parse_file('fixtures/minimal_test.gcode')

    writer = OutputWriter()
    output_path = make_output_path('fixtures/minimal_test.gcode', 'test')
    result = writer.write(events, output_path)
    print(f"Geschrieben: {result}")
    close_all()


if __name__ == '__main__':
    main()