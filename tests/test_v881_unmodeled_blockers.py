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
                ("TWSE", "1234"): {"close":20,"volume_shares":1000000,"turnover_ntd":20000000},
                ("TPEX", "5678"): {"close":20,"volume_shares":1000000,"turnover_ntd":20000000},
                ("TWSE", "2345"): {"close":20,"volume_shares":1000000,"turnover_ntd":20000000}
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

    def test_post_entry_failure_is_not_counted_as_a_comparable_valuation(self):
        data,report=self.fixture()
        report['all_model_row_summary']=[dict(code='1234',status='TAX_PARENT_EARNINGS_COMPONENTS_MISSING',rankable=False),
            dict(code='2345',status='CERTIFICATION_PENDING',rankable=False,exclusion_reasons=['PE_SAMPLE_INSUFFICIENT']),
            dict(code='5678',status='CERTIFICATION_PENDING',rankable=True)]
        report['data_scope'].update(model_rows=3,market_research_rankable=1)
        report['formal_decisions_evaluated']=2
        result=classify(data,report)
        self.assertEqual(result['entry_precheck_eligible_count'],3)
        self.assertEqual(result['modeled'],1);self.assertEqual(result['unmodeled'],2)
        self.assertEqual(result['quality_decision_evaluated_count'],2)
        self.assertEqual(result['primary_blocker_counts']['TAX_PARENT_EARNINGS_COMPONENTS_MISSING'],1)
        self.assertEqual(result['primary_blocker_counts']['PE_SAMPLE_INSUFFICIENT'],1)

    def test_tracked_issuer_outside_financial_universe_does_not_inflate_coverage(self):
        data,report=self.fixture();data.prices[('TWSE','9999')]={'close':100}
        report['all_model_row_summary']=[dict(code='1234',rankable=True,status='CERTIFICATION_PENDING'),
            dict(code='9999',rankable=False,status='CURRENT_FINANCIAL_STATEMENT_MISSING')]
        report['data_scope'].update(model_rows=2,market_research_rankable=1)
        result=classify(data,report)
        self.assertEqual(result['tracked_rows_outside_financial_universe'],1)
        self.assertEqual(result['tracked_comparable_valuation_count'],1)
        self.assertEqual(result['modeled']+result['unmodeled'],3)

    def test_partial_or_forged_valuation_summary_rejected(self):
        data,report=self.fixture();report['data_scope']['market_research_rankable']=1
        with self.assertRaisesRegex(ValueError,'VALUATION_STATUS_MISSING'):classify(data,report)
        report['all_model_row_summary'][0].update(rankable=False,status='CERTIFICATION_PENDING')
        with self.assertRaisesRegex(ValueError,'VALUATION_COUNT_MISMATCH'):classify(data,report)

if __name__ == "__main__":
    unittest.main()
