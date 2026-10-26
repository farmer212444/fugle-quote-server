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
NORMALIZER = "MOPS_QUERY6_1_MARKET_TRADES_V3"
DETAIL_COLUMNS = (
    "身份別", "姓名", "持股種類", "選任當時持有股數", "上月實際持有股數",
    "截至上月底保留運用決定權信託股數", "截至上月底累計設質", "截至上月底累計持有私募股票股數",
    "本月增加/自有股數(集中)", "本月增加/自有股數(其它原因－不含私募)",
    "本月增加/私募股數", "本月增加/保留運用決定權信託股數", "本月增加/設定質權股數",
    "本月減少/自有股數(集中)", "本月減少/自有股數(其它原因－不含私募)",
    "本月減少/私募股數", "本月減少/保留運用決定權信託股數", "本月減少/解除質權股數",
    "本月實際自有持有股數", "截至本月底分戶集保股數", "截至本月底保留運用決定權信託股數",
    "截至本月底累計設質", "截至本月底累計持有私募股票股數", "身份別備註")
REFERENCE_SITES = [
    {"name": "Goodinfo", "url": "https://goodinfo.tw/tw/StockDirectorSharehold.asp",
     "mode": "PUBLIC_HOLDINGS_REFERENCE_NOT_AUTOMATIC_TRADE_INPUT"},
    {"name": "CMoney", "url": "https://www.cmoney.com.tw/",
     "mode": "REFERENCE_ONLY_NO_VENDOR_DATA_CONNECTION"},
    {"name": "豹投資", "url": "https://www.gorich.com.tw/doc/archives/6",
     "mode": "FUNCTION_DOCUMENTATION_ONLY_NO_VENDOR_DATA_CONNECTION"}]

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

def flattened_titles(titles, parent=""):
    if not isinstance(titles, list):
        raise ValueError("MOPS_COLUMN_TITLES_MISSING")
    result = []
    for title in titles:
        if not isinstance(title, dict) or not isinstance(title.get("main"), str):
            raise ValueError("MOPS_COLUMN_TITLE_INVALID")
        name = re.sub(r"\s+", "", title["main"])
        path = parent + "/" + name if parent else name
        if title.get("sub"):
            result.extend(flattened_titles(title["sub"], path))
        else:
            result.append(path)
    return result

