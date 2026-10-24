import unittest
from scripts import research_2027_top3_bridge as m

class TopThreeOperatingBridgeTests(unittest.TestCase):
    def test_disclosed_H1_eps(self):
        self.assertEqual([m.DATA[x]["eps"] for x in ("2317","2376","3305")],
                         [7.84,17.73,3.84])
    def test_scenario_arithmetic(self):
        x=m.price_scenario(10,20,100)
        self.assertEqual(x["target"],200.0)
        self.assertEqual(x["upside_pct"],100.0)
    def test_no_assumed_execution_of_GDR(self):
        d=m.DATA["2376"]
        self.assertGreater(d["gdr_approved_max"],d["gdr_approved_min"])
        self.assertEqual(d["gdr_approved_max"],50000000)
    def test_cfo_and_expected_credit_impairment_alert(self):
        d=m.DATA["3305"]
        self.assertLess(d["h1_cfo_k"],0)
        self.assertGreater(d["h1_ecl_k"]/d["op"],.25)
        self.assertEqual(d["company_9m_revenue_explanation"],"原料價格上漲")
    def test_no_forward_outcome_claim(self):
        # The independently reconstructed EPS remains a conditional 2027 model.
        self.assertEqual(set(m.DATA),{"2317","2376","3305"})

if __name__=="__main__":
    unittest.main()
