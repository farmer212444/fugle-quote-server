#!/usr/bin/env python3
"""Independently check shadow insider aggregates, never certify MOPS originals.

Public monthly summaries may duplicate legal persons across director/manager/
10%-owner roles; transfers, pledges and market trades are separate channels.
Without original bytes, receipt date and stable holder identity, no insider
quality-gate PASS, 2027 valuation override, or PIT investment signal is allowed.
"""
import argparse
import json
import re
from pathlib import Path

MONTHS = tuple(f"2026-{month:02d}" for month in range(4, 10))
EXPECTED = {"9802": 3254, "9910": 5033, "6965": 1143,
            "6768": 95, "9904": 0, "6890": -42}


def integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("INVALID_NONNEGATIVE_LOTS_" + label)
    return value


def dedupe_primary_holder_rows(rows):
    """Deduplicate multiple *roles* of one holder, never distinct accounts.

    A trusted stable holder/account identifier is required. A display name
    alone, especially 'spouse/minor children', is NOT an identity key.
    Counts are 1,000-share lots here. This validates only supplied rows,
    not whether they originated from MOPS or were published as of any date.
    """
    grouped = {}
    fields = ("market_buy_lots", "market_sell_lots", "other_gain_lots",
              "other_loss_lots", "pledged_lots", "released_lots")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_HOLDER_ROW")
        holder = row.get("holder_account_key")
        account_class = row.get("account_class")
        issuer = str(row.get("issuer", ""))
        month = row.get("month")
        if (not isinstance(holder, str) or not holder.strip()
                or account_class not in ("SELF", "NOMINEE", "SPOUSE_MINORS", "LEGAL_ENTITY")
                or not re.fullmatch(r"\d{4}", issuer)
                or not re.fullmatch(r"\d{4}-\d{2}", str(month))):
            raise ValueError("AMBIGUOUS_HOLDER_OR_PERIOD_IDENTITY")
        key = (issuer, month, account_class, holder.strip())
        values = tuple(integer(row.get(k), k) for k in fields)
        before, after = row.get("opening_lots"), row.get("closing_lots")
        if before is not None:
            integer(before, "opening_lots")
        if after is not None:
            integer(after, "closing_lots")
        payload = (values, before, after)
        if key in grouped and grouped[key] != payload:
            raise ValueError("CONFLICTING_DUPLICATED_HOLDER_ROLES")
        grouped[key] = payload
    buy = sell = other = 0
    unmatched = []
    for key, (values, before, after) in grouped.items():
        b, s, other_in, other_out, _, _ = values
        buy += b
        sell += s
        other += other_in - other_out
        if before is None or after is None:
            unmatched.append({"issuer": key[0], "month": key[1],
                              "holder_key": key[3], "reason": "MISSING_ROLLFORWARD_ENDPOINT"})
        elif before + b - s + other_in - other_out != after:
            unmatched.append({"issuer": key[0], "month": key[1],
                              "holder_key": key[3], "reason": "HOLDINGS_ROLLFORWARD_MISMATCH"})
    return dict(unique_holder_accounts=len(grouped), market_buy_lots=buy,
                market_sell_lots=sell, market_net_lots=buy-sell,
                nonmarket_net_lots=other, rollforward_exceptions=unmatched,
                official_original_receipt_verified=False,
                insider_quality_gate="PENDING_ORIGINAL_IDENTITY_AND_PIT_CERTIFICATION")


def analyze_shadow(doc, expected=None):
    if (doc.get("schema") != "V1_INSIDER_SECONDARY_SHADOW_NOT_OFFICIAL"
            or doc.get("record_provenance") != "SECONDARY_MOPS_DERIVED_SUMMARY_ONLY"
            or doc.get("official_mops_post_trade_originals_received") is not False
            or doc.get("original_bytes_sha256") is not None
            or doc.get("asof_reporting_month") != "2026-09"
            or tuple(doc.get("months") or ()) != MONTHS
            or doc.get("unit") != "lots_1000_shares"):
        raise ValueError("UNSUPPORTED_OR_FALSE_OFFICIAL_SHADOW_CLAIM")
    if (doc.get("insider_claims_quality_gate") != "PENDING_ORIGINAL_MOPS_AND_IDENTITY_DEDUP"
            or doc.get("issuer_baseline_eps_pe_base_changed") is not False
            or doc.get("formal_aplus_changed") is not False
            or doc.get("automatic_exit") is not False):
        raise ValueError("UNAUTHORIZED_FORMAL_MODEL_PROMOTION")
    output = []
    seen = set()
    for row in doc["records"]:
        code = str(row["code"])
        if not re.fullmatch(r"\d{4}", code) or code in seen or row.get("market") != "TWSE":
            raise ValueError("DUPLICATE_OR_INVALID_ISSUER_MARKET")
        seen.add(code)
        if row.get("source_url") != f"https://toalpha.tw/stock/{code}/filings":
            raise ValueError("UNTRUSTED_OR_MISMATCHED_SECONDARY_URL")
        buys, sells = row["market_buys"], row["market_sells"]
        if len(buys) != 6 or len(sells) != 6:
            raise ValueError("MONTHLY_WINDOW_INCOMPLETE")
        total_buys = sum(integer(v, "buy") for v in buys)
        total_sells = sum(integer(v, "sell") for v in sells)
        net = total_buys-total_sells
        if expected is not None and expected.get(code) != net:
            raise ValueError("SECONDARY_MONTHLY_NET_RECONCILIATION_FAILED_" + code)
        output.append(dict(code=code, name=row["name"],
                           secondary_six_month_buys_lots=total_buys,
                           secondary_six_month_sells_lots=total_sells,
                           secondary_six_month_net_lots=net,
                           source_url=row["source_url"], evidence_status="SECONDARY_ONLY_PENDING_ORIGINAL",
                           warnings=row.get("unresolved", []), formal_grade_changed=False))
    if not output or (expected is not None and seen != set(expected)):
        raise ValueError("SELECTED_SIX_ISSUERS_MISSING")
    return dict(months=list(MONTHS), data_status="SECONDARY_ONLY_NOT_MOPS_CERTIFIED",
                selected_issuer_count=len(output), formal_Aplus_or_Aplusplus_promoted=0,
                valuation_override=False, automated_exit=False, issuers=output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_secondary_shadow.json")
    parser.add_argument("--output", default="tw-market-data/evidence/v880/insider_reviews/shoe_makers_202609_shadow_audit.json")
    args = parser.parse_args()
    doc = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = analyze_shadow(doc, EXPECTED)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["data_status"], "issuers": len(report["issuers"]),
                      "formal_promotions": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
