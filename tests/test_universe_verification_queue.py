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

    def test_normalized_unmodeled_identities_are_explicit_and_fail_closed(self):
        report = {"data_scope": {"normalized_issuers": 3}, "all_model_row_summary": [
            {"market": "TWSE", "code": "1111", "scenario_upside_pct": 40}]}
        universe = [
            {"market": "TWSE", "code": "1111", "name": "A"},
            {"market": "TWSE", "code": "2222", "name": "B"},
            {"market": "TPEX", "code": "3333", "name": "C"}]
        result = build(report, universe, [{"path": "x", "sha256": "abc"}])
        self.assertEqual(result["not_yet_in_model_count"], 2)
        self.assertEqual([x["code"] for x in result["normalized_not_yet_modeled"]], ["3333", "2222"])
        self.assertTrue(all(x["certification"] == "NOT_CERTIFIED" for x in result["normalized_not_yet_modeled"]))
        self.assertFalse(result["official_full_universe_certified"])
        self.assertEqual(len(result["normalized_universe_identity_receipts"]), 1)

    def test_normalized_universe_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            build({"data_scope": {"normalized_issuers": 2}, "all_model_row_summary": []},
                  [{"market": "TWSE", "code": "1111"}])

    def test_duplicate_codes_rejected(self):
        with self.assertRaises(ValueError):
            build({"all_model_row_summary": [{"code": "1234"}, {"code": "1234"}]})

if __name__ == "__main__":
    unittest.main()
