import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.v895_etf_accumulation import analyze, render, run, _snapshot, _interval

ASOF = "2026-10-20T23:00:00+08:00"
PRICES = [
    dict(date="2026-10-20", code="6206", turnover_ntd=100_000_000),
    dict(date="2026-10-20", code="9802", turnover_ntd=20_000_000),
]
SESSIONS = ["2026-10-19", "2026-10-20"]


def pcf(date, units=10000000, *, etf="0050", published=None, weight=.1,
        basis="ISSUER_PCF_BASKET", substitute=False, index_family="TAIWAN50"):
    return dict(etf_code=etf, issuer="TEST SYNTHETIC NOT REAL",
                fund_type="TAIWAN_EQUITY_UNLEVERAGED",
                weight_basis=basis, index_family=index_family,
                source_url="https://example.invalid/synthetic-pcf",
                raw_sha256="a"*64, issuer_source_verified=True,
                units_asof_date=date, basket_effective_date=(__import__("datetime").date.fromisoformat(date)+__import__("datetime").timedelta(days=1)).isoformat(),
                published_at=published or date+"T17:30:00+08:00",
                units_outstanding=units, nav_per_unit_twd=50,
                constituents=[
                    dict(code="6206", weight=weight, cash_substitution=substitute),
                    dict(code="9802", weight=.2, cash_substitution=False)
                ])


