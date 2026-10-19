import unittest
from scripts.build_universe_verification_queue import build, GATES

class VerificationQueueTests(unittest.TestCase):
    def test_priority_and_no_false_certification(self):
        report = {"model": "V8.8.1", "data_scope": {"normalized_issuers": 5, "priced_issuers": 5},
                  "formal_Aplus_count": 0, "all_model_row_summary": [
                      {"code": "9802", "name": "A", "scenario_upside_pct": 15},
                      {"code": "5439", "name": "B", "scenario_upside_pct": 110},
                      {"code": "1234", "name": "C", "scenario_upside_pct": None}]}
        result = build(report)
        self.assertEqual([r["code"] for r in result["queues"]], ["5439", "9802", "1234"])
        self.assertEqual(result["not_yet_in_model_count"], 2)
        self.assertFalse(result["official_full_universe_certified"])
        self.assertTrue(all(r["certification"] == "NOT_CERTIFIED" for r in result["queues"]))
        self.assertTrue(all(len(r["required_gates"]) == len(GATES) for r in result["queues"]))

    def test_duplicate_codes_rejected(self):
        with self.assertRaises(ValueError):
            build({"all_model_row_summary": [{"code": "1234"}, {"code": "1234"}]})

if __name__ == "__main__":
    unittest.main()
