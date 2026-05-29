# MCP-Server-Zuordnung

Dokumentation der verfügbaren MCP-Server und ihrer Nutzung im Projekt.

## 1. Filesystem MCP
- **Befehl**: `node ...filesystem... C:\Users\Marcus\outer perimeter F:\SVS2026 C:\Users\Marcus\io_webseite`
- **Nutzung**: Dateioperationen (lesen, schreiben, kopieren, Verzeichnisstruktur)
- **Alternativ zu**: built-in `read_file`/`write_to_file` für Dateien außerhalb des Workspace

## 2. Structured Logging MCP (structured-logging-mcp)
- **Nutzung**: Alle DEBUG-Logs:
  - `DEBUG_WIPE`
  - `DEBUG_RETRACT`
  - `DEBUG_ARC`
  - `DEBUG_CONTOUR`
  - `DEBUG_GEOMETRY`
  - `DEBUG_STATE`
- **Vorteil**: Strukturierte JSON-Events mit Timestamp, line_idx, Positionen
- **Filterbar**: Nach Typ, Zeit, Severity, line_idx-Bereich

## 3. Diff MCP (diff-mcp)
- **Nutzung**: 
  - `first_divergence`: WO entstand die erste Divergenz? (zentrale Debug-Regel)
  - `gcode_diff`: Geometrischer Vergleich Original vs. Output
  - `gcode_grep`: Gezielte Suche nach GCode-Befehlen
  - `context_window`: Kontext um eine Problemstelle

## 4. Test Runner MCP (test-runner-mcp)
- **Nutzung**: 
  - `register_test`: Tests mit expected_hash/expected_output
  - `run_test` / `run_all`: Regressionstests ausführen
  - `compare_snapshots`: Vorher/Nachher-Vergleich
  - `add_bug_regression`: Jeder gefundene Bug → permanenter Test

## 5. Search Index MCP (search-index-mcp)
- **Nutzung**:
  - `build_index`: Codebase indizieren
  - `find_symbol`: Funktions-/Klassensuche
  - `cross_reference`: Wo wird was verwendet?
  - `call_hierarchy`: Aufrufketten
  - `regex_search`: Codebase-Durchsuchung

## 6. AST Analysis MCP (ast-analysis-mcp)
- **Nutzung**:
  - `find_dead_code`: Unbenutzte Funktionen/Imports
  - `complexity_metrics`: Zyklomatische Komplexität
  - `trace_control_flow`: Kontrollflussanalyse
  - `find_duplicate_logic`: Duplikaterkennung

## 7. SQLite MCP (sqlite-mcp)
- **Nutzung**: Persistente Speicherung von:
  - Analyseergebnissen
  - Benchmark-Daten
  - Test-Historie
  - Geometrie-Anomalien

## 8. Schema MCP (schema-mcp)
- **Nutzung**: Validierung von Log-Events, Geometriedaten, Konfigurationen

## 9. Viz MCP (viz-mcp)
- **Nutzung**:
  - `plot_xy_path`: XY-Pfad-Visualisierung
  - `plot_travel_vs_extrusion`: Travel/Extrusion farbcodiert
  - `plot_layer_contours`: Layer-Konturen
  - `plot_distance_histogram`: Distanz-Histogramm

## 10. Monty MCP (monty-mcp)
- **Nutzung**: Sicheres Ausführen von Python-Code (Sandbox)
- Für: Integration-Tests, Regression-Tests

## 11. Sequential Thinking MCP
- **Nutzung**: Strukturierte Problemanalyse bei komplexen Geometriefehlern

## 12. PackRat MCP
- **Nutzung**: Codebook-Kompression für reduzierte Token-Nutzung

## 13. Context7 MCP
- **Nutzung**: Dokumentation von Bibliotheken (numpy, matplotlib, etc.)

## 14. 21st.dev Magic MCP
- **Nutzung**: (derzeit nicht relevant - UI-Komponenten)
