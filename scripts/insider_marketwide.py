#!/usr/bin/env python3
"""Progressive official MOPS insider market-trade collection; never invent missing months.

IRB110 is a monthly issuer/share master, NOT a market-trade feed.
query6_1 is the monthly post-trade disclosure. A prior-transfer notice,
holdings delta, pledge, gift or RSU is never counted as a market buy.
"""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import html
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tw-market-data" / "insider"
TW = dt.timezone(dt.timedelta(hours=8))
IRB_HOST = "https://siis.twse.com.tw"
MOPS_URL = "https://mops.twse.com.tw/mops/api/query6_1"
MARKETS = {"TWSE": "sii", "TPEX": "otc"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-audit/1.0)",
           "Accept": "application/json,text/html;q=0.9"}
TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")

def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def put_json(path, obj):
    atomic(path, (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())

def get_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

def number(v):
    if isinstance(v, bool):
        raise ValueError("INVALID_NUMBER")
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "—"):
        return 0
    if not re.fullmatch(r"\d+(?:\.0+)?", s):
        raise ValueError("INVALID_NONNEGATIVE_SHARE_VALUE")
    return int(float(s))

def months_ending(day, count):
    # Data from the preceding month is due by the 15th; no premature month.
    year, month = day.year, day.month
    index = year * 12 + month - (3 if day.day <= 15 else 2)
    return [f"{(index - n)//12:04d}-{(index - n)%12+1:02d}"
            for n in range(count - 1, -1, -1)]

def parse_irb110(raw):
    doc = raw.decode("big5", errors="replace")
    rows = {}
    for part in TR.findall(doc):
        fields = [html.unescape(TAG.sub("", x)).replace("\u3000", "").strip()
                  for x in TD.findall(part)]
        if len(fields) < 8:
            continue
        m = re.match(r"^(\d{4})(?!\d)", fields[0])
        if not m:
            continue
        code = m.group(1)
        issued = number(fields[1])
        if issued <= 0 or code in rows:
            raise ValueError("INVALID_OR_DUPLICATE_IRB_ISSUER")
        rows[code] = {"code": code, "issued_shares": issued}
    if len(rows) < 400:
        raise ValueError("IRB110_MISSING_MARKET_UNIVERSE")
    return rows

def parse_detail(raw):
    doc = json.loads(raw.decode("utf-8-sig"))
    if doc.get("code") != 200 or not isinstance(doc.get("result"), dict):
        raise ValueError("MOPS_UNSUCCESSFUL_RESPONSE_NOT_ZERO")
    rawrows = doc["result"].get("data")
    if not isinstance(rawrows, list):
        raise ValueError("MOPS_DATA_MISSING_NOT_ZERO")
    holdings = {}
    ambiguous = False
    for x in rawrows:
        if not isinstance(x, list) or len(x) < 19:
            raise ValueError("MOPS_UNKNOWN_SCHEMA")
        role, name, kind = [str(x[k] or "").strip() for k in (0, 1, 2)]
        if not role or not name:
            # MOPS may include blank/header rows in the API data array.
            # Only discard a row if it is demonstrably non-transactional.
            # A missing holder with nonzero or uninterpretable movement fails closed.
            try:
                movements = [number(x[k]) for k in (8, 9, 13, 14)]
                balance = [number(x[k]) for k in (4, 18)]
            except (ValueError, TypeError):
                raise ValueError("MOPS_UNIDENTIFIED_ROW_SCHEMA_REQUIRES_REVIEW")
            if any(movements) or any(balance):
                raise ValueError("MOPS_UNIDENTIFIED_ROW_WITH_SHARES_REQUIRES_REVIEW")
            continue
        # Different account classes MUST NOT be added twice as the same identity.
        # Do not count header, representative or summary records as trade rows.
        account_class = ("SPOUSE_MINOR" if ("配偶" in role or "未成年" in role)
                         else "NOMINEE" if "利用他人名義" in role
                         else "REPRESENTATIVE" if "法人代表人" in role
                         else "SELF")
        if account_class == "REPRESENTATIVE":
            continue
        before, buy, other_in, sell, other_out, after = (number(x[k]) for k in (4, 8, 9, 13, 14, 18))
        if abs(before + buy + other_in - sell - other_out - after) > 1:
            raise ValueError("MOPS_HOLDINGS_ROLLFORWARD_MISMATCH")
        key = (account_class, name, kind)
        values = (before, buy, other_in, sell, other_out, after)
        if key in holdings and holdings[key] != values:
            ambiguous = True
        elif key in holdings:
            # Same filing may repeat holder for director/manager dual roles.
            continue
        holdings[key] = values
    if ambiguous:
        raise ValueError("MOPS_SAME_NAME_ACCOUNT_COLLISION_NEEDS_REVIEW")
    if rawrows and not holdings:
        raise ValueError("MOPS_NO_VALID_HOLDER_ROWS")
    return {"buy_shares": sum(x[1] for x in holdings.values()),
            "sell_shares": sum(x[3] for x in holdings.values()),
            "other_in_shares": sum(x[2] for x in holdings.values()),
            "other_out_shares": sum(x[4] for x in holdings.values()),
            "unique_display_keys": len(holdings),
            "dedup_method": "DISPLAY_NAME_AND_ACCOUNT_CLASS_CONSERVATIVE_NOT_FORMAL",
            "original_holder_account_identity_certified": False}

