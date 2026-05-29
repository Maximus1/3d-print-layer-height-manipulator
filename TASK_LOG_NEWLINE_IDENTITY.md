# Task-Log: Newline-Handling & Byte-Exakte Reproduktion

**Erstellt:** 29.05.2026  
**Status:** ✅ Abgeschlossen  
**Thema:** Pipeline erzeugt byte-exakt identische Ausgabe bei deaktivierten Transformationsschritten – mit korrektem Newline-Format und trailing newline aus der Originaldatei.

---

## Problemstellung

Die Pipeline verarbeitete GCode-Dateien durch den Parser → Events → OutputWriter-Pfad, was zwei Probleme verursachte:

1. **Newline-Format verloren:** Die Originaldatei konnte `\r\n` (CRLF) oder `\n` (LF) verwenden. Der OutputWriter hat immer ein festes `'\n'` verwendet, wodurch das Newline-Format der Originaldatei überschrieben wurde.
2. **Trailing newline verloren:** Ob die Originaldatei mit einem Newline endet oder nicht, wurde nicht erkannt und nicht beibehalten.

**Folge:** Die Pipeline konnte niemals byte-exakt identische Ausgabe erzeugen, selbst wenn keine Transformation aktiv war – das Newline-Format unterschied sich immer.

---

## Änderungen im Detail

### 1. `output_writer.py` – `write_combined()` um Parameter erweitern

**Datei:** `C:\Users\Marcus\outer perimeter\output_writer.py`  
**Änderung:** Zwei neue Parameter für `write_combined()`:

```python
def write_combined(self, original_events: List, modified_lines: dict,
                   output_path: str,
                   original_newline: str = '\n',
                   has_trailing_newline: bool = True) -> str:
```

- **`original_newline`**: Zeilenende-Format der Originaldatei (`'\n'` oder `'\r\n'`). Jede Zeile wird mit diesem Format geschrieben.
- **`has_trailing_newline`**: Ob die Originaldatei mit einem Newline endet. Falls `False`, wird das letzte Newline aus dem Output entfernt (Binärmodus, präzise Byte-Korrektur).

**Gleiches Muster bereits existierend für `write()`:** Die Methode `write()` hatte diese Parameter schon früher erhalten. `write_combined()` wurde nachgebessert, damit beide Methoden konsistent arbeiten.

**Trailing-newline Korrektur-Logik (beide Methoden):**
```python
if not has_trailing_newline and lines:
    offset = len(original_newline)  # 1 für '\n', 2 für '\r\n'
    with open(str(path), 'rb') as f:
        data = f.read()
    if data[-offset:] == original_newline.encode('utf-8'):
        data = data[:-offset]
    with open(str(path), 'wb') as f:
        f.write(data)
```

### 2. `pipeline.py` – Newline-Detection & Durchreichen

**Datei:** `C:\Users\Marcus\outer perimeter\pipeline.py`  

#### `_detect_newline()` – Neue Methode
```python
def _detect_newline(self, filepath: str) -> str:
    """Erkennt das Zeilenende-Format der Originaldatei."""
    with open(filepath, 'rb') as f:
        raw = f.read(1024 * 64)  # erste 64KB
    if b'\r\n' in raw:
        return '\r\n'
    return '\n'
```

#### `_detect_trailing_newline()` – Neue Methode
```python
def _detect_trailing_newline(self, filepath: str) -> bool:
    """Erkennt ob die Originaldatei mit einem Newline endet."""
    with open(filepath, 'rb') as f:
        f.seek(-4, 2)
        tail = f.read()
    return tail.endswith(b'\n') or tail.endswith(b'\r\n')
```

#### `run()` – Detection in Pipeline integrieren
Vor dem Parsen werden beide Werte ermittelt und an `write_combined()` durchgereicht:

```python
# Newline-Format der Originaldatei erkennen
self.original_newline = self._detect_newline(filepath)
self.has_trailing_newline = self._detect_trailing_newline(filepath)
```

#### `PipelineConfig.__init__()` – kwargs akzeptieren
```python
def __init__(self, **kwargs):
    # ... bestehende Defaults ...
    for k, v in kwargs.items():
        if hasattr(self, k):
            setattr(self, k, v)
```

### 3. `regression_runner.py` – Neue Datei erstellt

**Datei:** `C:\Users\Marcus\outer perimeter\regression_runner.py`  
**Zweck:** Automatischer Vergleich von Pipeline-Output mit Golden Files für Byte-Identitäts-Beweis.

**Aufbau:**
- **`RegressionTest`** dataclass: name, fixture_path, description
- **`TestResult`** dataclass: test_name, passed, hashes, error
- **`TEST_CASES`**: Liste aller definierten Tests
- **`run_identity_pipeline()`**: Führt die Pipeline mit allen Schritten deaktiviert aus → reine Kopie
- **`generate_golden()`**: Erzeugt Golden Files unter `regression/golden/`
- **`run_tests()`**: Vergleicht Pipeline-Output byte-exakt mit Golden Files

**Nutzung:**
```bash
# Golden Files generieren (einmalig):
python regression_runner.py --generate

# Regressionstests ausführen:
python regression_runner.py
```

### 4. Neue Fixtures & Golden Files

| Datei | Pfad | Beschreibung |
|-------|------|-------------|
| `sublayer_clean.gcode` | `fixtures/sublayer_clean.gcode` | Saubere Testdatei mit 3 Konturen, kein Wipe-Ambiguität |
| `identity_minimal_test.gcode` | `regression/golden/identity_minimal_test.gcode` | Golden File für minimal_test (5532 bytes) |
| `identity_sublayer_clean.gcode` | `regression/golden/identity_sublayer_clean.gcode` | Golden File für sublayer_clean (542 bytes) |

---

## Test-Ergebnisse

```
✅ [identity_minimal_test] PASSED  (sha256=f9fd0d035b24fee4...)
✅ [identity_sublayer_clean] PASSED (sha256=fff6a167eb2f37db...)
ERGEBNIS: 2/2 bestanden, 0 fehlgeschlagen
🎉 Alle Tests bestanden!
```

**Beweis:** Pipeline erzeugt byte-exakt identische Ausgabe bei deaktivierten Transformationsschritten – Newline-Format und trailing newline werden korrekt beibehalten.

---

## Architektur-Entscheidungen

| Entscheidung | Begründung |
|-------------|------------|
| Binärmodus für Newline-Detection | `\r\n` vs `\n` nur im Binärmodus zuverlässig erkennbar |
| Trailing-newline Korrektur nach dem Schreiben | Zeilenumbrüche werden pro-Zeile korrekt gesetzt, das letzte Byte (Newline) muss separat korrigiert werden wenn die Originaldatei keinen trailing NL hatte |
| `original_newline` als Pipeline-Attribut | Muss von `run()` an beide write-Methoden durchgereicht werden |

---

## Bekannte Einschränkungen

1. **Pipeline mit aktivierten Schritten:** Die vollwertige Pipeline (Validierung, Sublayer, etc.) bricht bei Testdateien ab wegen Validierungsfehlern – separates Problem, nichts mit Newline-Handling zu tun.
2. **`write()` vs `write_combined()`:** Beide Methoden haben jetzt konsistente Parameter. Die Pipeline nutzt `write_combined()` für den kombinierten Output (Original + modifizierte Zeilen).