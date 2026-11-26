"""Independent market-session source for the first 0050 retrospective pilot.

FMTQIK is market-wide daily turnover, distinct from STOCK_DAY instrument
quotes. Preserve original response bytes and hashes. No PIT or OOS claims.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from alphamax.benchmark_0050_cash_reference import simulate_holding_period

START = "2025-01-02"
END = "2026-01-02"
MONTHS = tuple(f"2025{m:02d}" for m in range(1, 13)) + ("202601",)
URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={month}01&response=json"
SPLIT_NOTICE = "https://www.twse.com.tw/zh/ETFortune/announcement?company=A00005&date=20250509&fund=0050&seq=1&type=all"


def parse_market_sessions(raw, month):
    """Strict schema/date/positive market volume checks; reject duplicates."""
    obj = json.loads(raw)
    if obj.get("stat") != "OK":
        raise ValueError("MARKET_CALENDAR_SOURCE_NOT_OK")
    fields = obj.get("fields", [])
    if len(fields) < 2 or fields[0] != "日期" or fields[1] != "成交股數":
        raise ValueError("MARKET_CALENDAR_UNEXPECTED_FIELDS")
    rows = obj.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError("MARKET_CALENDAR_EMPTY")
    days = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("MARKET_CALENDAR_INVALID_ROW")
        y, m, d = map(int, row[0].split("/"))
        day = date(y + 1911, m, d)
        if day.strftime("%Y%m") != month or day.weekday() >= 5:
            raise ValueError("MARKET_CALENDAR_INVALID_SESSION")
        if int(str(row[1]).replace(",", "")) <= 0:
            raise ValueError("MARKET_CALENDAR_NONPOSITIVE_VOLUME")
        days.append(day.isoformat())
    if days != sorted(set(days)):
        raise ValueError("MARKET_CALENDAR_DUPLICATE_OR_UNORDERED")
    return days


def fetch_market(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise ValueError("MARKET_CALENDAR_HTTP_ERROR")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("MARKET_CALENDAR_RESPONSE_TOO_LARGE")
    return raw


def capture_pilot(price_root, notice_root, output_dir, fetch=fetch_market):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    report = {"status": "BLOCKED_0050_INDEPENDENT_CALENDAR",
              "start": START, "end": END, "receipts": [], "errors": [],
              "split_suspension_notice": SPLIT_NOTICE,
              "split_suspension_start": "2025-06-11",
              "split_suspension_end": "2025-06-17",
              "eligible_for_pit_or_oos_training": False,
              "formal_a_plus": False, "admitted_training_labels": 0}
    market_days = []
    for month in MONTHS:
        url = URL.format(month=month)
        try:
            raw = fetch(url)
            path = root / (month + ".json")
            path.write_bytes(raw)
            receipt = {"month": month, "url": url, "path": path.name,
                       "sha256": hashlib.sha256(raw).hexdigest()}
            report["receipts"].append(receipt)
            days = parse_market_sessions(raw, month)
            receipt["session_count"] = len(days)
            market_days.extend(days)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            report["errors"].append({"month": month, "reason": str(exc)})
    if not report["errors"] and len(report["receipts"]) == len(MONTHS):
        excluded = [d for d in market_days if "2025-06-11" <= d <= "2025-06-17"]
        expected = [d for d in market_days if START <= d <= END and d not in excluded]
        report.update({"market_sessions_in_interval": len(expected) + len(excluded),
                       "excluded_split_sessions": excluded, "expected_sessions": expected})
        try:
            if len(excluded) != 5:
                raise ValueError("UNEXPECTED_SPLIT_SUSPENSION_SESSIONS")
            result = simulate_holding_period(
                price_root, notice_root, start=START, end=END,
                buy_fee_rate="0.001425", sell_fee_rate="0.001425",
                sell_tax_rate="0.001", expected_trading_days=expected)
            report["simulation"] = result
            if result.get("calendar_matches_supplied_sessions"):
                report["status"] = "RETROSPECTIVE_PILOT_MARKET_SESSION_MATCH_PENDING_RECEIPT_AUDIT"
            else:
                report["status"] = result["status"]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report["errors"].append({"stage": "simulation", "reason": str(exc)})
    (root / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--price-root", required=True)
    p.add_argument("--notice-root", required=True)
    p.add_argument("--output-dir", required=True)
    a = p.parse_args()
    result = capture_pilot(a.price_root, a.notice_root, a.output_dir)
    print(json.dumps({"status": result["status"], "receipts": len(result["receipts"]),
                      "errors": result["errors"]}, ensure_ascii=False))
