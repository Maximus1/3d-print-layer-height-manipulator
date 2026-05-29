# PIPELINE_SPEC.md – GCode Sublayer Pipeline

## 1. ZWECK

Formale Spezifikation der vollständigen GCode-Verarbeitungspipeline.
Gültig ab Phase 13. Nur spezifizierte Änderungen sind erlaubt.

## 2. EINGABE / AUSGABE

### Eingabe
- Format: `.gcode` (ASCII, UTF-8 oder latin-1)
- Quelle: Slicer-Output (PrusaSlicer, SuperSlicer, OrcaSlicer, Cura, etc.)
- Pflicht: `input/` Verzeichnis, Original wird NIEMALS überschrieben

### Ausgabe
- Format: `.gcode`
- Pflicht: `output/` Verzeichnis
- Namenskonvention: `{original_name}_processed.gcode`
- Kein Überschreiben von Originalen

### Zwischenzustände
- `working/`: temporäre Dateien während der Verarbeitung
- `archive/`: historische Versionen
- `analysis/`: Analyse-Artefakte
- `logs/`: JSONL-Logs

## 3. MODULREIHENFOLGE (10 Schritte)

```
1.  parse_gcode()
2.  geometry_validator.validate()     ← BEFORE
3.  contour_extractor.extract()
4.  travel_classifier.classify()
5.  wipe_detector.detect()
6.  arc_handler.process()
7.  sublayer_processor.process()
8.  output_writer.write()
9.  geometry_validator.validate()     ← AFTER
10. debug_tools.compare(original, output)
```

Jeder Schritt muss:
- separat logbar
- separat validierbar
- separat deaktivierbar
- separat testbar sein

## 4. ERLAUBTE ZUSTANDSÄNDERUNGEN

### Erlaubt (nur durch sublayer_processor):
- Z-Werte erhöhen (Sublayer-Offset)
- E-Werte skalieren (Extrusion pro Sublayer)
- Feedrates anpassen (optional)

### Verboten:
- Konturen neu interpretieren
- Wipes erkennen/entfernen
- Travel klassifizieren
- Arcs reparieren
- Zustände korrigieren
- Neue GCode-Befehle einfügen (außer duplizierte Bewegungen)
- Kommentare ändern/löschen

## 5. ERLAUBTE GEOMETRIEÄNDERUNGEN

### Phase 13.5 (Identity): ✅ ABGESCHLOSSEN
- Keine Änderungen. Input == Output (byte-identisch).
- Status: Validiert (29.05.2026)

### Phase 13.6 (Z-Duplication): ✅ ABGESCHLOSSEN
- Z-Wert einer Bewegung erhöhen und Bewegung duplizieren
- Beispiel: `G1 X10 Y10 Z0.2 E0.4` → `G1 X10 Y10 Z0.2 E0.4` + `G1 X10 Y10 Z0.25`
- Keine E-Änderung im duplizierten Move
- Implementiert in: `z_duplication_processor.py`
- Integration: `pipeline.py` (Schritt 6.5)
- Tests: `tests/test_z_duplication.py` (14 Tests)
- Integrationstest: `test_z_duplication_integration.py`
- Status: Validiert (29.05.2026)

### Phase 13.7 (Extrusion Scaling):
- E-Werte mathematisch skalieren (M82/M83 korrekt)
- Keine Änderung an X/Y/Z
- Keine Änderung an G2/G3 I/J

### Phase 13.8 (Sublayer-Insertion):
- 1 zusätzliche Zwischenlage (keine beliebige Anzahl)
- Extrusion skaliert
- Z-Offset hinzugefügt

## 6. ABBRUCHBEDINGUNGEN

Die Pipeline MUSS abbrechen bei:
- Unbekannten GCode-Befehlen
- Inkonsistentem E-Modus (M82 ↔ M83 ohne Warnung)
- Arc-Fehlern (G2/G3 ohne I/J)
- Geometriesprüngen > 50mm mit E > 0 (während Extrusion)
- Extrusion während Retract
- Validierungsfehlern nach Verarbeitung

Abbruch ist KEIN Fehler. Abbruch ist KORREKTES Verhalten.

## 7. LOGGINGPUNKTE

### Pipeline-Logs (logs/pipeline.jsonl):
| Event-Typ | Auslöser | Pflichtfelder |
|-----------|----------|---------------|
| stage_start | Schritt beginnt | stage_name, timestamp |
| stage_complete | Schritt endet | stage_name, duration_ms, status |
| validation_failed | Validierungsfehler | line_idx, severity, description |
| divergence_found | Divergenz erkannt | line_idx, type, delta |
| abort | Pipeline bricht ab | reason, last_stage |

### Modul-Logs (logs/<modul>.jsonl):
Jedes Modul loggt eigene Event-Typen (siehe logging_system.py).

## 8. REGRESSIONEN

Jeder neue Fehlerfall erzeugt:
- `fixtures/production/<name>.gcode` – minimale reproduzierbare Fixture
- `tests/regression_<name>.py` – automatischer Regressionstest
- `analysis/ISSUE_XXXX/` – vollständiges Issue-Artefakt (report, diff, state_dump, geometry)

## 9. VALIDIERUNGSMATRIX

| Prüfung | BEFORE | AFTER | Methode |
|---------|--------|-------|---------|
| Extrusion während Retract | ✅ | ✅ | geometry_validator |
| Travel mit E > 0 | ✅ | ✅ | geometry_validator |
| G2/G3 ohne I/J | ✅ | ✅ | geometry_validator |
| Layer-Konsistenz | ✅ | ✅ | geometry_validator |
| Kontur-Struktur | ✅ | ✅ | contour_extractor |
| Arc-Geometrie | ✅ | ✅ | arc_handler |
| Divergenz (Original vs Output) | – | ✅ | debug_tools |

## 10. RISIKOMATRIX

| Risiko | Phase | Absicherung |
|--------|-------|-------------|
| Parser-Fehler | 13.0 | 80 Unit-Tests |
| State-Fehler | 13.0 | 48 Unit-Tests |
| Identity-Verletzung | 13.5 | Byte-identischer Vergleich |
| Z-Duplication-Fehler | 13.6 | State-Validierung nach Schritt |
| Extrusion-Scaling-Fehler | 13.7 | Isolierte mathematische Tests |
| Sublayer-Insertion-Fehler | 13.8 | Pipeline-Vergleich Before/After |

GENAU EIN RISIKO PRO ENTWICKLUNGSPHASE.