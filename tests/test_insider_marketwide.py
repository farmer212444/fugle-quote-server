"""Offline synthetic contract tests: no live claims, no invented trading history."""
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.insider_marketwide import (build_ranking, months_ending, parse_detail,
                                        parse_irb110, put_json, save_original)

def row(identity="董事本人", name="甲", prev=10000, buy=3000, sell=1000,
        other_in=0, other_out=0, after=None):
    if after is None:
        after = prev + buy + other_in - sell - other_out
    x = [""] * 24
    for i, value in {0: identity, 1: name, 2: "普通股", 4: prev, 8: buy, 9: other_in,
                     13: sell, 14: other_out, 18: after}.items():
        x[i] = str(value)
    return x

def body(rows, code=200):
    return json.dumps({"code": code, "result": {"data": rows}},
                      ensure_ascii=False).encode()

class MarketwideInsiderTests(unittest.TestCase):
    def test_period_is_last_12_reportable_months(self):
        a = months_ending(dt.date(2026,10,25), 12)
        self.assertEqual((a[0], a[-1]), ("2025-10", "2026-09"))
        self.assertEqual(months_ending(dt.date(2026,11,10), 1), ["2026-09"])
        self.assertEqual(months_ending(dt.date(2026,11,16), 1), ["2026-10"])

    def test_no_market_buy_from_gift_pledge_or_role_duplicate(self):
        a = row()
        b = row(identity="總經理本人")
        gifted = row(name="乙", prev=10000, buy=0, sell=0, other_in=800, after=10800)
        res = parse_detail(body([a,b,gifted]))
        self.assertEqual(res["buy_shares"], 3000)
        self.assertEqual(res["sell_shares"], 1000)
        self.assertEqual(res["other_in_shares"], 800)
        self.assertFalse(res["original_holder_account_identity_certified"])

    def test_fails_closed_on_malformed_and_ambiguous(self):
        with self.assertRaises(ValueError):
            parse_detail(body([row()], code=500))
        with self.assertRaises(ValueError):
            parse_detail(body([row(prev=10000, after=9999)]))
        with self.assertRaises(ValueError):
            parse_detail(body([row(name="同名"),row(name="同名", buy=4000)]))

    def test_no_partial_twelve_month_rank_and_hash_guard(self):
        with tempfile.TemporaryDirectory() as p:
            b = Path(p)
            months = months_ending(dt.date(2026,10,25), 12)
            master = {"1234":{"market":"TWSE","issued_shares":1000000}}
            data = body([row()])
            for month in months[:-1]:
                dest = b/"detail"/month/"1234.json"
                saved = save_original(dest, data, "https://mops.twse.com.tw/mops/api/query6_1", month)
                put_json(dest, dict(saved,code="1234",month=month,buy_shares=3000,sell_shares=1000))
            first = build_ranking(b, months, master)
            self.assertEqual(first["complete_issuer_count"], 0)
            self.assertFalse(first["positive_buy_complete_sample_top100"])
            month = months[-1]
            dest = b/"detail"/month/"1234.json"
            saved = save_original(dest,data,"https://mops.twse.com.tw/mops/api/query6_1",month)
            put_json(dest,dict(saved,code="1234",month=month,buy_shares=3000,sell_shares=1000))
            ok = build_ranking(b,months,master)
            self.assertEqual(ok["complete_issuer_count"],1)
            self.assertAlmostEqual(ok["all_complete_sample"][0]["buy_pct_of_issued"],3.6)
            self.assertEqual(ok["all_complete_sample"][0]["positive_net_months"],12)
            archive=dest.parent/saved["raw_archive"]
            archive.write_bytes(gzip.compress(body([row(buy=5000)])))
            broken=build_ranking(b,months,master)
            self.assertEqual(broken["complete_issuer_count"],0)

    def test_irb_rejects_tiny_response(self):
        with self.assertRaises(ValueError):
            parse_irb110("<table><tr><td>1234 公司</td><td>1,000,000</td>"+'<td>0</td>'*6+"</tr></table>".encode("big5"))

if __name__ == "__main__":
    unittest.main()
