# KOMPLETTE PROJEKTZUSAMMENFASSUNG + NEUSTART-SPEZIFIKATION

## Für die lokale KI / Agenten-Systeme / MCP-gestützte Entwicklung

---

# 1. PROJEKTZIEL

Es soll ein neues Python-Skript entwickelt werden, das einen bestehenden `.gcode`-Dateistream analysiert und gezielt Outer-Walls (Außenkonturen) in Sub-Layer aufteilt bzw. modifiziert.

Das bisherige Projekt ist gescheitert, weil:

* Architekturfehler früh eingebaut wurden
* Zustandsmaschinen unsauber waren
* Travel- und Extrusionszustände vermischt wurden
* Debugging zu spät begann
* Geometrie nie formal validiert wurde
* Hypothesen statt Beweise verwendet wurden
* Die KI wiederholt falsche Annahmen traf
* Fehler „weggepatcht“ statt bewiesen wurden

Der Neustart muss vollständig datengetrieben erfolgen.

---

# 2. ABSOLUTE REGELN

## 2.1 Keine Vermutungen

Verboten:

* „wahrscheinlich“
* „dürfte“
* „scheint“
* „könnte“
* „vermutlich“
* Viewerinterpretationen
* optische Schätzungen

Jede Aussage muss:

* reproduzierbar
* messbar
* beweisbar
* geometrisch validierbar

sein.

---

# 3. WICHTIGSTE LEKTION AUS DEM GESCHEITERTEN PROJEKT

Der Hauptfehler war NICHT:

* Arc-Handling
* Retracts
* E-Scaling
* Feedrates

Der Hauptfehler war:

# FEHLENDE SAUBERE GEOMETRISCHE ZUSTANDSLOGIK

Genauer:

Ein Wipe-Move wurde als Extrusion klassifiziert.

Dadurch wurde:

* ein Travel-Move
* mit großem XY-Sprung
* und positivem E-Wert

durch die Extrusions-Skalierung verändert.

Ergebnis:

75mm Luftextrusion.

Das darf architektonisch niemals möglich sein.

---

# 4. WAS DAS NEUE SYSTEM KÖNNEN MUSS

Das neue System muss:

* Outer-Walls sicher erkennen
* Konturen korrekt isolieren
* Travel und Extrusion strikt trennen
* Retracts sauber verwalten
* Relative/absolute E korrekt behandeln
* Arcs korrekt behandeln
* Wipes erkennen
* Geometrie formal validieren
* Debug-Ausgaben erzeugen
* reproduzierbar analysierbar sein

---

# 5. ENTWICKLUNGSREGELN

# WICHTIG:

## DEBUGGING BEGINNT VOR DER ERSTEN ZEILE PRODUKTIVCODE

Das alte Projekt scheiterte daran, dass:

* zuerst Code geschrieben wurde
* danach versucht wurde zu verstehen was passiert

Das neue Projekt MUSS umgekehrt aufgebaut werden.

---

# 6. VERPFLICHTENDER ENTWICKLUNGSABLAUF

# PHASE 0 — MCP-ÜBERBLICK

Die KI MUSS zuerst:

1. Alle verfügbaren MCP-Server identifizieren
2. Verfügbare Tools dokumentieren
3. Dateisystemstruktur analysieren
4. Bereits existierende GCode-Tools suchen
5. Bereits existierende Analyse-Skripte prüfen
6. Bereits vorhandene Testdateien identifizieren
7. Architektur dokumentieren

Vorher DARF KEIN Produktionscode geschrieben werden.

---

# 7. UMGEBUNGSVORGABEN

# ES WIRD IN EINER `.venv` GEARBEITET

Pflichtregeln:

* KEINE globale Paketinstallation
* KEINE System-Python-Abhängigkeiten
* ALLES innerhalb der `.venv`

---

# 8. PAKETMANAGEMENT (PFLICHT)

Jedes Script MUSS:

1. Prüfen ob benötigte Pakete vorhanden sind
2. Fehlende Pakete automatisch installieren
3. Danach sauber neu starten

Beispielablauf:

```python
try:
    import numpy
except ImportError:
    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        "numpy"
    ])
    os.execv(sys.executable, [sys.executable] + sys.argv)
```

