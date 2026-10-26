"""Offline synthetic contract tests: no live claims, no invented trading history."""
import datetime as dt
import gzip
import hashlib
import json
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path

from scripts.insider_marketwide import (build_ranking, capture_details, months_ending, months_year_to_date, parse_detail,
                                        parse_irb110, put_json, save_original, MOPS_URL, NORMALIZER, recover_failed_original)

SAVED = Path(__file__).resolve().parents[1]/'tw-market-data/insider'
REAL_SOURCES = {
    '1256': ('failed', '05a03114e42678963698c4f95a1fd5b5344ea878d5272c122a42640989187377'),
    '1231': ('failed', 'c87abe3f5a7270e1944a03eaf1618834be3c22551b49ce81000fb7cfc16e5e5d'),
    '1713': ('detail', 'b44fa0d3bbd460a8d551091f70d1770f68feb99d5987e5a11bc73b0b2f7e8fe1')}

def actual_original(code):
    kind, digest = REAL_SOURCES[code]
    raw = gzip.decompress((SAVED/kind/'2026-09'/f'{code}_{digest}.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('REAL_REGRESSION_ORIGINAL_HASH_MISMATCH')
    return raw

def row(identity="董事本人", name="甲", prev=10000, buy=3000, sell=1000,
        other_in=0, other_out=0, after=None):
    if after is None:
        after = prev + buy + other_in - sell - other_out
    x = [""] * 24
    for i, value in {0: identity, 1: name, 2: "普通股", 4: prev, 8: buy, 9: other_in,
                     13: sell, 14: other_out, 18: after}.items():
        x[i] = str(value)
    return x

def body(rows, code=200, month="09", year="115", market="上市公司"):
    titles=json.loads(actual_original('1256'))['result']['titles']
    return json.dumps({"code": code, "result": {"data": rows, "titles":titles,
                      "month":month, "year":year, "marketName":market,
                      "companyAbbreviation":"測試公司"}},
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
                return body([row()],month=payload['month'],year=payload['year'])
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
            for month in months[:-1]:
                data = body([row()],month=month[-2:],year=str(int(month[:4])-1911))
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
            data = body([row()],month=month[-2:],year=str(int(month[:4])-1911))
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

    def test_irb_rejects_tiny_response(self):
        with self.assertRaises(ValueError):
            parse_irb110(("<table><tr><td>1234 公司</td><td>1,000,000</td>"+'<td>0</td>'*6+"</tr></table>").encode("big5"))

    def test_unchanged_anonymous_balances_do_not_invent_holder_or_trade(self):
        anonymous = row(identity='董事本人之配偶及未成年子女',name='',prev=90000,buy=0,sell=0)
        result = parse_detail(body([row(),anonymous]))
        self.assertEqual((result['buy_shares'],result['sell_shares']),(3000,1000))
        self.assertEqual(result['unchanged_unidentified_rows_excluded_from_trade_totals'],1)
        self.assertFalse(result['original_holder_account_identity_certified'])
        for index in (8,9,10,11,12,13,14,15,16,17):
            changed=list(anonymous);changed[index]='100'
            with self.subTest(column=index),self.assertRaises(ValueError):
                parse_detail(body([changed,row()]))

    def test_named_representative_personal_trades_and_duplicate_manager_role(self):
        rep = row(identity='董事之法人代表人',name='同一位具名持有人')
        manager = list(rep);manager[0]='總經理本人'
        result=parse_detail(body([rep,manager]))
        self.assertEqual((result['buy_shares'],result['sell_shares']),(3000,1000))
        self.assertEqual(result['unique_display_keys'],1)
        self.assertEqual(result['named_representative_rows_included'],1)

    def test_schema_period_market_and_empty_responses_are_not_zero_trades(self):
        data=json.loads(body([row()]))
        data['result']['titles'][8]['sub'][0]['main']='設定質權股數'
        with self.assertRaisesRegex(ValueError,'COLUMN_LAYOUT'):
            parse_detail(json.dumps(data).encode())
        for month,market in [('2026-08','TWSE'),('2026-09','TPEX')]:
            with self.subTest(month=month,market=market),self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):
                parse_detail(body([row()]),month,market)
        with self.assertRaisesRegex(ValueError,'NOT_ZERO'):
            parse_detail(body([]))

    def test_real_saved_originals_recover_only_unambiguous_trade_totals(self):
        zero=parse_detail(actual_original('1256'),'2026-09','TWSE')
        self.assertEqual((zero['buy_shares'],zero['sell_shares']),(0,0))
        self.assertEqual(zero['unchanged_unidentified_rows_excluded_from_trade_totals'],13)
        positive=parse_detail(actual_original('1713'),'2026-09','TWSE')
        self.assertEqual((positive['buy_shares'],positive['sell_shares']),(229000,0))
        linked=parse_detail(actual_original('1231'),'2026-09','TWSE')
        self.assertEqual((linked['buy_shares'],linked['sell_shares']),(0,80000))
        self.assertFalse(linked['original_holder_account_identity_certified'])

    def test_reparse_saved_failure_uses_no_http_and_preserves_capture_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);month='2026-09';code='1256'
            failed=base/'failed'/month/(code+'.json')
            rec=save_original(failed,actual_original(code),MOPS_URL,month)
            master={code:dict(market='TWSE',issued_shares=1000000)}
            getter=Mock(side_effect=AssertionError('network must not be used'))
            state=capture_details(base,[month],master,0,gap=0,getter=getter)
            getter.assert_not_called();self.assertEqual(state['recovered_from_saved_originals'],1)
            active=json.loads((base/'detail'/month/(code+'.json')).read_text())
            self.assertEqual(active['first_captured_at'],rec['first_captured_at'])
            self.assertEqual(active['sha256'],rec['sha256'])
            self.assertEqual(active['normalizer'],NORMALIZER)
            self.assertFalse(active['request_payload_archived'])
            self.assertGreaterEqual(active['normalization_available_at'],rec['fetched_at'])
            cutoff=dt.datetime.fromisoformat(rec['fetched_at'])-dt.timedelta(seconds=1)
            self.assertEqual(build_ranking(base,[month],master,cutoff)['verified_detail_month_count'],0)

    def test_existing_stale_normalization_is_rebuilt_and_revision_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);month='2026-09';code='1234'
            record=base/'detail'/month/(code+'.json')
            raw=body([row(identity='董事之法人代表人')])
            rec=save_original(record,raw,MOPS_URL,month)
            old=dict(rec,code=code,month=month,market='TWSE',buy_shares=0,sell_shares=0)
            put_json(record,old)
            getter=Mock(side_effect=AssertionError('network must not be used'))
            master={code:dict(market='TWSE',issued_shares=1000000)}
            state=capture_details(base,[month],master,0,gap=0,getter=getter)
            getter.assert_not_called();self.assertEqual(state['renormalized_existing_details'],1)
            active=json.loads(record.read_text());self.assertEqual(active['buy_shares'],3000)
            history=list((record.parent/'normalization_history'/code).glob('*.json'))
            self.assertEqual(len(history),1);self.assertEqual(json.loads(history[0].read_text()),old)
            next_state=capture_details(base,[month],master,0,gap=0,getter=getter)
            self.assertEqual(next_state['renormalized_existing_details'],0)

    def test_ambiguous_saved_failure_remains_pending_and_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);month='2026-09';code='1231'
            orphan=body([row(identity='董事本人之配偶及未成年子女',name='',buy=100,sell=0)])
            save_original(base/'failed'/month/(code+'.json'),orphan,MOPS_URL,month)
            getter=Mock(side_effect=AssertionError('network must not be used'))
            master={code:dict(market='TWSE',issued_shares=1000000)}
            state=capture_details(base,[month],master,0,gap=0,getter=getter)
            getter.assert_not_called();self.assertEqual(state['recovered_from_saved_originals'],0)
            self.assertEqual(state['cached_reparse_error_count'],1)
            self.assertEqual(build_ranking(base,[month],master)['verified_detail_month_count'],0)
            self.assertFalse((base/'detail'/month/(code+'.json')).exists())

    def test_changed_source_version_does_not_inherit_old_first_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'1234.json'
            old=save_original(path,body([row()]),MOPS_URL,'2026-09')
            old['first_captured_at']='2026-01-01T00:00:00+00:00'
            same=save_original(path,body([row()]),MOPS_URL,'2026-09',old)
            self.assertEqual(same['first_captured_at'],old['first_captured_at'])
            new=save_original(path,body([row(buy=4000)]),MOPS_URL,'2026-09',old)
            self.assertNotEqual(new['first_captured_at'],old['first_captured_at'])

    def test_family_aggregate_that_matches_named_own_account_is_not_counted_twice(self):
        named=row(name='具名董事配偶',buy=500,sell=0)
        parent=row(name='另一位董事',buy=0,sell=0)
        family=row(identity='董事本人之配偶及未成年子女',name='',buy=500,sell=0)
        with self.assertRaisesRegex(ValueError,'FAMILY_NAMED_HOLDER_OVERLAP'):
            parse_detail(body([named,parent,family]))

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

if __name__ == "__main__":
    unittest.main()
