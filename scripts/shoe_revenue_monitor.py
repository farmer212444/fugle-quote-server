#!/usr/bin/env python3
"""Monitor Taiwan footwear-sector monthly revenue from official open-data feeds.

Fail closed: missing issuers or malformed data must not be interpreted as zero.
"""
import argparse
import datetime as dt
import json
import urllib.request
from pathlib import Path

WATCH = {"9802": "鈺齊-KY", "6768": "志強-KY", "9910": "豐泰", "9904": "寶成", "6890": "來億-KY", "6965": "中傑-KY", "9938": "百和", "8404": "百和興業-KY"}
DEFAULT_FEEDS = {
    "listed": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "otc": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
}
def field(row, *names):
    for name in names:
        if name in row and str(row[name]).strip():
            return str(row[name]).strip()
    return ""

def number(raw):
    return float(raw.replace(",", "").replace("%", "").replace("＋", "+"))

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TaiwanRevenueMonitor/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=35) as response:
        data = json.load(response)
    if not isinstance(data, list):
        raise ValueError("Official endpoint did not return an array")
    return data

def normalize(rows, month):
    output = {}
    year, mon = map(int, month.split("-"))
    for row in rows:
        code = field(row, "公司代號", "公司代碼", "股票代號")
        if code not in WATCH:
            continue
        raw_year = field(row, "資料年月", "年月", "營收年月")
        if raw_year:
            digits = "".join(c for c in raw_year if c.isdigit())
            if len(digits) >= 5:
                # 11510 (ROC) or 202610 (Gregorian), possibly 115/10/xx.
                y = int(digits[:4]) if len(digits) >= 6 and digits[:4].startswith("20") else int(digits[:3]) + 1911
                m = int(digits[4:6]) if y == int(digits[:4]) else int(digits[3:5])
                if (y, m) != (year, mon):
                    continue
        sales = field(row, "當月營收", "當月營業收入", "本月營收")
        yoy = field(row, "去年同月增減(%)", "去年同月增減％", "去年同月增減百分比", "去年同月增減")
        mom = field(row, "上月比較增減(%)", "上月比較增減％", "上月比較增減百分比", "上月比較增減")
        if not raw_year or not sales or not yoy:
            continue
        output[code] = {"code": code, "name": WATCH[code], "month": month, "revenue_thousand_twd": number(sales), "yoy_pct": number(yoy), "mom_pct": number(mom) if mom else None}
    return output

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--output", default="tw-market-data/revenue/shoe_revenue_latest.json")
    p.add_argument("--listed-url", default=DEFAULT_FEEDS["listed"])
    p.add_argument("--otc-url", default=DEFAULT_FEEDS["otc"])
    args = p.parse_args()
    dt.date.fromisoformat(args.month + "-01")
    records = {}
    errors = {}
    for market, url in (("listed", args.listed_url), ("otc", args.otc_url)):
        try:
            records.update(normalize(fetch(url), args.month))
        except Exception as exc:
            errors[market] = str(exc)
    if errors:
        raise SystemExit("Official feed unavailable; preserving previous snapshot: " + json.dumps(errors, ensure_ascii=False))
    if not records:
        raise SystemExit("No matching official monthly records; preserving previous snapshot")
    result = {"schema": "SHOE_REVENUE_OBSERVED_V1", "month": args.month, "source": DEFAULT_FEEDS, "records": [records[k] for k in sorted(records)], "missing_codes": sorted(set(WATCH)-set(records)), "partial": len(records) != len(WATCH), "note": "Unreported or missing data is NOT zero. Verify MOPS original filing before formal certification."}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}\n    if old.get("month", "") > args.month:\n        raise SystemExit("Refusing to replace a newer monthly snapshot with an older month")
    if old.get("month") == args.month and old.get("records") == result["records"]:
        print("NO_CHANGE")
        return
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"UPDATED {len(records)}/{len(WATCH)}; missing {result['missing_codes']}")
if __name__ == "__main__":
    main()
