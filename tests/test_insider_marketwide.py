"""Offline synthetic contract tests: no live claims, no invented trading history."""
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.insider_marketwide import (PRIORITY_REVIEW_CODES, build_ranking, capture_details, recover_failed_original, months_ending, months_year_to_date, parse_detail,
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

    def test_year_to_date_uses_only_this_year_reported_months(self):
        self.assertEqual(
            months_year_to_date(dt.date(2026, 10, 25)),
            [f"2026-{m:02d}" for m in range(1, 10)])
        self.assertEqual(months_year_to_date(dt.date(2026, 11, 10))[-1], "2026-09")
        self.assertEqual(months_year_to_date(dt.date(2026, 11, 16))[-1], "2026-10")
        self.assertEqual(months_year_to_date(dt.date(2026, 1, 10)), [])

    def test_2026_start_does_not_reset_in_2027(self):
        months = months_year_to_date(dt.date(2027, 2, 17))
        self.assertEqual(months[0], "2026-01")
        self.assertEqual(months[-1], "2027-01")
        self.assertEqual(len(months), 13)

    def test_private_placement_changes_are_not_market_trades(self):
        item = row(prev=10000, buy=0, sell=0, after=8400)
        item[15] = "1,600"  # private-placement share decrease, not market sale
        self.assertEqual(parse_detail(body([item]))["sell_shares"], 0)

    def test_blank_named_spouse_row_is_tied_to_named_parent(self):
        item = row(name="董事", buy=0, sell=0)
        family = row(identity="董事本人之配偶及未成年子女",
                     name="", prev=1000, buy=500, sell=0)
        got = parse_detail(body([item, family]))
        self.assertEqual(got["buy_shares"], 500)
        self.assertEqual(got["unique_display_keys"], 2)

    def test_replay_real_202609_official_failure_archives(self):
        base = Path(__file__).resolve().parents[1] / "tw-market-data" / "insider" / "failed" / "2026-09"
        cases = (
            ("1231_c87abe3f5a7270e1944a03eaf1618834be3c22551b49ce81000fb7cfc16e5e5d.gz", 0, 80000),
            ("1441_755f1b5d682e2e3b3eac34cb4ed5126254bf3e9605d3a53d488c75aa78f26333.gz", 0, 0),
        )
        for filename, buy, sell in cases:
            with self.subTest(filename=filename):
                parsed = parse_detail(gzip.decompress((base / filename).read_bytes()))
                self.assertEqual(parsed["buy_shares"], buy)
                self.assertEqual(parsed["sell_shares"], sell)

    def test_recover_archive_before_new_network_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = body([row(name="甲", buy=1000, sell=0),
                        row(identity="董事本人之配偶及未成年子女",
                            name="", prev=100, buy=500, sell=0)])
            target = base / "failed" / "2026-09" / "1234.json"
            save_original(target, raw, "https://mops.twse.com.tw/mops/api/query6_1", "2026-09")
            self.assertTrue(recover_failed_original(base, "2026-09", "1234", "TWSE"))
            def no_network(url, payload):
                raise AssertionError("Expected cached archive rather than live network")
            out = capture_details(base, ["2026-09"],
                                  {"1234": {"market": "TWSE", "issued_shares": 1000000}},
                                  10, gap=0, getter=no_network)
            self.assertEqual(out["requested"], 0)
            ranking = build_ranking(base, ["2026-09"],
                                    {"1234": {"market": "TWSE", "issued_shares": 1000000}})
            self.assertEqual(ranking["positive_buy_observed_sample_top100"][0]["buy_lots"], 1.5)

    def test_no_market_buy_from_gift_pledge_or_role_duplicate(self):
        a = row()
        b = row(identity="總經理本人")
        gifted = row(name="乙", prev=10000, buy=0, sell=0, other_in=800, after=10800)
        res = parse_detail(body([a,b,gifted]))
        self.assertEqual(res["buy_shares"], 3000)
        self.assertEqual(res["sell_shares"], 1000)
        self.assertEqual(res["other_in_shares"], 800)
        self.assertFalse(res["original_holder_account_identity_certified"])

    def test_empty_holder_api_row_skipped_without_inventing_trades(self):
        empty = [""] * 24
        good = row(name="真正持有人", buy=500, sell=300)
        result = parse_detail(body([empty, good]))
        self.assertEqual(result["buy_shares"], 500)
        self.assertEqual(result["sell_shares"], 300)
        with self.assertRaisesRegex(ValueError, "MOPS_(UNIDENTIFIED_ROW_WITH_SHARES|HOLDINGS_ROLLFORWARD_MISMATCH)"):
            trades_without_name = list(empty)
            trades_without_name[8] = "100"
            parse_detail(body([trades_without_name, good]))
        with self.assertRaisesRegex(ValueError, "NO_VALID_HOLDER_ROWS"):
            parse_detail(body([empty]))

    def test_issuer_first_queue_creates_complete_sample_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Path(tmp)
            masters = {"1234":{"market":"TWSE","issued_shares":1000000},
                       "5678":{"market":"TWSE","issued_shares":1000000}}
            seen = []
            def read(url, payload):
                seen.append((payload["companyId"],payload["month"]))
                return body([row()])
            out = capture_details(b,["2026-08","2026-09"],masters,3,gap=0,getter=read)
            self.assertEqual(out["succeeded"],3)
            self.assertEqual(seen, [("1234","09"),("5678","09"),("1234","08")])
            ranking = build_ranking(b,["2026-08","2026-09"],masters)
            self.assertEqual(ranking["complete_issuer_count"],1)
            self.assertEqual(ranking["observed_positive_issuer_count"],2)
            self.assertEqual(ranking["partial_positive_issuer_count"],1)

    def test_fails_closed_on_malformed_and_ambiguous(self):
        with self.assertRaises(ValueError):
            parse_detail(body([row()], code=500))
        with self.assertRaises(ValueError):
            parse_detail(body([row(prev=10000, after=9999)]))
        with self.assertRaises(ValueError):
            parse_detail(body([row(name="同名"),row(name="同名", buy=4000)]))

    def test_partially_observed_ytd_buyers_are_visible_with_coverage_and_hash_guard(self):
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
            self.assertEqual(first["observed_positive_issuer_count"], 1)
            self.assertEqual(first["positive_buy_observed_sample_top100"][0]["observed_month_count"], 11)
            self.assertTrue(first["positive_buy_observed_sample_top100"][0]["buy_amount_is_observed_months_only"])
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
            self.assertEqual(broken["positive_buy_observed_sample_top100"][0]["observed_month_count"],11)

    def test_no_purchase_only_sellers_are_not_ranked(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Path(tmp)
            code = "1234"
            month = "2026-09"
            dest = b / "detail" / month / (code + ".json")
            original = body([row(name="只賣", buy=0, sell=100)])
            receipt = save_original(dest, original, "https://mops.twse.com.tw/mops/api/query6_1", month)
            put_json(dest, dict(receipt, code=code, month=month, buy_shares=0, sell_shares=100))
            rank = build_ranking(b, [month], {code: {"market": "TWSE", "issued_shares": 1000000}})
            self.assertEqual(rank["complete_issuer_count"], 1)
            self.assertEqual(rank["observed_positive_issuer_count"], 0)

    def test_failed_capture_rotates_pending_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            master = {"1234": {"market":"TWSE","issued_shares":1000000}}
            def unavailable(url, payload):
                raise OSError("offline")
            first = capture_details(base, ["2026-09"], master, 10, gap=0, getter=unavailable)
            self.assertEqual(first["requested"], 1)
            self.assertEqual(first["succeeded"], 0)
            second = capture_details(base, ["2026-09"], master, 10, gap=0, getter=unavailable)
            self.assertEqual(second["requested"], 0)
            self.assertFalse((base/"detail"/"2026-09"/"1234.json").exists())

    def test_2026_buyer_leads_get_full_year_verified_before_broad_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            master = {code: {"market": "TWSE", "issued_shares": 1000000}
                      for code in ("1101", "2520", "9802")}
            seen = []
            def read(url, payload):
                seen.append((payload["companyId"], payload["month"]))
                return body([row(buy=1000, sell=0)])
            result = capture_details(base, ["2026-07", "2026-08", "2026-09"],
                                     master, 4, gap=0, getter=read)
            self.assertEqual(result["succeeded"], 4)
            self.assertEqual(seen, [("9802", "09"), ("9802", "08"),
                                    ("9802", "07"), ("2520", "09")])
            # Outside leads remain in the queue; a lead does not automatically
            # gain complete-year or full-market certification.
            ranking = build_ranking(base, ["2026-07", "2026-08", "2026-09"], master)
            self.assertFalse(ranking["marketwide_rank_claim_permitted"])
            self.assertEqual(ranking["complete_issuer_count"], 1)
            self.assertEqual(ranking["observed_positive_issuer_count"], 2)


    def test_stale_receipt_normalization_is_rechecked_and_refetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            code, month = "1234", "2026-09"
            original = body([row(buy=3000, sell=0)])
            receipt_path = base / "detail" / month / (code + ".json")
            receipt = save_original(receipt_path, original, "https://mops.twse.com.tw/mops/api/query6_1", month)
            put_json(receipt_path, dict(receipt, code=code, month=month,
                                        buy_shares=999999, sell_shares=0))
            requests = []
            def getter(url, payload):
                requests.append(payload["companyId"])
                return original
            master = {code: {"market": "TWSE", "issued_shares": 1000000}}
            state = capture_details(base, [month], master, 1, gap=0, getter=getter)
            self.assertEqual(requests, [code])
            self.assertEqual(state["succeeded"], 1)
            ranking = build_ranking(base, [month], master)
            self.assertEqual(ranking["complete_issuer_count"], 1)
            self.assertEqual(ranking["positive_buy_observed_sample_top100"][0]["buy_lots"], 3)

    def test_corrupted_cached_gzip_is_preserved_then_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            code, month = "1234", "2026-09"
            original = body([row(buy=1000, sell=0)])
            receipt_path = base / "detail" / month / (code + ".json")
            receipt = save_original(receipt_path, original, "https://mops.twse.com.tw/mops/api/query6_1", month)
            put_json(receipt_path, dict(receipt, code=code, month=month,
                                        buy_shares=1000, sell_shares=0))
            archive = receipt_path.parent / receipt["raw_archive"]
            archive.write_bytes(b"corrupted gzip source bytes")
            seen = []
            def getter(url, payload):
                seen.append(1)
                return original
            master = {code: {"market": "TWSE", "issued_shares": 1000000}}
            state = capture_details(base, [month], master, 1, gap=0, getter=getter)
            self.assertEqual(state["succeeded"], 1)
            self.assertEqual(len(seen), 1)
            self.assertTrue(list(archive.parent.glob(archive.name + ".*.corrupt")))
            self.assertEqual(gzip.decompress(archive.read_bytes()), original)
            self.assertEqual(build_ranking(base, [month], master)["complete_issuer_count"], 1)

    def test_many_identity_conflicts_do_not_masquerade_as_source_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codes = [f"{i:04d}" for i in range(3300, 3326)]
            master = {code: {"market": "TWSE", "issued_shares": 1000000}
                      for code in codes}
            conflicting = body([row(name="同名", buy=3000, sell=0),
                                row(name="同名", buy=4000, sell=0)])
            good = body([row(name="已確認", buy=1000, sell=0)])
            calls = []
            def fetcher(url, payload):
                calls.append(payload["companyId"])
                return good if payload["companyId"] == codes[-1] else conflicting
            result = capture_details(base, ["2026-09"], master, 40, gap=0, getter=fetcher)
            self.assertEqual(len(calls), 26)
            self.assertEqual(result["requested"], 26)
            self.assertEqual(result["succeeded"], 1)
            self.assertEqual(len(result["errors"]), 25)
            self.assertNotIn("stopped", result)
            self.assertEqual(build_ranking(base, ["2026-09"], master)["verified_detail_month_count"], 1)

            def offline(url, payload):
                raise AssertionError("Stable unresolved identity conflicts must be deferred")
            repeat = capture_details(base, ["2026-09"], master, 40, gap=0, getter=offline)
            self.assertEqual(repeat["requested"], 0)
            self.assertEqual(repeat["deferred_identity_conflicts"], 25)
            self.assertEqual(build_ranking(base, ["2026-09"], master)["pending_issuer_count"], 25)

    def test_identity_review_resets_consecutive_source_outage_streak(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            master = {f"{i:04d}": {"market": "TWSE", "issued_shares": 1000000}
                      for i in range(3300, 3350)}
            colliding = body([row(name="同名", buy=3000, sell=0),
                              row(name="同名", buy=4000, sell=0)])
            valid = body([row(name="可用資料", buy=5000, sell=0)])
            calls = []
            def mixed_feed(url, payload):
                code = payload["companyId"]
                calls.append(code)
                index = int(code) - 3300
                if index in (19, 39):
                    return colliding  # Official content with unresolved identity.
                if index == 49:
                    return valid
                raise OSError("temporary MOPS outage")
            out = capture_details(base, ["2026-09"], master, 50,
                                  gap=0, getter=mixed_feed)
            self.assertEqual(out["requested"], 50)
            self.assertEqual(out["succeeded"], 1)
            self.assertNotIn("stopped", out)
            self.assertEqual(len(calls), 50)
            self.assertEqual(build_ranking(base, ["2026-09"], master)
                             ["verified_detail_month_count"], 1)

    def test_time_budget_does_not_lose_partial_cached_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            month = "2026-09"
            code = "3300"
            orig = body([row(name="證實買入", buy=2000, sell=0)])
            receipt_path = base / "detail" / month / (code + ".json")
            saved = save_original(receipt_path, orig,
                                  "https://mops.twse.com.tw/mops/api/query6_1", month)
            put_json(receipt_path, dict(saved, code=code, month=month,
                                        buy_shares=2000, sell_shares=0))
            master = {code: {"market": "TWSE", "issued_shares": 1000000},
                      "3301": {"market": "TWSE", "issued_shares": 1000000}}
            def must_not_fetch(url, payload):
                raise AssertionError("time budget must prevent new HTTP requests")
            state = capture_details(base, [month], master, limit=100,
                                    gap=0, getter=must_not_fetch, deadline=-1)
            self.assertEqual(state["requested"], 0)
            self.assertEqual(state["stopped"], "TIME_BUDGET_GRACEFUL_PARTIAL_COMMIT")
            rank = build_ranking(base, [month], master)
            self.assertEqual(rank["verified_detail_month_count"], 1)
            self.assertEqual(rank["pending_issuer_count"], 1)
            self.assertEqual(rank["positive_buy_observed_sample_top100"][0]["buy_lots"], 2)

    def test_real_source_outage_still_stops_after_twenty_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            master = {f"{i:04d}": {"market": "TWSE", "issued_shares": 1000000}
                      for i in range(3300, 3330)}
            def offline(url, payload):
                raise OSError("official feed unavailable")
            result = capture_details(base, ["2026-09"], master, 30, gap=0, getter=offline)
            self.assertEqual(result["requested"], 20)
            self.assertEqual(result["succeeded"], 0)
            self.assertEqual(result["stopped"], "SOURCE_OUTAGE_NO_ZERO_FILL")
            self.assertEqual(build_ranking(base, ["2026-09"], master)["complete_issuer_count"], 0)

    def test_offline_reconcile_uses_merged_receipts_and_never_fetches(self):
        # Simulate publication after concurrent main updates: a matching
        # current-month archive must appear in the rebuilt coverage result.
        from unittest.mock import patch
        import scripts.insider_marketwide as insider
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "tw-market-data" / "insider"
            month = "2026-09"
            original = body([row(name="已驗證帳戶", buy=1500, sell=0)])
            dest = base / "detail" / month / "1234.json"
            receipt = save_original(dest, original,
                                    "https://mops.twse.com.tw/mops/api/query6_1", month)
            put_json(dest, dict(receipt, code="1234", month=month,
                                market="TWSE", buy_shares=1500, sell_shares=0))
            months = months_year_to_date(dt.date(2026, 10, 28))
            snapshot = root / "before-rebase.json"
            put_json(snapshot, {
                "schema": "INSIDER_MARKETWIDE_YTD_V2",
                "months": months,
                "collection": {"requested": 360, "succeeded": 354, "errors": []},
                "monthly_master_failures": []})
            master = {"1234": {"market": "TWSE", "issued_shares": 1000000}}
            argv = ["insider_marketwide.py", "--asof", "2026-10-28",
                    "--base", str(base), "--rebuild-only",
                    "--collection-state-file", str(snapshot),
                    "--max-details", "0"]
            with patch("sys.argv", argv), patch.object(insider, "ROOT", root), \
                 patch.object(insider, "irb_master", return_value=master), \
                 patch.object(insider, "capture_irb", side_effect=AssertionError("SIIS HTTP forbidden")), \
                 patch.object(insider, "capture_details", side_effect=AssertionError("MOPS HTTP forbidden")):
                self.assertEqual(insider.main(), 0)
            published = json.loads((root / "tw-market-data" / "rankings" /
                                    "insider_marketwide_latest.json").read_text())
            self.assertEqual(published["verified_detail_month_count"], 1)
            self.assertEqual(published["positive_buy_observed_sample_top100"][0]["buy_lots"], 1.5)
            self.assertEqual(published["collection"]["requested"], 360)
            self.assertEqual(published["collection"]["succeeded"], 354)
            self.assertTrue(published["collection"]["offline_reconciled_after_rebase"])
            self.assertFalse(published["marketwide_rank_claim_permitted"])

    def test_offline_reconcile_rejects_wrong_month_scope(self):
        from unittest.mock import patch
        import scripts.insider_marketwide as insider
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            put_json(snapshot, {"schema": "INSIDER_MARKETWIDE_YTD_V2",
                                "months": ["2026-09"],
                                "collection": {"requested": 10}})
            argv = ["insider_marketwide.py", "--asof", "2026-10-28",
                    "--rebuild-only", "--collection-state-file", str(snapshot)]
            with patch("sys.argv", argv):
                with self.assertRaises(SystemExit):
                    insider.main()

    def test_irb_rejects_tiny_response(self):
        with self.assertRaises(ValueError):
            parse_irb110(("<table><tr><td>1234 公司</td><td>1,000,000</td>"+'<td>0</td>'*6+"</tr></table>").encode("big5"))

    def test_footwear_supply_chain_leads_are_priority_not_certified_buyers(self):
        # A third-party lead only changes the MOPS collection order. It never
        # creates a purchase, a zero-purchase finding or a certified holder.
        buyer_leads = {"9910", "6965", "6768", "4766"}
        control_peers = {"9904", "6890", "8404", "1307"}
        self.assertTrue((buyer_leads | control_peers).issubset(set(PRIORITY_REVIEW_CODES)))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            master = {code: {"market": "TWSE", "issued_shares": 1000000}
                      for code in sorted(buyer_leads | control_peers)}
            before = build_ranking(base, ["2026-09"], master)
            self.assertEqual(before["observed_positive_issuer_count"], 0)
            self.assertEqual(before["pending_issuer_count"], len(master))
            self.assertFalse(before["marketwide_rank_claim_permitted"])
            self.assertEqual(len(before["footwear_supply_chain_watchlist"]), len(master))
            self.assertEqual({v["status"] for v in before["footwear_supply_chain_watchlist"]},
                             {"PARTIAL_SCOPE_NO_BUY_OBSERVED_NOT_ZERO"})
            queried = []
            def getter(url, payload):
                queried.append(payload["companyId"])
                return body([row(buy=2000, sell=0)])
            result = capture_details(base, ["2026-09"], master, 1,
                                     gap=0, getter=getter)
            self.assertEqual(result["succeeded"], 1)
            self.assertEqual(queried, ["9910"])
            after = build_ranking(base, ["2026-09"], master)
            self.assertEqual(after["observed_positive_issuer_count"], 1)
            self.assertEqual(after["all_observed_positive"][0]["code"], "9910")
            self.assertFalse(after["holder_identity_formal_certification"])
            self.assertFalse(after["marketwide_rank_claim_permitted"])
            observed_buyer = next(v for v in after["footwear_supply_chain_watchlist"]
                                  if v["code"] == "9910")
            self.assertEqual(observed_buyer["buy_lots"], 2)
            self.assertEqual(observed_buyer["status"],
                             "HASHED_MOPS_BUY_OBSERVED_HOLDER_NOT_FORMALLY_CERTIFIED")
            pending_peer = next(v for v in after["footwear_supply_chain_watchlist"]
                                if v["code"] == "9904")
            self.assertEqual(pending_peer["observed_month_count"], 0)
            self.assertEqual(pending_peer["missing_months"], ["2026-09"])
            self.assertEqual(pending_peer["status"], "PARTIAL_SCOPE_NO_BUY_OBSERVED_NOT_ZERO")


if __name__ == "__main__":
    unittest.main()
