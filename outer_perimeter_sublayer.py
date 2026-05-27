#!/usr/bin/env python3
"""
OrcaSlicer Post-Processing Script: Outer Perimeter Sub-Layer Printing
======================================================================
Druckt den äusseren Perimeter in dünneren Sub-Schichten (TARGET_HEIGHT).

WICHTIGES PRINZIP:
  Ein äusserer Perimeter ist eine geschlossene Schleife - nach Sub-Schicht 1
  ist die Düse bereits wieder am Startpunkt. Zwischen Sub-Schichten wird
  KEINE XY-Fahrt gemacht, nur ein Z-Wechsel. Dadurch wird das Druckobjekt
  nicht beschädigt.

  Bei mehreren Inseln pro Layer (mehrere geschlossene Schleifen in einer
  TYPE:Outer wall Sektion) wird fuer den Uebergang zwischen Sub-Schichten
  die Duese auf sichere Z-Hoehe gehoben bevor XY-Fahrten stattfinden.

Einrichtung in OrcaSlicer:
  Drucker-Einstellungen -> Post-Processing Scripts:
    python3 /pfad/zum/skript/outer_perimeter_sublayer.py;
"""

# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long
import sys
import re
import os

# =============================================================================
# KONFIGURATION
# =============================================================================

# Ziel-Schichthoehe fuer den aeusseren Perimeter (in mm)
TARGET_HEIGHT = 0.1

# Sicherheits-Z-Hop Hoehe fuer Travel Moves zwischen Konturen (in mm)
# FIX: Konstanter Wert von 0.8mm anstatt dynamisch (Layer-Hoehe + Hop)
# Dies verhindert inkonsistente Sicherheits-Lift-Hoehen zwischen Sub-Schichten
SAFETY_HOP_HEIGHT = 0.8

# Wird von der GUI gesetzt, um den Standardwert zu ueberschreiben
GUI_TARGET_HEIGHT = None


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def parse_params(line):
    # Entferne alles nach einem Semikolon und alles innerhalb von Klammern
    code_part = line.split(';')[0]
    code_part = re.sub(r'\(.*?\)', '', code_part)

    result = {}
    for param in 'XYZEFIJR':
        m = re.search(rf'(?<![A-Za-z]){param}([-+]?\d*\.?\d+)', code_part, re.I)
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


def remove_z_from_line(line):
    s = line.strip()
    if not re.match(r'^[Gg][0123](?!\d)', s):
        return line
    params = parse_params(s)
    # Entferne die Zeile ganz, wenn sie nur Z enthielt oder leer ist
    if ('Z' in params and not any(p in params for p in 'XYEFIJR')) or not params:
        return ""
    return re.sub(r'\s*(?<![A-Za-z])[Zz][-+]?\d*\.?\d+', '', line).rstrip() + '\n'


def remove_z_from_lines(lines):
    return [l for l in (remove_z_from_line(line) for line in lines) if l]


def is_outer_wall_comment(line):
    # Erlaube flexible Leerzeichen: ; TYPE : Outer wall
    match = re.match(r'^;\s*type\s*:\s*(.*)', line.strip(), re.I)
    if not match:
        return False
    t = match.group(1).lower()
    return any(k in t for k in ['outer wall', 'external perimeter', 'outer perimeter', 'overhang wall'])


def is_type_comment(line):
    # Erlaube flexible Leerzeichen fuer alle Typ-Kommentare
    return re.match(r'^;\s*type\s*:', line.strip(), re.I) is not None


def is_layer_change(line):
    s = line.strip().lower()
    return s.startswith(';layer_change') or s.startswith(';layer change')


def note(text):
    return f'; [SubLayer] {text}\n'


# =============================================================================
# SEGMENTIERUNG: Outer-Wall Zeilen in Konturen aufteilen
# =============================================================================

