# TASK_LOG – Phase 13.6: Z-Duplication

**Datum:** 29.05.2026  
**Status:** ✅ ABGESCHLOSSEN  
**Git-Commit:** `7629101`

---

## 1. AUSGANGSLAGE

### Vorheriger Stand
- Phase 13.5 (Identity) war bereits implementiert und validiert
- Pipeline existierte mit 10 Schritten
- Alle 128 Unit-Tests bestanden
- `identity_processor.py` validierte byte-identischen Output

### Ziel von Phase 13.6
Laut `PIPELINE_SPEC.md`:
> Z-Wert einer Bewegung erhöhen und Bewegung duplizieren  
> Beispiel: `G1 X10 Y10 Z0.2 E0.4` → `G1 X10 Y10 Z0.2 E0.4` + `G1 X10 Y10 Z0.25`  
> Keine E-Änderung im duplizierten Move

---

## 2. ANALYSE (VORHER)

### Dateien gelesen
| Datei | Zweck |
|-------|-------|
| `Projektplan.md` | Projektregeln und -philosophie |
| `PIPELINE_SPEC.md` | Formale Pipelinespezifikation |
| `MCP_DOKUMENTATION.md` | Verfügbare MCP-Server |
| `pipeline.py` | Hauptpipeline (10 Schritte) |
| `gcode_parser.py` | GCode-Parser mit GCodeEvent-Klasse |
| `state_tracker.py` | Zustandsmaschine |
| `identity_processor.py` | Phase 13.5 (Identity-Test) |
| `sublayer_processor.py` | Sublayer-Verarbeitung |
| `output_writer.py` | GCode-Output |
| `contour_extractor.py` | Konturextraktion |
| `travel_classifier.py` | Travel/Extrusion-Klassifizierung |
| `wipe_detector.py` | Wipe-Erkennung |
| `arc_handler.py` | Arc-Verarbeitung |
| `logging_system.py` | Strukturiertes Logging |

### Logs analysiert
- `logs/identity_processor.jsonl`: Zeigte 3 Durchläufe, letzter ERFOLGREICH
- Identity-Test war bereits validiert (byte-identisch)

### Erkenntnisse
1. `GCodeEvent.__init__` akzeptiert nur `(line_idx, raw)`, Attribute werden durch `parse()` gesetzt
2. `output_writer.write_combined` unterstützte nur 1:1-Ersetzungen
3. Pipeline hatte kein `run_z_duplication` Flag
4. Z-Duplication erzeugt MEHR Zeilen als Input (Insertion, nicht Replacement)

---

## 3. IMPLEMENTIERUNG

### 3.1 Tests ZUERST (TDD)
**Datei:** `tests/test_z_duplication.py`

| Testklasse | Tests | Beschreibung |
|------------|-------|--------------|
| TestZDuplicationConfig | 2 | Default-/Custom-Konfiguration |
| TestZDuplicationExtrusion | 3 | G1 mit E dupliziert, G1 ohne E nicht, G0 nicht |
| TestZDuplicationNonTargetType | 2 | FILL nicht dupliziert, WALL-INNER nicht default |
| TestZDuplicationCommentPassthrough | 1 | Kommentare unverändert |
| TestZDuplicationZCalculation | 2 | Z-Offset korrekt, Custom-Offset |
| TestZDuplicationWithComments | 1 | Inline-Kommentar im Duplikat |
| TestZDuplicationPreservesXY | 1 | X/Y bleiben identisch |
| TestZDuplicationDisabled | 1 | Deaktivierter Prozessor |
| TestZDuplicationFeedrate | 1 | Feedrate im Duplikat |
| **Gesamt** | **14** | |

**Hilfsfunktion:** `make_event(raw, line_idx, type_tag, layer_number)` – Erzeugt GCodeEvents korrekt via `parse()`.

### 3.2 Z-Duplication Prozessor
**Datei:** `z_duplication_processor.py`

**Klassen:**
- `ZDuplicationConfig` – Konfiguration (z_offset, target_types, enabled)
- `ZDuplicationProcessor` – Event-Verarbeitung

**Entscheidungslogik:**
```
_should_duplicate(event, type_tag):
  1. command == 'G1'? (kein G0, G2, G3)
  2. has_e == True? (kein Travel)
  3. type_tag in target_types?
  → Nur wenn ALLE JA
```

**Duplikat-Logik:**
```
_create_duplication(event):
  - Gleicher Befehl (G1)
  - Gleiche X/Y
  - Neues Z = Original + offset
  - Gleiche Feedrate
  - KEIN E-Parameter
  - KEIN Kommentar
```

**Statistiken:** total_events, duplications, skipped

### 3.3 Output-Writer Erweiterung
**Datei:** `output_writer.py`

**Änderung in `write_combined`:**
```python
# VORHER: Nur String-Ersetzung
mod_line = modified_lines[event.line_idx].rstrip('\n\r')

# NACHHER: String ODER Liste
mod = modified_lines[event.line_idx]
if isinstance(mod, list):
    for sub_line in mod:
        lines.append(sub_line.rstrip('\n\r') + original_newline)
else:
    lines.append(mod.rstrip('\n\r') + original_newline)
```

