#!/usr/bin/env python3
"""Official TWSE/TPEx institutional and TDCC ownership snapshots.

No third-party ranking input, no model/EPS/PE write, and no certification.
Only original official endpoint responses; unsuccessful sources are isolated.
"""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import html
import io
import json
import pathlib
import re
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

ROOT = pathlib.Path("tw-market-data/chip")
SOURCES = {
    "TWSE": "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={day}&selectType=ALL",
    "TPEX": "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
    "TDCC": "https://openapi.tdcc.com.tw/v1/opendata/1-5",
}
TWSE_FIELDS = {
    "code": "證券代號",
    "name": "證券名稱",
    "foreign": "外陸資買賣超股數(不含外資自營商)",
    "foreign_dealer": "外資自營商買賣超股數",
    "trust": "投信買賣超股數",
    "dealer": "自營商買賣超股數",
    "total": "三大法人買賣超股數",
}
TPEX_FIELDS = {
    "foreign": "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
    "foreign_dealer": "ForeignDealers-Difference",
    "trust": "SecuritiesInvestmentTrustCompanies-Difference",
    "dealer": "Dealers-Difference",
    "total": "TotalDifference",
}
TDCC_FIELDS = {"date": "資料日期", "code": "證券代號", "grade": "持股分級",
               "holders": "人數", "shares": "股數", "pct": "占集保庫存數比例%"}

def iso_date(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 7:
        digits = str(1911 + int(digits[:3])) + digits[3:]
    if len(digits) != 8:
        raise ValueError("INVALID_OFFICIAL_DATE: " + str(value)[:40])
    return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()

def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("MISSING_NUMERIC_CELL")
    s = str(value).replace(",", "").strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"\(\d+\)", s):
        return -int(s[1:-1])
    raise ValueError("INVALID_NUMERIC_CELL: " + s[:30])

def pct_number(value):
    s = str(value).replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        raise ValueError("INVALID_OWNERSHIP_PERCENT")
    v = float(s)
    if abs(v) > 100.01:
        raise ValueError("OWNERSHIP_PERCENT_OUT_OF_RANGE")
    return v

def ordinary(code):
    return bool(re.fullmatch(r"[1-9]\d{3}", str(code).strip()))

def parse_twse(obj):
    if not isinstance(obj, dict) or obj.get("stat") != "OK":
        raise ValueError("TWSE_NOT_OK_OR_NO_TRADING_SESSION")
    day = iso_date(obj.get("date"))
    fields = [re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html.unescape(str(f)))) for f in obj.get("fields", [])]
    indexes = {}
    for key, label in TWSE_FIELDS.items():
        try:
            indexes[key] = fields.index(label)
        except ValueError:
            if key == "foreign_dealer":
                indexes[key] = None
            else:
                raise ValueError("TWSE_MISSING_FIELD: " + label)
    if not isinstance(obj.get("data"), list):
        raise ValueError("TWSE_MISSING_ROWS")
    rows, seen = [], set()
    for raw in obj["data"]:
        if not isinstance(raw, (list, tuple)) or len(raw) < len(fields):
            raise ValueError("TWSE_ROW_SHAPE_CHANGED")
        code = str(raw[indexes["code"]]).strip()
        if not ordinary(code):
            continue
        if code in seen:
            raise ValueError("TWSE_DUPLICATE_CODE: " + code)
        seen.add(code)
        foreign = number(raw[indexes["foreign"]])
        trust = number(raw[indexes["trust"]])
        dealer = number(raw[indexes["dealer"]])
        reported = number(raw[indexes["total"]])
        fdealer = number(raw[indexes["foreign_dealer"]]) if indexes["foreign_dealer"] is not None else None
        computed = foreign + trust + dealer + fdealer if fdealer is not None else None
        rows.append(dict(market="TWSE", code=code, name=str(raw[indexes["name"]]).strip(),
                         date=day, foreign_ex_dealer_net_shares=foreign,
                         foreign_dealer_net_shares=fdealer, trust_net_shares=trust,
                         dealer_net_shares=dealer, official_total_net_shares=reported,
                         components_reconciled=computed == reported if computed is not None else None))
    if len(rows) < 300:
        raise ValueError("TWSE_ORDINARY_ISSUER_COVERAGE_TOO_LOW")
    return day, sorted(rows, key=lambda x: x["code"])

