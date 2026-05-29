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
    import combine_non_outer_layers as script
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    import combine_non_outer_layers as script

def interpolate_arc(start, end, params, is_cw):
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
        num = max(3, int(abs(e_ang - s_ang) * r / 0.5))
        angles = np.linspace(s_ang, e_ang, num + 1)
        return [[cx + r * np.cos(a), cy + r * np.sin(a), end[2]] for a in angles]
    except (ValueError, TypeError, IndexError, ArithmeticError):
        return [start, end]

def gcode_to_polydata(lines):
    points, segments, point_widths = [], [], []
    curr = [0.0, 0.0, 0.0]
    curr_w = 0.4
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
        if 'E' in params:
            if line_u.startswith(('G2', 'G3')):
                arc_pts = interpolate_arc(prev, curr, params, line_u.startswith('G2'))
                for i in range(len(arc_pts) - 1):
                    idx = len(points)
                    points.extend([arc_pts[i], arc_pts[i+1]])
                    point_widths.extend([curr_w / 2.0, curr_w / 2.0])
                    segments.append([2, idx, idx + 1])
            else:
                idx = len(points)
                points.extend([prev, list(curr)])
                point_widths.extend([curr_w / 2.0, curr_w / 2.0])
                segments.append([2, idx, idx + 1])
    if not points:
        return None
    pts = np.array(points)
    poly = pv.PolyData(pts, lines=np.array(segments).flatten())
    poly.point_data["Breite"] = np.array(point_widths)
    poly.point_data["Z-Höhe"] = pts[:, 2]
    return poly

class CombineGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Non-Outer Layer Combiner")
        self.root.geometry("500x350")
        tk.Label(root, text="Non-Outer Layer Combiner Tool", font=("Arial", 14, "bold")).pack(pady=15)

        frame_f = tk.Frame(root)
        frame_f.pack(pady=5)
        tk.Label(frame_f, text="Kombinations-Faktor (Layer):").pack(side=tk.LEFT)
        self.factor_entry = tk.Entry(frame_f, width=10)
        self.factor_entry.insert(0, str(script.COMBINE_FACTOR))
        self.factor_entry.pack(side=tk.LEFT, padx=5)

        self.file_label = tk.Label(root, text="Keine Datei ausgewählt", fg="blue", wraplength=400)
        self.file_label.pack(pady=10)
        tk.Button(root, text="G-Code Datei laden", command=self.load_file).pack(pady=5)

        self.btn_run = tk.Button(root, text="Verarbeiten & 3D-Vorschau", command=self.process_and_show,
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
            factor = int(self.factor_entry.get())
            script.GUI_COMBINE_FACTOR = factor
            with open(self.actual_file, 'r', encoding='utf-8', errors='ignore') as f:
                original_lines = f.readlines()

            processed_lines = script.process_gcode(original_lines)
            output_file = os.path.join(os.path.dirname(self.actual_file), "combined_" + os.path.basename(self.actual_file))
            with open(output_file, 'w', encoding='utf-8') as f:
                f.writelines(processed_lines)

            if not HAS_VISUALIZATION:
                messagebox.showinfo("Erfolg", f"Datei gespeichert unter:\n{os.path.basename(output_file)}")
                return

            messagebox.showinfo("Erfolg", f"Datei erfolgreich verarbeitet:\n{os.path.basename(output_file)}")
            poly_orig = gcode_to_polydata(original_lines)
            poly_proc = gcode_to_polydata(processed_lines)

            pl = pv.Plotter(shape=(1, 2), title="Vergleich (Links: Original | Rechts: Combined)")
            pl.subplot(0, 0)
            pl.add_text("Original (0.1mm)", font_size=10)
            if poly_orig:
                pl.add_mesh(poly_orig.tube(scalars="Breite", absolute=True), scalars="Z-Höhe", cmap="viridis")

            pl.subplot(0, 1)
            pl.add_text(f"Combined (Infill every {factor} layers)", font_size=10)
            if poly_proc:
                pl.add_mesh(poly_proc.tube(scalars="Breite", absolute=True), scalars="Z-Höhe", cmap="viridis")

            pl.link_views()
            pl.view_isometric()
            pl.show()

        except (ValueError, OSError, RuntimeError, TypeError, IndexError) as e:
            messagebox.showerror("Fehler", f"Verarbeitung fehlgeschlagen:\n{str(e)}")

if __name__ == "__main__":
    main_window = tk.Tk()
    gui = CombineGUI(main_window)
    main_window.mainloop()