Das gilt für ALLE externen Pakete.

---

# 9. VERBOTENE ANNAHMEN

Die KI darf NIEMALS annehmen:

* dass E absolut ist
* dass E relativ ist
* dass GCode linear ist
* dass G1 immer Extrusion bedeutet
* dass G2/G3 linear behandelbar sind
* dass Travel kein E enthalten darf
* dass Wipes keine Extrusion enthalten
* dass Retracts nur G10/G11 sind
* dass Layer logisch korrekt sind
* dass Slicer konsistent sind

Alles muss aus dem Datenstrom abgeleitet werden.

---

# 10. ARCHITEKTURVORGABEN

Das neue System MUSS modular aufgebaut sein.

Pflichtmodule:

```text
gcode_parser.py
geometry_validator.py
state_tracker.py
contour_extractor.py
travel_classifier.py
wipe_detector.py
arc_handler.py
debug_tools.py
analysis_runner.py
tests/
```

Keine Monolith-Datei.

---

# 11. ZENTRALE REGEL: ZUSTANDSMASCHINE

Das gesamte Projekt steht oder fällt mit einer sauberen Zustandsmaschine.

Die KI MUSS exakt tracken:

```python
current_xy
last_extrusion_xy
current_e
relative_e_mode
relative_xyz_mode
is_retracted
is_printing
current_layer
current_feedrate
awaiting_unretract
current_contour
```

Fehlende Zustandsvariablen sind Architekturfehler.

---

# 12. GEOMETRIE IST DIE EINZIGE WAHRHEIT

Viewer sind irrelevant.

Entscheidend sind:

* XY-Distanzen
* E-Deltas
* Kontinuität
* Bewegungszustände
* mathematische Validierung

---

# 13. VERPFLICHTENDE ANALYSEWERKZEUGE

Noch VOR Produktionscode:

Die KI MUSS Analysewerkzeuge bauen.

Pflicht:

## 13.1 Geometrische Anomalie-Erkennung

Muss erkennen:

* große Extrusionssprünge
* Extrusion ohne vorherigen Travel
* unterbrochene Konturen
* Geometrie-Divergenzen
* E-Skalierungsfehler
* Zustandswechsel ohne Ursache

---

# 14. ARCS (G2/G3)

Arcs waren eine große Fehlerquelle.

Regeln:

* G2/G3 dürfen NICHT linear bewertet werden
* Endpunktdistanz ist NICHT die Extrusionslänge
* I/J definieren die Geometrie
* Arc-Endpunkte müssen trotzdem Zustand aktualisieren

---

# 15. WIPE-ERKENNUNG

Das alte Projekt scheiterte exakt hier.

Pflicht:

Das neue System MUSS Wipes explizit erkennen.

Typische Eigenschaften:

* großer XY-Sprung
* positives E
* innerhalb bestehender Extrusion
* oft Konturende

Wipes dürfen NIEMALS wie normale Extrusion behandelt werden.

---

# 16. TRAVEL VS EXTRUSION

Das MUSS absolut getrennt sein.

Pflicht:

```python
travel_lines
extrusion_lines
```

dürfen niemals vermischt werden.

---

# 17. RETRACT-LOGIK

Retracts dürfen nicht geraten werden.

Pflicht:

* G10/G11 unterstützen
* negative E-Deltas erkennen
* relative/absolute E berücksichtigen
* Awaiting-Unretract tracken

---

# 18. TESTPHILOSOPHIE

Der alte Fehler:

„Patch schreiben → hoffen“

Neue Pflicht:

# ERST TEST

# DANN CODE

---

# 19. PFLICHT-TESTS

Vor jedem Produktionsschritt:

## 19.1 Parser-Test

Validieren:

* X/Y/Z
* E
* I/J
* G2/G3
* Kommentare
* Scientific notation
* negative Werte

---

## 19.2 Zustands-Test

Prüfen:

* relative E
* absolute E
* G92 E
* Retracts
* Unretracts

---

## 19.3 Geometrie-Test

Prüfen:

* Kontinuität
* Sprünge
* Travel-Ketten
* Arc-Konsistenz

---