def parse_tpex(obj):
    if not isinstance(obj, list) or not obj:
        raise ValueError("TPEX_NOT_A_DATA_ARRAY")
    rows, seen, days = [], set(), set()
    required = ("Date", "SecuritiesCompanyCode", *TPEX_FIELDS.values())
    for raw in obj:
        if not isinstance(raw, dict) or any(k not in raw for k in required):
            raise ValueError("TPEX_SCHEMA_CHANGED")
        code = str(raw["SecuritiesCompanyCode"]).strip()
        if not ordinary(code):
            continue
        date = iso_date(raw["Date"])
        days.add(date)
        if code in seen:
            raise ValueError("TPEX_DUPLICATE_CODE: " + code)
        seen.add(code)
        foreign = number(raw[TPEX_FIELDS["foreign"]])
        trust = number(raw[TPEX_FIELDS["trust"]])
        dealer = number(raw[TPEX_FIELDS["dealer"]])
        foreign_dealer = number(raw[TPEX_FIELDS["foreign_dealer"]])
        total = number(raw[TPEX_FIELDS["total"]])
        rows.append(dict(market="TPEX", code=code,
                         name=str(raw.get("SecuritiesCompanyName") or raw.get("CompanyName") or "").strip(),
                         date=date, foreign_ex_dealer_net_shares=foreign,
                         foreign_dealer_net_shares=foreign_dealer,
                         trust_net_shares=trust, dealer_net_shares=dealer,
                         official_total_net_shares=total,
                         components_reconciled=(total == foreign + foreign_dealer + trust + dealer)))
    if len(rows) < 300 or len(days) != 1:
        raise ValueError("TPEX_LOW_COVERAGE_OR_MIXED_DATES")
    return next(iter(days)), sorted(rows, key=lambda x: x["code"])

def decode_tdcc(raw):
    if not raw or len(raw) > 35000000:
        raise ValueError("TDCC_SIZE_INVALID")
    for enc in ("utf-8-sig", "cp950"):
        try:
            s = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("TDCC_ENCODING_UNKNOWN")
    if s.lstrip().startswith(("[", "{")):
        obj = json.loads(s)
        if isinstance(obj, dict):
            obj = obj.get("data")
        if not isinstance(obj, list):
            raise ValueError("TDCC_JSON_SHAPE_CHANGED")
        return obj
    return list(csv.DictReader(io.StringIO(s)))

def parse_tdcc(obj):
    if not isinstance(obj, list) or not obj:
        raise ValueError("TDCC_NOT_A_DATA_ARRAY")
    grouped = defaultdict(dict)
    days = set()
    for record in obj:
        # The official TDCC JSON uses a leading Unicode BOM inside its date key.
        # Normalize only this encoding marker, not names or numerical content.
        if isinstance(record, dict):
            record = {str(k).lstrip("\ufeff"): v for k, v in record.items()}
        if not isinstance(record, dict) or any(label not in record for label in TDCC_FIELDS.values()):
            raise ValueError("TDCC_SCHEMA_CHANGED")
        code = str(record[TDCC_FIELDS["code"]]).strip()
        if not ordinary(code):
            continue
        day = iso_date(record[TDCC_FIELDS["date"]])
        days.add(day)
        grade = number(record[TDCC_FIELDS["grade"]])
        if grade < 1 or grade > 17:
            raise ValueError("TDCC_GRADE_OUT_OF_RANGE")
        key = (day, code)
        if grade in grouped[key]:
            raise ValueError("TDCC_DUPLICATE_GRADE")
        grouped[key][grade] = (number(record[TDCC_FIELDS["holders"]]),
                               number(record[TDCC_FIELDS["shares"]]),
                               pct_number(record[TDCC_FIELDS["pct"]]))
    if not grouped:
        raise ValueError("TDCC_NO_ORDINARY_STOCKS")
    day = max(days)
    result = []
    for (d, code), grades in grouped.items():
        if d != day:
            continue
        if 17 not in grades or any(k not in grades for k in (12, 13, 14, 15)):
            continue
        total_shares = grades[17][1]
        if total_shares <= 0:
            continue
        large = round(sum(grades[k][2] for k in (12, 13, 14, 15)), 4)
        result.append(dict(code=code, date=day, level_12_15_pct=large,
                           total_deposited_shares=total_shares,
                           total_holders=grades[17][0],
                           grade_definition="TDCC_GRADES_12_TO_15_NOT_IDENTIFIED_INDIVIDUALS"))
    if len(result) < 300:
        raise ValueError("TDCC_COVERAGE_TOO_LOW_OR_MISSING_GRADE_17")
    return day, sorted(result, key=lambda x: x["code"])

