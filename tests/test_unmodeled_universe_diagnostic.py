import unittest
from scripts.diagnose_unmodeled_universe import summarize

class GapDiagnosticTest(unittest.TestCase):
    def test_counts_and_fail_closed(self):
        q = {"model": "V8.8.1", "not_yet_in_model_count": 2,
             "normalized_not_yet_modeled": [{"market": "TWSE", "code": "1111"}, {"market": "TPEX", "code": "2222"}],
             "queues": [{"code": "3333"}]}
        result = summarize(q)
        self.assertEqual(result["unmodeled"], 2)
        self.assertFalse(result["official_PIT_master_reconciled"])
        self.assertEqual(result["unmodeled_by_market"], {"TPEX": 1, "TWSE": 1})
    def test_missing_count_rejected(self):
        with self.assertRaises(ValueError):
            summarize({"not_yet_in_model_count": 1, "normalized_not_yet_modeled": []})
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            summarize({"not_yet_in_model_count": 2, "normalized_not_yet_modeled": [{"market":"TWSE","code":"1234"},{"market":"TWSE","code":"1234"}]})
if __name__ == "__main__":
    unittest.main()
