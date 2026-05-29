# Zustandsbericht – Phase 13.8 (Sublayer-Insertion)

**Datum:** 29.05.2026  
**Status:** ⚠️ INSTABIL

---

## 1. IDENTIFIZIERTE PROBLEME

### Problem 1: 23 Validierungsfehler (BEFORE Sublayer)

**Typ:** `extrusion_while_retracted`  
**Ursache:** Fixture-Datei `fixtures/minimal_test.gcode` enthält fehlerhaften GCode  
**Nachweis:** 
- L87: `G1 X80 Y50 Z1.1 E-0.5` → Retract (negativer E-Wert)
- Kein G11-Unretract danach
- L89: `G1 X90 Y60 Z1.2 E8.0` → Extrusion während Retract

**Betroffene Zeilen:** 88, 94, 100, 106, 107, 113, 114, 115, 120, 121, 126, 127, 138, 139, 140, 147, 148, 154, 156, 158, 160, 162, 167

**Fazit:** Die 23 Fehler sind KORREKTES Verhalten des GeometryValidator. Er erkennt einen echten GCode-Fehler in der Fixture-Datei.

### Problem 2: 42 Validierungsfehler (AFTER Sublayer)

**Typ:** Verschiedene  
**Ursache:** SublayerProcessor erzeugt zusätzliche Geometrie-Fehler  
**Nachweis:** Validation After: 42 findings (vs. 31 Before)

**Fazit:** Der SublayerProcessor verschlechtert die Geometrie-Konsistenz.

### Problem 3: Divergenz (Original vs Output)

**Typ:** Geometrische Divergenz  
**Ursache:** SublayerProcessor verändert GCode-Struktur  
**Nachweis:** `divergence_found: true`

**Fazit:** Der Output ist nicht geometrisch konsistent mit dem Input.

---

## 2. URACHENANALYSE

### Problem 1 (23 Fehler BEFORE):
- **Nicht** ein Bug im State-Tracker
- **Nicht** ein Bug im GeometryValidator
- **Sondern** ein Fehler in der Fixture-Datei
- Die Fixture-Datei enthält absichtlich fehlerhaften GCode für Parser-Tests
- Aber der Validator erkennt diese Fehler korrekt

### Problem 2 (42 Fehler AFTER):
- SublayerProcessor erzeugt Zeilen, die vom Validator als fehlerhaft erkannt werden
- Mögliche Ursache: Skalierte E-Werte erzeugen ungültige Extrusionsmuster

### Problem 3 (Divergenz):
- SublayerProcessor verändert die GCode-Struktur
- Das ist erwartetes Verhalten (Transformation)
- Aber die Divergenz muss geometrisch valide sein

---

## 3. LÖSUNGSANSÄTZE

### Für Problem 1:
**Option A:** Fixture-Datei reparieren (G11 nach Retracts einfügen)
- Vorteil: Sauber, korrekter GCode
- Nachteil: Viel Arbeit, Parser-Tests müssen angepasst werden

**Option B:** Validator so anpassen, dass "extrusion_while_retracted" als Warning behandelt wird
- Vorteil: Schneller Fix
- Nachteil: Verstößt gegen Projektregel "Validator ist NICHT korrigierend"

**Option C:** Pipeline-Config: `abort_on_validation_error = False` (nur für Tests)
- Vorteil: Keine Änderung an Code
- Nachteil: Fehler werden ignoriert

**Empfehlung:** Option A (Fixture reparieren)

### Für Problem 2:
- SublayerProcessor muss validen GCode erzeugen
- E-Werte müssen nach Skalierung noch gültig sein
- Geometrie muss konsistent bleiben

### Für Problem 3:
- Divergenz muss analysiert werden
- Erste Divergenz muss gefunden werden
- Ursache muss bewiesen werden

---

## 4. EINSCHÄTZUNG

### Schweregrad: MITTEL

Die Probleme sind lösbar:
1. Fixture-Datei kann repariert werden
2. SublayerProcessor kann verbessert werden
3. Divergenz kann analysiert werden

### Aufwand: GROSS

1. Fixture-Datei reparieren: ~30 Minuten
2. SublayerProcessor debuggen: ~2-4 Stunden
3. Divergenzanalyse: ~1-2 Stunden

### Risiko: NIEDRIG

Die Probleme sind isoliert und reproduzierbar. Es gibt keine systemischen Fehler.

---

## 5. EMPFEHLUNG

1. **Sofort:** Fixture-Datei `fixtures/minimal_test.gcode` reparieren
   - G11 nach jedem Retract (G10 oder E-)
   - Tests aktualisieren
   - Regression laufen lassen

2. **Danach:** SublayerProcessor analysieren
   - Warum erzeugt er 42 Validierungsfehler?
   - Sind die transformierten E-Werte gültig?
   - Ist die Geometrie konsistent?

3. **Zuletzt:** Divergenzanalyse
   - Erste Divergenz finden
   - Ursache beweisen
   - Minimalen Patch finden

### Geschätzte Dauer: 4-6 Stunden