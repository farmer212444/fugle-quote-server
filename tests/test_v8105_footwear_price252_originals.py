"""Tests for source-backed unadjusted closing-price prefilter, NOT live alpha."""
import datetime as dt
import unittest

from scripts.v8105_footwear_price252_originals import months_between, snapshot_window

END = dt.date(2026, 10, 22)


def synthetic_full():
    days = []
    d = END
    while len(days) < 252:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= dt.timedelta(days=1)
    days.sort()
    data = {}
    src={}
    for code in ("0050","9802","6965"):
        rows=[]
        for idx,day in enumerate(days):
            price = 50+idx/20 if code=="0050" else 60+(idx%33)
            if idx==len(days)-1:
                price=62 if code=="9802" else 64
            rows.append({"date":day,"close":price,"source_original_verified":True})
        data[code]=rows
        src[code]={d[:7] for d in days}
    return data,src


class FootwearPrice252Tests(unittest.TestCase):
    def test_months_15_and_no_unbounded_future(self):
        m=months_between()
        self.assertEqual((len(m),m[0],m[-1]),(15,"2025-08","2026-10"))
        with self.assertRaisesRegex(ValueError,"UNSUPPORTED_MONTH_RANGE"):
            months_between("2022-01","2026-10")

    def test_actual_252_dates_including_reference(self):
        prices,sources=synthetic_full()
        report=snapshot_window(prices,source_verified_months=sources)
        self.assertEqual(report["calendar_sessions"],252)
        self.assertFalse(report["signal_created"])
        for code in ("9802","6965"):
            self.assertEqual(report["research_price_candidates"][code]["window_sessions"],252)
            self.assertTrue(report["research_price_candidates"][code]["source_backed_unadjusted_prices"])
            self.assertFalse(report["research_price_candidates"][code]["price_low_window_certified"])

    def test_month_source_missing_blocks_signal(self):
        prices,sources=synthetic_full()
        sources["9802"].remove(prices["9802"][80]["date"][:7])
        report=snapshot_window(prices,source_verified_months=sources)
        self.assertEqual(report["status"],"PENDING_MONTH_SOURCE_9802")
        self.assertFalse(report["signal_created"])

    def test_one_missing_issuer_session_invalidates_candidate(self):
        prices,sources=synthetic_full()
        prices["6965"].pop(33)
        report=snapshot_window(prices,source_verified_months=sources)
        self.assertEqual(report["research_price_candidates"]["6965"]["status"],
                         "PENDING_MISSING_EXCHANGE_SESSIONS")
        self.assertEqual(report["research_price_candidates"]["6965"]["missing_session_count"],1)
        self.assertFalse(report["research_price_candidates"]["6965"]["price_low_window_certified"])

    def test_future_row_fails_closed(self):
        prices,sources=synthetic_full()
        prices["9802"].append({"date":"2026-10-23","close":77.2,"source_original_verified":True})
        with self.assertRaisesRegex(ValueError,"INVALID_DUPLICATE_OR_FUTURE_PRICE_ROW"):
            snapshot_window(prices,source_verified_months=sources)

    def test_duplicate_row_fails_closed(self):
        prices,sources=synthetic_full()
        prices["6965"].append(dict(prices["6965"][-1]))
        with self.assertRaisesRegex(ValueError,"INVALID_DUPLICATE_OR_FUTURE_PRICE_ROW"):
            snapshot_window(prices,source_verified_months=sources)

    def test_missing_anchor_252_cannot_infer_from_52wk_high_low(self):
        prices,sources=synthetic_full()
        prices["0050"].pop(0)
        r=snapshot_window(prices,source_verified_months=sources)
        self.assertEqual(r["status"],"PENDING_COMPLETE_ANCHOR_252_SESSIONS")

    def test_missing_sha_verification_never_promotes_price(self):
        prices,sources=synthetic_full()
        prices["6965"][5]["source_original_verified"]=False
        r=snapshot_window(prices,source_verified_months=sources)
        self.assertEqual(r["status"],"PENDING_UNVERIFIED_ROW_ORIGINAL")

    def test_cannot_construct_without_month_sources(self):
        prices,_=synthetic_full()
        r=snapshot_window(prices)
        self.assertEqual(r["status"],"PENDING_OFFICIAL_SOURCE_ORIGINALS")
        self.assertEqual(r["research_price_candidates"],{})

    def test_low_position_changes_when_only_end_quote_changes(self):
        prices,sources=synthetic_full()
        result=snapshot_window(prices,source_verified_months=sources)
        self.assertTrue(result["research_price_candidates"]["9802"]["provisional_bottom_20pct"])
        prices["9802"][-1]["close"]=90
        result=snapshot_window(prices,source_verified_months=sources)
        self.assertFalse(result["research_price_candidates"]["9802"]["provisional_bottom_20pct"])


if __name__=="__main__":
    unittest.main()
