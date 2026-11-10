"""Module 1 — Moteur ZFE (Geo).

Détecte, sans aucun réseau, si un camion entre dans une Zone à Faibles
Émissions (ZFE) décrite par un polygone.

Algorithme :
  1. Pré-filtre Bounding Box  : O(1) — rejette immédiatement les points
     hors du rectangle englobant du polygone (la grande majorité des points
     d'une journée de livraison).
  2. Ray Casting (Point in Polygon) : O(n) avec n = nombre de sommets —
     on trace une demi-droite vers l'est depuis le point et on compte les
     arêtes traversées : nombre impair = dedans, pair = dehors.
  3. Pré-alerte : distance au bord la plus courte (O(n)), pour prévenir le
     chauffeur AVANT l'entrée (500 m = 20 s à 90 km/h).

Aucune boucle imbriquée : la complexité reste O(n) par point GPS, compatible
avec la contrainte matérielle (Zebra ET40, pas d'algorithme en O(n²)).
"""
import json
import math
import time

from . import log

EARTH_RADIUS_M = 6_371_000.0
EPS = 1e-9   # tolérance numérique (~0,1 mm) commune à la bounding box et au test de bordure


class PolygonError(ValueError):
    """Polygone ZFE inutilisable (fichier absent, format ou géométrie invalide)."""


def _valid_coord(lat, lon):
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and not isinstance(lat, bool) and not isinstance(lon, bool)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)


class ZfePolygon:
    """Polygone ZFE prêt pour des tests rapides et répétés."""

    def __init__(self, points, name="ZFE"):
        self.name = name
        pts = []
        for i, p in enumerate(points):
            try:
                lat, lon = float(p["lat"]), float(p["lon"])
            except (KeyError, TypeError, ValueError):
                raise PolygonError(f"sommet n°{i + 1} invalide : {p!r}")
            if not _valid_coord(lat, lon):
                raise PolygonError(f"sommet n°{i + 1} hors limites : {p!r}")
            pts.append((lat, lon))
        # fermeture automatique si le dernier point n'est pas égal au premier
        if len(pts) >= 2 and pts[0] != pts[-1]:
            log.emit("WARN", f"Polygone {name} non fermé : fermeture automatique")
            pts.append(pts[0])
        if len(set(pts)) < 3:
            raise PolygonError("un polygone doit avoir au moins 3 sommets distincts")
        self.vertices = pts  # liste fermée : vertices[0] == vertices[-1]

        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        self.min_lat, self.max_lat = min(lats), max(lats)
        self.min_lon, self.max_lon = min(lons), max(lons)
        # projection locale (équirectangulaire) pour mesurer des distances en mètres
        self._ref_lat = math.radians((self.min_lat + self.max_lat) / 2.0)
        self._m_per_deg_lat = math.pi * EARTH_RADIUS_M / 180.0
        self._m_per_deg_lon = self._m_per_deg_lat * math.cos(self._ref_lat)

    # ---------- étape 1 : Bounding Box ----------
    def in_bbox(self, lat, lon, margin_m=0.0):
        dlat = margin_m / self._m_per_deg_lat + EPS
        dlon = margin_m / self._m_per_deg_lon + EPS
        return (self.min_lat - dlat <= lat <= self.max_lat + dlat
                and self.min_lon - dlon <= lon <= self.max_lon + dlon)

    # ---------- étape 2 : Ray Casting ----------
    def contains(self, lat, lon, use_bbox=True):
        """True si le point est dans le polygone (bord inclus, par prudence)."""
        if use_bbox and not self.in_bbox(lat, lon):   # O(1) : la plupart des points s'arrêtent ici
            return False
        y, x = lat, lon                          # y = latitude, x = longitude
        inside = False
        v = self.vertices
        for i in range(len(v) - 1):              # une seule boucle : O(n)
            yi, xi = v[i]
            yj, xj = v[i + 1]
            if self._on_segment(y, x, yi, xi, yj, xj):
                return True                      # sur le bord = considéré comme dedans
            # l'arête chevauche-t-elle la ligne horizontale du point ?
            # (règle semi-ouverte : évite de compter deux fois un sommet)
            if (yi > y) != (yj > y):
                x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
                if x < x_cross:                  # croisement à l'est du point
                    inside = not inside
        return inside

    @staticmethod
    def _on_segment(y, x, yi, xi, yj, xj):
        cross = (x - xi) * (yj - yi) - (y - yi) * (xj - xi)
        if abs(cross) > 1e-12:
            return False
        return (min(xi, xj) - EPS <= x <= max(xi, xj) + EPS
                and min(yi, yj) - EPS <= y <= max(yi, yj) + EPS)

    # ---------- étape 3 : distance au bord (pré-alerte) ----------
    def distance_to_edge_m(self, lat, lon):
        px = (lon - self.min_lon) * self._m_per_deg_lon
        py = (lat - self.min_lat) * self._m_per_deg_lat
        best = float("inf")
        v = self.vertices
        for i in range(len(v) - 1):              # une seule boucle : O(n)
            ax = (v[i][1] - self.min_lon) * self._m_per_deg_lon
            ay = (v[i][0] - self.min_lat) * self._m_per_deg_lat
            bx = (v[i + 1][1] - self.min_lon) * self._m_per_deg_lon
            by = (v[i + 1][0] - self.min_lat) * self._m_per_deg_lat
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            cx, cy = ax + t * dx, ay + t * dy
            best = min(best, math.hypot(px - cx, py - cy))
        return best


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise PolygonError(f"fichier introuvable : {path}")
    except json.JSONDecodeError as exc:
        raise PolygonError(f"JSON invalide dans {path} (ligne {exc.lineno}) : {exc.msg}")


