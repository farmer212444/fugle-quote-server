"""Synthetic-only offline tests of exchange notice recovery; never PIT verification."""
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest

from alphamax.benchmark_0050_notice_receipts import (
    NOTICES, _url, capture_notices, parse_notice,
)


def source_html(event):
    _name, day, _type, kind, ex_date, pay_date, cash = event
    spoken = f"{day[:4]}.{day[4:6]}.{day[6:]}"
    if kind == "split":
        body = ("本公司公告元大台灣卓越50證券投資信託基金 0050 分割比率"
                "（分割後受益權單位數/分割前受益權單位數）：4"
                " 受益憑證最後交易日期：114年6月10日"
                " 新受益憑證上市買賣日：114年6月18日")
    else:
        body = (f"元大台灣卓越50基金 證券代碼0050 收益分配 每受益權單位"
                f"實際配發金額為新臺幣{cash}元；除息交易日:{ex_date}；"
                f"收益分配發放日:{pay_date}")
    return (f"<html><body><table><tr><td>發言日期</td><td>{spoken}</td>"
            f"<td>發言時間</td><td>15:14:16</td></tr></table>"
            f"<p>{body}</p></body></html>").encode("utf-8")


class NoticeReceiptTests(unittest.TestCase):
    def test_each_pinned_event_has_a_valid_historical_filing_fixture(self):
        self.assertEqual(len(NOTICES), 6)
        for event in NOTICES:
            with self.subTest(event=event[0]):
                r = parse_notice(source_html(event), event)
                self.assertEqual(r["issuer"], "0050")
                self.assertFalse(
                    not r["reported_at_is_recovered_page_field_not_archived_asof_receipt"])

    def test_all_six_original_bytes_are_saved_with_hashes_and_no_certification(self):
        responses = {_url(x[1], x[2]): source_html(x) for x in NOTICES}
        with tempfile.TemporaryDirectory() as temp:
            r = capture_notices(temp, fetch=lambda url: responses[url],
                                captured_at="2026-11-22T11:00:00+00:00")
            self.assertEqual(r["attempted"], 6)
            self.assertEqual(r["receipt_verified_count"], 6)
            self.assertEqual(r["status"], "RETROSPECTIVE_NOTICE_RECEIPTS_CAPTURED_NOT_PIT")
            self.assertFalse(r["asof_publication_snapshot_verified"])
            self.assertFalse(r["investor_total_return_verified"])
            self.assertEqual(r["matured_12m_costed_oos_verified"], 0)
            for e in r["events"]:
                original = (Path(temp) / e["original_relative_path"]).read_bytes()
                self.assertEqual(sha256(original).hexdigest(), e["original_sha256"])
                self.assertFalse(e["independent_asof_publication_snapshot_verified"])
            self.assertTrue((Path(temp) / "capture-manifest.json").is_file())

    def test_wrong_payout_or_wrong_issuer_fails_closed(self):
        event = next(e for e in NOTICES if e[0] == "dividend_20250115")
        data = source_html(event)
        with self.assertRaisesRegex(ValueError, "WRONG_SECURITY"):
            parse_notice(data.replace("0050".encode(), "0056".encode()), event)
        with self.assertRaisesRegex(ValueError, "DISTRIBUTION_CASH_NOT_CONFIRMED"):
            parse_notice(data.replace("2.7".encode(), "0.675".encode()), event)
        with self.assertRaisesRegex(ValueError, "REPORT_DATE_NOT_MATCHED"):
            parse_notice(data.replace("2025.01.15".encode(), "2025.01.16".encode()), event)

    def test_dividend_text_may_omit_ticker_but_not_legal_issuer_name(self):
        event = next(e for e in NOTICES if e[0] == "dividend_20250717")
        body = source_html(event)
        without_ticker = body.replace("證券代碼0050".encode(), b"")
        self.assertEqual(parse_notice(without_ticker, event)["issuer"], "0050")
        with self.assertRaisesRegex(ValueError, "NOTICE_WRONG_SECURITY"):
            parse_notice(without_ticker.replace(
                "元大台灣卓越50".encode(), "元大台灣高股息".encode()), event)

    def test_missing_announcement_must_be_reported_blocked(self):
        responses = {_url(e[1], e[2]): source_html(e) for e in NOTICES}
        missing = NOTICES[-1]
        del responses[_url(missing[1], missing[2])]
        def fetch(url):
            if url not in responses:
                raise ValueError("OFFICIAL_ORIGINAL_UNAVAILABLE")
            return responses[url]
        with tempfile.TemporaryDirectory() as temp:
            r = capture_notices(temp, fetch=fetch)
            self.assertEqual(r["status"], "BLOCKED_0050_NOTICE_SOURCE_INCOMPLETE")
            self.assertEqual(r["receipt_verified_count"], 5)
            self.assertEqual(r["events"][-1]["status"], "BLOCKED_NOTICE_CAPTURE_OR_VALIDATION")
            self.assertFalse(r["split_and_dividend_adjusted"])


if __name__ == "__main__":
    unittest.main()