def fetch(url, raw_dir, key):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (public statistical archive; contact via repository)",
                                               "Accept": "application/json,text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=35) as response:
        raw = response.read(35000001)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / (key + ".response")).write_bytes(raw)
    if key == "TWSE" and len(raw) < 500:
        try:
            status = json.loads(raw.decode("utf-8-sig")).get("stat", "")
        except (ValueError, AttributeError):
            status = ""
        if status and status != "OK":
            raise ValueError("TWSE_NO_SESSION_OR_NOT_PUBLISHED: " + str(status)[:80])
    if len(raw) < 500 or len(raw) > 35000000 or b"<html" in raw[:200].lower():
        raise ValueError("OFFICIAL_RESPONSE_INVALID_SIZE_OR_HTML")
    return raw

def save_capture(out_root, family, day, market, raw, rows, url, fetched_at):
    archive = out_root / "raw" / family / day / (market + ".response.gz")
    archive.parent.mkdir(parents=True, exist_ok=True)
    packed = gzip.compress(raw, mtime=0)
    if archive.exists() and archive.read_bytes() != packed:
        raise ValueError("SAME_PERIOD_ORIGINAL_BYTES_CHANGED_REQUIRES_REVISION_REVIEW")
    archive.write_bytes(packed)
    dest = out_root / family / day / (market + ".json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    normalized = (json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    prior_normalized_sha = None
    if dest.exists() and dest.read_bytes() != normalized:
        # Same original HTTP bytes, but new strict parser/schema changed its normalized shape.
        # Preserve the previously published normalization verbatim for historical PIT replay.
        prior = dest.read_bytes()
        prior_normalized_sha = hashlib.sha256(prior).hexdigest()
        revision = out_root / "normalized_revisions" / family / day / market / (prior_normalized_sha + ".json")
        revision.parent.mkdir(parents=True, exist_ok=True)
        if revision.exists() and revision.read_bytes() != prior:
            raise ValueError("HISTORICAL_NORMALIZATION_HASH_COLLISION")
        revision.write_bytes(prior)
    dest.write_bytes(normalized)
    return dict(source=url, market=market, data_date=day, fetched_at=fetched_at,
                parser_reinterpretation_from_previous_sha256=prior_normalized_sha,
                raw_archive=archive.as_posix(), raw_sha256=hashlib.sha256(raw).hexdigest(),
                raw_gzip_sha256=hashlib.sha256(packed).hexdigest(),
                normalized_path=dest.as_posix(), normalized_sha256=hashlib.sha256(normalized).hexdigest(),
                rows=len(rows), verified="SCHEMA_DATE_HASH_ONLY_NOT_PIT_ORIGIN_CERTIFIED")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", default=str(ROOT))
    parser.add_argument("--artifact-dir", default="chip-capture-artifact")
    parser.add_argument("--asof", help="TWSE trading day YYYY-MM-DD; defaults to local Taiwan calendar day")
    args = parser.parse_args()
    now = dt.datetime.now(ZoneInfo("Asia/Taipei"))
    requested = args.asof or now.date().isoformat()
    if dt.date.fromisoformat(requested) > now.date():
        raise ValueError("FUTURE_REQUESTED_DATE")
    out_root = pathlib.Path(args.out_root)
    artifacts = pathlib.Path(args.artifact_dir)
    raw_dir = artifacts / "original_responses"
    reports, new = [], {}
    for key in ("TWSE", "TPEX", "TDCC"):
        url = SOURCES[key].format(day=requested.replace("-", ""))
        entry = {"market": key, "url": url, "status": "FAILED_PRESERVED_PREVIOUS"}
        try:
            raw = fetch(url, raw_dir, key)
            if key == "TDCC":
                day, rows = parse_tdcc(decode_tdcc(raw))
                family = "ownership"
            else:
                data = json.loads(raw.decode("utf-8-sig"))
                day, rows = parse_twse(data) if key == "TWSE" else parse_tpex(data)
                family = "institutional"
            lag = (now.date() - dt.date.fromisoformat(day)).days
            if lag < 0 or lag > (10 if key == "TDCC" else 5):
                raise ValueError("SOURCE_DATE_STALE_OR_FUTURE: " + day)
            if key == "TWSE" and day != requested:
                raise ValueError("TWSE_REQUEST_RESPONSE_DATE_MISMATCH")
            receipt = save_capture(out_root, family, day, key, raw, rows, url, now.isoformat())
            entry.update(status="SCHEMA_CAPTURED_NOT_CERTIFIED", **receipt)
            new[key] = entry
        except Exception as exc:
            entry["error"] = str(exc)
        reports.append(entry)
    valid_pair = all(k in new for k in ("TWSE", "TPEX")) and new["TWSE"]["data_date"] == new["TPEX"]["data_date"]
    if valid_pair:
        d = new["TWSE"]["data_date"]
        dated_receipt = out_root / "institutional" / d / "receipt.json"
        dated_receipt.write_text(json.dumps(dict(date=d, markets={"TWSE": new["TWSE"], "TPEX": new["TPEX"]},
                                               certification="SOURCE_SCHEMA_AND_HASH_ONLY"),
                                            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        latest = out_root / "institutional" / "latest_complete.json"
        past = json.loads(latest.read_text()) if latest.exists() else {}
        d = new["TWSE"]["data_date"]
        if not past.get("date") or d >= past["date"]:
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(json.dumps(dict(date=d, markets={"TWSE": new["TWSE"], "TPEX": new["TPEX"]},
                                              source_kind="OFFICIAL_EXCHANGE_DAILY",
                                              validity="DATA_SHAPE_AND_TIMESTAMP_VALIDATED_NOT_FULL_MARKET_CERTIFICATION"),
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if "TDCC" in new:
        d = new["TDCC"]["data_date"]
        dated_receipt = out_root / "ownership" / d / "receipt.json"
        dated_receipt.write_text(json.dumps(dict(date=d, receipt=new["TDCC"],
                                               certification="PUBLIC_GRADE_STATISTICS_ONLY"),
                                            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        latest = out_root / "ownership" / "latest.json"
        past = json.loads(latest.read_text()) if latest.exists() else {}
        if not past.get("date") or new["TDCC"]["data_date"] >= past["date"]:
            latest.parent.mkdir(parents=True, exist_ok=True)
            latest.write_text(json.dumps(dict(date=new["TDCC"]["data_date"], receipt=new["TDCC"],
                                              validity="PUBLIC_GRADE_STATISTICS_NOT_INSIDER_IDENTITIES"),
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts.mkdir(parents=True, exist_ok=True)
    attempt = dict(captured_at=now.isoformat(), requested_twse_date=requested, markets=reports,
                   institutional_pair_valid=valid_pair, official_PIT_master_verified=False,
                   no_issuer_certification_or_eps_pe_changes=True)
    (artifacts / "attempt_manifest.json").write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"institutional_pair_valid": valid_pair, "sources": {r["market"]: r["status"] for r in reports}},
                     ensure_ascii=False))
    return 0  # Any upstream failure must not interrupt the unrelated research model.

if __name__ == "__main__":
    raise SystemExit(main())