def fetch(url, payload=None, timeout=25):
    hdr = dict(HEADERS)
    if payload is not None:
        hdr["Content-Type"] = "application/json"
        hdr["Origin"] = "https://mops.twse.com.tw"
        hdr["Referer"] = "https://mops.twse.com.tw/"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=hdr, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("NON_200_RESPONSE")
        return response.read(6_000_001)

def save_original(path, raw, url, asof, previous=None):
    if not (20 <= len(raw) <= 6_000_000):
        raise ValueError("ORIGINAL_BYTES_EMPTY_OR_OVERSIZED")
    digest = hashlib.sha256(raw).hexdigest()
    archive = path.parent / (path.stem + "_" + digest + ".gz")
    if not archive.exists():
        atomic(archive, gzip.compress(raw, mtime=0))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rec = {"url": url, "source_date": asof, "sha256": digest,
           "raw_archive": archive.name, "fetched_at": now,
           "first_captured_at": (previous or {}).get("first_captured_at", now),
           "formal_PIT_verified": False}
    put_json(path, rec)
    return rec

def capture_irb(base, months, refresh_latest=2, getter=fetch):
    failures = []
    for month in months:
        year, m = month.split("-")
        for market, route in MARKETS.items():
            receipt = base / "irb110" / month / (market + ".json")
            existing = get_json(receipt)
            archive = receipt.parent / existing.get("raw_archive", "") if existing else None
            if existing and archive.is_file() and month not in months[-refresh_latest:]:
                continue
            url = f"{IRB_HOST}/publish/{route}/{int(year)-1911}IRB110_{m}.HTM"
            try:
                raw = getter(url)
                parse_irb110(raw)
                save_original(receipt, raw, url, month, existing)
            except (OSError, ValueError, TypeError, KeyError, urllib.error.HTTPError) as ex:
                failures.append({"month": month, "market": market, "reason": str(ex)[:250]})
    return failures

def irb_master(base, month):
    out = {}
    for market in MARKETS:
        rec = get_json(base / "irb110" / month / (market + ".json"))
        if not rec:
            return {}
        archive = base / "irb110" / month / rec["raw_archive"]
        try:
            raw = gzip.decompress(archive.read_bytes())
            if hashlib.sha256(raw).hexdigest() != rec["sha256"]:
                return {}
            rows = parse_irb110(raw)
        except (OSError, ValueError, KeyError):
            return {}
        for code, data in rows.items():
            if code in out:
                raise ValueError("CROSS_MARKET_DUPLICATE_CODE")
            out[code] = dict(data, market=market)
    return out