def split_into_contours(lines, is_relative_e, start_e):
    """
    Teilt Outer-Wall Zeilen in einzelne Konturen auf.

    Rueckgabe:
        Liste von (travel_lines, extrusion_lines)

    travel_lines:
        Bewegungen ZUR Kontur
        (Travels, Retracts, Z-Hops, Positionierung)

    extrusion_lines:
        Alle zur Kontur gehoerenden Druckbewegungen inklusive:
        - Wipes (E-Minus MIT XY)
        - Coasting / Pressure Cleanup
        - Retracts innerhalb der Kontur (Seam Hiding, Micro-Travels)
        - E0-Moves und Mikrosegmente innerhalb der Schleife
    """

    contours = []

    current_travel = []
    current_extrusion = []

    in_extrusion = False
    # NEU: Flag fuer Wipe-Erkennung (Bugfix #3):
    # Nach einem Retract (G10/G1-E-Minus ohne XY) sind XY ohne E
    # als Wipe-Bewegungen zu werten, NICHT als Travel.
    # Wipe endet mit Unretract (G11/G1-E-Plus ohne XY).
    awaiting_unretract = False
    last_e = start_e

    # Floating-Point-Toleranz
    EPS = 1e-6

    for line in lines:

        s = line.strip().upper()

        # ------------------------------------------------------------
        # Kommentare / Leerzeilen erhalten
        # ------------------------------------------------------------

        if not s or s.startswith(';'):

            if in_extrusion:
                current_extrusion.append(line)
            else:
                current_travel.append(line)

            continue

        params = parse_params(s)

        # ------------------------------------------------------------
        # Robuste G-Code Erkennung
        # ------------------------------------------------------------

        # Alle Bewegungen
        is_move = bool(re.match(r'^G[0123](?!\d)', s))

        # Nur echte Druckbewegungen (G0 darf NIEMALS Drucken sein)
        is_print_move = bool(re.match(r'^G[123](?!\d)', s))

        # Firmware Retract / Unretract
        is_g10 = bool(re.match(r'^G10(?!\d)', s))
        is_g11 = bool(re.match(r'^G11(?!\d)', s))

        has_e = 'E' in params
        e_val = params.get('E', 0.0)

        # XY / Arc Bewegung?
        # WICHTIG: I, J, R sind NUR für G2/G3 (Arcs) gültig, NIEMALS für G0/G1!
        is_g0g1 = bool(re.match(r'^G[01](?!\d)', s))
        has_xy_movement = (
            any(k in params for k in ('X', 'Y', 'I', 'J', 'R'))
            if (is_move and not is_g0g1)
            else ('X' in params or 'Y' in params) if is_move
            else False
        )

        # ------------------------------------------------------------
        # G92 E behandeln (Extruder-Reset)
        # ------------------------------------------------------------

        if s.startswith('G92') and has_e:
            last_e = e_val

            if in_extrusion:
                current_extrusion.append(line)
            else:
                current_travel.append(line)

            continue

        # ------------------------------------------------------------
        # E-Delta berechnen
        # ------------------------------------------------------------

        if has_e:
            e_delta = (
                e_val
                if is_relative_e
                else (e_val - last_e)
            )
        else:
            e_delta = 0.0

        # ------------------------------------------------------------
        # Klassifizierung der Moves
        # ------------------------------------------------------------

        # Echter Druckmove: Extrusion im Plusbereich mit XY-Weg
        is_printing = (
            is_print_move and
            has_xy_movement and
            has_e and
            e_delta > EPS
        )

        # Echter Retract: G10 oder G1 E-Minus OHNE XY-Weg
        if is_g10:
            is_retract = True
        elif has_e:
            is_retract = (
                e_delta < -EPS and
                not has_xy_movement
            )
        else:
            is_retract = False

        # Echter Unretract: G11 oder G1 E-Plus OHNE XY-Weg
        if is_g11:
            is_unretract = True
        elif has_e:
            is_unretract = (
                e_delta > EPS and
                not has_xy_movement
            )
        else:
            is_unretract = False

        # Echter Travel: Bewegung mit XY aber OHNE E-Parameter
        is_travel = (
            is_move and
            has_xy_movement and
            not has_e
        )

        # ------------------------------------------------------------
        # WIPE-ERKENNUNG (Bugfix #3):
        # awaiting_unretract signalisiert, dass ein Retract stattfand
        # und nachfolgende XY-ohne-E als Wipe zu werten sind.
        # ------------------------------------------------------------
        if is_retract:
            awaiting_unretract = True
        if is_unretract:
            awaiting_unretract = False

        # ------------------------------------------------------------
        # Zustandsmaschine
        # ------------------------------------------------------------

        if is_printing:

            if not in_extrusion:
                in_extrusion = True

            current_extrusion.append(line)

        elif in_extrusion:

            if is_retract:

                # BUGFIX #6: G10/G1-E-Minus beendet die Kontur
                # Bisher blieb G10 in current_extrusion, was is_travel
                # als einzigen Konturtrenner erzwang.
                # Jetzt beendet G10 die Kontur sauber – G1-ohne-E (Coasting)
                # kann in extrusion_lines bleiben.
                if current_extrusion:
                    contours.append((
                        list(current_travel),
                        list(current_extrusion)
                    ))
                current_travel = [line]
                current_extrusion = []
                in_extrusion = False

            elif is_travel:

                # BUGFIX #6: G1 XY ohne E bleibt immer in extrusion_lines
                # (Coasting, Wipe, F-Change). Nur G10/G1-E-Minus (Retract)
                # beendet die Kontur. awaiting_unretract wird dadurch obsolet.
                current_extrusion.append(line)

            else:

                # Wipes / Coasting / E0-Segmente /
                # Z-Hops mit konstantem E /
                # F-Änderungen bleiben Teil der Kontur
                current_extrusion.append(line)

        else:

            # Alles ausserhalb aktiver Extrusion
            # sammelt sich fuer die naechste Kontur
            current_travel.append(line)

        # ------------------------------------------------------------
        # last_e erst AM ENDE aktualisieren
        # ------------------------------------------------------------

        if has_e:
            last_e = e_val

    # ------------------------------------------------------------
    # Rest flushen
    # ------------------------------------------------------------

    if current_extrusion:

        contours.append((
            list(current_travel),
            list(current_extrusion)
        ))

    elif current_travel and contours:

        travel, extrusion = contours[-1]

        contours[-1] = (
            travel + current_travel,
            extrusion
        )

    return contours


