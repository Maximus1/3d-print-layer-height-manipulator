# TASK_LOG – Phase 13.7: Extrusion Scaling

**Datum:** 29.05.2026  
**Status:** ✅ ABGESCHLOSSEN  
**Git-Commit:** (wird erstellt)

---

## 1. AUSGANGSLAGE

### Ziel von Phase 13.7
Laut `PIPELINE_SPEC.md`:
> E-Werte mathematisch skalieren (M82/M83 korrekt)  
> Keine Änderung an X/Y/Z  
> Keine Änderung an G2/G3 I/J

### Kerneherausforderung
- M83 (relativ): E_delta * scale_factor (einfach)
- M82 (absolut): Delta berechnen, skalieren, neues absolutes E (komplex)

---

## 2. IMPLEMENTIERUNG

### 2.1 Tests (22 Tests)
**Datei:** `tests/test_extrusion_scaling.py`

| Testklasse | Tests | Beschreibung |
|------------|-------|--------------|
| TestExtrusionScalingConfig | 2 | Default-/Custom-Konfiguration |
| TestExtrusionScalingRelativeMode | 4 | M83: halbieren, skalieren, zero, negative |
| TestExtrusionScalingAbsoluteMode | 3 | M82: ab zero, ab nonzero, mehrere Schritte |
| TestExtrusionScalingNoE | 3 | Travel, G0, Kommentar unverändert |
| TestExtrusionScalingPreservesXYZ | 2 | X/Y/Z unverändert (relativ + absolut) |
| TestExtrusionScalingFeedrate | 1 | Feedrate unverändert |
| TestExtrusionScalingDisabled | 1 | Deaktivierter Prozessor |
| TestExtrusionScalingArc | 2 | G2/G3 E skaliert, I/J unverändert |
| TestExtrusionScalingEdgeCases | 4 | Kleiner E, großer E, factor=1, factor=0 |
| **Gesamt** | **22** | |

### 2.2 Prozessor
**Datei:** `extrusion_scaling_processor.py`

**Klassen:**
- `ExtrusionScalingConfig` – Konfiguration (scale_factor, enabled)
- `ExtrusionScalingProcessor` – Event-Verarbeitung

**Logik:**
```
M83 (relativ):
  new_e = e_value * scale_factor
  Ersetze E im Code-Teil

M82 (absolut):
  delta = e_neu - e_aktuell
  scaled_delta = delta * scale_factor
  new_absolute_e = e_aktuell + scaled_delta
  e_aktuell = new_absolute_e
  Ersetze E im Code-Teil
```

### 2.3 Pipeline-Integration
**Datei:** `pipeline.py` (Schritt 6.6)

**Neue Config-Slots:**
- `run_extrusion_scaling: bool = False`
- `extrusion_scaling_config: ExtrusionScalingConfig`

---

## 3. TESTERGEBNISSE

```
Unit-Tests: 164/164 ✅ ALL PASSED (0.32s)
Identity:   ✅ PASSED (byte-identisch)
```

---

## 4. OFFENE PUNKTE

### Für Phase 13.8 (Sublayer-Insertion)
- 1 zusätzliche Zwischenlage
- Extrusion skaliert + Z-Offset
- 23 Validierungsfehler zu beheben