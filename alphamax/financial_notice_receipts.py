"""Bind historical MOPS notice indexes to detail originals; never backdate filings."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from alphamax.core import ContractError

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
SCHEMA = "ALPHAMAX_HISTORICAL_FINANCIAL_NOTICE_RECEIPTS_V1"
MAX_BYTES = 2_000_000
TZ = timezone(timedelta(hours=8))
EVENTS = (
    {"id": "6967_2025q2_board", "code": "6967", "company": "汎瑋材料",
     "market": "otc", "kind": "board_financial_release", "period": "2025Q2",
     "date": "2025-08-13", "time": "14:01:48",
     "title": "公告本公司董事會通過114年第二季合併財務報告"},
    {"id": "6967_2025q2_correction", "code": "6967", "company": "汎瑋材料",
     "market": "otc", "kind": "ixbrl_correction", "period": "2025Q2",
     "date": "2025-08-14", "time": "15:37:02",
     "title": "更正本公司114年第二季合併財務報告iXBRL申報資訊",
     "expected_before_shares": 25637, "expected_after_shares": 500000},
)


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def roc_day(value):
    d = date.fromisoformat(value)
    return f"{d.year - 1911:03d}/{d.month:02d}/{d.day:02d}"


class Page(HTMLParser):
    """Read visible table cells and form assignments without executing scripts."""
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
            raise ContractError("INVALID_NOTICE_RESPONSE_SIZE")
        self.rows, self.text, self.forms = [], [], {}
        self.row, self.cell, self.form, self.skip = None, None, None, 0
        self.feed(raw.decode("utf-8-sig"))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if self.skip:
            return
        if tag == "form":
            self.form = a.get("name")
            if self.form == "t05st01_fm":
                if self.form in self.forms:
                    raise ContractError("DUPLICATE_NOTICE_DETAIL_FORM")
                self.forms[self.form] = {"action": a.get("action"), "hidden": {}}
        if tag == "input" and self.form == "t05st01_fm" and a.get("type") == "hidden":
            name = a.get("name")
            if name in self.forms[self.form]["hidden"]:
                raise ContractError("DUPLICATE_NOTICE_FORM_FIELD")
            self.forms[self.form]["hidden"][name] = a.get("value") or ""
        if tag == "tr":
            self.row = {"cells": [], "buttons": []}
        if tag in ("td", "th") and self.row is not None:
            self.cell = []
        if tag == "input" and self.row is not None and a.get("value") == "詳細資料":
            self.row["buttons"].append(a)

    def handle_data(self, data):
        if self.skip:
            return
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row["cells"].append(compact("".join(self.cell)))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == "form":
            self.form = None


def query_form(event):
    d = date.fromisoformat(event["date"])
    return {"encodeURIComponent": "1", "step": "1", "firstin": "1",
            "off": "1", "TYPEK": "all", "co_id": event["code"],
            "year": str(d.year - 1911), "month": f"{d.month:02d}",
            "b_date": f"{d.day:02d}", "e_date": f"{d.day:02d}",
            "queryName": "co_id", "inpuType": "co_id"}


def detail_form(raw, event):
    page = Page(raw)
    expected = [event["code"], event["company"], roc_day(event["date"]),
                event["time"], event["title"]]
    matches = [r for r in page.rows if r["cells"][:5] == [compact(x) for x in expected]]
    if len(matches) != 1 or len(matches[0]["buttons"]) != 1:
        raise ContractError("UNIQUE_TARGET_NOTICE_INDEX_ROW_REQUIRED")
    holder = page.forms.get("t05st01_fm")
    if not holder or holder["action"] not in ("ajax_t05st01", "/mops/web/ajax_t05st01"):
        raise ContractError("UNEXPECTED_NOTICE_FORM_ACTION")
    base = dict(holder["hidden"])
    q = query_form(event)
    if any(base.get(k) != q[k] for k in ("year", "month", "b_date", "e_date")):
        raise ContractError("NOTICE_INDEX_QUERY_RANGE_MISMATCH")
    if base.get("step") != "2" or base.get("off") != "1":
        raise ContractError("NOTICE_DETAIL_FORM_NOT_STEP_TWO")
    onclick = matches[0]["buttons"][0].get("onclick", "")
    action = re.findall(r"document\.t05st01_fm\.action\s*=\s*['\"]([^'\"]+)['\"]", onclick)
    if action != ["ajax_t05st01"]:
        raise ContractError("UNEXPECTED_NOTICE_BUTTON_ACTION")
    pairs = re.findall(r"document\.t05st01_fm\.([A-Za-z_]+)\.value\s*=\s*['\"]([^'\"]*)['\"]", onclick)
    keys = {"seq_no", "spoke_time", "spoke_date", "co_id", "TYPEK"}
    if {k for k, _ in pairs} != keys or len(pairs) != len(keys):
        raise ContractError("INVALID_NOTICE_DETAIL_ASSIGNMENTS")
    fields = dict(pairs)
    if (fields["co_id"] != event["code"] or fields["TYPEK"] != event["market"]
            or fields["spoke_date"] != event["date"].replace("-", "")
            or fields["spoke_time"] != event["time"].replace(":", "")
            or not re.fullmatch(r"[1-9][0-9]*", fields["seq_no"])):
        raise ContractError("NOTICE_INDEX_BUTTON_IDENTITY_MISMATCH")
    base.update(fields)
    return base


def parse_detail(raw, event, form):
    page = Page(raw)
    venue = {"otc": "上櫃公司", "sii": "上市公司"}[event["market"]]
    heading = compact(f"本資料由({venue}){event['code']}{event['company']}公司提供")
    if heading not in compact("".join(page.text)):
        raise ContractError("NOTICE_DETAIL_ISSUER_OR_MARKET_MISMATCH")
    wanted = {"序號", "發言日期", "發言時間", "主旨", "說明"}
    fields = {}
    for row in page.rows:
        cells = row["cells"]
        for i, value in enumerate(cells[:-1]):
            if value in wanted:
                if value in fields:
                    raise ContractError("DUPLICATE_NOTICE_DETAIL_FIELD")
                fields[value] = cells[i + 1]
    expected = {"序號": form["seq_no"], "發言日期": roc_day(event["date"]),
                "發言時間": event["time"], "主旨": event["title"]}
    if any(fields.get(k) != compact(v) for k, v in expected.items()) or not fields.get("說明"):
        raise ContractError("NOTICE_INDEX_DETAIL_FIELDS_DISAGREE")
    # This is the announcement's displayed clock, NOT an original filing clock.
    published = datetime.fromisoformat(event["date"] + "T" + event["time"]).replace(tzinfo=TZ)
    result = {"id": event["id"], "code": event["code"], "period": event["period"],
              "kind": event["kind"], "title": event["title"],
              "source_reported_announcement_at": published.isoformat(),
              "notice_index_detail_binding_verified": True,
              "original_filing_time_verified": False,
              "complete_revision_chain_verified": False}
    if event["kind"] == "ixbrl_correction":
        description = fields["說明"]
        if ("母公司暨子公司所持有之母公司庫藏股股數" not in description
                or "114年第2季資產負債表" not in description):
            raise ContractError("CORRECTION_SUBJECT_OR_FISCAL_PERIOD_MISMATCH")
        m = re.search(r"7\.更正前金額(.*?)8\.更正後金額(.*?)9\.因應措施", description)
        if not m:
            raise ContractError("CORRECTION_BEFORE_AFTER_FIELDS_MISSING")
        values = [re.search(r"股數\(單位:股\):([0-9,]+)", section) for section in m.groups()]
        if any(value is None for value in values):
            raise ContractError("CORRECTION_BEFORE_AFTER_FIELDS_MISSING")
        before, after = [int(value[1].replace(",", "")) for value in values]
        if (before, after) != (event["expected_before_shares"], event["expected_after_shares"]):
            raise ContractError("CORRECTION_BEFORE_AFTER_VALUES_CHANGED")
        result.update(before_shares=before, after_shares=after, unit="shares",
                      prior_value_historical_available_at=None,
                      corrected_ixbrl_upload_time_verified=False)
    return result


def post_official(url, form):
    if url != URL:
        raise ContractError("UNAPPROVED_NOTICE_SOURCE")
    request = Request(url, data=urlencode(form).encode(),
                      headers={"User-Agent": "Mozilla/5.0",
                               "Content-Type": "application/x-www-form-urlencoded"})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25) as response:
                if response.status != 200 or response.geturl().split("?")[0] != URL:
                    raise ContractError("UNEXPECTED_NOTICE_HTTP_RESPONSE")
                return response.read(MAX_BYTES + 1)
        except HTTPError as exc:
            if attempt or exc.code not in (502, 503, 504):
                raise
            exc.close()
            time.sleep(0.5)


def preserve(root, raw, event, stage, form):
    # Even rejected HTML is preserved before parsing for reproducible diagnosis.
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ContractError("INVALID_NOTICE_RESPONSE_SIZE")
    packed = gzip.compress(raw, mtime=0)
    original_sha = sha256(raw).hexdigest()
    relative = "originals/" + original_sha + ".html.gz"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and gzip.decompress(path.read_bytes()) != raw:
        raise ContractError("NOTICE_ORIGINAL_IMMUTABILITY_CONFLICT")
    if not path.exists():
        path.write_bytes(packed)
    return {"event_id": event["id"], "stage": stage, "source_url": URL,
            "method": "POST", "request_form": form,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "original_path": relative, "original_sha256": original_sha,
            "original_bytes": len(raw), "archive_sha256": sha256(path.read_bytes()).hexdigest()}


def reopen(root, receipt):
    relative = receipt["original_path"]
    if (receipt["source_url"] != URL or receipt["method"] != "POST"
            or not re.fullmatch(r"originals/[0-9a-f]{64}\.html\.gz", relative)
            or relative != "originals/" + receipt["original_sha256"] + ".html.gz"):
        raise ContractError("UNSAFE_OR_UNEXPECTED_NOTICE_RECEIPT")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ContractError("NOTICE_ORIGINAL_ESCAPES_ROOT")
    stamp = datetime.fromisoformat(receipt["observed_at"])
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise ContractError("INVALID_NOTICE_CAPTURE_CLOCK")
    packed = path.read_bytes()
    if sha256(packed).hexdigest() != receipt["archive_sha256"]:
        raise ContractError("NOTICE_ARCHIVE_HASH_MISMATCH")
    raw = gzip.decompress(packed)
    if len(raw) != receipt["original_bytes"] or sha256(raw).hexdigest() != receipt["original_sha256"]:
        raise ContractError("NOTICE_ORIGINAL_HASH_MISMATCH")
    return raw


def audit_archive(root, *, events=EVENTS):
    root = Path(root)
    manifest = json.loads((root / "capture-manifest.json").read_bytes())
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("receipts"), list):
        raise ContractError("INVALID_NOTICE_MANIFEST")
    verified, errors = [], []
    for event in events:
        try:
            rows = [r for r in manifest["receipts"] if r["event_id"] == event["id"]]
            stages = {stage: [r for r in rows if r["stage"] == stage] for stage in ("index", "detail")}
            if len(rows) != 2 or any(len(v) != 1 for v in stages.values()):
                raise ContractError("UNIQUE_NOTICE_INDEX_AND_DETAIL_RECEIPTS_REQUIRED")
            index, detail = stages["index"][0], stages["detail"][0]
            if index["request_form"] != query_form(event):
                raise ContractError("NOTICE_INDEX_RECEIPT_QUERY_MISMATCH")
            form = detail_form(reopen(root, index), event)
            if detail["request_form"] != form:
                raise ContractError("NOTICE_DETAIL_RECEIPT_FORM_MISMATCH")
            if datetime.fromisoformat(detail["observed_at"]) < datetime.fromisoformat(index["observed_at"]):
                raise ContractError("NOTICE_DETAIL_CAPTURE_PRECEDES_INDEX")
            verified.append(parse_detail(reopen(root, detail), event, form))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"event_id": event["id"], "reason": str(exc)})
    return {"schema": SCHEMA, "status": "RETROSPECTIVE_NOTICE_PAIRS_REVERIFIED_NOT_HISTORICAL_PIT"
            if len(verified) == len(events) else "BLOCKED_FINANCIAL_NOTICE_RECEIPTS",
            "verified_notices": len(verified), "events": verified, "errors": errors,
            "as_published_historical_snapshot_verified": False,
            "complete_revision_chain_verified": False, "admitted_historical_PIT_batches": 0,
            "formal_a_plus": False, "verified_model_oos_cohorts": 0}


def capture_pilot(root, *, fetch=post_official, events=EVENTS):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": SCHEMA, "receipts": [], "errors": []}
    for event in events:
        try:
            form = query_form(event)
            raw = fetch(URL, form)
            manifest["receipts"].append(preserve(root, raw, event, "index", form))
            form = detail_form(raw, event)
            raw = fetch(URL, form)
            manifest["receipts"].append(preserve(root, raw, event, "detail", form))
            parse_detail(raw, event, form)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            manifest["errors"].append({"event_id": event["id"], "reason": str(exc)})
    (root / "capture-manifest.json").write_bytes(canonical(manifest) + b"\n")
    report = audit_archive(root, events=events)
    report["capture_errors"] = manifest["errors"]
    (root / "audit-report.json").write_bytes(canonical(report) + b"\n")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args()
    report = audit_archive(args.output_dir) if args.verify_only else capture_pilot(args.output_dir)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
