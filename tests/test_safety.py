import json
import os
import tempfile
import unittest

from gml_edge.safety import analyse, run_safety

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


class TestSafety(unittest.TestCase):
    def test_freinage_de_l_enonce(self):
        r = analyse(os.path.join(DATA, "accelerometer_data.csv"))
        self.assertEqual(r["counts"]["HARSH_BRAKING"], 1)
        ev = r["events"][0]
        self.assertEqual(ev["data_row"], 6)
        self.assertEqual(ev["peak_raw_ms2"], -3.45)
        self.assertEqual(r["score"]["value"], 90)

    def test_csv_corrompu_sans_exception(self):
        r = analyse(os.path.join(DATA, "corrupted", "accelerometer_corrupted.csv"))
        self.assertEqual(r["samples"]["rejected"], 5)
        self.assertEqual(r["counts"]["HARSH_BRAKING"], 1)

    def test_100hz_chocs_isoles_ignores(self):
        path = os.path.join(DATA, "synthetic_100hz.csv")
        if not os.path.exists(path):
            self.skipTest("lancer d'abord tools/generate_synthetic_100hz.py")
        r = analyse(path)
        self.assertEqual(r["counts"]["HARSH_BRAKING"], 1)        # nid-de-poule à -6 m/s² ignoré
        self.assertEqual(r["counts"]["HARSH_ACCELERATION"], 0)   # dos-d'âne à +5 m/s² ignoré
        self.assertEqual(r["counts"]["HARSH_CORNERING"], 1)
        self.assertAlmostEqual(r["events"][0]["start_ts"], 1678880040.0, delta=0.3)

    def test_fichier_vide_ou_absent(self):
        for name in ["corrupted/empty.csv", "nexiste_pas.csv"]:
            r = analyse(os.path.join(DATA, name))
            self.assertIsNone(r["score"]["value"])
            self.assertFalse(r["insurance"]["bonus_eligible"])

    def test_daily_score_json_valide(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "daily_score.json")
            run_safety(os.path.join(DATA, "accelerometer_data.csv"), out)
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            for key in ["vehicle_id", "date", "samples", "events", "counts", "score", "insurance"]:
                self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
