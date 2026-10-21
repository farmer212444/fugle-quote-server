import copy
import datetime as dt
import statistics
import unittest

from scripts.v891_6206_gate_triage import check_report, render_md
from tw_model_v880.evidence import GATES


def sample():
    days = [(dt.date(2026, 10, 1) + dt.timedelta(days=i)).isoformat() for i in range(20)]
    price_date = days[-1]
    session_rows = [dict(date=d, turnover_ntd=10_000_000+i*100_000) for i,d in enumerate(days)]
    profile = {
        "code": "6206", "market": "TWSE",
        "pending_gates": list(GATES),
        "financial": {
            "normalized_income_8q_count": 8,
            "normalized_cashflow_8q_count": 8,
            "latest_primary_key_numbers_checked": True,
        },
        "capital": {"issued_share_master_present": True},
        "issuer_historical_market_data": {
            "twenty_day": {"sessions": 20, "first": days[0], "last": days[-1],
                            "median_turnover_ntd": statistics.median(x["turnover_ntd"] for x in session_rows)}
        },
    }
    val = {
        "issuer": "6206",
        "official_reference_price": {"date": price_date, "close": 100},
        "original_common_model": {
            "model_version": "V8.8.2",
            "model_vintage": "2026-10-20T08:13:00+08:00",
            "price_date": price_date,
            "Aplus": False,
            "existing_base_2027": {"eps": 10, "pe": 13, "target_price": 130, "price_upside_pct": 30},
        },
        "scenarios": {"base": {"parent_earnings_m": 1000, "diluted_share_proxy_m": 100,
                               "eps": 10, "pe": 13, "target_price": 130}},
        "source_receipts": [{"source_url": "https://www.flytech.com.tw/a.pdf", "pdf_sha256": "a"*64}],
    }
    ir = {"code": "6206", "presentations": [
        {"code": "6206", "source_url": "https://www.flytech.com.tw/a.pdf",
         "pdf_sha256": "a"*64, "original_company_filing_time_verified": False},
    ]}
    history = {"issuer": "6206", "market": "TWSE", "sessions": session_rows}
    return profile, val, ir, history


