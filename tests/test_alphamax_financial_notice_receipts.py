"""Synthetic regressions for index/detail binding, receipts and clock limits."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from alphamax.core import ContractError
from alphamax.financial_notice_receipts import (
    EVENTS, URL, audit_archive, canonical, capture_pilot, detail_form,
    parse_detail, query_form, roc_day,
)


def event_fixture(index=1):
    event = dict(EVENTS[index], id="synthetic_" + str(index), code="0001", company="SYNTHETIC")
    if index == 1:
        event.update(expected_before_shares=123, expected_after_shares=456)
    return event


def index_fixture(event):
    q = query_form(event)
    hidden = {k: q[k] for k in ("year", "month", "b_date", "e_date")}
    hidden.update(firstin="true", step="2", off="1", TYPEK="", co_id="",
                  seq_no="", spoke_date="", spoke_time="", MODEL="", ITEM="")
    fields = {"seq_no": "1", "spoke_time": event["time"].replace(":", ""),
              "spoke_date": event["date"].replace("-", ""), "co_id": event["code"],
              "TYPEK": event["market"]}
    onclick = "document.t05st01_fm.action='ajax_t05st01';" + "".join(
        f"document.t05st01_fm.{k}.value='{v}';" for k, v in fields.items()) + "openWindow(this.form,'');"
    inputs = "".join(f"<input type='hidden' name='{k}' value='{v}'>" for k, v in hidden.items())
    cells = "".join("<td>" + x + "</td>" for x in (
        event["code"], event["company"], roc_day(event["date"]), event["time"], event["title"]))
    return (f"<form name='t05st01_fm' action='/mops/web/ajax_t05st01'>{inputs}"
            f"<table><tr>{cells}<td><input type='button' value='詳細資料' onclick=\"{onclick}\"></td>"
            "</tr></table></form>").encode()


def detail_fixture(event):
    venue = "上櫃公司"
    if event["kind"] == "ixbrl_correction":
        description = (
            "母公司暨子公司所持有之母公司庫藏股股數 "
            "6.更正資訊:更正iXBRL114年第2季資產負債表 "
            f"7.更正前金額/內容/頁次:股數(單位:股)：{event['expected_before_shares']:,} "
            f"8.更正後金額/內容/頁次:股數(單位:股)：{event['expected_after_shares']:,} "
            "9.因應措施:重新上傳"
        )
    else:
        description = "SYNTHETIC board financial release"
    fields = {"序號": "1", "發言日期": roc_day(event["date"]), "發言時間": event["time"],
              "主旨": event["title"], "說明": description}
    return (f"<h4>本資料由 ({venue}) {event['code']} {event['company']} 公司提供</h4><table>"
            + "".join(f"<tr><td>{k}</td><td><pre>{v}</pre></td></tr>" for k, v in fields.items())
            + "</table><script>FAKE ignored</script>").encode()


class FinancialNoticeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.event = event_fixture()
        self.raw_index = index_fixture(self.event)
        self.form = detail_form(self.raw_index, self.event)

    def test_query_uses_official_date_range_names(self):
        form = query_form(self.event)
        self.assertEqual((form["b_date"], form["e_date"]), ("14", "14"))
        self.assertNotIn("date1", form)
        self.assertNotIn("date2", form)

    def test_detail_request_preserves_parent_hidden_year_month_and_step(self):
        self.assertEqual(self.form["firstin"], "true")
        self.assertEqual((self.form["year"], self.form["month"], self.form["step"]), ("114", "08", "2"))
        self.assertEqual(self.form["spoke_time"], "153702")

    def test_index_is_not_accepted_as_notice_full_text(self):
        with self.assertRaises(ContractError):
            parse_detail(self.raw_index, self.event, self.form)

    def test_before_after_values_do_not_absorb_next_section_number(self):
        result = parse_detail(detail_fixture(self.event), self.event, self.form)
        self.assertEqual((result["before_shares"], result["after_shares"]), (123, 456))
        self.assertIsNone(result["prior_value_historical_available_at"])
        self.assertFalse(result["corrected_ixbrl_upload_time_verified"])

    def test_wrong_detail_time_is_rejected_despite_correct_time_in_other_text(self):
        raw = detail_fixture(self.event).replace(b"<pre>15:37:02</pre>", b"<pre>15:37:03</pre>")
        with self.assertRaisesRegex(ContractError, "FIELDS_DISAGREE"):
            parse_detail(raw + b"15:37:02", self.event, self.form)

    def test_wrong_issuer_in_detail_is_rejected(self):
        raw = detail_fixture(self.event).replace(b"0001", b"0002", 1)
        with self.assertRaisesRegex(ContractError, "ISSUER_OR_MARKET"):
            parse_detail(raw, self.event, self.form)

    def test_changed_correction_value_is_rejected(self):
        raw = detail_fixture(self.event).replace(b"456", b"457")
        with self.assertRaisesRegex(ContractError, "VALUES_CHANGED"):
            parse_detail(raw, self.event, self.form)

    def test_wrong_fiscal_period_is_rejected(self):
        raw = detail_fixture(self.event).replace("114年第2季資產負債表".encode(), "114年第3季資產負債表".encode())
        with self.assertRaisesRegex(ContractError, "FISCAL_PERIOD"):
            parse_detail(raw, self.event, self.form)

    def test_external_button_action_is_never_followed(self):
        raw = self.raw_index.replace(b"action='ajax_t05st01'", b"action='https://invalid.example/'")
        with self.assertRaisesRegex(ContractError, "BUTTON_ACTION"):
            detail_form(raw, self.event)

    def test_button_identity_must_match_the_visible_index_row(self):
        raw = self.raw_index.replace(b"spoke_date.value='20250814'", b"spoke_date.value='20250815'")
        with self.assertRaisesRegex(ContractError, "BUTTON_IDENTITY"):
            detail_form(raw, self.event)

    def test_duplicate_target_rows_are_rejected(self):
        with self.assertRaises(ContractError):
            detail_form(self.raw_index + self.raw_index, self.event)

    def test_duplicate_detail_clock_is_rejected(self):
        raw = detail_fixture(self.event) + "<table><tr><td>發言時間</td><td>15:37:02</td></tr></table>".encode()
        with self.assertRaisesRegex(ContractError, "DUPLICATE_NOTICE_DETAIL_FIELD"):
            parse_detail(raw, self.event, self.form)

    def capture(self, root, events=None, failed_detail=False):
        events = [self.event] if events is None else events
        def fetch(url, form):
            self.assertEqual(url, URL)
            day = form["spoke_date"][-2:] if form["step"] == "2" else form["b_date"]
            event = next(e for e in events if e["date"].endswith(day))
            if form["step"] == "1":
                return index_fixture(event)
            return b"<html>empty response</html>" if failed_detail else detail_fixture(event)
        return capture_pilot(root, events=events, fetch=fetch)

    def test_two_notices_replay_from_four_original_receipts_without_pit_admission(self):
        events = [event_fixture(0), self.event]
        with tempfile.TemporaryDirectory() as root:
            self.capture(root, events)
            report = audit_archive(root, events=events)
            manifest = json.loads((Path(root) / "capture-manifest.json").read_bytes())
        self.assertEqual(len(manifest["receipts"]), 4)
        self.assertEqual(report["verified_notices"], 2)
        self.assertEqual(report["admitted_historical_PIT_batches"], 0)
        self.assertFalse(report["as_published_historical_snapshot_verified"])
        self.assertTrue(all(not e["original_filing_time_verified"] for e in report["events"]))

    def test_rejected_detail_html_is_preserved_for_diagnosis(self):
        with tempfile.TemporaryDirectory() as root:
            report = self.capture(root, failed_detail=True)
            manifest = json.loads((Path(root) / "capture-manifest.json").read_bytes())
            self.assertEqual(len(manifest["receipts"]), 2)
            self.assertTrue(all((Path(root) / r["original_path"]).exists() for r in manifest["receipts"]))
        self.assertEqual(report["verified_notices"], 0)

    def test_altered_original_bytes_block_offline_audit(self):
        with tempfile.TemporaryDirectory() as root:
            self.capture(root)
            manifest = json.loads((Path(root) / "capture-manifest.json").read_bytes())
            (Path(root) / manifest["receipts"][1]["original_path"]).write_bytes(b"tampered")
            report = audit_archive(root, events=[self.event])
        self.assertEqual(report["verified_notices"], 0)
        self.assertIn("HASH_MISMATCH", report["errors"][0]["reason"])

    def test_changed_request_receipt_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as root:
            self.capture(root)
            path = Path(root) / "capture-manifest.json"
            manifest = json.loads(path.read_bytes())
            manifest["receipts"][1]["request_form"]["year"] = "113"
            path.write_bytes(canonical(manifest))
            report = audit_archive(root, events=[self.event])
        self.assertEqual(report["verified_notices"], 0)
        self.assertIn("RECEIPT_FORM_MISMATCH", report["errors"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
