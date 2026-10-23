#!/usr/bin/env python3
"""Cross-check archived MOPS insider trade originals vs September TWSE balances.

Cross-source balance matching != named beneficial-owner identity verification.
Raw original hash and rolling own-share arithmetic are audited; prior-month
publication availability and issuer trade P&L are NEVER retrospectively inferred.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import html
import json
import pathlib
import re
import unicodedata
from collections import Counter
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.v8105_mops_insider_original_probe import parse_api, provisional_role_dedup

CODES = ("9802", "6965")
MONTHS = ("2026-07", "2026-08", "2026-09")
MOPS_ARCHIVE = "tw-market-data/evidence/v880/insider_reviews/original_probe_archive/run_39947008213_1"
HOLDINGS_ARCHIVE = "tw-market-data/evidence/v880/insider_reviews/twse_current_ownership_archive/run_39953995531_1"


def norm(s):
    value = html.unescape(unicodedata.normalize("NFKC", str(s or "")))
    return re.sub(r"""[\s,，.'"“”‘’]+""", "", unicodedata.normalize("NFKC", value).upper())


def checked_raw(folder, filename, sha):
    raw = gzip.decompress((folder / filename).read_bytes())
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("ORIGINAL_ARCHIVE_HASH_MISMATCH")
    return raw


def archive_mops(root, code, month):
    src = root/MOPS_ARCHIVE/month/code
    receipt = json.loads((src/"receipt.json").read_bytes())
    if (receipt.get("company_code") != code or receipt.get("reporting_month") != month
            or receipt.get("official_historical_published_at") is not None
            or receipt.get("pit_backtest_admitted") is not False):
        raise ValueError("MOPS_RECEIPT_VINTAGE_OR_PIT_MISMATCH")
    raw = checked_raw(src, "original_http_response.gz", receipt["original_response_sha256"])
    return parse_api(raw, code, month), receipt


def archive_twse(root, src):
    folder = root/HOLDINGS_ARCHIVE/src
    receipt = json.loads((folder/"receipt.json").read_bytes())
    if (receipt.get("source_family") != src
            or receipt.get("historical_publication_month_reconstructed") is not False
            or receipt.get("formal_13_gate_passed") is not False):
        raise ValueError("TWSE_CURRENT_AS_HISTORICAL_SOURCE")
    raw = checked_raw(folder, "original_response.gz", receipt["original_response_sha256"])
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("OFFICIAL_TWSE_SOURCE_NOT_ARRAY")
    return [r for r in data if str(r.get("公司代號")) in CODES], receipt


def audit(root):
    root = pathlib.Path(root)
    holdings, holding_receipt = archive_twse(root, "t187ap11_L")
    basics, company_receipt = archive_twse(root, "t187ap03_L")
    rows = {(r["公司代號"]):r for r in basics}
    if set(rows)!=set(CODES):
        raise ValueError("MISSING_OFFICIAL_ISSUED_SHARE_DENOMINATOR")
    if any(int(r["已發行普通股數或TDR原股發行股數"]) <=0 for r in rows.values()):
        raise ValueError("INVALID_OFFICIAL_ISSUED_SHARE_COUNT")
    by_company = {}
    for code in CODES:
        report = {}
        mops_monthly = {}
        for month in MONTHS:
            records, receipt = archive_mops(root, code, month)
            mismatch=[r for r in records if
              r["opening_own_shares"] + r["market_buy_shares"] - r["market_sell_shares"]
              + r["other_buy_shares"] - r["other_sell_shares"] != r["closing_own_shares"]]
            rollup=provisional_role_dedup(records)
            report[month]={"raw_rows":len(records),"rollforward_mismatched_rows":len(mismatch),
                            "economic_positions_provisional":rollup["provisionally_distinct_positions"],
                            "market_net_lots_provisional":rollup["market_net_lots_provisional"],
                            "asof_source_first_observed":receipt["first_observed_at_utc"]}
            mops_monthly[month]=records
        sep = mops_monthly["2026-09"]
        by_key = Counter((norm(x["name"]),x["closing_own_shares"]) for x in sep if x["name"])
        now_hold = [r for r in holdings if str(r.get("公司代號"))==code]
        if not now_hold:
            raise ValueError("MISSING_OFFICIAL_SEPTEMBER_BALANCES_"+code)
        periods=set(str(r.get("資料年月", "")) for r in now_hold)
        if periods != {"11509"}:
            raise ValueError("CURRENT_HOLDINGS_NOT_SEPTEMBER_BALANCES_"+code)
        matches = [r for r in now_hold if by_key[(norm(r["姓名"]),int(r["目前持股"]))]>0]
        unmatched = [r for r in now_hold if by_key[(norm(r["姓名"]),int(r["目前持股"]))]==0]
        if any(report[m]["rollforward_mismatched_rows"] for m in MONTHS):
            raise ValueError("INTERNAL_MOPS_SHARE_ROLLFORWARD_MISMATCH_"+code)
        net=sum(report[m]["market_net_lots_provisional"] for m in MONTHS)
        denom=int(rows[code]["已發行普通股數或TDR原股發行股數"])
        frac=net*1000/denom
        by_company[code]={
            "name":rows[code].get("公司簡稱"),
            "issuer_current_shares_at_basics_report":denom,
            "current_basic_report_date_roc":rows[code]["出表日期"],
            "holdings_month_roc":"11509",
            "holdings_report_date_roc":sorted({r["出表日期"] for r in now_hold}),
            "third_party_insider_net_lots_not_used":True,
            "month_rollforwards":report,
            "september_holding_rows_checked":len(now_hold),
            "september_holding_rows_matching_mops_balance":len(matches),
            "september_unmatched": [{"role":r["職稱"],"name":r["姓名"],"shares":r["目前持股"]} for r in unmatched],
            "all_cross_source_share_balances_match":not unmatched,
            "jul_sep_market_net_lots_provisional":round(net,3),
            "three_month_net_pct_of_oct22_issued_shares":round(100*frac,5),
            "research_materiality_0_05pct_current_denominator_observed":frac>=.0005,
            "historical_monthly_issued_shares_pit_certified":False,
            "beneficial_owner_unique_accounts_certified":False,
            "individual_transaction_first_publication_dates_certified":False,
            "pass_formal_insider_quality_gate":False,
        }
    return {
        "schema":"V8105_TWO_OFFICIAL_SOURCE_CROSSCHECK_RESEARCH_ONLY",
        "data_sources":"MOPS_POST_TRADE_ORIGINAL_BYTES_AND_TWSE_T187AP11_L_T187AP03_L",
        "twse_current_source_captured_at_utc":[holding_receipt["first_observed_at_utc"],company_receipt["first_observed_at_utc"]],
        "claims": {
            "raw_original_bytes_sha_verified":True,
            "mops_every_row_rollforward_checked":True,
            "september_name_and_close_share_balances_crosschecked":True,
            "market_buys_deduced_from_IRB_balance_change":False,
            "identity_proof_or_historical_PIT_completed":False,
            "2027_return_certified":False,
        },
        "issuer_count":len(by_company),
        "issued_capital_snapshot_not_all_historical_months":True,
        "formal_Aplus_or_Exit_changed":False,
        "crosschecks":by_company,
        "research_methods_remaining":["MOPS_BENEFICIAL_ACCOUNT_STABLE_IDENTITY",
          "FIRST_PUBLICATION_AND_REVISION_RECEIPTS_BEFORE_HISTORICAL_SIGNAL",
          "HISTORICAL_JUL_AUG_SEP_ISSUED_SHARES_ASOF",
          "252_DATED_TRADING_CLOSES_AND_NEXT_OPEN_FILLABILITY",
          "YEAR_LATER_CORPORATE_ACTION_ADJUSTED_0050_MATCHED_NET_RETURN"],
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=pathlib.Path,default=pathlib.Path("tw-market-data").parent)
    p.add_argument("--out",type=pathlib.Path)
    a=p.parse_args(argv)
    result=audit(a.root)
    s=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if a.out:
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.write_text(s,encoding="utf-8")
    print(s)


if __name__=="__main__":
    main()
