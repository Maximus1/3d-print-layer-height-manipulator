#!/usr/bin/env python3
"""
G-Code Post-Processor: Non-Outer Layer Combiner
==============================================
Dieses Skript geht davon aus, dass die Datei bereits in 0.1mm gesliced wurde.
Der aeussere Perimeter bleibt bei 0.1mm.
Andere Strukturen (Infill, Inner Walls) werden zusammengefasst (z.B. auf 0.2mm).
"""
# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long

import sys
import re
import os

# =============================================================================
# KONFIGURATION
# =============================================================================

# Faktor, wie viele Layer zusammengefasst werden sollen (2 = 0.2mm bei 0.1mm Basis)
COMBINE_FACTOR = 2

# Wird von der GUI gesetzt, um den Standardwert zu ueberschreiben
GUI_COMBINE_FACTOR = None

# Typen, die NICHT kombiniert werden sollen (immer 0.1mm bleiben)
PROTECTED_TYPES = ['outer wall', 'external perimeter', 'outer perimeter', 'overhang wall', 'brim', 'support']

# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def parse_params(line):
    # Entferne alles nach einem Semikolon und alles innerhalb von Klammern
    code_part = line.split(';')[0]
    code_part = re.sub(r'\(.*?\)', '', code_part)

    result = {}
    for param in 'XYZEFIJR':
        m = re.search(rf'(?<![A-Za-z0-9.]){param}([-+]?\d*\.?\d+)', code_part)
        if m:
            result[param] = float(m.group(1))
    return result

def replace_param(line, param, value):
    comment_pos = line.find(';')
    code = line[:comment_pos] if comment_pos >= 0 else line
    comment = line[comment_pos:] if comment_pos >= 0 else ""

    fmt = f'{param}{value:.5f}'.rstrip('0').rstrip('.')
    pattern = rf'(?<![A-Za-z0-9.]){param}[-+]?\d*\.?\d+'

    if re.search(pattern, code, re.I):
        return re.sub(pattern, fmt, code, flags=re.I) + comment
    return line

def is_protected_type(line):
    match = re.match(r'^;\s*type\s*:\s*(.*)', line.strip(), re.I)
    if not match:
        return False
    t = match.group(1).lower()
    return any(k in t for k in PROTECTED_TYPES)

def is_type_comment(line):
    return re.match(r'^;\s*type\s*:', line.strip(), re.I) is not None

def is_layer_change(line):
    s = line.strip().lower()
    return s.startswith(';layer_change') or s.startswith(';layer change')

# =============================================================================
# LOGIK
# =============================================================================

class State:
    def __init__(self):
        self.rel_e = False
        self.layer_count = 0
        self.current_type_protected = False
        self.e_abs_prev = 0.0

def process_gcode(lines):
    state = State()
    result = []

    # GUI-spezifischen Faktor bevorzugen
    eff_factor = GUI_COMBINE_FACTOR if GUI_COMBINE_FACTOR is not None else COMBINE_FACTOR
    result.append(f"; [CombineTool] Modus: Outer=0.1mm, Others={0.1 * eff_factor}mm\n")

    for line in lines:
        s = line.strip().upper()

        # Layer Wechsel erkennen
        if is_layer_change(line):
            state.layer_count += 1
            result.append(line)
            continue

        # Extrusions-Modus verfolgen
        if s.startswith('M82'):
            state.rel_e = False
        if s.startswith('M83'):
            state.rel_e = True

        # Wand-Typ erkennen
        if is_type_comment(line):
            state.current_type_protected = is_protected_type(line)
            result.append(line)
            continue

        # Falls geschuetzt oder im Kombinations-Intervall: Verarbeiten
        if state.current_type_protected:
            result.append(line)
            params = parse_params(s)
            if not state.rel_e and 'E' in params:
                state.e_abs_prev = params['E']
            continue

        # Logik fuer nicht-geschuetzte Layer (Infill etc.)
        if not state.current_type_protected:
            # Bestimme, ob dieser Layer gedruckt oder uebersprungen wird
            is_print_layer = state.layer_count % eff_factor == 0

            if s.startswith(('G0', 'G1', 'G2', 'G3')):
                params = parse_params(s)
                has_e = 'E' in params
                has_xy = any(k in params for k in 'XYIJR')

                # In Zwischenlayern: Pfade (Druck- und Travelmoves) komplett entfernen
                if not is_print_layer and (has_e or has_xy):
                    if has_e and not state.rel_e:
                        state.e_abs_prev = params['E']
                    continue

                if has_e and has_xy:
                    # Im Kombinations-Layer: E-Wert skalieren
                    if state.rel_e:
                        new_e = params['E'] * eff_factor
                        line = replace_param(line, 'E', new_e)
                    else:
                        # Absolutes E ist komplexer: Delta berechnen und skalieren
                        delta = params['E'] - state.e_abs_prev
                        new_e_abs = state.e_abs_prev + (delta * eff_factor)
                        line = replace_param(line, 'E', new_e_abs)
                        state.e_abs_prev = params['E'] # Wir tracken das Original weiter
                    result.append(line)
                else:
                    # Travel oder Retracts ohne XY
                    if 'E' in params and not state.rel_e:
                        state.e_abs_prev = params['E']
                    result.append(line)
            else:
                result.append(line)

    return result

def main():
    if len(sys.argv) < 2:
        print("Verwendung: python3 combine_non_outer_layers.py <datei.gcode>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        sys.exit(1)

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='latin-1') as f:
            lines = f.readlines()

    processed = process_gcode(lines)

    output_path = os.path.join(os.path.dirname(filepath), "combined_" + os.path.basename(filepath))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(processed)
    print(f"Datei gespeichert: {output_path}")

if __name__ == '__main__':
    main()
