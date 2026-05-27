#!/usr/bin/env python3

# pylint: disable=missing-function-docstring, missing-module-docstring, missing-class-docstring, line-too-long

import tkinter as tk
from tkinter import filedialog, messagebox
import os
import re


def find_layer_positions(lines):
    """
    Findet alle Positionen von ;LAYER_CHANGE Markern in der G-Code Datei.
    
    Rueckgabe: Liste von (zeilen_index, layer_nummer) Tupeln.
    Layer 1 beginnt beim ersten ;LAYER_CHANGE.
    """
    positions = []
    for i, line in enumerate(lines):
        if re.match(r'^\s*;LAYER_CHANGE\s*$', line, re.I):
            positions.append((i, len(positions) + 1))
    return positions


def extract_layer_from_file(filepath, layer_number):
    """
    Extrahiert die G-Code Zeilen eines bestimmten Layers aus einer .gcode Datei.
    
    Args:
        filepath: Pfad zur .gcode Datei
        layer_number: Die gewünschte Layer-Nummer (1-indexed)
    
    Returns:
        Tuple (erfolgreich: bool, result: str/None, nachricht: str)
    """
    if not os.path.isfile(filepath):
        return False, None, f"Datei nicht gefunden: {filepath}"

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        return False, None, f"Fehler beim Lesen der Datei: {e}"

    layer_positions = find_layer_positions(lines)

    if layer_number < 1:
        return False, None, f"Layer-Nummer muss >= 1 sein (eingegeben: {layer_number})"

    if layer_number > len(layer_positions):
        max_layer = len(layer_positions)
        return False, None, f"Layer {layer_number} existiert nicht. Die Datei hat {max_layer} Layer (1-{max_layer})."

    # Start-Index des Layers (die ;LAYER_CHANGE Zeile selbst)
    start_idx = layer_positions[layer_number - 1][0]

    # End-Index: entweder naechster ;LAYER_CHANGE oder Ende der Datei
    if layer_number < len(layer_positions):
        end_idx = layer_positions[layer_number][0]
    else:
        end_idx = len(lines)

    # Zeilen extrahieren (alles von start_idx bis end_idx, exklusive end_idx)
    extracted_lines = lines[start_idx:end_idx]

    # Output-Dateiname: gleicher Name wie .gcode Datei, aber .txt
    base_name = os.path.splitext(os.path.basename(filepath))[0] + ".txt"
    output_dir = os.path.dirname(filepath)
    output_path = os.path.join(output_dir, base_name)

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(extracted_lines)
        return True, output_path, f"Layer {layer_number} erfolgreich extrahiert nach:\n{output_path}"
    except Exception as e:
        return False, None, f"Fehler beim Schreiben der Ausgabedatei: {e}"


class LayerExtractorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Layer Extractor")
        self.root.geometry("600x350")
        self.root.resizable(False, False)

        # Hauptframe mit Padding
        main_frame = tk.Frame(root, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Titel
        tk.Label(main_frame, text="G-Code Layer Extraktor", font=("Arial", 14, "bold")).pack(pady=(0, 20))

        # ---- Quelldatei ----
        src_frame = tk.Frame(main_frame)
        src_frame.pack(fill=tk.X, pady=5)

        tk.Label(src_frame, text="Quelldatei:", width=12, anchor=tk.W).pack(side=tk.LEFT)

        self.src_path_var = tk.StringVar()
        src_entry = tk.Entry(src_frame, textvariable=self.src_path_var, state="readonly", width=50)
        src_entry.pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)

        tk.Button(src_frame, text="Durchsuchen", command=self.browse_source).pack(side=tk.RIGHT)

        # ---- Zieldatei ----
        dst_frame = tk.Frame(main_frame)
        dst_frame.pack(fill=tk.X, pady=5)

        tk.Label(dst_frame, text="Zieldatei:", width=12, anchor=tk.W).pack(side=tk.LEFT)

        self.dst_path_var = tk.StringVar()
        dst_entry = tk.Entry(dst_frame, textvariable=self.dst_path_var, state="readonly", width=50)
        dst_entry.pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)

        tk.Button(dst_frame, text="Durchsuchen", command=self.browse_destination).pack(side=tk.RIGHT)

        # ---- Layer-Nummer ----
        layer_frame = tk.Frame(main_frame)
        layer_frame.pack(fill=tk.X, pady=(15, 10))

        tk.Label(layer_frame, text="Layer-Nr:", width=12, anchor=tk.W).pack(side=tk.LEFT)

        self.layer_var = tk.StringVar()
        layer_entry = tk.Entry(layer_frame, textvariable=self.layer_var, width=10)
        layer_entry.pack(side=tk.LEFT, padx=(5, 0))

        # Validation: nur Zahlen erlaubt
        vcmd = (root.register(self._validate_number), '%P')
        layer_entry.config(validate="key", validatecommand=vcmd)

        # Trace für automatische Button-Aktualisierung
        self.layer_var.trace_add("write", lambda *args: self._update_extract_button())

        # Info-Text
        tk.Label(layer_frame, text="(1 = erster Layer)", fg="gray").pack(side=tk.LEFT, padx=(10, 0))

        # ---- Extraktions-Button ----
        self.btn_extract = tk.Button(
            main_frame,
            text="Extrahieren",
            command=self.extract,
            bg="#2E7D32",
            fg="white",
            font=("Arial", 11, "bold"),
            state=tk.DISABLED,
            height=2,
            width=25
        )
        self.btn_extract.pack(pady=(15, 15))

        # ---- Status ----
        self.status_var = tk.StringVar(value="Bereit. Bitte Quelldatei und Zieldatei auswählen.")
        self.status_label = tk.Label(
            main_frame,
            textvariable=self.status_var,
            fg="gray",
            wraplength=550,
            justify=tk.LEFT,
            anchor=tk.W
        )
        self.status_label.pack(fill=tk.X, pady=(0, 5))

        # ---- Fortschritt / Detail-Status ----
        self.detail_var = tk.StringVar(value="")
        self.detail_label = tk.Label(
            main_frame,
            textvariable=self.detail_var,
            fg="gray",
            wraplength=550,
            justify=tk.LEFT,
            anchor=tk.W
        )
        self.detail_label.pack(fill=tk.X)

    def _validate_number(self, value):
        """Erlaubt nur leere Strings oder positive ganze Zahlen."""
        if value == "":
            return True
        try:
            v = int(value)
            return v >= 1
        except ValueError:
            return False

    def _update_extract_button(self):
        """Aktiviert/Deaktiviert den Extract-Button basierend auf den Eingaben."""
        src_ok = bool(self.src_path_var.get())
        dst_ok = bool(self.dst_path_var.get())
        layer_ok = False
        try:
            layer_val = int(self.layer_var.get())
            layer_ok = layer_val >= 1
        except (ValueError, TypeError):
            pass

        if src_ok and dst_ok and layer_ok:
            self.btn_extract.config(state=tk.NORMAL)
        else:
            self.btn_extract.config(state=tk.DISABLED)

    def browse_source(self):
        path = filedialog.askopenfilename(
            title="Quell-G-Code Datei auswählen",
            filetypes=[("G-Code", "*.gcode"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.src_path_var.set(path)
            self.status_var.set(f"Quelldatei: {os.path.basename(path)}")
            self.detail_var.set("")
            self._update_extract_button()

    def browse_destination(self):
        path = filedialog.askopenfilename(
            title="Ziel-G-Code Datei auswählen",
            filetypes=[("G-Code", "*.gcode"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.dst_path_var.set(path)
            self.detail_var.set("")
            self._update_extract_button()

    def _process_single(self, filepath, label, layer_number):
        """Extrahiert einen Layer aus einer Datei und gibt Status-Infos zurueck."""
        self.status_var.set(f"Verarbeite {label}: {os.path.basename(filepath)} ...")
        self.root.update_idletasks()

        success, output_path, msg = extract_layer_from_file(filepath, layer_number)

        if success:
            return f"✓ {label}: Layer {layer_number} → {os.path.basename(output_path)}"
        else:
            return f"✗ {label}: {msg}"

    def extract(self):
        """Fuehrt die Extraktion fuer beide Dateien durch."""
        # Eingaben holen
        src_path = self.src_path_var.get()
        dst_path = self.dst_path_var.get()

        try:
            layer_number = int(self.layer_var.get())
        except ValueError:
            messagebox.showerror("Fehler", "Bitte eine gültige Layer-Nummer eingeben.")
            return

        if layer_number < 1:
            messagebox.showerror("Fehler", "Layer-Nummer muss >= 1 sein.")
            return

        # Button deaktivieren waehrend der Verarbeitung
        self.btn_extract.config(state=tk.DISABLED, text="Verarbeite...")
        self.detail_var.set("")
        self.root.update_idletasks()

        # Quelldatei verarbeiten
        src_result = self._process_single(src_path, "Quelldatei", layer_number)

        # Status aktualisieren
        self.detail_var.set(src_result)
        self.root.update_idletasks()

        # Zieldatei verarbeiten
        dst_result = self._process_single(dst_path, "Zieldatei", layer_number)

        # Endstatus
        self.detail_var.set(f"{src_result}\n{dst_result}")

        # Hat alles geklappt?
        if src_result.startswith("✓") and dst_result.startswith("✓"):
            self.status_var.set("✅ Extraktion erfolgreich abgeschlossen!")
        else:
            self.status_var.set("⚠️ Extraktion teilweise fehlgeschlagen. Details siehe unten.")

        # Button wieder aktivieren
        self.btn_extract.config(state=tk.NORMAL, text="Extrahieren")


def main():
    window = tk.Tk()
    app = LayerExtractorGUI(window)
    window.mainloop()


if __name__ == "__main__":
    main()