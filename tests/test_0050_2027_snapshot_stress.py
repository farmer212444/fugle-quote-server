"""Synthetic-only verification of hypothetical EPS/PE haircut mechanics."""
import unittest
from scripts.research_0050_2027_snapshot import (
    mechanical_sensitivity, PUBLIC_EPS_OBSERVATIONS
)

class ScenarioStressTests(unittest.TestCase):
    def test_haircut_risks_and_threshold(self):
        x=mechanical_sensitivity(245,26.966569351132843*16.235,26.966569351132843,16.235)
        self.assertAlmostEqual(x["upside_eps_pe_both_minus_20_pct"],14.36,places=1)
        self.assertFalse(x["can_keep_30_pct_upside_under_20_20_stress"])
        self.assertAlmostEqual(x["minimum_2027_eps_for_30_pct_upside_at_base_pe"],
                               1.3*245/16.235,places=2)

    def test_reject_mismatched_base(self):
        with self.assertRaisesRegex(ValueError,"BASE_TARGET_NOT_EQUAL"):
            mechanical_sensitivity(100,150,10,10)
        with self.assertRaisesRegex(ValueError,"INVALID_PRICE"):
            mechanical_sensitivity(0,150,10,15)

    def test_real_obs_never_certifies_predictions(self):
        for code,obs in PUBLIC_EPS_OBSERVATIONS.items():
            self.assertFalse(obs["audited"])
            self.assertTrue(obs["source_url"].startswith("https://"))
            self.assertIn(obs["period"],("2026-H1","2026-9M"))
            self.assertIn(code,("2317","2382","6505"))

if __name__=="__main__":
    unittest.main()