# =============================================================================
# E-WERT SKALIERUNG
# =============================================================================

def scale_extrusion_lines(lines, e_factor, is_relative_e, e_state, actual_sh=None, is_first=True, is_last=True):
    """
    Skaliert E-Werte proportional zur Sub-Schichtdicke.
    Nur fuer Extrusion-Lines (mit E-Bewegungen).
    e_state: dict mit Schluesseln 'e' (neuer abs. E) und 'e_orig' (original abs. E)
    """
    # Falls keine Breitenreduzierung stattfindet (z.B. nur 1 Sublayer)
    w_factor = 0.66667 if e_factor < 0.99 else 1.0

    result = []
    for line in lines:
        # Skaliert WIDTH/HEIGHT Metadaten statt sie zu loeschen, um segmentweise Infos zu erhalten
        if actual_sh and is_first:
            def repl_meta(m):
                tag, val = m.group(1).upper(), float(m.group(2))
                return f';{tag}:{val * w_factor if tag == "WIDTH" else actual_sh:.4f}'
            line = re.sub(r';\s*(WIDTH|HEIGHT)\s*[:=]\s*([\d.]+)', repl_meta, line, flags=re.I)
        else:
            line = re.sub(r';\s*(WIDTH|HEIGHT)\s*[:=]\s*([\d.]+)', '', line, flags=re.I)

        s = line.strip().upper()
        if not s or s == ';':
            continue

        # G10/G11 (Firmware Retracts) immer beibehalten - sie gehoren zur Kontur
        if s.startswith('G10') or s.startswith('G11'):
            result.append(line)
            continue

        if s.startswith(('G0', 'G1', 'G2', 'G3')):
            params = parse_params(s)
            if 'E' in params:
                # ------------------------------------------------------------
                # Echte Extrusionserkennung
                # ------------------------------------------------------------

                EPS = 1e-6

                # WICHTIG: I, J, R sind NUR für G2/G3 (Arcs) gültig, NIEMALS für G0/G1!
                is_g0g1_s = s.startswith('G0') or s.startswith('G1')
                has_xy_movement = (
                    any(k in params for k in ('X', 'Y', 'I', 'J', 'R'))
                    if not is_g0g1_s
                    else ('X' in params or 'Y' in params)
                )

                if is_relative_e:

                    e_delta = params['E']

                else:

                    e_delta = params['E'] - e_state['e_orig']

                # Nur positive Extrusion MIT XY-Bewegung
                is_real_extrusion = (
                    has_xy_movement and
                    e_delta > EPS
                )

                # ------------------------------------------------------------
                # Relative Extrusion (M83)
                # ------------------------------------------------------------

                if is_relative_e:

                    val = params['E']

                    # Keine echte Extrusion:
                    # Retracts / Wipes / Coasting / E0 unverändert lassen
                    if not is_real_extrusion:

                        result.append(line)

                        e_state['e'] += val

                        continue

                    # Nur echte Druckextrusion skalieren
                    new_e_val = round(val * e_factor, 5)

                    line = replace_param(line, 'E', new_e_val)

                    e_state['e'] += new_e_val

                # ------------------------------------------------------------
                # Absolute Extrusion (M82)
                # ------------------------------------------------------------

                else:

                    src_delta = e_delta

                    # Originalwert immer zuerst merken
                    e_state['e_orig'] = params['E']

                    # Keine echte Extrusion:
                    # originalen E-Wert beibehalten
                    if not is_real_extrusion:

                        e_state['e'] += src_delta

                        result.append(line)

                        continue

                    # Nur positive Druckextrusion skalieren
                    scaled_delta = round(src_delta * e_factor, 5)

                    e_state['e'] += scaled_delta

                    line = replace_param(line, 'E', e_state['e'])
        result.append(line)
    return result