def load_polygon(path, name="ZFE Lyon"):
    data = load_json(path)
    if not isinstance(data, list):
        raise PolygonError("le polygone doit être une liste de points {lat, lon}")
    return ZfePolygon(data, name=name)


class ZfeMonitor:
    """Machine à états OUT -> APPROCHE -> IN, qui ne journalise que les changements.

    Une alerte n'est émise qu'au changement d'état : pas de répétition qui
    fatiguerait le chauffeur (anti « alert fatigue »).
    """

    def __init__(self, polygon, prealert_m=500.0, speed_kmh=90.0):
        self.polygon = polygon
        self.prealert_m = prealert_m
        self.speed_ms = speed_kmh / 3.6
        self.state = "OUT"
        self.stats = {"points": 0, "rejected": 0, "bbox_skips": 0, "alerts": 0, "prealerts": 0}

    def process(self, point):
        """Traite un point GPS. Ne lève jamais d'exception : un point invalide est ignoré."""
        pid = point.get("id", "?") if isinstance(point, dict) else "?"
        try:
            lat, lon = float(point["lat"]), float(point["lon"])
            if not _valid_coord(lat, lon):
                raise ValueError("coordonnées hors limites")
        except KeyError as exc:
            return self._reject(pid, f"champ manquant : {exc.args[0]}")
        except (TypeError, ValueError) as exc:
            return self._reject(pid, f"donnée invalide : {exc}")

        self.stats["points"] += 1
        ts = point.get("timestamp", "--:--:--")
        t0 = time.perf_counter()
        near_box = self.polygon.in_bbox(lat, lon, margin_m=self.prealert_m)
        if not near_box:
            self.stats["bbox_skips"] += 1
            status, dist = "OUT", None
        elif self.polygon.contains(lat, lon):
            status, dist = "IN", 0.0
        else:
            dist = self.polygon.distance_to_edge_m(lat, lon)
            status = "APPROCHE" if dist <= self.prealert_m else "OUT"
        elapsed_us = (time.perf_counter() - t0) * 1e6

        how = "bbox (O(1))" if not near_box else "ray casting (O(n))"
        dist_txt = "" if dist is None or status == "IN" else f" | bord à {dist:,.0f} m".replace(",", " ")
        log.emit("GPS", f"#{pid} {ts} ({lat:.4f}, {lon:.4f}) -> {status}{dist_txt} | {how} en {elapsed_us:.0f} µs")

        expected = point.get("expected")
        if expected:
            exp_in = str(expected).upper().startswith("IN")
            got_in = status == "IN"
            if exp_in != got_in:
                log.emit("CHECK", f"#{pid} attendu « {expected} », calculé {status} : voir README (§ Écart sur le point 3)")

        self._transition(status, pid, ts, dist)
        return status

    def _reject(self, pid, reason):
        self.stats["rejected"] += 1
        log.emit("WARN", f"Point GPS #{pid} ignoré ({reason}) — le moteur continue")
        return None

    def _transition(self, status, pid, ts, dist):
        if status == self.state:
            return
        if status == "APPROCHE" and self.state == "OUT":
            self.stats["prealerts"] += 1
            secs = dist / self.speed_ms if self.speed_ms > 0 else float("inf")
            log.emit("PRE-ALERT ZFE", f"{self.polygon.name} à {dist:.0f} m (≈ {secs:.0f} s à {self.speed_ms * 3.6:.0f} km/h) — préparer l'itinéraire de contournement")
        elif status == "IN":
            self.stats["alerts"] += 1
            log.emit("ALERT ZFE", f"ENTRÉE dans {self.polygon.name} — point #{pid} à {ts} — événement horodaté enregistré localement")
        elif self.state == "IN":
            log.emit("INFO", f"Sortie de {self.polygon.name} — point #{pid} à {ts}")
        self.state = status


