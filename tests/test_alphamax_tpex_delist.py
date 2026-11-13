"""Synthetic-only TPEx historical delisting capture regressions."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from alphamax.core import ContractError
from alphamax.tpex_delist_ledger import (
    OLD_URL, capture_tpex_delist, parse_tpex_html, parse_tpex_json,
)

NOW = "2026-11-11T01:00:00+00:00"
HEADER = "<tr><th>代號</th><th>名稱</th><th>終止上櫃日期</th><th>原因</th></tr>"
DATA1 = "<tr><td>6747</td><td><a>亨泰光</a></td><td>114/12/04</td><td>股份轉換</td></tr>"
DATA2 = "<tr><td>4739</td><td><a>康普</a></td><td>106/07/10</td><td>轉上市</td></tr>"
DATA3 = "<tr><td>1234</td><td>示例公司</td><td>115/10/01</td><td>其他</td></tr>"


def page(*trs):
    return ("<html><body><table>"+HEADER+"".join(trs)+"</table></body></html>").encode()


class TpexDelistTests(unittest.TestCase):
    def test_dates_and_transfer_not_failure(self):
        obj=parse_tpex_html(page(DATA1,DATA2),OLD_URL,NOW)
        self.assertEqual(obj["record_count"],2)
        self.assertEqual(obj["records_with_explicit_termination_date"],2)
        self.assertEqual(obj["event_rows"][0]["termination_effective_date"],"2025-12-04")
        self.assertEqual(obj["event_rows"][1]["termination_effective_date"],"2017-07-10")
        self.assertIs(obj["event_rows"][1]["transfer_vs_actual_death_verified"],False)
        self.assertFalse(obj["investment_certified"])

    def test_missing_dates_not_fabricated(self):
        obj=parse_tpex_html(page(DATA1.replace("114/12/04","")),OLD_URL,NOW)
        self.assertEqual(obj["record_count"],1)
        self.assertEqual(obj["records_with_explicit_termination_date"],0)
        self.assertIsNone(obj["event_rows"][0]["termination_effective_date"])

    def test_conflicting_dates_block(self):
        obj=page(DATA1.replace("<td>股份轉換</td>","<td>115/01/01</td>"))
        with self.assertRaisesRegex(ContractError,"CONFLICTING"):
            parse_tpex_html(obj,OLD_URL,NOW)

    def test_future_event_block(self):
        with self.assertRaisesRegex(ContractError,"FUTURE"):
            parse_tpex_html(page(DATA3.replace("115/10/01","116/01/01")),OLD_URL,NOW)

    def test_missing_table_block(self):
        with self.assertRaisesRegex(ContractError,"NO_RECOGNIZED"):
            parse_tpex_html(b"<html><body>no records</body></html>",OLD_URL,NOW)

    def test_duplicate_block(self):
        with self.assertRaisesRegex(ContractError,"DUPLICATE"):
            parse_tpex_html(page(DATA1,DATA1),OLD_URL,NOW)

    def test_json_explicit_fields(self):
        raw=json.dumps({"stat":"ok","tables":[{
            "fields":["證券代號","證券名稱","終止上櫃日期","終止原因"],
            "data":[["6747","亨泰光","114/12/04","股份轉換"]]
        }]},ensure_ascii=False).encode()
        out=parse_tpex_json(raw,NOW)
        self.assertEqual(out["record_count"],1)
        self.assertEqual(out["records_with_explicit_termination_date"],1)
        self.assertFalse(out["source_publication_time_verified"])

    def test_six_digit_tpex_history_code_kept_but_class_not_certified(self):
        raw=json.dumps({"date":"2021","stat":"ok","tables":[{
            "fields":["股票代號","公司名稱","終止上櫃日期","終止上櫃原因"],
            "data":[["911613","特藝石油能源有限公司","110-09-03","依規定終止上櫃"]],
            "totalCount":1
        }]},ensure_ascii=False).encode()
        out=parse_tpex_json(raw,NOW)
        self.assertEqual(out["record_count"],1)
        self.assertEqual(out["event_rows"][0]["code"],"911613")
        self.assertTrue(out["event_rows"][0]["security_class_review_required"])
        self.assertIs(out["event_rows"][0]["announced_at_pit_verified"],False)

    def test_json_missing_dates_block(self):
        raw=json.dumps({"stat":"ok","tables":[{
            "fields":["證券代號","證券名稱","原因"],"data":[["6747","亨泰光","合併"]]
        }]},ensure_ascii=False).encode()
        with self.assertRaisesRegex(ContractError,"NO_MATCHING"):
            parse_tpex_json(raw,NOW)

    def test_two_pages_and_repetition_is_not_full_certification(self):
        with TemporaryDirectory() as tmp:
            calls=[]
            def fetch(n):
                calls.append(n)
                return page(DATA1) if n==1 else page(DATA2) if n==2 else page(DATA2)
            result=capture_tpex_delist(tmp,captured_at_utc=NOW,legacy_fetch=fetch,
                                      modern_fetch=lambda: (_ for _ in ()).throw(AssertionError("not needed")),page_limit=6)
            self.assertEqual(calls,[1,2,3])
            self.assertEqual(result["event_count"],2)
            self.assertTrue(result["legacy_pagination_exhaustion_verified"])
            self.assertEqual(len(result["source_receipts"]),2)
            self.assertTrue(Path(tmp,"tpex-old-page-01.html").exists())
            self.assertFalse(result["full_history_coverage_verified"])
            self.assertFalse(result["investment_certified"])

    def test_modern_fallback_when_legacy_failed(self):
        raw=json.dumps({"stat":"ok","tables":[{
            "fields":["證券代號","證券名稱","終止上櫃日期"],
            "data":[["6747","亨泰光","114/12/04"]]
        }]},ensure_ascii=False).encode()
        with TemporaryDirectory() as tmp:
            out=capture_tpex_delist(tmp,captured_at_utc=NOW,page_limit=1,
                legacy_fetch=lambda _: (_ for _ in ()).throw(OSError("synthetic 403")),
                modern_fetch=lambda:raw)
            self.assertEqual(out["event_count"],1)
            self.assertTrue(Path(tmp,"tpex-modern-raw.json").exists())
            self.assertFalse(out["investment_certified"])

    def test_all_sources_rejected_blocks(self):
        with TemporaryDirectory() as tmp:
            out=capture_tpex_delist(tmp,captured_at_utc=NOW,page_limit=1,
                legacy_fetch=lambda _: (_ for _ in ()).throw(OSError("synthetic 403")),
                modern_fetch=lambda: (_ for _ in ()).throw(OSError("synthetic 403")),
                page_fetch=lambda: b'<html><body>synthetic official page only</body></html>')
            self.assertEqual(out["event_count"],0)
            self.assertEqual(out["status"],"BLOCKED_TPEX_DELIST_SOURCE_NOT_PARSED")
            self.assertTrue(Path(tmp,"capture-manifest.json").exists())

    def test_official_page_action_probe_preserves_raw_and_remains_blocked(self):
        with TemporaryDirectory() as tmp:
            raw=b'<html><script>tables.init({ action: "mainboard/listed/delisted" });</script></html>'
            out=capture_tpex_delist(tmp,captured_at_utc=NOW,page_limit=1,
                legacy_fetch=lambda _: (_ for _ in ()).throw(OSError("synthetic")),
                modern_fetch=lambda: (_ for _ in ()).throw(OSError("synthetic")),
                page_fetch=lambda: raw)
            self.assertEqual(out["event_count"],0)
            self.assertEqual(out["status"],"BLOCKED_TPEX_DELIST_SOURCE_NOT_PARSED")
            self.assertIn("mainboard/listed/delisted",
                          out["unparsed_source_discovery"]["current_official_page"]["embedded_actions"])
            self.assertEqual(Path(tmp,"tpex-current-public-page.html").read_bytes(),raw)

    @staticmethod
    def mock_year_json(year):
        code = str(3000 + year - 2020)
        return json.dumps({"date":str(year),"stat":"ok","tables":[{
            "fields":["股票代號","公司名稱","終止上櫃日期","終止上櫃原因"],
            "data":[[code,"合成測試公司",f"{year-1911}/06/01","轉上市"]],
            "totalCount":1
        }]},ensure_ascii=False).encode()

    def test_2021_to_2026_bounded_year_ledger_only_after_all_year_receipts(self):
        with TemporaryDirectory() as tmp:
            with patch("alphamax.tpex_delist_ledger._fetch_modern",
                       return_value=self.mock_year_json(2026)):
                with patch("alphamax.tpex_delist_ledger._fetch_year",
                           side_effect=lambda year: self.mock_year_json(year)):
                    out = capture_tpex_delist(
                        tmp, captured_at_utc=NOW, page_limit=1,
                        legacy_fetch=lambda _: (_ for _ in ()).throw(OSError("legacy down")))
            self.assertEqual(out["verified_annual_slices"],list(range(2021,2027)))
            self.assertTrue(out["bounded_2021_2026_window_complete"])
            self.assertEqual(out["event_count"],6)
            self.assertFalse(out["full_history_coverage_verified"])
            self.assertFalse(out["investment_certified"])
            self.assertEqual(len(out["source_receipts"]),6)
            self.assertTrue(Path(tmp,"tpex-year-2021-probe.json").exists())

    def test_wrong_year_echo_is_not_accepted_or_fabricated(self):
        with TemporaryDirectory() as tmp:
            with patch("alphamax.tpex_delist_ledger._fetch_modern",
                       return_value=self.mock_year_json(2026)):
                with patch("alphamax.tpex_delist_ledger._fetch_year",
                           side_effect=lambda year: self.mock_year_json(2026) if year==2024 else self.mock_year_json(year)):
                    out = capture_tpex_delist(
                        tmp, captured_at_utc=NOW,page_limit=1,
                        legacy_fetch=lambda _: (_ for _ in ()).throw(OSError("legacy down")))
            self.assertNotIn(2024,out["verified_annual_slices"])
            self.assertEqual(out["event_count"],5)
            self.assertFalse(out["bounded_2021_2026_window_complete"])
            self.assertFalse(out["investment_certified"])

    def test_bad_capture_timezone_blocks(self):
        with self.assertRaisesRegex(ContractError,"TZ_REQUIRED"):
            capture_tpex_delist("/tmp/missing",captured_at_utc="2026-11-11T01:00:00",page_limit=1)


if __name__=="__main__":
    unittest.main()