def process_travel_lines(travel_lines, is_relative_e, e_state):
    """
    Verarbeitet Travel-Lines OHNE E-Skalierung.
    Aktualisiert den E-State korrekt fuer Retracts/Unretracts.

    BUGFIX #3: Retracts/Unretracts in travel_lines sollten durch die
    Wipe-Erkennung in split_into_contours gar nicht mehr vorkommen.
    Sollten dennoch G1-E-Befehle hier landen, wird der E-State
    mitgefuehrt aber E-Parameter aus den Zeilen entfernt (damit
    waehrend XY-Travels nicht extrudiert wird).
    """
    result = []
    for line in travel_lines:
        s = line.strip().upper()
        if not s:
            continue

        # G10/G11 immer beibehalten
        if s.startswith('G10') or s.startswith('G11'):
            result.append(line)
            continue

        if s.startswith(('G0', 'G1', 'G2', 'G3')):
            params = parse_params(s)
            if 'E' in params:
                if is_relative_e:
                    e_state['e'] += params['E']
                else:
                    # Bei absolutem E: wir uebernehmen den Wert direkt
                    e_state['e_orig'] = params['E']
                    # e_state['e'] wird auf den gleichen Wert gesetzt,
                    # da der Drucker physikalisch dorthin faehrt
                    e_state['e'] = params['E']
                # E-Parameter aus Travel-Zeilen entfernen, damit nicht
                # waehrend XY-Travels extrudiert wird.
                # (Retracts/Unretracts werden durch die Wipe-Erkennung
                # in split_into_contours korrekt behandelt)
                line = re.sub(r'\s*(?<![A-Za-z])[Ee][-+]?\d*\.?\d+', '', line).rstrip() + '\n'
        result.append(line)
    return result


