#!/usr/bin/env python3
"""Research-only 9802 Q3 early-filing revaluation. Does not change official Top10/A+."""
import datetime as dt
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880.math import operating_scenario, returns
from scripts.v896_original_archive import validate_bundle, read_original_archive

DATA=Path("tw-market-data")
SOURCE="https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"

def read(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def num(v):
    try:
        if v is None or isinstance(v,bool):return None
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None
def timestamp(v):
    t=dt.datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("UNZONED_TIMESTAMP")
    return t

def revalue(research,full,receipt,prior):
    if (research.get("estimate_vintage")!=full.get("estimate_vintage") or
        research.get("model")!=full.get("model") or
        research.get("asof_price_date")!=full.get("asof_price_date")):
        raise ValueError("FROZEN_RESEARCH_MODEL_VINTAGE_MISMATCH")
    if full.get("financial_last_quarter")!="2026-Q2":
        return dict(status="QUARTER_ALREADY_IN_MAIN_MODEL",code="9802",certified_Aplus=False)
    if any((receipt.get("code")!="9802",receipt.get("market")!="TWSE",
            receipt.get("financial_period")!="2026-Q3",receipt.get("source_url")!=SOURCE,
            receipt.get("quarter_title_checked") is not True,
            receipt.get("issuer_filing_PIT_verified") is not False,
            receipt.get("must_not_set_certification_gate_pass") is not True)):
        raise ValueError("EARLY_OFFICIAL_RECEIPT_NOT_ADMISSIBLE")
    sha=receipt.get("original_html_sha256","")
    if len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("ORIGINAL_RECEIPT_HASH_MISSING")
    if timestamp(receipt["captured_at_utc"])>timestamp(research["estimate_vintage"]):
        raise ValueError("FUTURE_RECEIPT_REFUSED")
    if prior.get("period")!="2026-Q2" or prior.get("market")!="TWSE" or prior.get("kind")!="income":
        raise ValueError("PRIOR_QUARTER_BASIS_MISMATCH")
    oldrows=[r for r in full.get("all_model_rows",[]) if r.get("code")=="9802" and r.get("market")=="TWSE"]
    if len(oldrows)!=1 or oldrows[0].get("financial_period")!="2026-Q2" or not oldrows[0].get("rankable"):
        raise ValueError("UNVERIFIED_PRIOR_9802_MODEL_ROW")
    old=oldrows[0]
    if old.get("formal_Aplus") or old.get("formal_Aplusplus"):
        raise ValueError("EARLY_REVALUE_MUST_NOT_EDIT_FORMAL_CERTIFICATE")
    p=[r for r in prior.get("rows",[]) if str(r.get("code"))=="9802"]
    n=receipt.get("observed_income_row",{})
    if len(p)!=1 or n.get("code")!="9802" or n.get("market")!="TWSE" or n.get("period")!="2026-Q3":
        raise ValueError("ISSUER_QUARTER_IDENTITY_MISMATCH")
    prev=p[0]
    for r in (prev,n):
        if r.get("unit")!="NTD_thousands_except_EPS" or r.get("year_to_date_values") is not True:
            raise ValueError("CUMULATIVE_REPORT_UNIT_MISMATCH")
    fields=("revenue_ytd_k","gross_profit_ytd_k","operating_profit_ytd_k")
    h=[num(prev.get(k)) for k in fields];q=[num(n.get(k)) for k in fields]
    if None in h+q:raise ValueError("Q3_REQUIRED_INCOME_LINE_MISSING")
    r2,g2,op2=h;r3,g3,op3=q
    if r2<=0 or r3<=r2:raise ValueError("Q3_REVENUE_YTD_INVALID")
    standalone=(g3-g2)/(r3-r2)
    cumul=g3/r3
    if not 0<=standalone<=.8 or not 0<=cumul<=.8:raise ValueError("Q3_MARGIN_OUTSIDE_PLAUSIBLE_RANGE")
    for key,v in [("new_quarter_gross_margin_pct",standalone),("year_to_date_gross_margin_pct",cumul)]:
        if num(receipt.get(key)) is None or abs(num(receipt[key])-100*v)>.02:
            raise ValueError("Q3_WATCH_GROSS_MARGIN_RECONCILIATION_FAIL")
    gm_diff=cumul-g2/r2
    expense_diff=(g3-op3)/r3-(g2-op2)/r2
    if max(abs(gm_diff),abs(expense_diff))>.035:
        raise ValueError("EXCESSIVE_MARGIN_REBASE_REQUIRES_REVIEW")
    close=num(old.get("reference_close"))
    if close is None or close<=0:raise ValueError("REFERENCE_PRICE_INVALID")
    new={}
    weights={"bear":.25,"base":.5,"bull":.75}
    for k,factor in weights.items():
        b=old[k]
        keys=("revenue_k","gross_margin","opex_ratio","nonoperating_k","tax_rate",
              "parent_fraction","shares","pe")
        v=[num(b.get(t)) for t in keys]
        if None in v:raise ValueError("FROZEN_OPERATING_BRIDGE_MISSING_"+k)
        revenue,gm,cost,nonop,tax,parent,shares,pe=v
        scenario=operating_scenario(revenue,max(0,min(1,gm+factor*gm_diff)),
                                    max(0,cost+factor*expense_diff),
                                    nonop,tax,parent,shares,pe)
        scenario.update(returns(scenario["target_price"],close,None,
                                research["asof_price_date"],old["target_date"]))
        new[k]=dict(eps=scenario["eps"],pe=scenario["pe"],
                    target_price=scenario["target_price"],
                    upside_pct=scenario["price_upside_pct"])
    compare=[r for r in research.get("all_model_row_summary",[])
             if r.get("rankable") and r.get("code")!="9802"
             and num(r.get("scenario_upside_pct")) is not None]
    up=new["base"]["upside_pct"]
    rank=1+sum(num(x["scenario_upside_pct"])>up for x in compare) if up is not None else None
    return dict(status="RESEARCH_ONLY_EARLY_Q3_REVALUED",code="9802",
                source=SOURCE,source_capture_sha256=sha,
                quarter="2026-Q3",source_published_at_verified=False,
                standalone_q3_gm_pct=round(100*standalone,3),
                q3_ytd_gm_pct=round(100*cumul,3),
                prior_h1_gm_pct=round(100*g2/r2,3),
                q3_minus_h1_ytd_gm_pp=round(100*gm_diff,3),
                opex_ratio_delta_pp=round(100*expense_diff,3),
                persistence_assumption=weights,
                old={k:dict(eps=old[k]["eps"],target_price=old[k]["target_price"]) for k in weights},
                new=new,shadow_if_substituted_rank=rank,
                comparator_sample_count=len(compare)+1,
                official_top10_unchanged=True,certified_Aplus=False,
                formal_gate_PASSES_created=0,
                all_market_other_issuers_remain_Q2=True,
                revenue_PE_and_dilution_denominator_unchanged=True,
                margin_persistence_is_unvalidated_sensitivity=True)

def issuer_press_source_status(research,data_root=DATA):
    """Cross-verify archived publisher Q3 press release and discovery receipts.

    A company-published *self-reported press release* is a research source,
    never a signed MOPS quarterly financial row or a formal gate PASS.
    """
    data_root=Path(data_root)
    original_status=validate_bundle(data_root,"9802")
    if not original_status.get("original_archive_hashes_verified"):
        return dict(status="WAITING_ISSUER_Q3_ARCHIVED_ORIGINAL",code="9802",
                    certified_Aplus=False,formal_gate_PASSES_created=0,
                    estimate_vintage=research.get("estimate_vintage"))
    source=read(data_root/"issuer/9802/manifest.json")
    if source.get("issuer")!="9802" or source.get("publisher")!="鈺齊國際":
        raise ValueError("PUBLISHER_ISSUER_IDENTITY_MISMATCH")
    archive=read_original_archive(data_root,"9802")
    candidates=[d for d in archive["documents"] if
                d.get("document_kind")=="news" and
                d.get("title")=="2026年第三季自結財報新聞稿" and
                d.get("document_date")=="2026-10-20"]
    if not candidates:
        return dict(status="WAITING_ISSUER_Q3_ARCHIVED_ORIGINAL",code="9802",
                    certified_Aplus=False,formal_gate_PASSES_created=0)
    if len(candidates)!=1:
        raise ValueError("AMBIGUOUS_PUBLISHER_Q3_NEWS_VERSION")
    doc=candidates[0]
    matches=[item for item in source.get("discovered",[]) if
             item.get("id")==doc["id"] and
             item.get("url")==doc["source_url"] and
             item.get("category")=="news" and
             item.get("site_display_date")==doc["document_date"]]
    if len(matches)!=1:
        raise ValueError("PUBLISHER_PRESS_SOURCE_MISSING_IN_DISCOVERY")
    original_versions=(source.get("receipts",{}).get(doc["id"],{}).get("versions",[]))
    receipts=[v for v in original_versions if v.get("sha256")==doc["sha256"]
              and v.get("bytes")==doc["bytes"]
              and v.get("source_url")==doc["source_url"]]
    if len(receipts)!=1:
        raise ValueError("PUBLISHER_PRESS_HASH_OR_SIZE_MISMATCH")
    captured_at=timestamp(doc["captured_at_utc"])
    recorded_at=timestamp(receipts[0]["captured_at_utc"])
    if captured_at!=recorded_at:
        raise ValueError("PUBLISHER_PRESS_RECEIPT_TIME_MISMATCH")
    if captured_at>timestamp(research["estimate_vintage"]):
        raise ValueError("Q3_PRESS_NOT_AVAILABLE_AT_RESEARCH_VINTAGE")
    if (doc["formal_gate_pass"] is not False or
            doc["independently_verified_issuer_filing_time"] is not False):
        raise ValueError("FALSE_PUBLISHER_PRESS_MOPS_OR_FORMAL_CLAIM")
    return dict(status="OFFICIAL_ISSUER_Q3_SELF_REPORTED_SOURCE_ARCHIVED",
                code="9802",quarter="2026-Q3",
                source=doc["source_url"],original_source_sha256=doc["sha256"],
                original_pdf_size_bytes=doc["bytes"],
                first_captured_at_utc=doc["captured_at_utc"],
                issuer_website_display_date=doc["document_date"],
                issuer_company_publication_PIT_verified=False,
                issuer_Q3_press_numbers_not_yet_reconciled_with_signed_MOPS_income=True,
                main_model_financial_last_quarter="2026-Q2",
                early_2027_eps_margin_sensitivity_updated=False,
                eps_pe_base_2027_unchanged=True,
                formal_gate_PASSES_created=0,certified_Aplus=False,
                original_bytes_sha256_checked=True,
                source_is_self_reported_press_not_full_quarterly_statement=True)

def main():
    rankings=DATA/"rankings"
    research=read(rankings/"latest_research.json")
    early=DATA/"fundamentals/early_watch/9802_2026-Q3.json"
    if not early.exists():
        try:
            result=issuer_press_source_status(research,DATA)
        except (OSError,ValueError,KeyError,TypeError) as e:
            result=dict(status="ISSUER_Q3_PRESS_EVIDENCE_UNVERIFIED",code="9802",
                        certified_Aplus=False,formal_gate_PASSES_created=0,
                        reason=type(e).__name__+":"+str(e)[:180])
    else:
        try:
            packed=(rankings/"v880_full_results.json.gz").read_bytes()
            if hashlib.sha256(packed).hexdigest()!=research.get("full_results",{}).get("sha256"):
                raise ValueError("FROZEN_FULL_RESULTS_HASH_MISMATCH")
            full=json.loads(gzip.decompress(packed))
            result=revalue(research,full,read(early),
                           read(DATA/"fundamentals/2026-Q2/TWSE_income.json"))
        except (ValueError,KeyError,TypeError,ZeroDivisionError,OverflowError) as e:
            result=dict(status="EARLY_9802_DATA_AUDIT_PENDING",
                        code="9802",certified_Aplus=False,
                        reason=type(e).__name__+":"+str(e)[:180])
    rankings.mkdir(exist_ok=True,parents=True)
    (rankings/"v886_9802_early_q3.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    body=["# 9802 Q3提前公告估值研究","",f"狀態：{result['status']}","",
          "提前Q3資料只產生獨立研究影子估值，不修改正式全市場排名或13項認證。"]
    if result["status"]=="RESEARCH_ONLY_EARLY_Q3_REVALUED":
        body+=[f"Q3單季毛利率：**{result['standalone_q3_gm_pct']:.2f}%**；前三季累計毛利率：{result['q3_ytd_gm_pct']:.2f}%。",
               "", "|情境|原EPS|更新EPS|原價|更新價|","|---|---:|---:|---:|---:|"]
        for k in ("bear","base","bull"):
            a=result["old"][k];b=result["new"][k]
            body.append(f"|{k}|{a['eps']:.2f}|{b['eps']:.2f}|{a['target_price'] or 0:.2f}|{b['target_price'] or 0:.2f}|")
        body+=["",f"原榜暫定替換排名：{result['shadow_if_substituted_rank']} / {result['comparator_sample_count']}（研究用，其他公司仍採Q2）。"]
    elif result.get("status")=="OFFICIAL_ISSUER_Q3_SELF_REPORTED_SOURCE_ARCHIVED":
        body+=["","公司2026Q3官方自結新聞稿PDF已封存並完成SHA256及網址日期對帳。",
               "然而原始自結稿尚非經公司當季MOPS核驗的合併財報；毛利、淨利與EPS尚未獲正式逐項對帳，不能以此直接調整2027合理價。",
               "",f"公司原件：{result['source']}。",
               f"首次擷取：{result['first_captured_at_utc']}（非獨立認證的MOPS公告時點）。"]
    elif result.get("reason"):body+=["","待補證據："+result["reason"]]
    (rankings/"v886_9802_early_q3.md").write_text("\n".join(body)+"\n",encoding="utf-8")
    print(json.dumps({k:result.get(k) for k in ("status","standalone_q3_gm_pct",
                      "shadow_if_substituted_rank","reason")},ensure_ascii=False))

if __name__=="__main__":main()
