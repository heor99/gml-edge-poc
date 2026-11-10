#!/usr/bin/env python3
"""Génère data/synthetic_100hz.csv : 60 s d'accéléromètre à 100 Hz (fréquence réelle de la tablette).

Contenu (graine fixe, résultat reproductible) :
  - bruit de route gaussien (vibrations) sur les 3 axes ;
  - t = 10 s : nid-de-poule, pic isolé de -6,0 m/s² sur l'axe Y pendant 10 ms  -> doit être IGNORÉ ;
  - t = 20 s : dos-d'âne, pic isolé de +5,0 m/s² sur Y                          -> doit être IGNORÉ ;
  - t = 40 s : vrai freinage violent, -3,5 m/s² pendant 0,6 s                   -> doit être DÉTECTÉ ;
  - t = 50 s : virage brusque, +3,6 m/s² latéral (X) pendant 1,0 s              -> doit être DÉTECTÉ.
"""
import os
import random

random.seed(42)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "synthetic_100hz.csv")
T0 = 1678880000.0
FS = 100

with open(OUT, "w", encoding="utf-8") as f:
    f.write("timestamp,acc_x,acc_y,acc_z\n")
    for i in range(60 * FS):
        t = i / FS
        ax = random.gauss(0, 0.35)
        ay = random.gauss(0, 0.40)
        az = 9.81 + random.gauss(0, 0.30)
        if i == 10 * FS:
            ay = -6.0
        if i == 20 * FS:
            ay = 5.0
        if 40.0 <= t < 40.6:
            ay = -3.5 + random.gauss(0, 0.25)
        if 50.0 <= t < 51.0:
            ax = 3.6 + random.gauss(0, 0.25)
        f.write(f"{T0 + t:.2f},{ax:.3f},{ay:.3f},{az:.3f}\n")
print("écrit :", os.path.normpath(OUT))