# =============================================================================
# SUB-LAYER ERZEUGUNG
# =============================================================================

def generate_sublayer_gcode(outer_lines, layer_h, prev_z, current_z,
                              current_e, is_relative_e, state_f):
    """
    Erzeugt Sub-Layer G-Code fuer den aeusseren Perimeter.

    KERNPRINZIP: Geschlossene Schleife -> nach Sub-Schicht 1 ist die Duese
    am Startpunkt -> NUR Z-Wechsel zwischen Sub-Schichten, KEIN XY-Travel.
    Das verhindert das Zerreissen des Druckobjekts.

    BUGFIX #4: E-State wird fuer jeden Sub-Layer neu initialisiert (auch bei M83).
    """
    # GUI-spezifische Hoehe bevorzugen, falls gesetzt (CLI nutzt weiterhin TARGET_HEIGHT)
    eff_target = GUI_TARGET_HEIGHT if GUI_TARGET_HEIGHT is not None else TARGET_HEIGHT

    num_sublayers = max(1, round(layer_h / eff_target))
    actual_sh = layer_h / num_sublayers
    # Verringerung der Extrusionsbreite um 1/3 zur Vermeidung von Ueberextrusion (nur bei Sub-Layern)
    w_factor = 0.66667 if num_sublayers > 1 else 1.0
    e_factor = (actual_sh / layer_h) * w_factor

    result = []
    result.append(note(
        f'Outer Perimeter: {num_sublayers} Sub-Schichten a {actual_sh:.4f}mm '
        f'(Layer {layer_h:.4f}mm, E*{e_factor:.4f})'
    ))

    # Metadaten fuer die Slicer-Vorschau (behebt "zu dicke" Linien)
    result.append(f';HEIGHT:{actual_sh:.4f}\n')

    # Originalbreite extrahieren, um die verringerte Breite fuer die Vorschau korrekt zu setzen
    orig_width = 0.35
    for l in outer_lines:
        m = re.search(r';\s*WIDTH\s*[:=]\s*([\d.]+)', l, re.I)
        if m:
            orig_width = float(m.group(1))
            break
    result.append(f';WIDTH:{orig_width * w_factor:.4f}\n')

    contours = split_into_contours(outer_lines, is_relative_e, current_e)
    result.append(note(f'Erkannte Konturen: {len(contours)}'))

    # E-Stand Initialisierung
    if is_relative_e:
        e_state = {'e': 0.0}  # Delta-Akkumulator fuer M83
    else:
        e_state = {'e': current_e, 'e_orig': current_e}
    start_e_val = current_e

    current_f = state_f
    for sub_idx in range(num_sublayers):
        is_first = sub_idx == 0
        is_last = sub_idx == num_sublayers - 1

        # BUGFIX #4: E-State fuer jeden Sub-Layer neu initialisieren (auch bei M83)
        if is_relative_e:
            e_state = {'e': 0.0}
        else:
            e_state['e_orig'] = start_e_val
            e_state['e'] = start_e_val

        sub_z = round(prev_z + actual_sh * (sub_idx + 1), 5)
        if is_last:
            sub_z = current_z
        result.append(note(f'Sub-Schicht {sub_idx + 1}/{num_sublayers} @ Z={sub_z:.5f}mm'))

        for c_idx, (travel_lines, extrusion_lines) in enumerate(contours):
            # Ueberspringe reine Cleanup-Konturen (Wipes/Retracts ohne Extrusion)
            # oder wenn es nur einen Sub-Layer gibt und es keine echten Travel-Moves sind
            if not extrusion_lines and not is_last and num_sublayers > 1:
                continue

            if is_first:
                # === BUGFIX #2: M83 statt M204 S1 fuer Insel-Wechsel ===
                # M83 stellt sicher, dass der relative E-Modus aktiv ist.
                # (vorher fälschlich M204 S1, was Beschleunigung setzt, nicht den Extrusionsmodus)
                if is_relative_e and c_idx > 0:
                    result.append('M83 ; Relative extrusion mode for island transition\n')

                # 1. XY-Anfahrt auf der Kontur
                # Sicherheits-Lift auf Original-Z (current_z), um Kollisionen
                # beim Insel-Wechsel zu vermeiden (nur bei tatsaechlichen Travel-Moves)
                has_real_travel = False
                for l in travel_lines:
                    su = l.strip().upper()
                    if su.startswith(('G0', 'G1', 'G2', 'G3')):
                        p = parse_params(su)
                        is_arc_t = su.startswith(('G2', 'G3'))
                        if (any(k in p for k in 'XYIJR') if is_arc_t else ('X' in p or 'Y' in p)):
                            has_real_travel = True
                            break

                if has_real_travel:
                    safe_z = current_z + SAFETY_HOP_HEIGHT
                    # Aktuelle Feedrate fuer den Sicherheitslift verwenden (nicht hardcodiert F3000)
                    # Der Lift erfolgt VOR den Travel-Moves, daher state_f als Basis
                    result.append(f'G1 Z{safe_z:.5f} F{state_f:.0f} ; Sicherheits-Lift auf Original-Z\n')

                # Travel-Lines verarbeiten (mit E-State-Tracking aber ohne Skalierung)
                processed_travel = process_travel_lines(
                    remove_z_from_lines(travel_lines),
                    is_relative_e, e_state
                )
                # Merke die aktuellste Feedrate aus den Travel-Moves
                for tl in processed_travel:
                    tp = parse_params(tl)
                    if 'F' in tp:
                        current_f = tp['F']

                # G11 (Unretract) aus Travels extrahieren - muss NACH Z-Absenkung erfolgen
                # BUGFIX B: Nur EIN G11 am Ende behalten (keine Duplikate)
                travels_without_g11 = []
                pending_g11 = []
                for tl in processed_travel:
                    if tl.strip().upper().startswith('G11'):
                        pending_g11.append(tl)
                    else:
                        travels_without_g11.append(tl)
                if len(pending_g11) > 1:
                    pending_g11 = [pending_g11[-1]]  # Nur letztes G11

                # Travels OHNE G11 ausgeben (G10 Retracts bleiben vor dem Travel)
                result.extend(travels_without_g11)

                # 2. Erst jetzt auf die exakte Z-Hoehe des Sub-Layers absenken
                # Feedrate in den Z-Move integrieren (spart eine Zeile)
                result.append(f'G1 Z{sub_z:.5f} F{current_f:.0f} ; Sub-Layer Z-Hoehe & Feedrate\n')

                # G11 erst NACH der Z-Absenkung, damit Unretract auf korrekter Hoehe erfolgt
                result.extend(pending_g11)

            else:
                # BUGFIX #5 revidiert: Sub-Schicht > 1
                # c_idx == 0: Duese ist am Startpunkt der ERSTEN Kontur
                #   -> Z-Wechsel + XY-Travel aus travel_lines beibehalten
                # c_idx > 0: Inselwechsel - XY-Travel aus travel_lines beibehalten
                if c_idx == 0:
                    # XY-Anfahrweg aus travel_lines extrahieren (erste Zeile mit X/Y vor G10)
                    approach_found = False
                    for l in travel_lines:
                        su = l.strip().upper()
                        if su.startswith(('G0', 'G1')):
                            p = parse_params(su)
                            if ('X' in p or 'Y' in p) and 'Z' not in p:
                                # Reine XY-Positionierung ohne Z - uebernehmen
                                result.append(f'{l.rstrip()}\n')
                                approach_found = True
                                break
                            elif ('X' in p or 'Y' in p):
                                # XY + Z - Z entfernen
                                line_no_z = re.sub(r'\s*Z[-+]?\d*\.?\d+', '', l).rstrip() + '\n'
                                result.append(line_no_z)
                                approach_found = True
                                break
                    if not approach_found:
                        # Fallback: nur Z-Wechsel
                        result.append(f'G0 Z{sub_z:.5f} F{current_f:.0f} ; Sub-Layer Z-Hoehe\n')
                    else:
                        # Z-Wechsel NACH XY-Positionierung
                        result.append(f'G0 Z{sub_z:.5f} F{current_f:.0f} ; Sub-Layer Z-Hoehe\n')
                else:
                    # Travel-Lines fuer Inselwechsel verarbeiten (wie is_first, aber ohne Sicherheitslift)
                    processed_travel = process_travel_lines(
                        remove_z_from_lines(travel_lines),
                        is_relative_e, e_state
                    )
                    # G11 aus Travels extrahieren - muss NACH Z-Absenkung erfolgen
                    # BUGFIX B: Nur EIN G11 am Ende behalten (keine Duplikate)
                    travels_without_g11 = []
                    pending_g11 = []
                    for tl in processed_travel:
                        if tl.strip().upper().startswith('G11'):
                            pending_g11.append(tl)
                        else:
                            travels_without_g11.append(tl)
                    if len(pending_g11) > 1:
                        pending_g11 = [pending_g11[-1]]  # Nur letztes G11
                    # M83 vor Inselwechsel
                    if is_relative_e:
                        result.append('M83 ; Relative extrusion mode for island transition\n')
                    # Travels OHNE G11 ausgeben (G1 XY, G10)
                    result.extend(travels_without_g11)
                    # Z auf Sub-Layer Hoehe (XY bereits positioniert)
                    result.append(f'G0 Z{sub_z:.5f} ; Sub-Layer Z-Hoehe nach Insel-Wechsel\n')
                    # G11 nach Z-Absenkung
                    result.extend(pending_g11)

            # 3. Wand drucken mit skaliertem E (immer)
            scaled = scale_extrusion_lines(
                remove_z_from_lines(extrusion_lines),
                e_factor, is_relative_e, e_state, actual_sh=actual_sh,
                is_first=is_first, is_last=is_last
            )
            result.extend(scaled)

    # Z am Ende auf original Layer-Hoehe zuruecksetzen
    if abs(round(prev_z + layer_h, 5) - current_z) < 0.001:
        result.append(f'G0 Z{current_z:.5f} ; Zurueck auf Layer-Hoehe\n')
        # Slicer-Vorschau wieder auf Originalhoehe setzen
        result.append(f';HEIGHT:{layer_h:.4f}\n')

    result.append(note('Ende Outer Perimeter Sub-Layer'))
    return result, e_state['e']