def run_zfe(polygon_path, gps_path, prealert_m=500.0, speed_kmh=90.0, realtime=False, speedup=10.0):
    """Exécute le module ZFE de bout en bout. Retourne les statistiques ou None si impossible."""
    log.emit("INFO", "=== Module 1 : moteur ZFE (Geo) — mode hors réseau ===")
    try:
        polygon = load_polygon(polygon_path)
    except PolygonError as exc:
        log.emit("ERROR", f"Polygone ZFE inutilisable : {exc}. Module ZFE désactivé, le reste du système continue.")
        return None
    log.emit("INFO", f"Polygone chargé : {len(polygon.vertices) - 1} sommets, bounding box "
                     f"lat [{polygon.min_lat}, {polygon.max_lat}] lon [{polygon.min_lon}, {polygon.max_lon}]")
    try:
        points = load_json(gps_path)
        if not isinstance(points, list):
            raise PolygonError("la trace GPS doit être une liste")
    except PolygonError as exc:
        log.emit("ERROR", f"Trace GPS illisible : {exc}. Aucun point traité.")
        return None

    monitor = ZfeMonitor(polygon, prealert_m=prealert_m, speed_kmh=speed_kmh)
    previous = None
    for point in points:
        if realtime and isinstance(point, dict):
            current = _seconds(point.get("timestamp"))
            if previous is not None and current is not None and current > previous:
                time.sleep((current - previous) / max(speedup, 0.1))
            previous = current if current is not None else previous
        if not isinstance(point, dict):
            monitor._reject("?", f"entrée non reconnue : {str(point)[:40]!r}")
            continue
        monitor.process(point)
    s = monitor.stats
    log.emit("INFO", f"Bilan ZFE : {s['points']} points traités, {s['rejected']} rejetés, "
                     f"{s['bbox_skips']} écartés par la bounding box, {s['prealerts']} pré-alerte(s), {s['alerts']} alerte(s)")
    return s


def _seconds(hms):
    try:
        h, m, s = (int(x) for x in str(hms).split(":"))
        return h * 3600 + m * 60 + s
    except (ValueError, TypeError):
        return None
