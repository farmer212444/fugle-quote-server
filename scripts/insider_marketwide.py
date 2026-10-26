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
# Publicly identified 2026 buyer leads are first in the verification queue,
# NOT accepted as official purchases until each MOPS original is hash-verified.
# The remaining listed/OTC universe is always scanned after these leads.
PRIORITY_REVIEW_CODES = (
    "9802", "2520", "6116", "4919", "3705",
    "6176", "2106", "6869", "9938", "3040",
)
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

def months_year_to_date(day):
    """All reportable months since 2026-01, including future years.

    Retain the legacy function name for compatibility with existing jobs.
    Never reset to January of the next year.
    """
    latest = months_ending(day, 1)[0]
    year, month = (int(v) for v in latest.split("-"))
    start_index = 2026 * 12
    last_index = year * 12 + month - 1
    return [f"{i//12:04d}-{i%12+1:02d}"
            for i in range(start_index, last_index + 1)]


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
    """Parse MOPS query6_1 holdings rollforward and actual exchange trades.

    API position 8/13 is centralized-market purchase/sale. Position 10/15
    covers private-placement increases/decreases, which affect the holdings
    bridge but are NOT market trades. Pledges never count as purchases.
    """
    doc = json.loads(raw.decode("utf-8-sig"))
    if doc.get("code") != 200 or not isinstance(doc.get("result"), dict):
        raise ValueError("MOPS_UNSUCCESSFUL_RESPONSE_NOT_ZERO")
    rawrows = doc["result"].get("data")
    if not isinstance(rawrows, list):
        raise ValueError("MOPS_DATA_MISSING_NOT_ZERO")
    holdings = {}
    parent_name = None
    for x in rawrows:
        if not isinstance(x, list) or len(x) < 19:
            raise ValueError("MOPS_UNKNOWN_SCHEMA")
        role, name, kind = [str(x[k] or "").strip() for k in (0, 1, 2)]
        # Verify all share-changing categories, including private placements.
        before, buy, other_in, private_in, sell, other_out, private_out, after = (
            number(x[k]) for k in (4, 8, 9, 10, 13, 14, 15, 18))
        if abs(before + buy + other_in + private_in
               - sell - other_out - private_out - after) > 1:
            raise ValueError("MOPS_HOLDINGS_ROLLFORWARD_MISMATCH")

        family = ("配偶" in role or "未成年" in role)
        if family:
            # MOPS deliberately leaves family-holder name blank; associate
            # it with the nearest preceding named insider, not a new trade.
            if name:
                identity = name + "::SPOUSE_MINOR"
            elif parent_name:
                identity = parent_name + "::SPOUSE_MINOR"
            elif any((before, buy, other_in, private_in, sell,
                      other_out, private_out, after)):
                raise ValueError("MOPS_ORPHAN_FAMILY_HOLDER_NEEDS_REVIEW")
            else:
                continue
        elif role and name:
            parent_name = name
            identity = name
        elif any((before, buy, other_in, private_in, sell,
                  other_out, private_out, after)):
            raise ValueError("MOPS_UNIDENTIFIED_ROW_WITH_SHARES_REQUIRES_REVIEW")
        else:
            continue

        # One account can appear under multiple director, executive, legal
        # representative and major-shareholder roles. Never sum duplicates.
        # Conflicting names/amounts remain review-required, not guessed.
        key = (identity, kind)
        values = (before, buy, other_in, private_in,
                  sell, other_out, private_out, after)
        if key in holdings and holdings[key] != values:
            raise ValueError("MOPS_SAME_NAME_ACCOUNT_COLLISION_NEEDS_REVIEW")
        holdings[key] = values
    if rawrows and not holdings:
        raise ValueError("MOPS_NO_VALID_HOLDER_ROWS")
    return {"buy_shares": sum(x[1] for x in holdings.values()),
            "sell_shares": sum(x[4] for x in holdings.values()),
            "other_in_shares": sum(x[2] + x[3] for x in holdings.values()),
            "other_out_shares": sum(x[5] + x[6] for x in holdings.values()),
            "unique_display_keys": len(holdings),
            "dedup_method": "NAME_AND_ACCOUNT_TYPE_EXACT_HOLDINGS_CONSERVATIVE_NOT_FORMAL",
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

def recover_failed_original(base, month, code, market):
    """Reparse a previously archived failed response without any HTTP request.

    A failed payload becomes an accepted filing only if its SHA256, response
    schema and every holder's holdings bridge pass the current parser.
    """
    failed = base / "failed" / month / (code + ".json")
    saved = get_json(failed)
    if not saved:
        return False
    try:
        archive = failed.parent / saved["raw_archive"]
        raw = gzip.decompress(archive.read_bytes())
        if hashlib.sha256(raw).hexdigest() != saved["sha256"]:
            return False
        parsed = parse_detail(raw)
        record = base / "detail" / month / (code + ".json")
        receipt = save_original(record, raw, MOPS_URL, month)
        put_json(record, dict(receipt, **parsed, code=code, month=month,
                              market=market,
                              status="OFFICIAL_ARCHIVED_RESPONSE_REPARSED_DEDUP_UNVERIFIED"))
        return True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False

def capture_details(base, months, master, limit, gap=2.0, getter=fetch):
    requested, succeeded, errors = 0, 0, []
    # Accelerate official verification of public 2026 buyer leads, then scan
    # EVERY remaining listed/OTC issuer. Prioritization never proves a buy.
    # Fill each priority issuer's entire Jan-2026-onward window first;
    # broad market discovery remains most-recent-month-first after that.
    def pairs():
        for code in PRIORITY_REVIEW_CODES:
            if code in master:
                for month in reversed(months):
                    yield month, code
        other_codes = [code for code in sorted(master)
                       if code not in PRIORITY_REVIEW_CODES]
        for month in reversed(months):
            for code in other_codes:
                yield month, code

    for month, code in pairs():
            record = base / "detail" / month / (code + ".json")
            prior = get_json(record)
            if prior:
                continue
            if recover_failed_original(base, month, code, master[code]["market"]):
                succeeded += 1
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
    complete, pending, positive_observed = [], [], []
    detail_ok = 0
    for code, item in sorted(master.items()):
        buy = sell = 0
        positive_months = 0
        missing = []
        observed = []
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
            observed.append(month)
            buy += parsed["buy_shares"]
            sell += parsed["sell_shares"]
            if parsed["buy_shares"] > parsed["sell_shares"]:
                positive_months += 1
        if not item.get("issued_shares") or item["issued_shares"] <= 0:
            pending.append({"code": code, "missing_months": missing,
                            "reason": "INVALID_DENOMINATOR"})
            continue
        complete_months = len(observed) == len(months) and len(months) > 0
        if not complete_months:
            pending.append({"code": code, "missing_months": missing})
        if not observed:
            continue
        shares = item["issued_shares"]
        entry = {"code": code, "market": item["market"], "issued_shares": shares,
                 "buy_lots": round(buy / 1000, 3), "sell_lots": round(sell / 1000, 3),
                 "net_lots": round((buy - sell) / 1000, 3),
                 "buy_pct_of_issued": round(buy / shares * 100, 5),
                 "net_pct_of_issued": round((buy - sell) / shares * 100, 5),
                 "positive_net_months": positive_months,
                 "observed_month_count": len(observed),
                 "expected_ytd_month_count": len(months),
                 "observed_months": observed,
                 "missing_months": missing,
                 "year_to_date_complete": complete_months,
                 "buy_amount_is_observed_months_only": not complete_months}
        if complete_months:
            complete.append(entry)
        # The user wants ONLY stocks with recorded actual market purchases.
        # An incomplete issuer can appear provisionally with coverage disclosed.
        if buy > 0:
            positive_observed.append(entry)
    sort_by_purchase = lambda x: (-x["buy_pct_of_issued"], -x["net_pct_of_issued"], x["code"])
    complete.sort(key=sort_by_purchase)
    positive_observed.sort(key=sort_by_purchase)
    status = ("COMPLETE_YTD_RESEARCH_SCOPE_NOT_FORMALLY_CERTIFIED"
              if master and not pending and months
              else "PARTIAL_YTD_BUYER_DISCOVERY_NOT_MARKETWIDE")
    return {"schema": "INSIDER_MARKETWIDE_YTD_V2", "status": status,
            "scope_start_month": "2026-01", "scope_rule": "SINCE_2026",
            "months": months, "listed_otc_issuer_count": len(master),
            "complete_issuer_count": len(complete), "pending_issuer_count": len(pending),
            "observed_positive_issuer_count": len(positive_observed),
            "partial_positive_issuer_count": sum(not r["year_to_date_complete"] for r in positive_observed),
            "verified_detail_month_count": detail_ok,
            "expected_detail_month_count": len(master) * len(months),
            "marketwide_rank_claim_permitted": False,
            "observed_ranking_is_not_full_year_total": bool(pending),
            "holder_identity_formal_certification": False,
            "forward_EPS_PE_Aplus_or_Exit_changed": False,
            "positive_buy_observed_sample_top100": positive_observed[:100],
            "positive_buy_complete_sample_top100": [r for r in complete if r["buy_lots"] > 0][:100],
            "pending_examples": pending[:60],
            "all_observed_positive": positive_observed,
            "all_complete_sample": complete}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=str(BASE))
    p.add_argument("--months", type=int, default=None,
                   help="Optional rolling period override; default is current-year reported months")
    p.add_argument("--max-details", type=int, default=160)
    p.add_argument("--gap", type=float, default=2.0)
    p.add_argument("--asof", default=None, help="Taiwan-local date YYYY-MM-DD")
    args = p.parse_args()
    if (args.months is not None and not 1 <= args.months <= 36) or not 0 <= args.max_details <= 2000:
        p.error("unsafe window or request cap")
    today = dt.date.fromisoformat(args.asof) if args.asof else dt.datetime.now(TW).date()
    months = months_ending(today, args.months) if args.months is not None else months_year_to_date(today)
    base = Path(args.base)
    failures = capture_irb(base, months)
    master = irb_master(base, months[-1]) if months else {}
    if master:
        state = capture_details(base, months, master, args.max_details, args.gap)
        result = build_ranking(base, months, master)
    else:
        state = {"requested": 0, "succeeded": 0, "errors": [],
                 "blocked": "OFFICIAL_LATEST_MONTH_TWO_MARKET_MASTER_MISSING"}
        result = {"schema": "INSIDER_MARKETWIDE_YTD_V2", "status": "PENDING_TWO_MARKET_OFFICIAL_MASTER_OR_START_MONTH_NOT_YET_REPORTABLE",
                  "scope_start_month": "2026-01", "scope_rule": "SINCE_2026",
                  "months": months, "listed_otc_issuer_count": 0, "complete_issuer_count": 0,
                  "marketwide_rank_claim_permitted": False, "observed_positive_issuer_count": 0,
                  "positive_buy_observed_sample_top100": [], "positive_buy_complete_sample_top100": []}
    result["attempted_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result["collection"] = state
    result["monthly_master_failures"] = failures
    output = ROOT / "tw-market-data" / "rankings" / "insider_marketwide_latest.json"
    put_json(output, result)
    md = ["# 上市櫃內部人2026年起有買進公司／股本比率",
          "", "已完成申報月份：" + ("～".join((months[0], months[-1])) if months else "尚無"),
          f"狀態：{result['status']}；已觀察到買進 {result.get('observed_positive_issuer_count', 0)} 家，"
          f"完整核對本年度 {result['complete_issuer_count']} / {result['listed_otc_issuer_count']} 家",
          "",
          "**只要有已核實的集中市場買進就列入暫時追蹤，不要求先收齊全年月份。**",
          "**部分月份資料只能稱為『已觀察到的買進量』；不是自2026年起算的完整累計，更不是全市場正式名次。**",
          "不把贈與、質押、增資、員工股、人事異動當成市場買進。",
          "內部人帳戶身分去重仍未正式認證；不更改模型EPS、PE、A+、Exit。",
          "", "|樣本序|股票|已核月份|買進張數|賣出張數|買進/股本|淨買/股本|淨買月數|",
          "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(result["positive_buy_observed_sample_top100"], 1):
        md.append(f"|{i}|{r['code']}|{r['observed_month_count']}/{r['expected_ytd_month_count']}|"
                  f"{r['buy_lots']:,.1f}|{r['sell_lots']:,.1f}|"
                  f"{r['buy_pct_of_issued']:.3f}%|{r['net_pct_of_issued']:.3f}%|"
                  f"{r['positive_net_months']}|")
    atomic(ROOT / "tw-market-data" / "rankings" / "insider_marketwide_latest.md",
           ("\n".join(md) + "\n").encode("utf-8"))
    print(json.dumps({"status": result["status"], "issuers": len(master),
                      "complete_issuers": result["complete_issuer_count"],
                      "attempts": state["requested"], "successful": state["succeeded"]},
                     ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