def capture_details(base, months, master, limit, gap=2.0, getter=fetch):
    requested, succeeded, errors = 0, 0, []
    # Newest reports first, but every successful archived issuer-month is never re-fetched.
    # Finish twelve months per issuer before moving to the next issuer:
    # incremental output can then contain real full-window samples.
    for code in sorted(master):
        for month in reversed(months):
            record = base / "detail" / month / (code + ".json")
            prior = get_json(record)
            if prior:
                continue
            retry = base / "retry" / month / (code + ".json")
            last_error = get_json(retry)
            if last_error and last_error.get("last_attempted_at"):
                try:
                    elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last_error["last_attempted_at"])
                    if elapsed.total_seconds() < 24 * 3600:
                        continue
                except (ValueError, TypeError):
                    pass
            if requested >= limit:
                return {"requested": requested, "succeeded": succeeded, "errors": errors}
            requested += 1
            y, m = month.split("-")
            payload = {"companyId": code, "dataType": "2", "subsidiaryCompanyId": "",
                       "year": str(int(y) - 1911), "month": m}
            raw = None
            try:
                raw = getter(MOPS_URL, payload)
                parsed = parse_detail(raw)
                receipt = save_original(record, raw, MOPS_URL, month)
                put_json(record, dict(receipt, **parsed, code=code, month=month,
                                      market=master[code]["market"],
                                      status="OFFICIAL_MOPS_CAPTURED_HOLDER_DEDUP_UNVERIFIED"))
                succeeded += 1
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as ex:
                err = {"code": code, "month": month, "reason": str(ex)[:250]}
                errors.append(err)
                # Preserve parse-failure response bytes for a reproducible schema audit.
                # Never mark the company/month as a successful filing when parsing fails.
                if isinstance(raw, bytes) and raw:
                    try:
                        failed = base / "failed" / month / (code + ".json")
                        save_original(failed, raw, MOPS_URL, month, get_json(failed))
                    except (OSError, ValueError):
                        err["failed_payload_archive"] = "UNAVAILABLE"
                put_json(retry, dict(err, last_attempted_at=dt.datetime.now(dt.timezone.utc).isoformat()))
                if len(errors) >= 20 and succeeded == 0:
                    return {"requested": requested, "succeeded": succeeded,
                            "errors": errors, "stopped": "SOURCE_OUTAGE_NO_ZERO_FILL"}
            if gap > 0:
                time.sleep(gap)
    return {"requested": requested, "succeeded": succeeded, "errors": errors}