# =============================================================================
# ZUSTANDSVERFOLGUNG
# =============================================================================

class State:
    def __init__(self):
        self.x = self.y = self.z = self.prev_z = self.e = 0.0
        self.f = 3000.0
        self.layer_h = None
        self.global_lh = None
        self.rel_e = False
        self.rel_pos = False
        self.lh_explicit = False
        self.target_z = None
        self.prev_target_z = 0.0

    def update(self, line):
        s = line.strip()
        su = s.upper()

        if is_layer_change(line):
            self.lh_explicit = False
            return

        if su.startswith('M82'):
            self.rel_e = False
            return
        if su.startswith('M83'):
            self.rel_e = True
            return
        if su.startswith('G90'):
            self.rel_pos = False
            return
        if su.startswith('G91'):
            self.rel_pos = True
            return

        m = re.search(r';\s*(?:HEIGHT|layer_height)\s*[=:]\s*([\d.]+)', s, re.I)
        if m:
            new_lh = float(m.group(1))
            if not self.global_lh:
                self.global_lh = new_lh
            self.layer_h = new_lh
            self.lh_explicit = True
            return

        m = re.search(r';\s*Z\s*[=:]\s*([\d.]+)', s, re.I)
        if m:
            nz = float(m.group(1))
            if self.target_z is not None and abs(nz - self.target_z) > 1e-5:
                self.prev_target_z = self.target_z
            self.target_z = nz
            # Falls HEIGHT fehlt, berechne lh aus Z-Differenz
            if not self.lh_explicit and self.target_z > self.prev_target_z:
                self.layer_h = round(self.target_z - self.prev_target_z, 5)
            return

        if not re.match(r'^[Gg][01](?!\d)', su):
            return

        params = parse_params(s)
        if not self.rel_pos:
            if 'X' in params:
                self.x = params['X']
            if 'Y' in params:
                self.y = params['Y']
            if 'Z' in params:
                nz = params['Z']
                self.z = nz

        if 'F' in params:
            self.f = params['F']
        if 'E' in params:
            self.e = self.e + params['E'] if self.rel_e else params['E']

    def get_layer_h(self):
        # Falls HEIGHT Kommentar gefunden wurde, diesen nutzen
        if self.lh_explicit and self.layer_h:
            return self.layer_h
        # Fallback auf Standard, falls HEIGHT fehlt
        return 0.2


