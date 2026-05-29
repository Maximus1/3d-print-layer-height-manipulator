#!/usr/bin/env python3

# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long

import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import re
try:
    import pyvista as pv
    import numpy as np
    HAS_VISUALIZATION = True
except ImportError:
    HAS_VISUALIZATION = False

# Importiere das Logik-Skript
try:
    import outer_perimeter_sublayer as script
except ImportError:
    # Sicherstellen, dass das Skript im aktuellen Verzeichnis gefunden wird
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import outer_perimeter_sublayer as script

def interpolate_arc(start, end, params, is_cw):
    """Erzeugt Zwischenpunkte für G2/G3 Bögen zur originalgetreuen Darstellung."""
    try:
        cx = start[0] + params.get('I', 0)
        cy = start[1] + params.get('J', 0)
        r = np.hypot(start[0] - cx, start[1] - cy)
        s_ang = np.arctan2(start[1] - cy, start[0] - cx)
        e_ang = np.arctan2(end[1] - cy, end[0] - cx)

        if is_cw and e_ang > s_ang:
            e_ang -= 2 * np.pi
        if not is_cw and e_ang < s_ang:
            e_ang += 2 * np.pi

        # Anzahl Segmente basierend auf Bogenlänge (ca. alle 0.5mm ein Punkt)
        num = max(3, int(abs(e_ang - s_ang) * r / 0.5))
        angles = np.linspace(s_ang, e_ang, num + 1)
        return [[cx + r * np.cos(a), cy + r * np.sin(a), end[2]] for a in angles]
    except (ValueError, TypeError, IndexError, ArithmeticError):
        return [start, end]

def gcode_to_polydata(lines):
    """Konvertiert G-Code Zeilen in ein Pfad-Objekt fuer PyVista."""
    points = []
    segments = []
    point_widths = []
    curr = [0.0, 0.0, 0.0]
    curr_w = 0.4  # Standardbreite
    initialized = False

    for line in lines:
        m_w = re.search(r';\s*WIDTH\s*[:=]\s*([\d.]+)', line, re.I)
        if m_w:
            curr_w = float(m_w.group(1))

        line_u = line.strip().upper()
        if not line_u.startswith(('G0', 'G1', 'G2', 'G3')):
            continue

        params = script.parse_params(line)
        prev = list(curr)

        if 'X' in params:
            curr[0] = params['X']
        if 'Y' in params:
            curr[1] = params['Y']
        if 'Z' in params:
            curr[2] = params['Z']

        if not initialized:
            if any(k in params for k in "XYZ"):
                initialized = True
            continue

        # Nur Pfade mit Extrusion (E-Parameter) erfassen
        if 'E' in params:
            if line_u.startswith(('G2', 'G3')):
                arc_pts = interpolate_arc(prev, curr, params, line_u.startswith('G2'))
                for i in range(len(arc_pts) - 1):
                    idx = len(points)
                    points.append(arc_pts[i])
                    points.append(arc_pts[i+1])
                    point_widths.extend([curr_w / 2.0, curr_w / 2.0])
                    segments.append([2, idx, idx + 1])
            else:
                idx = len(points)
                points.append(prev)
                points.append(list(curr))
                point_widths.extend([curr_w / 2.0, curr_w / 2.0])
                segments.append([2, idx, idx + 1])

    if not points:
        return None

    pts = np.array(points)
    # Connectivity für diskrete Segmente: [2, p1, p2, 2, p3, p4, ...]
    connectivity = np.array(segments).flatten()
    poly = pv.PolyData(pts, lines=connectivity)
    poly.point_data["Breite"] = np.array(point_widths)
    poly.point_data["Z-Höhe"] = pts[:, 2]  # Z-Koordinate als Skalar für Einfärbung
    return poly

class SubLayerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sub-Layer Prozessor & Visualisierer")
        self.root.geometry("500x350")

        tk.Label(root, text="Outer Perimeter Sub-Layer Tool", font=("Arial", 14, "bold")).pack(pady=15)

        # Target Height Eingabe
        frame_h = tk.Frame(root)
        frame_h.pack(pady=5)
        tk.Label(frame_h, text="Ziel-Höhe (mm):").pack(side=tk.LEFT)
        self.height_entry = tk.Entry(frame_h, width=10)
        self.height_entry.insert(0, str(script.TARGET_HEIGHT))
        self.height_entry.pack(side=tk.LEFT, padx=5)

        # Dateiwahl
        self.file_label = tk.Label(root, text="Keine Datei ausgewählt", fg="blue", wraplength=400)
        self.file_label.pack(pady=10)
        tk.Button(root, text="G-Code Datei laden", command=self.load_file).pack(pady=5)

        # Run Button
        self.btn_run = tk.Button(root, text="Verarbeiten & 3D-Vorschau",
                                 command=self.process_and_show,
                                 bg="#2E7D32", fg="white", font=("Arial", 10, "bold"),
                                 state=tk.DISABLED, height=2, width=25)
        self.btn_run.pack(pady=20)

        self.actual_file = None

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("G-Code", "*.gcode"), ("All Files", "*.*")])
        if path:
            self.actual_file = path
            self.file_label.config(text=os.path.basename(path), fg="black")
            self.btn_run.config(state=tk.NORMAL)

    def process_and_show(self):
        try:
            # Parameter aus GUI übernehmen
            target_h = float(self.height_entry.get())
            script.GUI_TARGET_HEIGHT = target_h

            with open(self.actual_file, 'r', encoding='utf-8', errors='ignore') as f:
                original_lines = f.readlines()

            # Logik des Hauptskripts ausführen
            processed_lines = script.process_gcode(original_lines)

            # Verarbeiteten G-Code in eine neue Datei mit Präfix schreiben
            output_file = os.path.join(os.path.dirname(self.actual_file), "sublayered_" + os.path.basename(self.actual_file))
            with open(output_file, 'w', encoding='utf-8') as f:
                f.writelines(processed_lines)

            if not HAS_VISUALIZATION:
                messagebox.showinfo("Erfolg", f"Datei wurde unter neuem Namen gespeichert:\n{os.path.basename(output_file)}\n\nHinweis: 3D-Vorschau nicht verfügbar.")
                return

            messagebox.showinfo("Erfolg", f"Datei wurde erfolgreich verarbeitet und gespeichert unter:\n{os.path.basename(output_file)}")

            # Daten für Visualisierung aufbereiten
            poly_orig = gcode_to_polydata(original_lines)
            poly_proc = gcode_to_polydata(processed_lines)

            # PyVista Side-by-Side Plotter
            pl = pv.Plotter(shape=(1, 2), title="Synchronisierter Vergleich (Links: Original | Rechts: Bearbeitet)")

            pl.subplot(0, 0)
            pl.add_text("Original G-Code", font_size=10)
            if poly_orig:
                # Erzeuge echte 3D-Geometrie basierend auf der Breite
                mesh_orig = poly_orig.tube(scalars="Breite", absolute=True)
                pl.add_mesh(mesh_orig, scalars="Z-Höhe", cmap="viridis")

            pl.subplot(0, 1)
            pl.add_text(f"Sub-Layer G-Code (Target: {target_h}mm)", font_size=10)
            if poly_proc:
                mesh_proc = poly_proc.tube(scalars="Breite", absolute=True)
                pl.add_mesh(mesh_proc, scalars="Z-Höhe", cmap="viridis")

            pl.link_views()  # Synchronisiert Rotation und Zoom beider Ansichten
            pl.view_isometric()
            pl.show()

        except (ValueError, OSError, RuntimeError, TypeError, IndexError) as e:
            messagebox.showerror("Fehler", f"Verarbeitung fehlgeschlagen:\n{str(e)}")

if __name__ == "__main__":
    main_window = tk.Tk()
    gui = SubLayerGUI(main_window)
    main_window.mainloop()
