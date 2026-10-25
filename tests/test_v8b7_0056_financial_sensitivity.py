"""Nine finance Ke/g hurdle sensitivity: source integrity, grid and no PASS."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v8b7_0056_financial_hurdle_sensitivity import sensitivity,write

ROOT=Path(__file__).resolve().parents[1]/"tw-market-data"
INPUT=ROOT/"rankings/0056_financial_pb_hurdle_latest.json"


class Financial0056KegTests(unittest.TestCase):
    def record(self):
        return json.loads(INPUT.read_text(encoding="utf-8"))

    def test_nine_hurdle_scenarios_and_no_2027_target(self):
        x=sensitivity(self.record(),ROOT)
        self.assertEqual(x["member_count"],9)
        self.assertEqual(x["grid_scenario_count"],9)
        self.assertTrue(x["no_probability_or_scenario_calibration"])
        self.assertTrue(x["no_2027_fair_price_estimated"])
        self.assertTrue(x["no_full_50_stock_return_ranking"])
        self.assertTrue(x["original_0056_nonfinancial_top10_unchanged"])
        self.assertEqual(x["formal_Aplus_count_added"],0)
        for row in x["all_financials"]:
            self.assertEqual(len(row["stress_cases"]),9)
            self.assertTrue(row["issuer_original_BVPS_not_yet_verified"])
            self.assertFalse(row["original_2027_price_target_available"])
            self.assertFalse(row["formal_Aplus"])
            values=[c["gap_vs_h1_proxy_pp"] for c in row["stress_cases"]]
            self.assertAlmostEqual(min(values),row["min_conditional_hurdle_gap_pp"])
            self.assertAlmostEqual(max(values),row["max_conditional_hurdle_gap_pp"])
            self.assertEqual(row["positive_gap_scenario_count"],sum(v>0 for v in values))
            self.assertEqual(row["positive_gap_scenario_count"]+
                             row["negative_gap_scenario_count"]+
                             row["zero_gap_scenario_count"],9)

    def test_megafins_keep_a_positive_gap_over_specified_grid(self):
        a=sensitivity(self.record(),ROOT)
        z={r["code"]:r for r in a["all_financials"]}
        self.assertEqual(z["2886"]["positive_gap_scenario_count"],9)
        self.assertEqual(z["2891"]["positive_gap_scenario_count"],9)
        self.assertAlmostEqual(z["2886"]["min_conditional_hurdle_gap_pp"],0.505,delta=.12)
        self.assertAlmostEqual(z["2891"]["min_conditional_hurdle_gap_pp"],0.18,delta=.12)
        self.assertEqual(z["2883"]["positive_gap_scenario_count"],5)
        self.assertFalse(z["2883"]["sign_invariant_positive_across_grid"])

    def test_base_matches_prior_hurdle_exactly_and_price_not_changed(self):
        original=self.record()
        copied=copy.deepcopy(original)
        a=sensitivity(original,ROOT)
        self.assertEqual(original,copied)
        prior={x["code"]:x for x in original["financials_sorted_by_conditional_hurdle_gap"]}
        for r in a["all_financials"]:
            scenario=next(x for x in r["stress_cases"] if x["Ke_pct"]==10 and x["g_pct"]==3)
            self.assertAlmostEqual(scenario["required_roe_pct"],
                                   prior[r["code"]]["illustrative_required_sustainable_roe_pct"])
            self.assertAlmostEqual(scenario["gap_vs_h1_proxy_pp"],
                                   prior[r["code"]]["illustrative_required_roe_minus_h1_proxy_pp"])

    def test_tampering_with_issuer_or_equity_source_does_not_pass(self):
        r=self.record()
        r["financials_sorted_by_conditional_hurdle_gap"][0]["book_per_share_2026q2_ntd"]+=1
        with self.assertRaisesRegex(ValueError,"0056_FINANCIAL_BASE_ROE_HURDLE_ARITHMETIC_INCONSISTENT"):
            sensitivity(r,ROOT)
        r=self.record()
        r["financials_sorted_by_conditional_hurdle_gap"][0]["formal_Aplus"]=True
        with self.assertRaisesRegex(ValueError,"0056_FINANCIAL_ORIGINAL_AND_CERTIFICATION_FALSIFIED"):
            sensitivity(r,ROOT)
        r=self.record()
        r["model_estimate_vintage"]="2026-10-22T09:00:00+08:00"
        with self.assertRaisesRegex(ValueError,"0056_FINANCIAL_HURDLE_FUTURE_SOURCE"):
            sensitivity(r,ROOT)

    def test_deterministic_reports(self):
        a=sensitivity(self.record(),ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"stress.json"
            write(a,path)
            write(a,path.with_suffix(".md"))
            raw=path.read_bytes()
            write(a,path)
            self.assertEqual(raw,path.read_bytes())
            md=path.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("九組情境",md)
            self.assertIn("中信金",md)
            self.assertIn("不是確定高估",md)

    def test_log_summary(self):
        x=sensitivity(self.record(),ROOT)
        print("BEGIN_0056_9_FINANCE_GRID="+json.dumps(dict(
            robust=[r["code"] for r in x["all_financials"]
                    if r["sign_invariant_positive_across_grid"]],
            rows=[dict(code=r["code"],positive=r["positive_gap_scenario_count"],
                       min=round(r["min_conditional_hurdle_gap_pp"],1),
                       max=round(r["max_conditional_hurdle_gap_pp"],1))
                  for r in x["all_financials"]]),ensure_ascii=False))


if __name__=="__main__":
    unittest.main()
