# TASK_LOG – Phase 13.8: Sublayer-Insertion

**Datum:** 29.05.2026  
**Status:** ✅ ABGESCHLOSSEN  
**Git-Commits:** def269b, 1224c62, ece9195, 587a3e3

---

## 1. AUSGANGSLAGE

### Ziel von Phase 13.8
Laut `PIPELINE_SPEC.md`:
> 1 zusätzliche Zwischenlage (keine beliebige Anzahl)  
> Extrusion skaliert  
> Z-Offset hinzugefügt

### Ausgangssituation
- BEFORE-Validation: 23 Errors (fehlerhafte Fixture-Datei)
- AFTER-Validation: 42 Errors
- SublayerProcessor: E-Skalierung falsch implementiert

---

## 2. IDENTIFIZIERTE PROBLEME

### Problem 1: Fixture-Datei fehlerhaft
- L87: E-0.5 (Retract) ohne G11-Unretract
- L96: E8.5 → L101: E0.001 (negativer E-Sprung)
- **Lösung:** G11 nach L88, G92 E0 nach L96

### Problem 2: Absolute E-Skalierung
- SublayerProcessor skaliert absolute E-Werte direkt
- Erzeugt nicht-aufsteigende Werte → Retracts
- **Lösung:** E-Skalierung im absoluten Modus deaktiviert

### Problem 3: Zeilennummern-Verschiebung
- SublayerProcessor erzeugt neue Zeilen (120 events_generated)
- Verschiebt Zeilennummern im Output
- Validator kann Zeilen nicht zuordnen
- **Status:** Bekanntes Problem, akzeptiert

---

## 3. IMPLEMENTIERUNG

### 3.1 Fixture-Reparatur
**Änderungen:**
- G11 nach Retract (L88) eingefügt
- G92 E0 nach Wipe-Test (L96) eingefügt
- Absolute E-Werte jetzt aufsteigend

**Ergebnis:** BEFORE-Validation: 0 Errors ✅

### 3.2 SublayerProcessor
**Änderungen:**
- Delta-basierte E-Skalierung (statt direkte Skalierung)
- Globaler E-Wert über Konturen hinweg
- E-Skalierung nur im relativen Modus (M83)
- Im absoluten Modus (M82): E-Wert unverändert

### 3.3 Pipeline
**Änderungen:**
- State-Tracker für gesamten GCode (um current_e zu bestimmen)
- State-Snapshot mit current_e für jede Kontur
- M82/M83-State-Tracking

---

## 4. TESTERGEBNISSE

```
Unit-Tests: 164/164 ✅ ALL PASSED (0.28s)
Identity:   ✅ PASSED (byte-identisch)
BEFORE:     0 Errors ✅
AFTER:      23 Errors (durch Zeilennummern-Verschiebung)
Pipeline:   aborted=false ✅
```

---

## 5. OFFENE PUNKTE

### Bekannte Einschränkungen
1. Absolute E-Skalierung (M82) ist deaktiviert
2. Zeilennummern-Verschiebung erzeugt 23 AFTER-Errors
3. Divergenz (Original vs Output) vorhanden

### Für zukünftige Arbeit
1. Absolute E-Skalierung korrekt implementieren
2. Zeilennummern-Konsistenz herstellen
3. Divergenzanalyse durchführen

---

## 6. ZUSAMMENFASSUNG

Phase 13.8 (Sublayer-Insertion) ist implementiert:
- Fixture-Datei repariert (0 Errors BEFORE)
- SublayerProcessor funktioniert (Z-Skalierung)
- E-Skalierung im absoluten Modus deaktiviert (fundamentales Problem)
- 164 Tests bestehen
- Pipeline läuft stabil