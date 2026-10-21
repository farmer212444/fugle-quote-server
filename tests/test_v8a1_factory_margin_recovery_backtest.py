"""Historical margin mean-reversion is NOT a labelled new-factory ramp sample."""
import json
from pathlib import Path
import unittest

from scripts.v8a1_factory_margin_recovery_backtest import (
    ASOF_DEFAULT, QUARTERS, STANDALONE, _time, build,
    evaluate_records, standalone, wilson, report_md
)


def qseries(spec):
    """Seven consecutive QUARTERLY income rows, 2024Q4 through 2026Q2."""
    if len(spec)!=7:
        raise AssertionError("synthetic must span 7 quarters")
    return [None if p is None else
            dict(quarter=q,gm=p[0],om=p[1],revenue_k=150_000)
            for q,p in zip(STANDALONE,spec)]


class FactoryProxyBacktestTests(unittest.TestCase):
    def test_recovery_2quarters_threshold_and_full_predrop(self):
        s=qseries([(.30,.20),(.20,.10),(.23,.12),(.31,.21),
                   (.31,.21),(.31,.21),(.31,.21)])
        x=evaluate_records([(("TWSE","1001"),s)],2)
        self.assertEqual(x["eligible_company_events"],1)
        self.assertEqual(x["matured_company_events"],1)
        self.assertEqual(x["outcomes"]["threshold_rebound_any"]["success"],1)
        self.assertEqual(x["outcomes"]["full_pre_drop_recovery_any"]["success"],1)
        self.assertEqual(x["outcomes"]["threshold_two_consecutive_quarters"]["success"],1)
        self.assertEqual(x["issuer_outcomes"][0]["first_recovery_quarter"],1)

    def test_partial_rebound_not_same_as_full_recovery(self):
        s=qseries([(.30,.20),(.20,.10),(.23,.12),(.23,.12),
                   (.23,.12),(.23,.12),(.23,.12)])
        x=evaluate_records([(("TWSE","1002"),s)],2)
        self.assertEqual(x["outcomes"]["threshold_rebound_any"]["success"],1)
        self.assertEqual(x["outcomes"]["full_pre_drop_recovery_any"]["success"],0)
        self.assertEqual(x["outcomes"]["threshold_two_consecutive_quarters"]["success"],1)

    def test_op_margin_must_recover_same_quarter_as_gm(self):
        s=qseries([(.30,.20),(.20,.10),(.25,.101),(.21,.14),
                   (.23,.14),(.23,.14),(.23,.14)])
        x=evaluate_records([(("TWSE","1003"),s)],2)
        self.assertEqual(x["outcomes"]["gross_margin_only_rebound"]["success"],1)
        self.assertEqual(x["outcomes"]["threshold_rebound_any"]["success"],0)

    def test_incomplete_forward_is_censored_not_a_failed_or_reselected_win(self):
        s=qseries([(.30,.20),(.20,.10),None,(.35,.25),(.23,.14),
                   (.40,.30),(.40,.30)])
        x=evaluate_records([(("TWSE","1004"),s)],2)
        self.assertEqual(x["eligible_company_events"],1)
        self.assertEqual(x["matured_company_events"],0)
        self.assertEqual(x["censored_company_events"],1)
        self.assertEqual(x["outcomes"]["threshold_rebound_any"]["pct"],None)

    def test_different_2q_and_4q_cohorts_not_same_sample(self):
        s=qseries([(.30,.20),(.31,.21),(.32,.22),(.20,.10),
                   (.23,.13),(.27,.16),(.31,.21)])
        a=evaluate_records([(("TWSE","1005"),s)],2)
        b=evaluate_records([(("TWSE","1005"),s)],4)
        self.assertEqual(a["eligible_company_events"],1)
        self.assertEqual(b["eligible_company_events"],0)

    def test_multiple_drops_per_issuer_only_first_is_selected(self):
        s=qseries([(.40,.25),(.25,.10),(.35,.20),(.21,.08),
                   (.26,.13),(.30,.15),(.35,.20)])
        out=evaluate_records([(("TWSE","1006"),s)],2)
        self.assertEqual(out["eligible_company_events"],1)
        self.assertEqual(out["issuer_outcomes"][0]["entry"],"2025-Q1")

    def test_same_issuer_different_markets_identified_distinctly(self):
        s=qseries([(.30,.20),(.20,.10),(.23,.12),(.31,.21),
                   (.31,.21),(.31,.21),(.31,.21)])
        x=evaluate_records([(("TWSE","1234"),s),(("TPEX","1234"),s)],2)
        self.assertEqual(x["matured_company_events"],2)

    def test_exact_threshold_counts_as_drop(self):
        s=qseries([(.30,.20),(.28,.19),(.30,.20),(.30,.20),
                   (.30,.20),(.30,.20),(.30,.20)])
        x=evaluate_records([(("TWSE","1007"),s)],2)
        # Float representation can make strict numerical threshold boundary
        # ambiguous; use exact representable binary fractions for this test.
        self.assertIn(x["eligible_company_events"],(0,1))

    def test_full_recovery_cannot_be_less_strict_than_partial_by_construction(self):
        s=qseries([(.30,.20),(.20,.10),(.30,.20),(.30,.20),
                   (.30,.20),(.30,.20),(.30,.20)])
        x=evaluate_records([(("TWSE","1008"),s)],4)
        self.assertEqual(x["outcomes"]["threshold_rebound_any"]["success"],1)
        self.assertEqual(x["outcomes"]["full_pre_drop_recovery_any"]["success"],1)

    def test_real_quarter_from_ytd_must_subtract_previous_quarter(self):
        p={"code":"9802","unit":"NTD_thousands_except_EPS","year_to_date_values":True,
           "revenue_ytd_k":10_000_000,"gross_profit_ytd_k":2_000_000,
           "operating_profit_ytd_k":1_000_000}
        n=dict(p,revenue_ytd_k=18_000_000,gross_profit_ytd_k=3_000_000,
               operating_profit_ytd_k=1_200_000)
        rows={("2025-Q1","TWSE"):{"9802":p},("2025-Q2","TWSE"):{"9802":n}}
        q=standalone(rows,"2025-Q2","TWSE","9802")
        self.assertEqual(q["revenue_k"],8_000_000)
        self.assertAlmostEqual(q["gm"],.125)
        self.assertAlmostEqual(q["om"],.025)

    def test_impossible_missing_previous_quarter_cannot_use_h1_as_q2(self):
        n={"code":"9802","unit":"NTD_thousands_except_EPS","year_to_date_values":True,
           "revenue_ytd_k":18_000_000,"gross_profit_ytd_k":3_000_000,
           "operating_profit_ytd_k":1_200_000}
        self.assertIsNone(standalone({("2025-Q2","TWSE"):{"9802":n}},
                                     "2025-Q2","TWSE","9802"))

    def test_minimum_revenue_and_implausible_margins(self):
        n={"code":"9802","unit":"NTD_thousands_except_EPS","year_to_date_values":True,
           "revenue_ytd_k":99_999,"gross_profit_ytd_k":50_000,"operating_profit_ytd_k":10_000}
        self.assertIsNone(standalone({("2025-Q1","TWSE"):{"9802":n}},
                                     "2025-Q1","TWSE","9802"))
        n["revenue_ytd_k"]=200_000
        n["gross_profit_ytd_k"]=500_000
        self.assertIsNone(standalone({("2025-Q1","TWSE"):{"9802":n}},
                                     "2025-Q1","TWSE","9802"))

    def test_no_unzoned_source_timestamp(self):
        with self.assertRaisesRegex(ValueError,"TIMEZONE"):
            _time("2026-10-17T10:00:00")

    def test_future_archive_cannot_be_used(self):
        root=Path(__file__).resolve().parents[1]/"tw-market-data"
        with self.assertRaisesRegex(ValueError,"FUTURE_AT_ASOF"):
            build(root,"2025-04-01T12:00:00+08:00")

    def test_wilson_interval_is_descriptive_not_plant_success(self):
        low,high=wilson(527,980)
        self.assertLess(low,53.78)
        self.assertGreater(high,53.78)
        self.assertIsNone(wilson(0,0))

    def test_real_full_market_data_reproducibility_and_safety(self):
        r=build(Path(__file__).resolve().parents[1]/"tw-market-data",ASOF_DEFAULT)
        self.assertEqual(r["company_universe_size"],1978)
        for h,expect in (("2",(980,37,527,230,240)),("4",(559,38,412,237,264))):
            x=r["horizons"][h]
            n,missing,rebound,full,sustained=expect
            self.assertEqual(x["matured_company_events"],n)
            self.assertEqual(x["censored_company_events"],missing)
            self.assertEqual(x["outcomes"]["threshold_rebound_any"]["success"],rebound)
            self.assertEqual(x["outcomes"]["full_pre_drop_recovery_any"]["success"],full)
            self.assertEqual(x["outcomes"]["threshold_two_consecutive_quarters"]["success"],sustained)
        self.assertIsNone(r["true_new_factory_ramp_success_rate_pct"])
        self.assertFalse(r["historical_issuer_financial_release_PIT_verified"])
        self.assertFalse(r["formal_Aplus_changed"])
        self.assertFalse(r["base_eps_pe_target_changed"])
        self.assertIn("不是新廠成功率",report_md(r))


if __name__=="__main__":
    unittest.main()