# =============================================================================
# HAUPTVERARBEITUNG
# =============================================================================

def process_gcode(lines):
    state = State()
    result = []
    in_outer = False
    outer_buffer = []

    def flush():
        nonlocal outer_buffer
        if not outer_buffer:
            return
        lh = state.get_layer_h()
        base_z = state.target_z if state.target_z is not None else state.z
        sub_lines, new_e = generate_sublayer_gcode(
            outer_buffer, lh, base_z - lh, base_z,
            state.e, state.rel_e, state.f
        )
        if state.rel_e:
            state.e += new_e
        else:
            state.e = new_e
        result.extend(sub_lines)
        outer_buffer = []

    for i, line in enumerate(lines):
        if is_outer_wall_comment(line):
            # BUGFIX #7: Idempotenz – bereits sublayerte Bloecke ueberspringen
            # Pruefe, ob die naechsten Zeilen einen ; [SubLayer] Marker enthalten
            already_sublayered = False
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].strip().startswith('; [SubLayer]'):
                    already_sublayered = True
                    break
            if already_sublayered:
                result.append(line)
                continue
            if in_outer:
                flush()
            in_outer = True
            outer_buffer = []
            result.append(line)
            continue

        if in_outer and (is_type_comment(line) or is_layer_change(line)):
            flush()
            in_outer = False
            state.update(line)
            result.append(line)
            continue

        if in_outer:
            outer_buffer.append(line)
            # Wir updaten den Status NICHT waehrend wir im Buffer sind,
            # da generate_sublayer_gcode den End-Status berechnet.
        else:
            state.update(line)
            result.append(line)

    if outer_buffer:
        flush()

    return result


