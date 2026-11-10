"""Nine finance Ke/g hurdle sensitivity: source integrity, grid and no PASS."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v8b7_0056_financial_hurdle_sensitivity import sensitivity,write

ROOT=Path(__file__).resolve().parents[1]/"tw-market-data"
INPUT=ROOT/"rankings/0056_financial_pb_hurdle_latest.json"


class Financial0056KegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Named-bank sign expectations belong to this exact archived price
        # context; a later market move is not a failed model control.
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.root=Path(cls.temp.name)
        fixture=Path(__file__).parent/'fixtures/0056_financial_hurdle_20261022.json'
        for rel,source in [('rankings/0056_financial_pb_hurdle_latest.json',fixture),
                           ('fundamentals/2026-Q2/TWSE_income.json',ROOT/'fundamentals/2026-Q2/TWSE_income.json'),
                           ('prices/2026-10-22.json',ROOT/'prices/2026-10-22.json')]:
            target=cls.root/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)

    def record(self):
        return json.loads((self.root/'rankings/0056_financial_pb_hurdle_latest.json').read_text(encoding="utf-8"))

    def test_nine_hurdle_scenarios_and_no_2027_target(self):
        x=sensitivity(self.record(),self.root)
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
        a=sensitivity(self.record(),self.root)
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
        a=sensitivity(original,self.root)
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
            sensitivity(r,self.root)
        r=self.record()
        r["financials_sorted_by_conditional_hurdle_gap"][0]["formal_Aplus"]=True
        with self.assertRaisesRegex(ValueError,"0056_FINANCIAL_ORIGINAL_AND_CERTIFICATION_FALSIFIED"):
            sensitivity(r,self.root)
        r=self.record()
        r["model_estimate_vintage"]="2026-10-22T09:00:00+08:00"
        with self.assertRaisesRegex(ValueError,"0056_FINANCIAL_HURDLE_FUTURE_SOURCE"):
            sensitivity(r,self.root)

    def test_deterministic_reports(self):
        a=sensitivity(self.record(),self.root)
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
        x=sensitivity(self.record(),self.root)
        print("BEGIN_0056_9_FINANCE_GRID="+json.dumps(dict(
            robust=[r["code"] for r in x["all_financials"]
                    if r["sign_invariant_positive_across_grid"]],
            rows=[dict(code=r["code"],positive=r["positive_gap_scenario_count"],
                       min=round(r["min_conditional_hurdle_gap_pp"],1),
                       max=round(r["max_conditional_hurdle_gap_pp"],1))
                  for r in x["all_financials"]]),ensure_ascii=False))

    def test_current_dated_hurdle_rejects_quote_revisions_without_refreezing(self):
        data=json.loads(INPUT.read_text(encoding='utf-8'))
        raw=(ROOT/'prices'/(data['official_close_date']+'.json')).read_bytes()
        current_sha=hashlib.sha256(raw).hexdigest()
        if current_sha!=data['official_price_sha256']:
            # A daily source refresh may occur after an earlier model-vintage
            # financial hurdle was published. It is NOT legal to change that
            # model's receipt or use the later price as an earlier quote.
            with self.assertRaisesRegex(ValueError,'0056_FINANCIAL_SOURCE_CLOSE_HASH_MISMATCH'):
                sensitivity(data,ROOT)
        else:
            result=sensitivity(data,ROOT)
            self.assertEqual(result['official_close_date'],data['official_close_date'])
            self.assertEqual(result['member_count'],9)
            self.assertEqual(result['formal_Aplus_count_added'],0)

    def test_future_or_noncanonical_price_date_never_reads_an_unbound_file(self):
        for day in ('2099-01-01','../outside','20261022'):
            data=self.record();data['official_close_date']=day
            with self.subTest(day=day),self.assertRaises(ValueError):
                sensitivity(data,self.root)


if __name__=="__main__":
    unittest.main()
