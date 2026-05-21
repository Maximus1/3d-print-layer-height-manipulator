#!/usr/bin/env python3
"""
G-Code Post-Processor: Non-Outer Layer Combiner (TRULY FINAL - Minimal Fix)
=============================================================================

EINZIGE ÄNDERUNG ZU ORIGINAL: Zeile 149 repariert.

ORIGINAL (FEHLERHAFT):
    state.e_abs_prev = params['E'] # Überschreibt mit ORIGINALwert nach jedem Layer!

KORRIGIERT:
    state.e_abs_prev = new_e_abs   # Behält SKALIERTEM Wert für nächste Skalierung bei!
"""

import sys
import re
import os

COMBINE_FACTOR = 2
GUI_COMBINE_FACTOR = None

PROTECTED_TYPES = ['outer wall', 'external perimeter', 'outer perimeter', 'overhang wall', 'brim', 'support']

def parse_params(line):
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

class State:
    def __init__(self):
        self.rel_e = False
        self.layer_count = 0
        self.current_type_protected = False
        self.e_abs_prev = 0.0

def process_gcode(lines):
    state = State()
    result = []

    eff_factor = GUI_COMBINE_FACTOR if GUI_COMBINE_FACTOR is not None else COMBINE_FACTOR
    result.append(f"; [CombineTool] Modus: Outer=0.1mm, Others={0.1 * eff_factor}mm (Factor={eff_factor})\n")

    for line in lines:
        s = line.strip().upper()

        if is_layer_change(line):
            state.layer_count += 1
            result.append(line)
            continue

        if s.startswith('M82'):
            state.rel_e = False
        if s.startswith('M83'):
            state.rel_e = True

        if is_type_comment(line):
            state.current_type_protected = is_protected_type(line)
            result.append(line)
            continue

        if state.current_type_protected:
            result.append(line)
            params = parse_params(s)
            if not state.rel_e and 'E' in params:
                state.e_abs_prev = params['E']
            continue

        if not state.current_type_protected:
            is_print_layer = state.layer_count % eff_factor == 0

            if s.startswith(('G0', 'G1', 'G2', 'G3')):
                params = parse_params(s)
                has_e = 'E' in params
                has_xy = any(k in params for k in 'XYIJR')

                # In Zwischenlayern: Pfade entfernen (Druck- und Travelmoves)
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
                        delta = params['E'] - state.e_abs_prev
                        new_e_abs = state.e_abs_prev + (delta * eff_factor)
                        line = replace_param(line, 'E', new_e_abs)
                        # ========== KRITISCHE REPARATUR Zeile 149 ==========
                        # VORHER: state.e_abs_prev = params['E'] # FALSCH! Originalwert!
                        # JETZT: e_abs_prev mit SKALIERTEM Wert aktualisieren
                        state.e_abs_prev = new_e_abs
                        # =======================
                    result.append(line)
                else:
                    if 'E' in params and not state.rel_e:
                        state.e_abs_prev = params['E']
                    result.append(line)
            else:
                result.append(line)

    return result

def main():
    if len(sys.argv) < 2:
        print("Verwendung: python combine_truly_final.py <datei.gcode>")
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
