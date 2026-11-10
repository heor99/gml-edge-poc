#!/usr/bin/env python3
"""Banc de performance du moteur ZFE : intérêt de la Bounding Box et empreinte mémoire.

Simule une journée de positions GPS sur la région lyonnaise et compare le temps
de calcul avec et sans le pré-filtre Bounding Box, sur le polygone de l'énoncé
et sur un polygone réaliste de 1 000 sommets.
"""
import math
import os
import random
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gml_edge.geo import ZfePolygon, load_polygon  # noqa: E402

random.seed(7)
N = 200_000


def polygon_1000():
    c_lat, c_lon, r = 45.76, 4.84, 0.03
    pts = [{"lat": c_lat + r * (1 + 0.15 * math.sin(7 * a)) * math.sin(a),
            "lon": c_lon + 1.4 * r * (1 + 0.15 * math.sin(7 * a)) * math.cos(a)}
           for a in (2 * math.pi * k / 1000 for k in range(1000))]
    pts.append(pts[0])  # polygone fermé
    return ZfePolygon(pts, name="ZFE 1000 sommets")


def bench(poly, pts):
    t = time.perf_counter()
    a = sum(poly.contains(la, lo) for la, lo in pts)
    with_bbox = time.perf_counter() - t
    t = time.perf_counter()
    b = sum(poly.contains(la, lo, use_bbox=False) for la, lo in pts)
    without = time.perf_counter() - t
    assert a == b, "la bounding box ne doit jamais changer le résultat"
    return with_bbox, without, a


here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "lyon_polygon.json")
# journée type : positions dans un carré de ~ 110 km x 80 km autour de Lyon
pts = [(45.76 + random.uniform(-0.5, 0.5), 4.84 + random.uniform(-0.5, 0.5)) for _ in range(N)]
print(f"{N:,} positions GPS simulées".replace(",", " "))
for poly in (load_polygon(here), polygon_1000()):
    w, wo, inside = bench(poly, pts)
    n = len(poly.vertices) - 1
    print(f"- {poly.name} ({n} sommets) : avec bbox {w * 1e6 / N:.2f} µs/point | sans bbox {wo * 1e6 / N:.2f} µs/point "
          f"| gain x{wo / w:.1f} | {inside} points dans la zone")

tracemalloc.start()
poly = polygon_1000()
for la, lo in pts[:50_000]:
    poly.contains(la, lo)
cur, peak = tracemalloc.get_traced_memory()
print(f"Mémoire de pointe du moteur (polygone 1 000 sommets + traitement en flux) : {peak / 1024:.0f} Ko (limite tablette : 150 Mo)")