# =============================================================================
# EINSTIEGSPUNKT
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print("Verwendung: python3 outer_perimeter_sublayer.py <datei.gcode>")
        print("\nEinrichtung in OrcaSlicer:")
        print("  Drucker-Einstellungen -> Post-Processing Scripts:")
        print("  python3 /pfad/zum/skript/outer_perimeter_sublayer.py;")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        print(f"Fehler: Datei nicht gefunden: {filepath}")
        sys.exit(1)

    print(f"[SubLayer] Verarbeite: {filepath}")
    print(f"[SubLayer] Ziel-Perimeter-Schichthoehe: {TARGET_HEIGHT}mm")
    print("[SubLayer] Bugfixes aktiv: M83 (statt M204 S1), Wipe-Erkennung, E-Reset, E-State in Travels")

    # Backup der Originaldatei erstellen
    backup_path = filepath + '.bak'
    try:
        import shutil
        shutil.copy2(filepath, backup_path)
        print(f"[SubLayer] Backup erstellt: {backup_path}")
    except Exception as e:
        print(f"[SubLayer] Warnung: Backup fehlgeschlagen: {e}")

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='latin-1') as f:
            lines = f.readlines()

    orig = len(lines)
    processed = process_gcode(lines)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(processed)

    print(f"[SubLayer] Zeilen: {orig} -> {len(processed)} (+{len(processed) - orig})")
    print("[SubLayer] Fertig!")


if __name__ == '__main__':
    main()