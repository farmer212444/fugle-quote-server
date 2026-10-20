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
            "existing_base_2027": {"target_price": 130, "price_upside_pct": 30},
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
        for row in args[3]["sessions"]:\n            row["turnover_ntd"] += 100_000
        with self.assertRaisesRegex(ValueError, "TWENTY_DAY_SOURCE_RECONCILIATION_FAILED"):
            check_report(*args)
        args = list(sample())
        args[1]["scenarios"]["base"]["target_price"] = 999
        with self.assertRaisesRegex(ValueError, "SCENARIO_PRICE_MISMATCH"):
            check_report(*args)


if __name__ == "__main__":
    unittest.main()
