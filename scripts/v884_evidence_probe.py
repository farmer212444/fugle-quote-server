#!/usr/bin/env python3
"""V8.8.4 source-evidence probe: observable coverage, NEVER automatic gate PASS.

Reads frozen local official batch mirrors and dated price archives. Missing source
material, market microstructure, dated filing originals and PIT facts stay pending.
Only archives <= the research reference date may influence the report.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880.data import MarketData
from tw_model_v880.evidence import GATES

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def price_archive(root,asof,manifest,minimum_rows=300,limit=60):
    """Reject altered latest archive, duplicate issuers and mixed or future dates."""
    folder=Path(root)/"prices"
    if manifest.get("date")!=asof:
        raise ValueError("MANIFEST_RESEARCH_PRICE_DATE_MISMATCH")
    archives=sorted(folder.glob("????-??-??.json"),reverse=True)
    dated=[];receipts=[]
    for path in archives:
        try: day=dt.date.fromisoformat(path.stem)
        except ValueError:raise ValueError("MALFORMED_PRICE_ARCHIVE_DATE")
        if day.isoformat()>asof:continue
        if len(dated)>=limit:break
        raw=path.read_bytes()
        if path.stem==asof and sha(raw)!=manifest.get("normalized_sha256"):
            raise ValueError("LATEST_OFFICIAL_PRICE_MANIFEST_HASH_MISMATCH")
        rows=json.loads(raw)
        if not isinstance(rows,list) or len(rows)<minimum_rows:
            raise ValueError("PRICE_ARCHIVE_UNDERSIZED_"+path.stem)
        parsed={};dates=set()
        for r in rows:
            if not isinstance(r,dict):raise ValueError("PRICE_ROW_NOT_OBJECT")
            dates.add(r.get("date"))
            market,code=r.get("market"),str(r.get("code",""))
            if not market or not re.fullmatch(r"\d{4}",code):
                raise ValueError("INVALID_STOCK_IDENTITY_"+path.stem)
            key=(market,code)
            if key in parsed:raise ValueError("DUPLICATE_PRICE_ISSUER_"+path.stem)
            turnover=r.get("turnover_ntd")
            valid=(isinstance(turnover,(int,float)) and not isinstance(turnover,bool)
                   and math.isfinite(turnover) and turnover>=0)
            parsed[key]=int(turnover) if valid else None
        if dates!={path.stem}:raise ValueError("MIXED_PRICE_ARCHIVE_DATES_"+path.stem)
        dated.append((path.stem,parsed))
        receipts.append(dict(date=path.stem,path=path.as_posix(),sha256=sha(raw),
                             raw_official_bytes_independently_authenticated=False,
                             manifest_crosscheck=(path.stem==asof)))
    if not dated or dated[0][0]!=asof:
        raise ValueError("REFERENCE_PRICE_ARCHIVE_MISSING")
    return dated,receipts

def liquidity_probe(dated,key,position_ntd=5_000_000,participation=.20):
    if not 0<participation<=1 or position_ntd<=0:raise ValueError("INVALID_EXIT_ASSUMPTIONS")
    observations=[]
    for day,universe in dated:
        observations.append((day,universe.get(key)))
    def sample(n,span):
        a=observations[:n]
        complete=(len(a)==n and all(value is not None for _,value in a)
                  and (dt.date.fromisoformat(a[0][0])-dt.date.fromisoformat(a[-1][0])).days<=span)
        if not complete:return None
        values=[v for _,v in a]
        med=statistics.median(values)
        return dict(sessions=n,first=a[-1][0],last=a[0][0],median_turnover_ntd=med,
                    min_turnover_ntd=min(values),zero_turnover_days=sum(x==0 for x in values),
                    hypothetical_position_ntd=position_ntd,participation_cap=participation,
                    exit_sessions_at_median=(round(position_ntd/(med*participation),2) if med>0 else None),
                    estimates_are_idealized_not_fills=True)
    return dict(available_market_archives=len(dated),
                observed_20_session_issuer_count=sum(v is not None for _,v in observations[:20]),
                five_day=sample(5,15),twenty_day=sample(20,45),
                sixty_day=sample(60,120),
                spread_and_order_book_evidence_available=False,
                tradability_gate="PENDING_NOT_CERTIFIED")

def issuer_backfill_probe(root,asof,market,code):
    """Source-receipted single-issuer monthly history, not full-market archive or PIT."""
    path=Path(root)/"prices/issuer_history"/market/(code+".json")
    if not path.exists():return None
    source=read(path)
    if source.get("schema")=="V893_OFFICIAL_TPEX_DAILY":
        if (market!="TPEX" or source.get("issuer")!=code or source.get("market")!="TPEX"
                or source.get("formal_tradability_gate")!="PENDING_NOT_CERTIFIED"):
            raise ValueError("TPEX_DAILY_SOURCE_IDENTITY_MISMATCH")
        import urllib.parse
        unique={}
        for day,entry in (source.get("by_day") or {}).items():
            if entry.get("date")!=day or day>asof:
                raise ValueError("TPEX_DAILY_DATE_MISMATCH_OR_FUTURE")
            url=entry.get("source_url","")
            uri=urllib.parse.urlparse(url)
            q=urllib.parse.parse_qs(uri.query)
            roc=str(int(day[:4])-1911)+"/"+day[5:7]+"/"+day[8:10]
            if (uri.scheme!="https" or uri.hostname!="www.tpex.org.tw" or
                uri.path!="/www/zh-tw/afterTrading/dailyQuotes" or
                q.get("response")!=["json"] or q.get("date")!=[roc]):
                raise ValueError("TPEX_DAILY_UNTRUSTED_MARKET_SOURCE")
            hashvalue=entry.get("original_response_sha256")
            if not isinstance(hashvalue,str) or not re.fullmatch(r"[a-f0-9]{64}",hashvalue):
                raise ValueError("TPEX_DAILY_SOURCE_SHA_MISSING")
            row=entry.get("row",{})
            if row.get("date")!=day or not isinstance(row.get("turnover_ntd"),int):
                raise ValueError("TPEX_DAILY_ROW_DATE_OR_TURNOVER_MISMATCH")
            unique[day]=row["turnover_ntd"]
        sorted_days=sorted(unique,reverse=True)
        archived=source.get("sessions",[])
        if ([(r.get("date"),r.get("turnover_ntd")) for r in archived] !=
                [(d,unique[d]) for d in sorted_days]):
            raise ValueError("TPEX_DAILY_NORMALIZED_SOURCE_MISMATCH")
        if not sorted_days or sorted_days[0]!=asof:
            return dict(status="PENDING_REFERENCE_SESSION_MISSING",available_sessions=len(sorted_days),
                        twenty_day=None,tradability_gate="PENDING_NOT_CERTIFIED")
        dated=[(day,{(market,code):unique[day]}) for day in sorted_days[:60]]
        score=liquidity_probe(dated,(market,code))
        return dict(status="SOURCE_CAPTURED_NOT_FULL_TRADABILITY",
                    available_sessions=len(sorted_days),twenty_day=score["twenty_day"],
                    five_day=score["five_day"],sixty_day=score["sixty_day"],
                    original_capture_is_not_authenticated_issuer_PIT=True,
                    spread_and_limit_price_execution_not_verified=True,
                    tradability_gate="PENDING_NOT_CERTIFIED")
    expected_schema={"TWSE":"V889_OFFICIAL_TWSE_ISSUER_MONTHLY",
                     "TPEX":"V892_OFFICIAL_TPEX_ISSUER_MONTHLY"}
    if (source.get("issuer")!=code or
            source.get("market")!=market or
            source.get("schema")!=expected_schema.get(market) or
            source.get("formal_tradability_gate")!="PENDING_NOT_CERTIFIED"):
        raise ValueError("ISSUER_HISTORICAL_SOURCE_IDENTITY_MISMATCH")
    if source.get("price_reference_asof","")>asof:
        raise ValueError("FUTURE_ISSUER_HISTORICAL_REFERENCE_DATE")
    months=source.get("by_month",{})
    if not months:raise ValueError("EMPTY_ISSUER_HISTORICAL_SOURCE")
    unique={}
    for month,entry in months.items():
        u=entry.get("source_url","")
        import urllib.parse
        uri=urllib.parse.urlparse(u)
        query=urllib.parse.parse_qs(uri.query)
        verified_url=(uri.scheme=="https" and
            ((market=="TWSE" and uri.hostname=="www.twse.com.tw" and
              uri.path=="/rwd/zh/afterTrading/STOCK_DAY" and
              query.get("stockNo")==[code] and query.get("response")==["json"])
             or (market=="TPEX" and uri.hostname=="www.tpex.org.tw" and
              uri.path=="/web/stock/aftertrading/daily_trading_info/st43_result.php" and
              query.get("stkno")==[code] and query.get("d")==[
                  str(int(month[:4])-1911)+"/"+month[5:7]])))
        if not verified_url:
            raise ValueError("UNTRUSTED_ISSUER_HISTORY_SOURCE_URL")
        h=entry.get("original_response_sha256","")
        if len(h)!=64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError("HISTORICAL_ORIGINAL_RECEIPT_SHA_MISSING")
        for row in entry.get("rows",[]):
            date=row.get("date")
            if not isinstance(date,str) or date[:7]!=month:
                raise ValueError("ISSUER_HISTORY_MONTH_MISMATCH")
            if date in unique:raise ValueError("ISSUER_DUPLICATE_SESSION")
            if date>asof:continue
            volume=row.get("turnover_ntd")
            if not isinstance(volume,int) or isinstance(volume,bool) or volume<0:
                raise ValueError("ISSUER_HISTORY_INVALID_TURNOVER")
            unique[date]=volume
    archived=source.get("sessions",[])
    from_months=sorted(unique,reverse=True)
    exposed=[x for x in archived if x.get("date")<=asof]
    if [(x.get("date"),x.get("turnover_ntd")) for x in exposed] != [(d,unique[d]) for d in from_months]:
        raise ValueError("ISSUER_HISTORY_NORMALIZED_SOURCE_MISMATCH")
    # Historical month backfill must contain the exact exchange reference session.
    if not from_months or from_months[0]!=asof:
        return dict(status="PENDING_REFERENCE_SESSION_MISSING",available_sessions=len(from_months),
                    twenty_day=None,tradability_gate="PENDING_NOT_CERTIFIED")
    dated=[(d,{(market,code):unique[d]}) for d in from_months[:60]]
    result=liquidity_probe(dated,(market,code))
    return dict(status="SOURCE_CAPTURED_NOT_FULL_TRADABILITY",available_sessions=len(from_months),
       twenty_day=result["twenty_day"],five_day=result["five_day"],sixty_day=result["sixty_day"],
       original_capture_is_not_authenticated_issuer_PIT=True,
       spread_and_limit_price_execution_not_verified=True,
       tradability_gate="PENDING_NOT_CERTIFIED")

def financial_probe(data,key):
    history=data.history.get(key,{})
    cf=data.cash.get(key,{})
    quarters=data.required_periods
    income=[p for p in quarters if p in history]
    cash=[p for p in quarters if p in cf]
    code=key[1];primary=data.primary(code)
    return dict(normalized_income_8q_count=len(income),normalized_cashflow_8q_count=len(cash),
                missing_income_periods=[p for p in quarters if p not in history],
                missing_cashflow_periods=[p for p in quarters if p not in cf],
                latest_primary_key_numbers_checked=primary is not None,
                full_eight_quarter_original_notes_audit=False,
                filing_specific_disclosure_timestamps_verified=False,
                original_eight_quarter_gate="PENDING_NOT_CERTIFIED")

def capital_probe(data,code):
    master=data.evidence.get("master",{}).get(code)
    bonds=data.evidence.get("bonds",{}).get(code,[])
    unknown=[str(x.get("code","")) for x in bonds if not x.get("current_terms_verified")]
    terms=Path(data.root)/"evidence/v880/capital_terms"/(code+".json")
    legal=read(terms) if terms.exists() else {}
    return dict(issued_share_master_present=master is not None,
                reported_bond_count=len(bonds),unverified_bond_terms=unknown,
                dated_capital_terms_receipt_present=bool(legal),
                dated_capital_terms_fully_certified=bool(legal.get("formal_share_certification")),
                no_listed_bond_does_not_prove_no_other_dilution=True,
                fully_diluted_shares_gate="PENDING_NOT_CERTIFIED")

MANUAL_GATES=("management_promises","auditor_scope","forecast_bridge",
              "matched_peers_and_cycle","point_in_time","out_of_sample_validation")
def probe(research,dispatch,data,dated,receipts,top=50,focus_codes=()):
    if research.get("estimate_vintage")!=dispatch.get("vintage") or research.get("model")!=dispatch.get("model"):
        raise ValueError("DISPATCH_RESEARCH_VINTAGE_MISMATCH")
    if research.get("asof_price_date")!=dispatch.get("price_date"):
        raise ValueError("DISPATCH_PRICE_DATE_MISMATCH")
    ledger=dispatch.get("all_issuer_jobs",[])
    if len(ledger)!=dispatch.get("tracked_issuer_count") or len(ledger)!=research.get("data_scope",{}).get("model_rows"):
        raise ValueError("DISPATCH_TRACKED_ISSUER_COUNT_MISMATCH")
    if any(j.get("evidence_state")!="PENDING_NOT_CERTIFIED" or j.get("formal_Aplus") is not False for j in ledger):
        raise ValueError("DISPATCH_FALSE_PROMOTION")
    live=set((r.get("market"),r.get("code")) for r in ledger)
    if len(live)!=len(ledger):raise ValueError("AMBIGUOUS_MARKET_ISSUER_IDENTITY")
    prioritized=[r for r in ledger if r.get("research_upside_pct") is not None]
    selected=prioritized[:top]
    # Keep ranked top-N intact; append explicitly requested issuers without duplicates.
    focus=set(focus_codes)
    selected_keys={(r["market"],r["code"]) for r in selected}
    for candidate in prioritized:
        key=(candidate["market"],candidate["code"])
        if candidate["code"] in focus and key not in selected_keys:
            selected.append(candidate)
            selected_keys.add(key)
    manual=[];profiles=[];counts=Counter()
    for row in selected:
        code=row["code"];market=row["market"];key=(market,code)
        finance=financial_probe(data,key);capital=capital_probe(data,code)
        liq=liquidity_probe(dated,key)
        # Synthetic gate-dispatch fixtures may intentionally use a minimal data stub.
        issuer_history=(issuer_backfill_probe(data.root,research["asof_price_date"],market,code)
                        if hasattr(data,"root") else None)
        st=dict(code=code,name=row.get("name"),market=market,research_upside_pct=row.get("research_upside_pct"),
                source_status=row.get("source_status"),financial=finance,capital=capital,market_history=liq,issuer_historical_market_data=issuer_history,
                pending_gates=list(row.get("pending_gates",[])),
                ready_for_formal_certification=False,newly_passed_gates=[],
                source_tier="NORMALIZED_ARCHIVE_AND_CAPTURE_RECEIPTS_NOT_INDEPENDENT_ORIGINAL_ATTESTATION")
        profiles.append(st)
        counts["normalized_full_8q_income"]+=finance["normalized_income_8q_count"]==8
        counts["normalized_full_8q_cash"]+=finance["normalized_cashflow_8q_count"]==8
        counts["latest_primary_numbers"]+=finance["latest_primary_key_numbers_checked"]
        counts["20_sessions_observed"]+=(liq["twenty_day"] is not None or bool(issuer_history and issuer_history.get("twenty_day")))
        counts["20_sessions_from_individual_TWSE_history"]+=bool(issuer_history and issuer_history.get("twenty_day"))
        counts["unverified_bond_terms_issuers"]+=bool(capital["unverified_bond_terms"])
        for gate in MANUAL_GATES:
            if gate in row.get("pending_gates",[]):
                manual.append(dict(code=code,name=row.get("name"),gate=gate,
                                   status="MANUAL_OR_DATED_ORIGINAL_REVIEW_PENDING",
                                   automatic_pass_prohibited=True))
    return dict(model=research["model"],estimate_vintage=research["estimate_vintage"],
                asof_price_date=research["asof_price_date"],tracked_issuers=len(ledger),
                valued_candidates=len(prioritized),prioritized_count=len(profiles),
                market_price_archived_sessions=len(dated),official_price_archival_receipts=receipts,
                counts=dict(counts),top_priority_evidence=profiles,manual_review_queue=manual,
                formal_Aplus_source_count=research.get("formal_Aplus_count"),
                newly_certified_Aplus=0,newly_verified_gates=0,
                historic_daily_quotes_unavailable_before_archive_start=True,
                source_hash_is_capture_receipt_not_independent_authentication=True,
                model_eps_pe_and_rankings_unchanged=True,
                note="Progress/collection diagnostic only: 20 dated values do not prove executable spread or exit. No issuer filing PIT, legal terms, auditor scope, management judgement or true out-of-sample trade result is certified.")

def summary_md(result):
    out=["# V8.8.4 官方證據蒐集進度（不代表正式通過）","",
         f"估值形成：{result['estimate_vintage']}；參考價日期：{result['asof_price_date']}。","",
         f"逐家列管 {result['tracked_issuers']}；研究候選 {result['valued_candidates']}；前 {result['prioritized_count']} 檔進行證據診斷。",
         f"已封存市場交易日 {result['market_price_archived_sessions']} 日。20日成交值完整：{result['counts'].get('20_sessions_observed',0)}檔；正式新增A+：0。","",
         "|順位|公司|8季損益|8季現金流|20日成交|CB待確認|",
         "|---:|---|---:|---:|---|---|"]
    for i,r in enumerate(result["top_priority_evidence"],1):
        a=r["financial"];b=r["capital"];c=r["market_history"]
        h=r.get("issuer_historical_market_data") or {}
        twenty=c["twenty_day"] or h.get("twenty_day")
        tag="20/20（個股回補）" if h.get("twenty_day") and not c["twenty_day"] else ("20/20" if twenty else str(c["observed_20_session_issuer_count"])+"/20")
        out.append(f"|{i}|{r['code']} {r['name'] or ''}|{a['normalized_income_8q_count']}/8|{a['normalized_cashflow_8q_count']}/8|{tag}|{len(b['unverified_bond_terms'])} 檔|")
    out+=["","目前只有標準化財報鏡像及價格封存收據，未完成原始附註核對、完整成交價差、正式法律稀釋與公告PIT。所有13項正式門檻仍遵守原有驗證規則。",""]
    return "\n".join(out)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="tw-market-data")
    p.add_argument("--research",default="tw-market-data/rankings/latest_research.json")
    p.add_argument("--dispatch",default="tw-market-data/rankings/v883_gate_dispatch.json")
    p.add_argument("--output",default="tw-market-data/rankings/v884_evidence_progress.json")
    p.add_argument("--markdown",default="tw-market-data/rankings/v884_evidence_progress.md")
    p.add_argument("--top",type=int,default=50)
    p.add_argument("--focus",nargs="*",default=[],help="Additional issuer codes to probe after ranked top-N")
    args=p.parse_args()
    r=read(args.research);d=read(args.dispatch)
    if r["estimate_vintage"]!=d["vintage"]:raise ValueError("INCONSISTENT_RANKING_AND_DISPATCH")
    data=MarketData(args.data_dir,r["estimate_vintage"])
    manifest=read(Path(args.data_dir)/"prices/latest_manifest.json")
    dated,receipts=price_archive(args.data_dir,r["asof_price_date"],manifest)
    out=probe(r,d,data,dated,receipts,args.top,args.focus)
    dst=Path(args.output);dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    dest=Path(args.markdown);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(summary_md(out),encoding="utf-8")
    print(json.dumps({k:out[k] for k in ["model","tracked_issuers","valued_candidates","prioritized_count","market_price_archived_sessions","counts","newly_certified_Aplus"]},ensure_ascii=False))

if __name__=="__main__":main()