def parse_detail(raw, expected_month=None, expected_market=None):
    doc = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("code") != 200 or not isinstance(doc.get("result"), dict):
        raise ValueError("MOPS_UNSUCCESSFUL_RESPONSE_NOT_ZERO")
    result = doc["result"]
    if tuple(flattened_titles(result.get("titles"))) != DETAIL_COLUMNS:
        raise ValueError("MOPS_COLUMN_LAYOUT_REQUIRES_REVIEW")
    try:
        year, month = int(result["year"]), int(result["month"])
        year = year + 1911 if year < 1911 else year
        period = dt.date(year, month, 1).strftime("%Y-%m")
        market = {"上市公司": "TWSE", "上櫃公司": "TPEX"}[result["marketName"]]
    except (KeyError, TypeError, ValueError):
        raise ValueError("MOPS_PERIOD_OR_MARKET_IDENTITY_MISSING")
    if ((expected_month is not None and period != expected_month)
            or (expected_market is not None and market != expected_market)):
        raise ValueError("MOPS_PERIOD_OR_MARKET_IDENTITY_MISMATCH")
    if not str(result.get("companyAbbreviation") or "").strip():
        raise ValueError("MOPS_COMPANY_NAME_MISSING")
    rawrows = result.get("data")
    if not isinstance(rawrows, list) or not rawrows:
        raise ValueError("MOPS_DATA_MISSING_NOT_ZERO")
    holdings = {}
    unchanged_unidentified = representatives = 0
    linked_families = 0
    parent = None
    family_keys = set()
    for x in rawrows:
        if not isinstance(x, list) or len(x) != len(DETAIL_COLUMNS):
            raise ValueError("MOPS_UNKNOWN_SCHEMA")
        role, name, kind = [str(x[k] or "").strip() for k in (0, 1, 2)]
        before, buy, other_in, private_in, sell, other_out, private_out, after = (
            number(x[k]) for k in (4, 8, 9, 10, 13, 14, 15, 18))
        if abs(before + buy + other_in + private_in - sell - other_out - private_out - after) > 1:
            raise ValueError("MOPS_HOLDINGS_ROLLFORWARD_MISMATCH")
        family = '配偶' in role or '未成年' in role
        if (not role or not name) and not (family and name):
            # Anonymous spouse/minor summaries can have an unchanged balance.
            # Exclude only zero-activity rows from trade totals; do not invent
            # a holder identity, or discard anonymous purchases/sales/transfers.
            try:
                movements = [number(x[k]) for k in range(8, 18)]
                balance = [number(x[k]) for k in (4, 18)]
            except (ValueError, TypeError):
                raise ValueError("MOPS_UNIDENTIFIED_ROW_SCHEMA_REQUIRES_REVIEW")
            if not any(movements) and balance[0] == balance[1]:
                unchanged_unidentified += 1
                continue
            if not family:
                raise ValueError("MOPS_UNIDENTIFIED_ROW_WITH_SHARES_REQUIRES_REVIEW")
        if family:
            if name:
                identity = name + '::SPOUSE_MINOR'
            elif parent and role == parent[0] + '之配偶及未成年子女' and kind == parent[2]:
                identity = parent[1] + '::SPOUSE_MINOR'
                linked_families += 1
            else:
                raise ValueError('MOPS_ORPHAN_FAMILY_HOLDER_NEEDS_REVIEW')
        else:
            parent = (role, name, kind)
            identity = name
        # A representative's reported personal holding is not the legal
        # entity's holding. Include it, deduplicating an identical named personal
        # account also disclosed under a director/manager role.
        if "法人代表人" in role and not family and '利用他人名義' not in role:
            representatives += 1
        key = (identity, kind)
        values = (before, buy, other_in, private_in, sell, other_out, private_out, after)
        if key in holdings and holdings[key] != values:
            raise ValueError("MOPS_SAME_NAME_ACCOUNT_COLLISION_NEEDS_REVIEW")
        holdings[key] = values
        if family:
            family_keys.add(key)
    # An anonymous family aggregate can overlap a named director's own account.
    # Matching active records are not proof of separate accounts; do not add both.
    for key in family_keys:
        values = holdings[key]
        if (values[1] or values[4]) and any(
                other not in family_keys and other[1] == key[1] and item == values
                for other, item in holdings.items()):
            raise ValueError('MOPS_FAMILY_NAMED_HOLDER_OVERLAP_NEEDS_REVIEW')
    if rawrows and not holdings:
        raise ValueError("MOPS_NO_VALID_HOLDER_ROWS")
    return {"buy_shares": sum(x[1] for x in holdings.values()),
            "sell_shares": sum(x[4] for x in holdings.values()),
            "other_in_shares": sum(x[2] + x[3] for x in holdings.values()),
            "other_out_shares": sum(x[5] + x[6] for x in holdings.values()),
            "unique_display_keys": len(holdings),
            "dedup_method": "NAME_AND_DISCLOSED_FAMILY_RELATION_EXACT_HOLDINGS_NOT_FORMAL",
            "original_holder_account_identity_certified": False,
            "unchanged_unidentified_rows_excluded_from_trade_totals": unchanged_unidentified,
            "named_representative_rows_included": representatives,
            "anonymous_family_rows_linked_by_disclosure": linked_families,
            "reported_month": period, "reported_market": market,
            "reported_company_abbreviation": result["companyAbbreviation"],
            "normalizer": NORMALIZER}

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
    same_version = previous and previous.get("sha256") == digest
    rec = {"url": url, "source_date": asof, "sha256": digest,
           "raw_archive": archive.name, "fetched_at": now,
           "first_captured_at": previous.get("first_captured_at", now) if same_version else now,
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

def irb_master(base, month, asof=None):
    out = {}
    for market in MARKETS:
        rec = get_json(base / "irb110" / month / (market + ".json"))
        if not rec:
            return {}
        archive = base / "irb110" / month / rec["raw_archive"]
        try:
            if asof and dt.datetime.fromisoformat(rec["fetched_at"]) > asof:
                return {}
            raw = gzip.decompress(archive.read_bytes())
            if hashlib.sha256(raw).hexdigest() != rec["sha256"]:
                return {}
            rows = parse_irb110(raw)
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            return {}
        for code, data in rows.items():
            if code in out:
                raise ValueError("CROSS_MARKET_DUPLICATE_CODE")
            out[code] = dict(data, market=market)
    return out

def read_detail_capture(record, month, market):
    receipt = get_json(record)
    if not receipt:
        raise ValueError("MOPS_CAPTURE_RECEIPT_MISSING")
    name = receipt.get("raw_archive", "")
    if not name or Path(name).name != name:
        raise ValueError("MOPS_CAPTURE_ARCHIVE_PATH_INVALID")
    raw = gzip.decompress((record.parent / name).read_bytes())
    if hashlib.sha256(raw).hexdigest() != receipt.get("sha256"):
        raise ValueError("MOPS_CAPTURE_HASH_MISMATCH")
    if receipt.get("source_date") != month or receipt.get("url") != MOPS_URL:
        raise ValueError("MOPS_CAPTURE_SOURCE_OR_PERIOD_MISMATCH")
    payload = receipt.get("request_payload")
    if payload is not None:
        year, m = month.split('-')
        expected = dict(companyId=record.stem, dataType="2", subsidiaryCompanyId="",
                        year=str(int(year)-1911), month=m)
        if payload != expected:
            raise ValueError("MOPS_ARCHIVED_REQUEST_ISSUER_OR_PERIOD_MISMATCH")
    return receipt, raw, parse_detail(raw, month, market)

def normalized_detail(record, receipt, raw, parsed, code, month, market, prior=None, payload=None):
    # Keep the old normalized receipt for replay; revised interpretation becomes
    # available now, even when original response bytes were captured earlier.
    if (prior and prior.get("normalizer") == NORMALIZER and prior.get("code") == code
            and prior.get("month") == month and prior.get("market") == market and all(
            prior.get(k) == v for k, v in parsed.items())):
        return False
    if prior:
        packed = (json.dumps(prior, ensure_ascii=False, sort_keys=True) + "\n").encode()
        history = record.parent / "normalization_history" / code / (hashlib.sha256(packed).hexdigest() + ".json")
        if not history.exists():
            atomic(history, packed)
    archive = record.parent / (code + "_" + receipt["sha256"] + ".gz")
    if archive.exists():
        if gzip.decompress(archive.read_bytes()) != raw:
            raise ValueError("MOPS_EXISTING_ARCHIVE_BYTES_CONFLICT")
    else:
        atomic(archive, gzip.compress(raw, mtime=0))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    updated = dict(receipt, **parsed, code=code, month=month, market=market,
                   raw_archive=archive.name, normalization_available_at=now,
                   status="OFFICIAL_MOPS_CAPTURED_HOLDER_DEDUP_UNVERIFIED")
    if payload is not None:
        updated["request_payload"] = payload
    updated["request_payload_archived"] = isinstance(updated.get("request_payload"), dict)
    put_json(record, updated)
    return True

def recover_failed_original(base, month, code, market):
    """Compatibility entrypoint; preserve capture and interpretation clocks."""
    try:
        rec, raw, parsed = read_detail_capture(base / 'failed' / month / (code + '.json'), month, market)
        record = base / 'detail' / month / (code + '.json')
        normalized_detail(record, rec, raw, parsed, code, month, market, prior=get_json(record))
        return True
    except (OSError, ValueError, TypeError, KeyError, EOFError):
        return False

def capture_details(base, months, master, limit, gap=2.0, getter=fetch):
    requested, succeeded, recovered, renormalized, errors = 0, 0, 0, 0, []
    queue = []
    cached_errors = []
    # Discover recent-year buyers across the *whole* market first, not nine
    # months of one stock before checking the next. Earlier months backfill later.
    for month in reversed(months):
        for code in sorted(master):
            record = base / "detail" / month / (code + ".json")
            prior = get_json(record)
            # Recheck both successful and previously rejected originals before
            # making any new HTTP request. Parser repairs must not wait for the
            # network retry delay or leave a silently stale normalization.
            reused = False
            for source in (record, base / "failed" / month / (code + ".json")):
                try:
                    rec, raw, parsed = read_detail_capture(source, month, master[code]["market"])
                    changed = normalized_detail(record, rec, raw, parsed, code, month,
                                                master[code]["market"], prior=prior)
                    if source != record:
                        recovered += 1
                    elif changed:
                        renormalized += 1
                    reused = True
                    break
                except (OSError, ValueError, TypeError, KeyError, EOFError) as ex:
                    if source.is_file():
                        cached_errors.append(dict(code=code, month=month, reason=str(ex)[:250]))
            if reused:
                continue
            queue.append((month, code))
    for month, code in queue:
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
            break
        requested += 1
        y, m = month.split("-")
        payload = {"companyId": code, "dataType": "2", "subsidiaryCompanyId": "",
                   "year": str(int(y) - 1911), "month": m}
        raw = None
        try:
            raw = getter(MOPS_URL, payload)
            parsed = parse_detail(raw, month, master[code]["market"])
            record = base / "detail" / month / (code + ".json")
            prior = get_json(record)
            receipt = save_original(record, raw, MOPS_URL, month, prior)
            normalized_detail(record, receipt, raw, parsed, code, month,
                              master[code]["market"], prior=prior, payload=payload)
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
                        "errors": errors, "recovered_from_saved_originals": recovered,
                        "renormalized_existing_details": renormalized,
                        "cached_reparse_error_count": len(cached_errors),
                        "cached_reparse_errors": cached_errors[:60],
                        "stopped": "SOURCE_OUTAGE_NO_ZERO_FILL"}
        if gap > 0:
            time.sleep(gap)
    return {"requested": requested, "succeeded": succeeded, "errors": errors,
            "recovered_from_saved_originals": recovered,
            "renormalized_existing_details": renormalized,
            "cached_reparse_error_count": len(cached_errors),
            "cached_reparse_errors": cached_errors[:60]}

