"""Synthetic contracts for selling samples and conservative model overlay."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts.insider_marketwide import build_ranking, put_json, save_original
from scripts.insider_sell_risk import (annotate_issuer_rows, assess_sell_risk,
                                      load_sell_feed)


def market_row(*, buy=0, sell=0, other_out=0):
    # query6_1 actual centralized purchases=8; actual sales=13.
    x = [""] * 24
    values = {0: "董事本人", 1: "甲", 2: "普通股", 4: 100000,
              8: buy, 13: sell, 14: other_out,
              18: 100000 + buy - sell - other_out}
    for k, v in values.items():
        x[k] = str(v)
    return x


def archive(base, code, month, *, buy=0, sell=0, other_out=0):
    doc = {"code": 200, "result": {"data": [
        market_row(buy=buy, sell=sell, other_out=other_out)]}}
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    target = base / "detail" / month / (code + ".json")
    receipt = save_original(target, raw, "https://mops.twse.com.tw/mops/api/query6_1", month)
    put_json(target, dict(receipt, code=code, month=month,
                          buy_shares=buy, sell_shares=sell))


class InsiderSellRiskTests(unittest.TestCase):
    def test_actual_selling_ranked_in_same_marketwide_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for month in ("2026-08", "2026-09"):
                archive(base, "3189", month, sell=2500)
                archive(base, "9802", month, buy=2000, sell=100)
                archive(base, "1234", month, other_out=5000)
            master = {code: {"market": "TWSE", "issued_shares": 1000000}
                      for code in ("3189", "9802", "1234")}
            result = build_ranking(base, ["2026-08", "2026-09"], master)
            self.assertEqual(result["observed_selling_issuer_count"], 2)
            self.assertEqual(result["positive_sell_observed_sample_top100"][0]["code"], "3189")
            self.assertEqual(result["positive_sell_observed_sample_top100"][0]["sell_lots"], 5)
            self.assertEqual(result["positive_sell_observed_sample_top100"][0]["negative_net_months"], 2)
            self.assertEqual(result["positive_sell_observed_sample_top100"][0]["max_consecutive_net_sell_months"], 2)
            self.assertEqual(result["positive_sell_observed_sample_top100"][0]["net_sell_pct_of_issued"], .5)
            self.assertEqual(result["observed_positive_issuer_count"], 1)
            self.assertEqual([x["code"] for x in result["all_observed_selling"]], ["3189", "9802"])
            self.assertFalse(result["holder_identity_formal_certification"])
            self.assertFalse(result["marketwide_rank_claim_permitted"])

    def test_missing_month_does_not_imply_zero_and_breaks_streak(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive(base, "3189", "2026-07", sell=3000)
            archive(base, "3189", "2026-09", sell=3000)
            result = build_ranking(base, ["2026-07", "2026-08", "2026-09"],
                                   {"3189": {"market": "TWSE", "issued_shares": 1000000}})
            v = result["positive_sell_observed_sample_top100"][0]
            self.assertTrue(v["sell_amount_is_observed_months_only"])
            self.assertEqual(v["missing_months"], ["2026-08"])
            self.assertEqual(v["max_consecutive_net_sell_months"], 1)
            self.assertFalse(v["year_to_date_complete"])

    def test_corrupt_original_excluded_from_sell_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive(base, "3189", "2026-09", sell=2000)
            receipt = json.loads((base/"detail"/"2026-09"/"3189.json").read_text())
            (base/"detail"/"2026-09"/receipt["raw_archive"]).write_bytes(b"not gzip")
            result = build_ranking(base, ["2026-09"],
                                   {"3189": {"market": "TWSE", "issued_shares": 1000000}})
            self.assertEqual(result["observed_selling_issuer_count"], 0)
            self.assertEqual(result["pending_issuer_count"], 1)

    def test_exploratory_thresholds_are_not_certified_trade_gates(self):
        data = dict(sell_pct_of_issued=.8, net_sell_pct_of_issued=.5,
                    negative_net_months=2, max_consecutive_net_sell_months=2,
                    observed_month_count=2, expected_ytd_month_count=3,
                    year_to_date_complete=False, missing_months=["2026-07"])
        result = assess_sell_risk(data, "ASOF_VALID_RESEARCH_ONLY_UNCERTIFIED_HOLDER_IDENTITY")
        self.assertEqual(result["tier"], "HIGH_REVIEW")
        self.assertTrue(result["needs_manual_review"])
        self.assertTrue(result["sell_amount_is_observed_months_only"])
        self.assertFalse(result["holder_identity_certified"])
        self.assertFalse(result["historical_PIT_certified"])
        no_net = dict(data, net_sell_pct_of_issued=-.2, negative_net_months=0,
                      max_consecutive_net_sell_months=0)
        self.assertEqual(assess_sell_risk(no_net, "ok")["tier"], "NO_MATERIAL_OBSERVED_SIGNAL")

    def test_model_annotations_do_not_change_formal_a_plus_or_forecasts(self):
        observed = dict(sell_pct_of_issued=1.2, net_sell_pct_of_issued=.9,
                        negative_net_months=1, max_consecutive_net_sell_months=1,
                        observed_month_count=1, expected_ytd_month_count=1,
                        year_to_date_complete=True)
        row = {"code": "3189", "name": "synthetic", "market": "TWSE",
               "formal_Aplus": True, "formal_Aplusplus": True,
               "recommendation_blocked": False,
               "base": {"eps": 7.5, "pe": 15, "target_price": 112.5},
               "warning_flags": []}
        watch = annotate_issuer_rows([row], {"status": "ASOF_VALID_RESEARCH_ONLY_UNCERTIFIED_HOLDER_IDENTITY",
                                            "records": {"3189": observed}})
        self.assertEqual(len(watch), 1)
        self.assertTrue(row["formal_Aplus"])
        self.assertTrue(row["formal_Aplusplus"])
        self.assertFalse(row["recommendation_blocked"])
        self.assertEqual(row["base"], {"eps": 7.5, "pe": 15, "target_price": 112.5})
        self.assertIn("INSIDER_SELL_RESEARCH_REVIEW_REQUIRED", row["warning_flags"])

    def test_no_sell_record_is_unknown_not_claimed_zero(self):
        self.assertEqual(assess_sell_risk(None, "MISSING")["tier"], "UNKNOWN")
        self.assertEqual(assess_sell_risk(None, "MISSING")["reason"],
                         "NO_VERIFIED_SELL_OBSERVATION_FOR_ISSUER")

    def test_cutoff_disallows_lookahead_and_incomplete_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"rank.json"
            document = {"schema": "INSIDER_MARKETWIDE_YTD_V2",
                        "attempted_at_utc": "2026-11-07T12:30:00+00:00",
                        "holder_identity_formal_certification": False,
                        "marketwide_rank_claim_permitted": False,
                        "months": ["2026-09"],
                        "all_observed_selling": [{"code": "3189", "sell_pct_of_issued": .5}],
                        "all_complete_sample": []}
            path.write_text(json.dumps(document))
            self.assertFalse(load_sell_feed(path, "2026-11-07T19:00:00+08:00")["records"])
            before = load_sell_feed(path, "2026-11-07")
            self.assertEqual(before["status"], "INSIDER_SELL_SNAPSHOT_NOT_AVAILABLE_AT_ASOF")
            after = load_sell_feed(path, "2026-11-08T09:00:00+08:00")
            self.assertIn("3189", after["records"])
            document.pop("all_observed_selling")
            path.write_text(json.dumps(document))
            self.assertEqual(load_sell_feed(path, "2026-11-08T09:00:00+08:00")["status"],
                             "INSIDER_SELL_FIELDS_NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main()
