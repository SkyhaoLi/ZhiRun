import json
import unittest
from pathlib import Path

import joblib


ROOT = Path(__file__).resolve().parents[1]


class PolicyV2Tests(unittest.TestCase):
    def test_model_package_and_metrics(self):
        package = joblib.load(ROOT / "models" / "hohhot_fertigation_policy_v2.joblib")
        self.assertIn("pipeline", package)
        self.assertEqual(package["targets"], ["water_m3_mu", "n_kg_mu", "p2o5_kg_mu", "k2o_kg_mu"])
        metrics = json.loads((ROOT / "models" / "policy_v2_metrics.json").read_text(encoding="utf-8"))
        self.assertGreater(metrics["test"]["water_m3_mu"]["r2"], 0.9)
        self.assertGreater(metrics["test"]["irrigation_decision_accuracy"], 0.9)
        self.assertTrue(metrics["not_a_yield_model"])


if __name__ == "__main__":
    unittest.main()