## 19.4 Kontur-Test

Prüfen:

* geschlossene Konturen
* Layerwechsel
* Inselwechsel
* Start-/Endpunkte

---

# 20. DEBUGGING-REGELN

Pflicht:

Jeder Fehler muss:

1. reproduziert werden
2. isoliert werden
3. bewiesen werden
4. minimal getestet werden
5. erst dann gefixt werden

---

# 21. VERBOTENE FEHLERBEHANDLUNG

Verboten:

* zusätzliche Sonderfälle stapeln
* „Patch über Patch“
* magische Schwellwerte ohne Analyse
* Heuristiken ohne Datennachweis
* globale Quickfixes

---

# 22. LOGGING-PFLICHT

Alle kritischen Entscheidungen müssen logbar sein.

Pflicht:

```python
DEBUG_WIPE
DEBUG_RETRACT
DEBUG_ARC
DEBUG_CONTOUR
DEBUG_GEOMETRY
DEBUG_STATE
```

---

# 23. DATEIVERARBEITUNG

Das System darf Originaldateien NIEMALS überschreiben.

Pflicht:

```text
input.gcode
→
processed_input.gcode
```

---

# 24. VALIDIERUNG NACH JEDEM SCHRITT

Nach jeder Transformation MUSS:

1. Geometrieanalyse laufen
2. Erste Divergenz gesucht werden
3. Original vs Output verglichen werden

---

# 25. WICHTIGSTE DEBUG-REGEL

Nicht:

„Warum sieht das falsch aus?“

Sondern:

# WO ENTSTAND DIE ERSTE DIVERGENZ?

Nur das zählt.

---

# 26. PERFORMANCE IST SEKUNDÄR

Das alte Projekt fokussierte zeitweise zu früh auf Optimierung.

Verboten bevor Stabilität erreicht ist:

* Multithreading
* aggressive Caches
* Streaming-Optimierungen
* Micro-Optimierungen

Erst Korrektheit.
Dann Performance.

---

# 27. DOKUMENTATIONSPFLICHT

Jeder Modulbereich MUSS dokumentieren:

* Eingaben
* Zustände
* Annahmen
* Invarianten
* Fehlerfälle

---

# 28. EMPFOHLENE ENTWICKLUNGSSTRATEGIE

Reihenfolge:

1. MCP-Überblick
2. Testumgebung
3. Parser
4. Zustandsmaschine
5. Analysewerkzeuge
6. Geometrievalidierung
7. Konturextraktion
8. Travel/Extrusion-Trennung
9. Wipe-Erkennung
10. Arc-Handling
11. Erst DANACH Produktionslogik

---

# 29. HARTE STOPPREGEL

Wenn:

* neue Hypothesen entstehen
* unklare Zustände auftreten
* Geometrie unstimmig wird
* zusätzliche Sonderfälle nötig werden

DANN:

# STOPP

# ANALYSIEREN

# KEIN WEITERER PATCH

---

# 30. ENDZIEL

Nicht:

* „funktioniert meistens“
* „Viewer sieht okay aus“
* „keine offensichtlichen Fehler“

Sondern:

# FORMAL VALIDIERTE GEOMETRISCHE KORREKTHEIT

Das System muss beweisen können:

* warum jede Extrusion existiert
* warum jede Bewegung korrekt klassifiziert wurde
* warum keine Divergenz entsteht
* warum Travel und Extrusion getrennt bleiben

---

# 31. ABSCHLIESSENDE WARNUNG AN DIE KI

Das vorherige Projekt scheiterte NICHT an Syntax.

Es scheiterte an:

* fehlender Architekturdisziplin
* fehlender Zustandslogik
* fehlender Geometrievalidierung
* zu frühem Patchen
* zu spätem Debugging
* unbewiesenen Annahmen

Wenn dieselben Muster erneut auftreten, wird das neue Projekt ebenfalls scheitern.

Die KI MUSS datengetrieben, reproduzierbar und beweisbasiert arbeiten.

Keine Vermutungen.
Keine Schnellschüsse.
Keine Viewer-Magie.
Keine „wahrscheinlich“-Logik.

Nur Zustände.
Nur Geometrie.
Nur Beweise.