class EtfEvidenceTests(unittest.TestCase):
    def test_no_pcf_is_blocked_not_fake_top20(self):
        r = analyze([], SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual(r["status"], "BLOCKED_MISSING_VERIFIED_ETF_PCF")
        self.assertEqual(r["top20"], [])
        self.assertFalse(r["stock_buy_execution_verified"])
        self.assertIn("尚無可驗證", render(r))

    def test_never_treat_creation_as_actual_stock_buying(self):
        rows = [pcf("2026-10-19"), pcf("2026-10-20", units=10200000)]
        r = analyze(rows, SESSIONS, PRICES, "2026-10-20", asof=ASOF,
                    research=dict(formal_Aplus_count=0, formal_Aplusplus_count=0))
        by_code = {x["code"]: x for x in r["top20"]}
        # 200,000 ETF units x NT$50 previous NAV x 10% PCF basket weight.
        self.assertEqual(by_code["6206"]["estimated_1d_exposure_ntd"], 1000000)
        self.assertEqual(by_code["6206"]["one_day_exposure_to_market_turnover"], .01)
        self.assertEqual(by_code["9802"]["estimated_1d_exposure_ntd"], 2000000)
        self.assertFalse(by_code["6206"]["actual_institutional_net_buy_verified"])
        self.assertEqual(r["etf_count_with_full_5d"], 0)
        self.assertIsNone(by_code["6206"]["estimated_5d_exposure_ntd"])
        self.assertEqual(r["formal_Aplus_count_unchanged"], 0)
        self.assertFalse(r["model_pe_or_eps_changed"])

    def test_outflow_creates_negative_exposure_proxy(self):
        rows = [pcf("2026-10-19"), pcf("2026-10-20", units=9900000)]
        r = analyze(rows, SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual({x["code"]: x["estimated_1d_exposure_ntd"] for x in r["top20"]},
                         {"6206": -500000, "9802": -1000000})

    def test_future_published_data_rejected_even_same_effective_date(self):
        rows = [pcf("2026-10-19"), pcf("2026-10-20", published="2026-10-21T09:00:00+08:00")]
        r = analyze(rows, SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual(r["status"], "BLOCKED_MISSING_COMPARABLE_ETF_SESSIONS")
        self.assertTrue(any(x["reason"] == "ETF_FUTURE_PIT_INPUT" for x in r["excluded_records"]))

    def test_future_input_with_other_timezone_is_blocked(self):
        rows = [pcf("2026-10-19"), pcf("2026-10-20",
                                       published="2026-10-20T15:01:00Z")]
        r = analyze(rows, SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual(r["etf_count_with_at_least_1d"], 0)

    def test_no_timezone_no_issuer_proof_and_bad_hash_rejected(self):
        for update in [
            dict(published_at="2026-10-20T10:00:00"),
            dict(issuer_source_verified=False),
            dict(raw_sha256="bogus"),
            dict(source_url="http://example.invalid/pcf"),
            dict(weight_basis="GUESS"),
        ]:
            row = pcf("2026-10-20")
            row.update(update)
            with self.assertRaises(ValueError):
                _snapshot(row, __import__("datetime").datetime.fromisoformat(ASOF))

    def test_unit_asof_and_next_session_basket_are_distinct(self):
        r = pcf("2026-10-20", published="2026-10-20T16:10:50+08:00")
        checked = _snapshot(r, __import__("datetime").datetime.fromisoformat(ASOF))
        self.assertEqual(checked["units_asof_date"], "2026-10-20")
        self.assertEqual(checked["basket_effective_date"], "2026-10-21")
        # A next-day PCF may be published after today's close; cannot be
        # used to infer the morning's stock trades.
        old = pcf("2026-10-20", published="2026-10-19T16:10:50+08:00")
        with self.assertRaisesRegex(ValueError, "UNITS_PUBLISHED_BEFORE"):
            _snapshot(old, __import__("datetime").datetime.fromisoformat(ASOF))

    def test_future_effective_basket_not_backdated_into_yesterday(self):
        r = pcf("2026-10-20")
        r["basket_effective_date"] = "2026-10-29"
        with self.assertRaisesRegex(ValueError, "BASKET_EFFECTIVE_DATE"):
            _snapshot(r, __import__("datetime").datetime.fromisoformat(ASOF))

    def test_cash_substitution_not_counted_as_stock_exposure(self):
        old = pcf("2026-10-19", substitute=True)
        new = pcf("2026-10-20", units=10100000)
        r = analyze([old, new], SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual([x["code"] for x in r["top20"]], ["9802"])
        old2 = pcf("2026-10-19")
        new2 = pcf("2026-10-20", units=10100000, substitute=True)
        r2 = analyze([old2, new2], SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual([x["code"] for x in r2["top20"]], ["9802"])

    def test_missing_session_not_invented_as_consecutive(self):
        r = analyze([pcf("2026-10-16"), pcf("2026-10-20")],
                    ["2026-10-16", "2026-10-19", "2026-10-20"],
                    PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual(r["etf_count_with_at_least_1d"], 0)

    def test_duplicate_issuer_session_excluded_not_silently_overwritten(self):
        r = analyze([pcf("2026-10-19"), pcf("2026-10-20"), pcf("2026-10-20")],
                    SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertTrue(any(x["reason"] == "ETF_DUPLICATE_SESSION" for x in r["excluded_records"]))

    def test_invalid_constituents_and_unsupported_product(self):
        for update in [
            dict(fund_type="INVERSE"),
            dict(constituents=[dict(code="6206", weight=1.1, cash_substitution=False)]),
            dict(constituents=[dict(code="6206", weight=.1, cash_substitution=False)]*2),
            dict(constituents=[dict(code="6206", weight=True, cash_substitution=False)]),
            dict(constituents=[dict(code="6206", weight=.1)]),
            dict(units_outstanding=True),
        ]:
            r = pcf("2026-10-20")
            r.update(update)
            with self.assertRaises(ValueError):
                _snapshot(r, __import__("datetime").datetime.fromisoformat(ASOF))

    def test_weight_drift_without_creation_never_fake_trade(self):
        rows = [pcf("2026-10-19", weight=.1), pcf("2026-10-20", weight=.2)]
        r = analyze(rows, SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual(next(x for x in r["top20"] if x["code"]=="6206")["estimated_1d_exposure_ntd"], 0)
        self.assertFalse(r["stock_buy_execution_verified"])

    def test_5_and_20_day_require_complete_contemporaneous_archive(self):
        sessions = [f"2026-10-{d:02}" for d in range(1,22)]
        all_pcf = [pcf(d, units=10000000+(i*100000)) for i,d in enumerate(sessions)]
        prices = [dict(x, date=sessions[-1]) for x in PRICES]
        r = analyze(all_pcf, sessions, prices, sessions[-1],
                    asof="2026-10-21T23:00:00+08:00")
        self.assertEqual(r["etf_count_with_full_5d"], 1)
        self.assertEqual(r["etf_count_with_full_20d"], 1)
        self.assertEqual(next(x for x in r["top20"] if x["code"]=="6206")["estimated_20d_exposure_ntd"], 10000000)
        missing = [row for row in all_pcf if row["units_asof_date"] != sessions[13]]
        r2 = analyze(missing, sessions, prices, sessions[-1],
                     asof="2026-10-21T23:00:00+08:00")
        self.assertEqual(r2["etf_count_with_full_20d"], 0)

    def test_no_unsupported_equal_etf_independence(self):
        a, b = pcf("2026-10-19"), pcf("2026-10-20", units=10100000)
        c, d = pcf("2026-10-19", etf="0062"), pcf("2026-10-20", units=10100000, etf="0062")
        r = analyze([a,b,c,d], SESSIONS, PRICES, "2026-10-20", asof=ASOF)
        self.assertEqual(r["etf_count_with_at_least_1d"], 2)
        self.assertEqual(r["etf_coverage"][0]["index_family"], "TAIWAN50")
        self.assertEqual(r["etf_coverage"][1]["index_family"], "TAIWAN50")

    def test_canonical_cli_fails_closed_when_pcf_not_archived(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/"prices").mkdir()
            (root/"rankings").mkdir()
            raw = (json.dumps(PRICES)+"\n").encode("utf-8")
            (root/"prices"/"2026-10-20.json").write_bytes(raw)
            (root/"prices"/"latest_manifest.json").write_text(json.dumps(dict(
                date="2026-10-20", normalized_sha256=hashlib.sha256(raw).hexdigest())))
            report = run(root, ASOF)
            self.assertEqual(report["status"], "BLOCKED_MISSING_VERIFIED_ETF_PCF")
            self.assertTrue((root/"rankings"/"v895_etf_accumulation.md").exists())
            (root/"prices"/"2026-10-20.json").write_text("[]")
            with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
                run(root, ASOF)


if __name__ == "__main__":
    unittest.main()
