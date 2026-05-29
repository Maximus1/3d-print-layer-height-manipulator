# Zustandsbericht UPDATE – Phase 13.8 (Sublayer-Insertion)

**Datum:** 29.05.2026  
**Status:** ⚠️ BLOCKIERT

---

## 1. ERGEBNIS NACH FIXTURE-REPARATUR

### BEFORE-Validation: ✅ SAUBER
```
Total: 18, Errors: 0, Warnings: 7
```

### AFTER-Validation: ❌ 41 FEHLER
```
Total: 50, Errors: 41, Warnings: 1
```

---

## 2. URACHE DER 41 AFTER-ERRORS

**Typ:** `extrusion_while_retracted`  
** Ursache:** SublayerProcessor skaliert absolute E-Werte falsch

**Beispiel:**
```
Original:  E2.5 (L27) → E3.0 (L34) → E3.5 (L35)
Skaliert:  E2.25 (L37) → E1.5 (L34) → E1.75 (L35)
                                      ↑
                              Negativer Sprung!
```

**Mechanismus:**
1. SublayerProcessor hat `scale_factor = 0.5`
2. Er skaliert alle E-Werte: E3.0 → E1.5
3. Aber absolute E-Werte müssen aufsteigend sein
4. Skalierung erzeugt nicht-aufsteigende Werte
5. State-Tracker erkennt negative Deltas als Retract
6. Validator meldet "extrusion_while_retracted"

---

## 3. FUNDAMENTALES PROBLEM

Der SublayerProcessor behandelt E-Werte wie lineare Größen:
```python
scaled_e = e_value * scale = 0.5  # Skalierung
```

ABER: Absolute E-Werte sind AKKUMULIERTE Größen:
```
E0.5 → E1.0 → E1.5 → E2.0 → E2.5
  ↓      ↓      ↓      ↓      ↓
E0.25 → E0.5 → E0.75 → E1.0 → E1.25  ← Korrekt (Deltas halbiert)
```

Das Problem: Der SublayerProcessor skaliert die absoluten Werte, nicht die Deltas.

---

## 4. LÖSUNGSANSÄTZE

### Option A: Deltas skalieren (statt absolute Werte)
- Berechne Delta = E_neu - E_alt
- Skaliere Delta: scaled_delta = delta * scale_factor
- Berechne neues absolutes E: E_neu = E_alt + scaled_delta
- **Vorteil:** Absoluter Wert bleibt aufsteigend
- **Nachteil:** Komplexe Logik,尤其 für M82/M83-Wechsel

### Option B: Relative E-Modi erzwingen
- Konvertiere alle absoluten E-Werte in relative
- Skaliere relative Werte
- Konvertiere zurück in absolute
- **Vorteil:** Einfacher
- **Nachteil:** Verändert GCode-Struktur

### Option C: Nur in relativem Modus skalieren
- Nur wenn M83 aktiv ist, skalieren
- Im absoluten Modus: keine Skalierung
- **Vorteil:** Sicher
- **Nachteil:** Keine Skalierung im absoluten Modus

---

## 5. EMPFEHLUNG

**Option A** ist die sauberste Lösung:
- Deltas skalieren (nicht absolute Werte)
- Korrekte Behandlung von M82/M83
- Aufsteigende absolute E-Werte bleiben erhalten

**Aufwand:** ~2-3 Stunden
**Risiko:** MITTEL (komplexe Logik)

---

## 6. AKTUELLER STATUS

| Metrik | BEFORE | AFTER | Delta |
|--------|--------|-------|-------|
| Errors | 0 | 41 | +41 |
| Findings | 18 | 50 | +32 |
| Contouren | 6 | 6 | 0 |
| Wipes | 46 | 46 | 0 |
| Arcs | 5 | 5 | 0 |
| Events | 176 | 176 | 0 |

**Fazit:** Der SublayerProcessor erzeugt 41 zusätzliche Fehler durch falsche E-Skalierung.