**Abwärtskompatibel:** String-Werte werden weiterhin unterstützt.

### 3.4 Pipeline-Integration
**Datei:** `pipeline.py`

**Neue Config-Slots:**
- `run_z_duplication: bool = False` (standardmäßig deaktiviert)
- `z_duplication_config: ZDuplicationConfig`

**Neuer Schritt 6.5 (zwischen Arc-Analyse und Sublayer):**
```python
if self.config.run_z_duplication:
    z_processor = ZDuplicationProcessor(config)
    current_type_tag = ''
    for event in events:
        if event.type_tag:
            current_type_tag = event.type_tag
        if event.command in ('G0', 'G1', ...):
            result_lines = z_processor.process_event(event, current_type_tag)
            if len(result_lines) > 1:
                modified_lines[event.line_idx] = result_lines
```

**Type-Tag-Tracking:** Wird über Kommentare (`;TYPE:WALL-OUTER`) getrackt.

### 3.5 Integrationstest
**Datei:** `test_z_duplication_integration.py`

| Test | Beschreibung | Ergebnis |
|------|--------------|----------|
| Test 1 | Identity (deaktiviert) | ✅ Byte-identisch |
| Test 2 | Z-Duplication aktiviert | ✅ 38 Zeilen mehr |
| Test 3 | Duplikate analysieren | ✅ 38 korrekte Duplikate |
| Test 4 | Z-Werte prüfen | ✅ Alle Vielfache von 0.05 |

---

## 4. TESTERGEBNISSE

### Unit-Tests
```
tests/test_parser.py:           75 passed
tests/test_state_tracker.py:    53 passed
tests/test_z_duplication.py:    14 passed
─────────────────────────────────────────
Gesamt:                        142 passed in 0.33s
```

### Identity-Test
```
Status: ✅ PASSED
Input:  5532 bytes
Output: 5532 bytes
Byte-identisch: True
```

### Integrationstest
```
Phase 13.6 (Z-Duplication) – ALLE TESTS BESTANDEN
Input:  174 Zeilen
Output: 212 Zeilen
Duplikate: 38
Z-Offset: 0.05 mm
Target: ['WALL-OUTER']
```

---

## 5. ARCHITEKTUR-ENTSCHEIDUNGEN

| Entscheidung | Begründung |
|--------------|------------|
| Isolierter Prozessor (nicht in pipeline.py) | Modulare Architektur, separat testbar |
| Type-Tag-Tracking via current_type_tag | Korrekte Zuordnung von WALL-OUTER |
| output_writer erweitert (nicht ersetzt) | Abwärtskompatibilität |
| Z-Duplication standardmäßig deaktiviert | Identity-Test muss weiterhin funktionieren |
| Nur G1 (kein G2/G3) | Arcs haben andere Geometrie-Logik |
| Nur target_types | WALL-OUTER ist Hauptziel |

---

## 6. RISIKOANALYSE

| Risiko | Status | Absicherung |
|--------|--------|-------------|
| Parser-Fehler | ✅ Getestet | 75 Unit-Tests |
| State-Fehler | ✅ Getestet | 53 Unit-Tests |
| Identity-Verletzung | ✅ Getestet | Byte-identischer Vergleich |
| Z-Duplication-Fehler | ✅ Getestet | 14 Unit-Tests + Integrationstest |

---

## 7. OFFENE PUNKTE

### Für Phase 13.7 (Extrusion Scaling)
- E-Werte mathematisch skalieren
- M82/M83 korrekt behandeln
- Keine Änderung an X/Y/Z
- Isolierte mathematische Tests

### Technische Schulden
- `TASK_LOG_NEWLINE_IDENTITY.md` existiert nicht (möglicherweise umbenannt)
- SublayerProcessor hat potenzielle Konflikte mit Z-Duplication (beide ändern Z)
- G2/G3-Arcs werden in Phase 13.6 nicht dupliziert (bewusst)

---

## 8. COMMIT-LOG

```
Commit: 7629101
Branch: master
Message: Phase 13.6: Z-Duplication implementiert und validiert

Dateien:
  z_duplication_processor.py (neu)
  tests/test_z_duplication.py (neu)
  test_z_duplication_integration.py (neu)
  pipeline.py (geändert)
  output_writer.py (geändert)
  PIPELINE_SPEC.md (geändert)

+1606 Zeilen
```

---

## 9. ZUSAMMENFASSUNG

Phase 13.6 (Z-Duplication) wurde erfolgreich implementiert:

1. **Analyse:** 14 Dateien gelesen, Logs analysiert, API verstanden
2. **TDD:** 14 Tests ZUERST geschrieben
3. **Implementierung:** Isolierter Prozessor mit klarer Trennung
4. **Integration:** Pipeline um Schritt 6.5 erweitert
5. **Validierung:** 142 Unit-Tests + Integrationstest + Identity
6. **Dokumentation:** PIPELINE_SPEC.md aktualisiert
7. **Commit:** Sauberer Git-Commit mit Beschreibung

**Geometrie ist die Wahrheit.** Alle Aussagen sind reproduzierbar, messbar und beweisbar.