def build_ranking(base, months, master):
    eligible, pending = [], []
    detail_ok = 0
    for code, item in sorted(master.items()):
        buy = sell = 0
        positive_months = 0
        missing = []
        for month in months:
            row = get_json(base / "detail" / month / (code + ".json"))
            if not row or row.get("code") != code or row.get("month") != month:
                missing.append(month)
                continue
            rawpath = base / "detail" / month / row.get("raw_archive", "")
            try:
                original = gzip.decompress(rawpath.read_bytes())
                if hashlib.sha256(original).hexdigest() != row["sha256"]:
                    raise ValueError("BAD_SOURCE_HASH")
                parsed = parse_detail(original)
                if any(parsed[k] != row[k] for k in ("buy_shares", "sell_shares")):
                    raise ValueError("NORMALIZED_SOURCE_MISMATCH")
            except (OSError, ValueError, KeyError):
                missing.append(month)
                continue
            detail_ok += 1
            buy += parsed["buy_shares"]
            sell += parsed["sell_shares"]
            if parsed["buy_shares"] > parsed["sell_shares"]:
                positive_months += 1
        if missing:
            pending.append({"code": code, "missing_months": missing})
            continue
        shares = item["issued_shares"]
        if shares <= 0:
            pending.append({"code": code, "missing_months": [], "reason": "INVALID_DENOMINATOR"})
            continue
        eligible.append({"code": code, "market": item["market"], "issued_shares": shares,
                         "buy_lots": round(buy/1000, 3), "sell_lots": round(sell/1000, 3),
                         "net_lots": round((buy-sell)/1000, 3),
                         "buy_pct_of_issued": round(buy/shares*100, 5),
                         "net_pct_of_issued": round((buy-sell)/shares*100, 5),
                         "positive_net_months": positive_months,
                         "fully_observed_months": len(months)})
    eligible.sort(key=lambda x: (-x["buy_pct_of_issued"], -x["net_pct_of_issued"], x["code"]))
    status = ("COMPLETE_RESEARCH_SCOPE_NOT_FORMALLY_CERTIFIED" if master and not pending
              else "PARTIAL_NOT_MARKETWIDE_RANKING")
    return {"schema": "INSIDER_MARKETWIDE_V1", "status": status,
            "months": months, "listed_otc_issuer_count": len(master),
            "complete_issuer_count": len(eligible), "pending_issuer_count": len(pending),
            "verified_detail_month_count": detail_ok,
            "expected_detail_month_count": len(master)*len(months),
            "marketwide_rank_claim_permitted": False,
            "holder_identity_formal_certification": False,
            "forward_EPS_PE_Aplus_or_Exit_changed": False,
            "positive_buy_complete_sample_top100": [r for r in eligible if r["buy_lots"] > 0][:100],
            "pending_examples": pending[:60],
            "all_complete_sample": eligible}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=str(BASE))
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--max-details", type=int, default=160)
    p.add_argument("--gap", type=float, default=2.0)
    p.add_argument("--asof", default=None, help="Taiwan-local date YYYY-MM-DD")
    args = p.parse_args()
    if not 1 <= args.months <= 36 or not 0 <= args.max_details <= 2000:
        p.error("unsafe window or request cap")
    today = dt.date.fromisoformat(args.asof) if args.asof else dt.datetime.now(TW).date()
    months = months_ending(today, args.months)
    base = Path(args.base)
    failures = capture_irb(base, months)
    master = irb_master(base, months[-1])
    if master:
        state = capture_details(base, months, master, args.max_details, args.gap)
        result = build_ranking(base, months, master)
    else:
        state = {"requested": 0, "succeeded": 0, "errors": [],
                 "blocked": "OFFICIAL_LATEST_MONTH_TWO_MARKET_MASTER_MISSING"}
        result = {"schema": "INSIDER_MARKETWIDE_V1", "status": "PENDING_TWO_MARKET_OFFICIAL_MASTER",
                  "months": months, "listed_otc_issuer_count": 0, "complete_issuer_count": 0,
                  "marketwide_rank_claim_permitted": False, "positive_buy_complete_sample_top100": []}
    result["attempted_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result["collection"] = state
    result["monthly_master_failures"] = failures
    output = ROOT / "tw-market-data" / "rankings" / "insider_marketwide_latest.json"
    put_json(output, result)
    md = ["# 上市櫃內部人近12個月市場買進／股本比率",
          "", "申報月份：" + "～".join((months[0], months[-1])),
          f"狀態：{result['status']}；完整公司 {result['complete_issuer_count']} / {result['listed_otc_issuer_count']}",
          "", "**未完整涵蓋全部公司者，以下僅為完整樣本，不是全市場Top榜。**",
          "不把申報轉讓、增資、贈與、設質、董監人事異動當成市場買進。",
          "內部人帳戶身分去重仍未正式認證；不更改模型估值、A+、Exit。",
          "", "|樣本序|股票|買進張數|賣出張數|買進/股本|淨買/股本|淨買月份|",
          "|---:|---|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(result["positive_buy_complete_sample_top100"], 1):
        md.append(f"|{i}|{r['code']}|{r['buy_lots']:,.1f}|{r['sell_lots']:,.1f}|"
                  f"{r['buy_pct_of_issued']:.3f}%|{r['net_pct_of_issued']:.3f}%|"
                  f"{r['positive_net_months']}/{len(months)}|")
    atomic(ROOT / "tw-market-data" / "rankings" / "insider_marketwide_latest.md",
           ("\n".join(md) + "\n").encode("utf-8"))
    print(json.dumps({"status": result["status"], "issuers": len(master),
                      "complete_issuers": result["complete_issuer_count"],
                      "attempts": state["requested"], "successful": state["succeeded"]},
                     ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
