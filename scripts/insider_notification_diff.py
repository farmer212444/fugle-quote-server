#!/usr/bin/env python3
"""Fail-closed comparison of observed insider buyers against last *delivered* notice.

This program does not certify official raw filings. The caller must supply a
separately audited allowlist of issuer codes whose MOPS originals and SHA-256
receipts were verified. A successful comparison never advances the baseline;
only the delivery system may do that after confirmed notification.
"""
import argparse
import json
from pathlib import Path

def compare(previous, current, verified_codes, threshold=0.25, coverage_step=1.0):
    if current.get("marketwide_rank_claim_permitted") is True:
        raise ValueError("Unexpected marketwide certification claim")
    if current.get("status") != "PARTIAL_YTD_BUYER_DISCOVERY_NOT_MARKETWIDE":
        raise ValueError("Unknown report status; refuse notification")
    expected = current.get("expected_detail_month_count", 0)
    done = current.get("verified_detail_month_count", 0)
    if not isinstance(expected, int) or expected <= 0 or not isinstance(done, int) or not 0 <= done <= expected:
        raise ValueError("Invalid coverage counts")
    oldrows = {r["code"]: r for r in previous.get("positive_buy_observed_sample_top100", [])}
    rows = current.get("positive_buy_observed_sample_top100", [])
    changes = []
    for row in rows:
        code = row["code"]
        if code not in verified_codes or row.get("buy_lots", 0) <= 0:
            continue
        old = oldrows.get(code)
        delta = round(row["buy_pct_of_issued"] - old["buy_pct_of_issued"], 5) if old else None
        if old is None or abs(delta) >= threshold:
            changes.append({
                "code": code, "buy_lots": row["buy_lots"],
                "buy_pct_of_issued": row["buy_pct_of_issued"],
                "observed_months": row.get("observed_months", []),
                "missing_months": row.get("missing_months", []),
                "expected_ytd_month_count": row.get("expected_ytd_month_count"),
                "change_pct_points": delta,
                "reason": "new_observed_buyer" if old is None else "significant_ratio_change"
            })
    old_expected = previous.get("expected_detail_month_count", 0)
    old_done = previous.get("verified_detail_month_count", 0)
    old_coverage = 100 * old_done / old_expected if old_expected else 0
    coverage = 100 * done / expected
    coverage_improved = coverage - old_coverage >= coverage_step and done > old_done
    return {
        "notify": bool(changes or coverage_improved),
        "changes": changes,
        "coverage_pct": round(coverage, 4),
        "previous_coverage_pct": round(old_coverage, 4),
        "coverage_improved": coverage_improved,
        "verified_detail_month_count": done,
        "expected_detail_month_count": expected,
        "missing_detail_month_count": expected - done,
        "warning": "部分月份觀察量不是2026完整累計，也不是正式全市場Top排行",
        "source": "https://github.com/farmer212444/fugle-quote-server/blob/main/tw-market-data/rankings/insider_marketwide_latest.json"
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-notified", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--verified-manifest", required=True,
                        help="Independently audited JSON with verified_codes array; never infer from ranking")
    parser.add_argument("--threshold-pp", type=float, default=0.25)
    parser.add_argument("--coverage-step-pp", type=float, default=1.0)
    args = parser.parse_args()
    def read(p):
        return json.loads(Path(p).read_text(encoding="utf-8"))
    manifest = read(args.verified_manifest)
    if manifest.get("official_originals_sha256_verified") is not True:
        raise SystemExit("FAIL CLOSED: no independently verified MOPS/SHA-256 manifest")
    verified = set(manifest.get("verified_codes", []))
    result = compare(read(args.previous_notified), read(args.current), verified,
                     args.threshold_pp, args.coverage_step_pp)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
