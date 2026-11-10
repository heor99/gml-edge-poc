import json
import os
import unittest

from gml_edge.geo import PolygonError, ZfeMonitor, ZfePolygon, load_polygon

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


class TestRayCasting(unittest.TestCase):
    def setUp(self):
        self.poly = load_polygon(os.path.join(DATA, "lyon_polygon.json"))

    def test_trace_de_l_enonce(self):
        with open(os.path.join(DATA, "truck_gps.json"), encoding="utf-8") as f:
            pts = json.load(f)
        got = [self.poly.contains(p["lat"], p["lon"]) for p in pts]
        # le point 3 est géométriquement HORS du polygone (≈ 450 m au nord du bord) : voir README
        self.assertEqual(got, [False, False, False, True, True])

    def test_point_3_dans_la_zone_de_pre_alerte(self):
        d = self.poly.distance_to_edge_m(45.7850, 4.8050)
        self.assertTrue(400 < d < 500, d)

    def test_bord_et_sommet_comptes_dedans(self):
        self.assertTrue(self.poly.contains(45.7800, 4.8000))   # sommet
        self.assertTrue(self.poly.contains(45.7850, 4.8300))   # milieu de l'arête nord

    def test_bbox_ne_change_pas_le_resultat(self):
        for lat in [45.70 + i * 0.005 for i in range(25)]:
            for lon in [4.75 + j * 0.01 for j in range(20)]:
                self.assertEqual(self.poly.contains(lat, lon), self.poly.contains(lat, lon, use_bbox=False))

    def test_polygone_concave(self):
        # « U » : le creux du U est dehors, les branches sont dedans
        u = ZfePolygon([{"lat": 0, "lon": 0}, {"lat": 0, "lon": 3}, {"lat": 3, "lon": 3}, {"lat": 3, "lon": 2},
                        {"lat": 1, "lon": 2}, {"lat": 1, "lon": 1}, {"lat": 3, "lon": 1}, {"lat": 3, "lon": 0}])
        self.assertTrue(u.contains(2, 0.5))
        self.assertFalse(u.contains(2, 1.5))
        self.assertTrue(u.contains(0.5, 1.5))

    def test_polygone_ouvert_ferme_automatiquement(self):
        p = load_polygon(os.path.join(DATA, "corrupted", "polygon_open.json"))
        self.assertEqual(p.vertices[0], p.vertices[-1])

    def test_polygone_invalide(self):
        with self.assertRaises(PolygonError):
            ZfePolygon([{"lat": 45, "lon": 4}, {"lat": 46, "lon": 4}])
        with self.assertRaises(PolygonError):
            load_polygon(os.path.join(DATA, "absent.json"))


class TestMonitor(unittest.TestCase):
    def test_points_invalides_sans_exception(self):
        m = ZfeMonitor(load_polygon(os.path.join(DATA, "lyon_polygon.json")))
        for bad in [{"id": 1}, {"id": 2, "lat": "N/A", "lon": 4.8}, {"id": 3, "lat": 145, "lon": 4.8}, {"lat": None, "lon": None}]:
            self.assertIsNone(m.process(bad))
        self.assertEqual(m.stats["rejected"], 4)

    def test_une_seule_alerte_par_entree(self):
        m = ZfeMonitor(load_polygon(os.path.join(DATA, "lyon_polygon.json")))
        for _ in range(5):
            m.process({"id": 1, "lat": 45.76, "lon": 4.8357})
        self.assertEqual(m.stats["alerts"], 1)


if __name__ == "__main__":
    unittest.main()
