G28; Home all axes
G90; Absolute positioning
G91 E0; Reset extruder relative mode - not needed, using absolute
M83; Relative extrusion

; Layer 1 - Clean sublayer test contour
G1 Z5 F3000
G1 X10 Y10 F6000
G1 E0.2
G1 X50 Y10 E0.5
G1 X50 Y50 E0.8
G1 X10 Y50 E1.1
G1 X10 Y10 E1.4

; Layer 2 - Second contour
G1 Z10 F3000
G1 X10 Y60 F6000
G1 E0.2
G1 X90 Y60 E0.7
G1 X90 Y100 E1.2

; Layer 3 - Third contour with longer segment
G1 Z15 F3000
G1 X20 Y20 F6000
G1 E0.2
G1 X80 Y20 E1.0
G1 X80 Y80 E1.8
G1 X20 Y80 E2.6

; End
M104 S0
M300 P5 S1
G91 E-1