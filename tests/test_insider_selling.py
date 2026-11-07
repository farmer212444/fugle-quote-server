"""Contract tests for source-replayed insider sell observations; fully offline."""
import datetime as dt
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts.insider_marketwide import build_ranking, put_json, save_original
from tw_model_v880.insider_selling import load_selling_observations, attach_selling_risk


def row(buy=0, sell=2000, private_decrease=0):
    opening = 10000
    raw = [""] * 24
    for key, val in {
        0: "董事", 1: "測試持有人", 2: "普通股", 4: opening,
        8: buy, 13: sell, 15: private_decrease,
        18: opening + buy - sell - private_decrease,
    }.items():
        raw[key] = str(val)
    return raw


def original(rows):
    return json.dumps({"code": 200, "result": {"data": rows}},
                      ensure_ascii=False).encode()


class InsiderSellingResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "insider"
        self.months = ["2026-09"]
        self.master = {"1234": {"market": "TWSE", "issued_shares": 1000000}}
        self.dest = self.base / "detail" / "2026-09" / "1234.json"

    def record(self, rows):
        raw = original(rows)
        receipt = save_original(self.dest, raw, "https://mops.twse.com.tw/mops/api/query6_1", "2026-09")
        put_json(self.dest, dict(receipt, code="1234", month="2026-09", market="TWSE",
                                 buy_shares=sum(int(r[8] or 0) for r in rows),
                                 sell_shares=sum(int(r[13] or 0) for r in rows)))
        return receipt

    def publish(self):
        ranking = build_ranking(self.base, self.months, self.master)
        ranking["attempted_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        put_json(self.root / "rankings" / "insider_marketwide_latest.json", ranking)
        return ranking

    def asof(self, minutes=5):
        return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()

    def test_sell_only_is_visible_without_fabricating_buy(self):
        self.record([row(buy=0, sell=2000)])
        report = self.publish()
        self.assertEqual(report["observed_positive_issuer_count"], 0)
        self.assertEqual(report["observed_selling_issuer_count"], 1)
        self.assertFalse(report["marketwide_sell_rank_claim_permitted"])
        seller = report["positive_sell_observed_sample_top100"][0]
        self.assertEqual(seller["sell_lots"], 2)
        self.assertEqual(seller["sell_pct_of_issued"], 0.2)
        self.assertEqual(seller["net_sell_pct_of_issued"], 0.2)
        self.assertEqual(seller["negative_net_months"], 1)
        self.assertTrue(seller["year_to_date_complete"])
        self.assertFalse(report["holder_identity_formal_certification"])

    def test_sales_replayed_into_model_watch_not_formal_exit(self):
        self.record([row(buy=0, sell=2000)])
        self.publish()
        observations = load_selling_observations(self.root, self.asof())
        self.assertEqual(observations["verified_seller_count"], 1)
        self.assertEqual(observations["invalid_seller_count"], 0)
        candidate = {"code": "1234", "market": "TWSE", "base": {"eps": 4.5, "pe": 12},
                     "formal_Aplus": False, "score": None, "warning_flags": [],
                     "revenue_bridge": {"trend_inputs": {"latest_month_yoy": -0.07}},
                     "margin_bridge": {"current_ytd_gm": 0.14, "prior_ytd_gm": 0.17}}
        attach_selling_risk(candidate, observations)
        risk = candidate["insider_selling_risk"]
        self.assertEqual(risk["risk_review_priority"], "REVIEW")
        self.assertIn("INSIDER_SELLING_WITH_OPERATING_WEAKNESS_RESEARCH_ONLY",
                      candidate["warning_flags"])
        self.assertEqual(set(risk["operating_context_flags"]),
                         {"LATEST_MONTH_REVENUE_YOY_NEGATIVE", "YTD_GROSS_MARGIN_BELOW_PRIOR_YEAR"})
        self.assertEqual(candidate["base"], {"eps": 4.5, "pe": 12})
        self.assertIsNone(candidate["score"])
        self.assertFalse(risk["can_change_EPS_PE_Aplus_or_Exit"])
        self.assertFalse(risk["can_automatically_sell"])

    def test_private_transfer_is_not_market_sale(self):
        self.record([row(buy=0, sell=0, private_decrease=3000)])
        report = self.publish()
        self.assertEqual(report["observed_selling_issuer_count"], 0)
        self.assertEqual(load_selling_observations(self.root, self.asof())["verified_seller_count"], 0)

    def test_hash_change_invalidates_seller_in_model(self):
        receipt = self.record([row(buy=0, sell=2000)])
        self.publish()
        original_archive = self.dest.parent / receipt["raw_archive"]
        original_archive.write_bytes(gzip.compress(original([row(buy=0, sell=3000)])))
        observations = load_selling_observations(self.root, self.asof())
        self.assertEqual(observations["verified_seller_count"], 0)
        self.assertEqual(observations["invalid_seller_count"], 1)
        candidate = {"market": "TWSE", "code": "1234"}
        attach_selling_risk(candidate, observations)
        self.assertEqual(candidate["insider_selling_risk"]["risk_review_priority"], "UNKNOWN")

    def test_spoofed_report_totals_are_not_used(self):
        self.record([row(buy=0, sell=2000)])
        report = self.publish()
        report["all_observed_sellers"][0]["sell_lots"] = 999
        put_json(self.root / "rankings" / "insider_marketwide_latest.json", report)
        observations = load_selling_observations(self.root, self.asof())
        self.assertEqual(observations["verified_seller_count"], 0)
        self.assertEqual(observations["invalid_seller_count"], 1)

    def test_partial_months_flagged_not_zero_filled(self):
        self.record([row(buy=0, sell=2000)])
        self.months = ["2026-08", "2026-09"]
        report = self.publish()
        seller = report["all_observed_sellers"][0]
        self.assertFalse(seller["year_to_date_complete"])
        self.assertEqual(seller["missing_months"], ["2026-08"])
        observations = load_selling_observations(self.root, self.asof())
        self.assertEqual(observations["verified_seller_count"], 1)
        self.assertEqual(observations["by_code"][("TWSE", "1234")]["missing_months"],
                         ["2026-08"])

    def test_older_asof_does_not_use_future_snapshot(self):
        self.record([row(buy=0, sell=2000)])
        self.publish()
        observations = load_selling_observations(self.root, self.asof(minutes=-5))
        self.assertEqual(observations["status"], "SNAPSHOT_POSTDATES_ESTIMATE_NOT_USED")
        self.assertEqual(observations["verified_seller_count"], 0)

    def test_net_buyer_with_sales_is_context_only(self):
        self.record([row(buy=3000, sell=1000)])
        self.publish()
        observations = load_selling_observations(self.root, self.asof())
        risk = observations["by_code"][("TWSE", "1234")]
        self.assertEqual(risk["risk_review_priority"], "CONTEXT_ONLY")
        self.assertEqual(risk["net_sell_lots"], 0)


if __name__ == "__main__":
    unittest.main()