class FlytechGateTriageTest(unittest.TestCase):
    def test_complete_archived_coverage_is_not_certification(self):
        result = check_report(*sample())
        self.assertEqual(len(result["gates"]), 13)
        self.assertEqual(result["issuer_presentation_receipts_matched"], 1)
        self.assertTrue(result["twenty_day_turnover_reconciled"])
        self.assertFalse(result["formal_Aplus"])
        self.assertEqual(result["newly_certified_gates"], 0)
        self.assertTrue(all(x["formal_status"] == "PENDING" for x in result["gates"]))
        self.assertTrue(all(x["automatically_certified"] is False for x in result["gates"]))
        self.assertIn("6206", render_md(result))

    def test_newer_official_daily_session_replays_20day_6206_median(self):
        args = list(sample())
        last = args[3]["sessions"].pop()
        self.assertEqual(last["date"],args[1]["official_reference_price"]["date"])
        details=args[0]["issuer_historical_market_data"]
        details["status"]="SOURCE_CAPTURED_NOT_FULL_TRADABILITY"
        details["validated_archive_additions"]=1
        details["validated_archive_added_sessions"]=[dict(
            date=last["date"],turnover_ntd=last["turnover_ntd"],
            source="SHA_CHECKED_MARKET_DAILY_ARCHIVE"
        )]
        result=check_report(*args)
        self.assertTrue(result["twenty_day_turnover_reconciled"])
        self.assertEqual(result["individual_history_sessions"],19)
        self.assertEqual(result["merged_reference_daily_sessions"],1)
        self.assertEqual(result["all_reconciled_history_sessions"],20)
        row=next(g for g in result["gates"] if g["gate"]=="tradability")
        self.assertEqual(row["source_coverage"],"OBSERVED_PARTIAL")
        self.assertEqual(row["formal_status"],"PENDING")
        self.assertIn("追加核對官方全市場",render_md(result))

    def test_inaccurate_reference_turnover_cannot_claim_reconciled_20day(self):
        args=list(sample())
        last=args[3]["sessions"].pop()
        details=args[0]["issuer_historical_market_data"]
        details["validated_archive_additions"]=1
        details["validated_archive_added_sessions"]=[dict(
            date=last["date"],turnover_ntd=last["turnover_ntd"]*2,
            source="SHA_CHECKED_MARKET_DAILY_ARCHIVE")]
        with self.assertRaisesRegex(ValueError,"TWENTY_DAY_SOURCE_RECONCILIATION_FAILED"):
            check_report(*args)

    def test_invalid_pit_session_conflict_or_fake_count_rejected(self):
        for mode in ("future","duplicate","fake","conflict"):
            args=list(sample())
            last=args[3]["sessions"].pop()
            details=args[0]["issuer_historical_market_data"]
            details["validated_archive_additions"]=1
            details["validated_archive_added_sessions"]=[dict(
                date=last["date"],turnover_ntd=last["turnover_ntd"],
                source="SHA_CHECKED_MARKET_DAILY_ARCHIVE")]
            if mode=="future":
                details["validated_archive_added_sessions"][0]["date"]="2026-10-25"
            elif mode=="duplicate":
                details["validated_archive_added_sessions"][0]["date"]=args[3]["sessions"][0]["date"]
            elif mode=="fake":
                details["validated_archive_additions"]=2
            else:
                details["status"]="SOURCE_CONFLICT_REVIEW_REQUIRED"
            expected=("UNVERIFIED_REFERENCE_ADDITION_COUNT" if mode=="fake" else
                      "UNRECONCILED_20DAY_COVERAGE_CLAIM" if mode=="conflict" else
                      "INVALID_VALIDATED_REFERENCE_SESSION")
            with self.assertRaisesRegex(ValueError,expected):
                check_report(*args)

    def test_fast_threshold_and_stress_do_not_mint_formal_Aplus(self):
        result = check_report(*sample())
        risk = result["fast_decision"]
        self.assertEqual(risk["required_target_for_30pct"], 130)
        self.assertEqual(risk["minimum_eps_for_30pct_at_common_pe"], 10)
        self.assertEqual(risk["minimum_pe_for_30pct_at_common_eps"], 13)
        self.assertEqual(risk["max_reference_close_for_30pct_if_target_unchanged"], 100)
        self.assertFalse(risk["stresses"]["both_down_10pct"]["numerical_30pct_met"])
        self.assertEqual(risk["stresses"]["both_down_10pct"]["price"], 105.3)
        self.assertFalse(result["formal_Aplus"])
        self.assertIn("估值脆弱度", render_md(result))

    def test_common_eps_pe_mismatch_rejected(self):
        args = list(sample())
        args[1]["original_common_model"]["existing_base_2027"]["eps"] = 999
        with self.assertRaisesRegex(ValueError, "COMMON_EPS_PE_TARGET_INCONSISTENT"):
            check_report(*args)

    def test_mismatched_quote_date_is_rejected(self):
        args = list(sample())
        args[1]["official_reference_price"]["date"] = "2026-10-19"
        with self.assertRaisesRegex(ValueError, "PRICE_DATE_CONFLICT"):
            check_report(*args)

    def test_wrong_issuer_and_duplicate_gates_fail_closed(self):
        args = list(sample())
        args[0]["code"] = "9802"
        with self.assertRaisesRegex(ValueError, "WRONG_ISSUER"):
            check_report(*args)
        args = list(sample())
        args[0]["pending_gates"].append("tradability")
        with self.assertRaisesRegex(ValueError, "INVALID_PENDING_GATES"):
            check_report(*args)

    def test_fake_ir_digest_not_treated_as_source(self):
        args = list(sample())
        args[2]["presentations"][0]["pdf_sha256"] = "f"*64
        result = check_report(*args)
        self.assertEqual(result["issuer_presentation_receipts_matched"], 0)
        row = next(g for g in result["gates"] if g["gate"] == "management_promises")
        self.assertEqual(row["source_coverage"], "MISSING_OR_UNVERIFIED")
        self.assertEqual(row["formal_status"], "PENDING")

    def test_fake_liquidity_coverage_and_price_arithmetic_fail_closed(self):
        args = list(sample())
        for row in args[3]["sessions"]:
            row["turnover_ntd"] += 100_000
        with self.assertRaisesRegex(ValueError, "TWENTY_DAY_SOURCE_RECONCILIATION_FAILED"):
            check_report(*args)
        args = list(sample())
        args[1]["scenarios"]["base"]["target_price"] = 999
        with self.assertRaisesRegex(ValueError, "SCENARIO_PRICE_MISMATCH"):
            check_report(*args)


if __name__ == "__main__":
    unittest.main()
