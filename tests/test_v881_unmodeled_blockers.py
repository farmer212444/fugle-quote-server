import unittest
from types import SimpleNamespace

from scripts.v881_unmodeled_blockers import classify

class TestRealModelEntryBlockers(unittest.TestCase):
    def fixture(self):
        data = SimpleNamespace(
            history={
                ("TWSE", "1234"): {"2026-Q2":{"name":"in model"}},
                ("TPEX", "5678"): {"2026-Q1":{"name":"missing latest"}},
                ("TWSE", "2345"): {"2026-Q1":{"name":"missing master"}, "2026-Q2":{"name":"missing master"}}
            },
            period="2026-Q2",
            required_periods=["2026-Q1", "2026-Q2"],
            prices={
                ("TWSE", "1234"): {"close":20,"volume_shares":1000000},
                ("TPEX", "5678"): {"close":20,"volume_shares":1000000},
                ("TWSE", "2345"): {"close":20,"volume_shares":1000000}
            },
            revenue={"1234":{},"5678":{},"2345":{}},
            evidence={"master":{"1234":{"issued_shares":1},"5678":{"issued_shares":1}}},
            errors=[]
        )
        report = {
            "model":"V8.8.1","estimate_vintage":"2026-10-19T14:00:00+08:00",
            "asof_price_date":"2026-10-16",
            "data_scope":{"normalized_issuers":3,"model_rows":1},
            "all_model_row_summary":[{"code":"1234"}]
        }
        return data, report

    def test_exact_gap_reconciliation(self):
        data, report = self.fixture()
        result = classify(data, report)
        self.assertEqual(result["unmodeled"], 2)
        self.assertEqual(result["primary_blocker_counts"]["NO_CURRENT_ELIGIBLE_QUARTER_INCOME"],1)
        self.assertEqual(result["primary_blocker_counts"]["NO_ELIGIBLE_SHARE_MASTER_INPUT"],1)
        self.assertFalse(result["certified_marketwide_ranking"])

    def test_never_invent_missing_share_master(self):
        data, report = self.fixture()
        result = classify(data, report)
        row = next(r for r in result["unmodeled_issuers"] if r["code"] == "2345")
        self.assertIn("NO_ELIGIBLE_SHARE_MASTER_INPUT", row["all_blockers"])
        self.assertFalse(row["formal_Aplus"])

    def test_financial_universe_change_blocks_output(self):
        data, report = self.fixture()
        report["data_scope"]["normalized_issuers"] = 4
        with self.assertRaisesRegex(ValueError,"NORMALIZED_SNAPSHOT_COUNT_MISMATCH"):
            classify(data, report)

    def test_low_price_not_mistaken_for_missing_quote(self):
        data, report = self.fixture()
        data.prices[("TWSE", "2345")]["close"]=5
        result=classify(data, report)
        row=next(x for x in result["unmodeled_issuers"] if x["code"]=="2345")
        self.assertIn("PRICE_BELOW_8_MODEL_RESEARCH_FLOOR",row["all_blockers"])

if __name__ == "__main__":
    unittest.main()