def build_ranking(base, months, master, asof=None):
    asof = asof or dt.datetime.now(dt.timezone.utc)
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
            try:
                for clock in ("fetched_at", "normalization_available_at"):
                    if row.get(clock) and dt.datetime.fromisoformat(row[clock]) > asof:
                        raise ValueError("MOPS_CAPTURE_OR_NORMALIZATION_FROM_FUTURE")
                _, _, parsed = read_detail_capture(base / "detail" / month / (code + ".json"),
                                                   month, item["market"])
                if any(parsed[k] != row[k] for k in ("buy_shares", "sell_shares")):
                    raise ValueError("NORMALIZED_SOURCE_MISMATCH")
            except (OSError, ValueError, KeyError, TypeError, EOFError):
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
                 "buy_amount_is_observed_months_only": not complete_months,
                 "goodinfo_holdings_crosscheck_url":
                     "https://goodinfo.tw/tw/StockDirectorSharehold.asp?STOCK_ID=" + code}
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
    p.add_argument("--reparse-only", action="store_true",
                   help="Recheck saved original responses without any HTTP request")
    p.add_argument("--asof", default=None, help="Taiwan-local date YYYY-MM-DD")
    args = p.parse_args()
    if (args.months is not None and not 1 <= args.months <= 36) or not 0 <= args.max_details <= 2000:
        p.error("unsafe window or request cap")
    today = dt.date.fromisoformat(args.asof) if args.asof else dt.datetime.now(TW).date()
    months = months_ending(today, args.months) if args.months is not None else months_year_to_date(today)
    base = Path(args.base)
    failures = [] if args.reparse_only else capture_irb(base, months)
    cutoff = (dt.datetime.combine(today, dt.time.max, tzinfo=TW)
              if args.asof else None)
    master = irb_master(base, months[-1], cutoff) if months else {}
    if master:
        state = capture_details(base, months, master, 0 if args.reparse_only else args.max_details,
                                0 if args.reparse_only else args.gap)
        result = build_ranking(base, months, master, cutoff)
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
    result["normalizer"] = NORMALIZER
    result["source_connections"] = {
        "automatic_primary_sources": [{"name": "公開資訊觀測站事後申報", "url": MOPS_URL},
                                       {"name": "證交所SIIS月報", "url": IRB_HOST}],
        "external_references_not_automatic_inputs": REFERENCE_SITES,
        "holdings_delta_or_pretransfer_notice_is_not_market_purchase": True}
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
          "自動資料來源為公開資訊觀測站事後申報與證交所月報；Goodinfo提供持股口徑交叉查核連結。",
          "CMoney與豹投資目前僅列外部參考，未串接其資料服務；持股增減不直接視為集中市場買進。",
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
                      "verified_detail_month_count": result.get("verified_detail_month_count", 0),
                      "observed_positive_issuer_count": result.get("observed_positive_issuer_count", 0),
                      "recovered_from_saved_originals": state.get("recovered_from_saved_originals", 0),
                      "renormalized_existing_details": state.get("renormalized_existing_details", 0),
                      "attempts": state["requested"], "successful": state["succeeded"]},
                     ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
