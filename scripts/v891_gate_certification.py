#!/usr/bin/env python3
"""V8.9.1 evidence-to-certificate admission + per-issuer completion diagnostics.

This DOES NOT infer PASS from bulk financial mirrors, source URLs, hash receipts,
20 daily close prices, estimated upside, or unreviewed notes. Formal PASS/FAIL
comes only from dated reviewer-attested packs with locally archived matching
original bytes and a source identity review. Issuance is fully automated once
those source+review requirements actually exist. No trades or forecasts change.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tw_model_v880.evidence import GATES, certify, timestamp, verify_certificate_archives
from scripts.v896_original_archive import validate_bundle

MANUAL_REVIEW_GATES = frozenset((
    "matched_peers_and_cycle", "management_promises", "auditor_scope",
    "forecast_bridge", "insider_claims", "point_in_time",
    "out_of_sample_validation", "nonoperating_components",
    "cash_and_working_capital", "dividend_window", "fully_diluted_shares",
    "original_eight_quarter_statements", "tradability",
))
STATUS_RANK = {"NOT_PROBED":0, "SOURCE_MISSING":1, "MIRROR_CAPTURED":2,
               "SOURCE_CAPTURED":3, "REVIEW_PENDING":4,
               "FORMAL_FAIL":5, "FORMAL_PASS":6}
CODE_RE = re.compile(r"[0-9]{4,6}")
SHA_RE = re.compile(r"[0-9a-f]{64}")

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def write_if_changed(p, s):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_text(encoding="utf-8") == s:
        return False
    p.write_text(s, encoding="utf-8")
    return True

def strong_iso(s):
    if not isinstance(s, str):
        raise ValueError("EVIDENCE_TIMESTAMP_MISSING")
    return timestamp(s)

def validate_review_pack(pack, path, data_root, cutoff, financial_period):
    """Fail closed: every certificate source must have archived checked bytes."""
    code = pack.get("code")
    if not isinstance(code,str) or not CODE_RE.fullmatch(code) or path.stem != code:
        raise ValueError("REVIEW_PACK_ISSUER_PATH_MISMATCH")
    if pack.get("financial_period") != financial_period:
        raise ValueError("REVIEW_PACK_FINANCIAL_PERIOD_STALE")
    gates = pack.get("gates")
    if not isinstance(gates,dict) or not gates:
        raise ValueError("REVIEW_PACK_EMPTY")
    assembled = {}
    root = Path(data_root).resolve()
    for name, item in gates.items():
        if name not in GATES or not isinstance(item,dict):
            raise ValueError("REVIEW_PACK_UNKNOWN_GATE")
        status=item.get("status")
        if status not in ("PASS","FAIL"):
            raise ValueError("REVIEW_PACK_NOT_AN_EXPLICIT_DECISION")
        if item.get("issuer") != code or item.get("financial_period") != financial_period:
            raise ValueError("REVIEW_GATE_IDENTITY_MISMATCH")
        checked=strong_iso(item.get("checked_at"))
        start=strong_iso(item.get("available_at"))
        expiry=strong_iso(item.get("expires_at"))
        if not start <= checked <= cutoff <= expiry:
            raise ValueError("REVIEW_GATE_TIME_EXPIRED_OR_FUTURE")
        if not isinstance(item.get("method"),str) or len(item["method"].strip())<15:
            raise ValueError("REVIEW_GATE_METHOD_NOT_AUDITABLE")
        if item.get("review_completed") is not True:
            raise ValueError("REVIEW_GATE_NOT_REVIEWED")
        reviewer=item.get("reviewer_id")
        if name in MANUAL_REVIEW_GATES and (not isinstance(reviewer,str) or len(reviewer.strip())<3):
            raise ValueError("REVIEW_GATE_NAMED_REVIEWER_REQUIRED")
        if not isinstance(item.get("review_note"),str) or len(item["review_note"].strip())<15:
            raise ValueError("REVIEW_GATE_SIGNOFF_RATIONALE_REQUIRED")
        if item.get("source_identity_reviewed") is not True:
            raise ValueError("REVIEW_GATE_SOURCE_IDENTITY_NOT_VERIFIED")
        sources=item.get("sources")
        if not isinstance(sources,list) or not sources:
            raise ValueError("REVIEW_GATE_ORIGINAL_SOURCES_REQUIRED")
        cert_sources=[]
        for src in sources:
            if not isinstance(src,dict) or src.get("origin_authenticated") is not True:
                raise ValueError("REVIEW_SOURCE_ORIGIN_NOT_ATTESTED")
            url=src.get("url")
            sha=src.get("sha256")
            file_path=src.get("archive_path")
            if not isinstance(url,str) or not url.startswith("https://"):
                raise ValueError("REVIEW_SOURCE_URL_MISSING")
            if not isinstance(sha,str) or not SHA_RE.fullmatch(sha):
                raise ValueError("REVIEW_SOURCE_HASH_INVALID")
            if not isinstance(file_path,str) or not file_path:
                raise ValueError("REVIEW_SOURCE_ARCHIVED_BYTES_REQUIRED")
            rel=Path(file_path)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("REVIEW_SOURCE_UNSAFE_ARCHIVE_PATH")
            orig=(root/rel).resolve()
            if orig == root or root not in orig.parents or not orig.is_file():
                raise ValueError("REVIEW_SOURCE_ARCHIVE_MISSING_OR_ESCAPES_ROOT")
            if hashlib.sha256(orig.read_bytes()).hexdigest() != sha:
                raise ValueError("REVIEW_SOURCE_ARCHIVE_HASH_MISMATCH")
            if strong_iso(src.get("available_at"))>checked:
                raise ValueError("REVIEW_SOURCE_NOT_PUBLISHED_AT_SIGNOFF")
            cert_sources.append(dict(url=url,sha256=sha,origin_authenticated=True,
                                     archive_path=file_path,available_at=src["available_at"]))
        assembled[name]=dict(
            issuer=code,financial_period=financial_period,status=status,
            reason=item["review_note"].strip(),method=item["method"].strip(),
            reviewed_by=reviewer,checked_at=item["checked_at"],
            available_at=item["available_at"],expires_at=item["expires_at"],
            sources=cert_sources,
            original_archive_sha256_recomputed=True,
            human_source_identity_review_documented=True,
            **({"stress_verified":True} if name=="fully_diluted_shares" and item.get("stress_verified") is True else {}),
            **({"materiality_assessment_complete":True} if name=="auditor_scope" and item.get("materiality_assessment_complete") is True else {}),
            **({"margin_normalization_review_complete":True} if name=="forecast_bridge" and item.get("margin_normalization_review_complete") is True else {}),
            **({"model_code_sha256":item.get("model_code_sha256"),
                "target_date":item.get("target_date"),
                "reference_price_date":item.get("reference_price_date")} if name=="forecast_bridge" else {}),
            **({"forecast_denominator_shares":item.get("forecast_denominator_shares")} if name=="fully_diluted_shares" else {}),
            **({"multi_session_liquidity_verified":item.get("multi_session_liquidity_verified"),
                "exit_capacity_verified":item.get("exit_capacity_verified")} if name=="tradability" else {})
        )
    return {"code":code,"financial_period":financial_period,
            "source":"DATED_REVIEWED_ORIGINALS_WITH_LOCALLY_RECOMPUTED_HASHES",
            "independent_legal_attestation":False,"gates":assembled}

def emit_certificates(root, cutoff, period):
    reviews = root/"evidence"/"v880"/"review_packs"
    certificates = root/"evidence"/"v880"/"certificates"
    reports=[]
    for p in sorted(reviews.glob("*.json")):
        try:
            cert=validate_review_pack(load(p), p, root, cutoff, period)
            out=certificates/(p.stem+".json")
            changed=write_if_changed(out,json.dumps(cert,ensure_ascii=False,indent=2)+"\n")
            reports.append(dict(code=p.stem,status="CERTIFICATE_EMITTED" if changed else "CERTIFICATE_UNCHANGED",
                                gates=list(cert["gates"])))
        except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError) as e:
            # Never manufacture a PASS or halt independent companies.
            reports.append(dict(code=p.stem,status="REVIEW_PACK_REJECTED",
                                rejection=str(e),gates=[]))
    return reports

def stage_for(gate_name, profile):
    if profile is None:
        return "NOT_PROBED", "No issuer-specific original/reconciliation probe yet"
    fin=profile.get("financial") or {}
    capital=profile.get("capital") or {}
    market=(profile.get("issuer_historical_market_data") or
            profile.get("market_history") or {})
    if gate_name=="original_eight_quarter_statements":
        if fin.get("normalized_income_8q_count")==8 and fin.get("normalized_cashflow_8q_count")==8:
            return "MIRROR_CAPTURED", "8 income and 8 cashflow summary periods; original full notes and issuer filing PIT missing"
        return "SOURCE_MISSING", "8-quarter summary coverage incomplete"
    if gate_name=="tradability":
        if market.get("twenty_day") is not None:
            return "SOURCE_CAPTURED", "20 daily turnovers archived; bid/ask spread and actual executable exit not verified"
        return "SOURCE_MISSING", "20 daily market sessions unavailable for this issuer"
    if gate_name=="fully_diluted_shares":
        if capital.get("unverified_bond_terms"):
            return "REVIEW_PENDING", "Convertible legal conversion/reset terms remain unverified"
        if capital.get("issued_share_master_present"):
            return "SOURCE_CAPTURED", "Issued shares present; no listed CB alone does not validate all potential dilution"
        return "SOURCE_MISSING", "Issued shares or capital original missing"
    if gate_name=="cash_and_working_capital":
        if fin.get("normalized_cashflow_8q_count")==8:
            return "MIRROR_CAPTURED", "Cashflow mirror 8/8; receivable/inventory/capex notes need reconciliation"
        return "SOURCE_MISSING", "Cashflow periods incomplete"
    if gate_name=="point_in_time":
        return "REVIEW_PENDING", "Issuer-specific publication and restatement timestamps not verified"
    if gate_name=="out_of_sample_validation":
        return "REVIEW_PENDING", "No frozen PIT trading and total-return backtest"
    if gate_name=="auditor_scope" and fin.get("latest_primary_key_numbers_checked"):
        return "REVIEW_PENDING", "Issuer numeric origin checked; full auditor scope and important qualifications not reviewed"
    return "REVIEW_PENDING", "Dated issuer source, analytical bridge and evidence signoff outstanding"

def build_progress(root):
    rankings=root/"rankings"
    research=load(rankings/"latest_research.json")
    dispatch=load(rankings/"v883_gate_dispatch.json")
    probe=load(rankings/"v884_evidence_progress.json")
    if (research.get("estimate_vintage")!=dispatch.get("vintage") or
        research.get("estimate_vintage")!=probe.get("estimate_vintage") or
        research.get("asof_price_date")!=dispatch.get("price_date") or
        research.get("asof_price_date")!=probe.get("asof_price_date")):
        raise ValueError("GATE_CERTIFICATION_INPUT_VINTAGES_MISMATCH")
    asof=research["estimate_vintage"]
    period=research["financial_last_quarter"]
    profiles={(p["market"],p["code"]):p for p in probe["top_priority_evidence"]}
    # Recompute durable original bytes, not just source URLs or stored hashes.
    # A corrupt existing archive must fail closed rather than silently count
    # a non-existent source or mint a PASS.
    original_bundles={code:validate_bundle(root,code) for code in ("6206","9802")}
    jobs=dispatch.get("all_issuer_jobs",[])
    if len(jobs)!=dispatch.get("tracked_issuer_count") or len(jobs)!=research["data_scope"]["model_rows"]:
        raise ValueError("GATE_CERTIFICATION_LEDGER_INCOMPLETE")
    issuer_reports=[]
    counts=collections.Counter()
    high_upside=0
    for item in jobs:
        upside=item.get("research_upside_pct")
        if upside is None:continue
        code=str(item["code"])
        if not (isinstance(upside,(float,int)) and not isinstance(upside,bool) and math.isfinite(upside)):
            raise ValueError("NONFINITE_DISPATCH_UPSIDE")
        is_high=upside >= 30.0
        high_upside+=is_high
        profile=profiles.get((item["market"],code))
        cert_path=root/"evidence"/"v880"/"certificates"/(code+".json")
        cert={}
        if cert_path.exists():
            obj=load(cert_path)
            if obj.get("code")!=code or obj.get("financial_period")!=period:
                raise ValueError("CERTIFICATE_ISSUER_PERIOD_MISMATCH")
            verify_certificate_archives(obj,root)
            cert=obj.get("gates",{})
        evaluated=certify(code,upside,None,cert,asof,period)
        stage={}
        for gate in GATES:
            if gate in evaluated["gates_passed"]:
                state,reason="FORMAL_PASS","Dated original reviewed certificate passes the model's metadata gate"
            elif gate in evaluated["gates_failed"]:
                state,reason="FORMAL_FAIL","Dated reviewed certificate explicitly FAIL"
            else:
                state,reason=stage_for(gate,profile)
                archives=original_bundles.get(code) or {}
                kinds=archives.get("document_kinds") or {}
                if (gate=="original_eight_quarter_statements" and
                        kinds.get("quarterly",0)>0 and
                        state in ("MIRROR_CAPTURED","SOURCE_MISSING")):
                    state="SOURCE_CAPTURED"
                    reason=(str(kinds["quarterly"])+" dated issuer-hosted original quarterly "
                            "PDFs permanently archived with verified bytes; full 8q note, "
                            "audit-scope and publication-PIT review still missing")
                if (gate=="management_promises" and kinds.get("presentation",0)>0
                        and state=="REVIEW_PENDING"):
                    state="SOURCE_CAPTURED"
                    reason=(str(kinds["presentation"])+" issuer-hosted IR presentation PDFs "
                            "permanently archived with verified bytes; management guidance "
                            "and subsequent delivery have not yet been reviewed")
            stage[gate]={"stage":state,"reason":reason,"formal_pass":gate in evaluated["gates_passed"]}
            if is_high:counts[gate+"__"+state]+=1
        if is_high and (evaluated["gates_passed"] or evaluated["gates_failed"]):
            counts["high_upside_with_decided_gates"]+=1
        if is_high and not evaluated["formal_Aplus"]:
            counts["high_upside_formal_pending"]+=1
        if evaluated["formal_Aplus"]:counts["formal_Aplus_total"]+=1
        if (is_high or profile is not None):
            issuer_reports.append(dict(code=code,name=item.get("name"),market=item.get("market"),
                 research_upside_pct=round(upside,2),pre_certification_status=evaluated["status"],
                 formally_passed_gates=evaluated["gates_passed"],
                 formally_failed_gates=evaluated["gates_failed"],
                 still_pending_gates=evaluated["gates_pending"],
                 formal_Aplus=evaluated["formal_Aplus"],formal_Aplusplus=evaluated["formal_Aplusplus"],
                 gate_stage=stage,
                 durable_original_archive=original_bundles.get(code,{})))
    issuer_reports.sort(key=lambda x:(not x["formal_Aplus"],-x["research_upside_pct"],x["code"]))
    status={
        "model":research["model"],"estimate_vintage":asof,
        "asof_price_date":research["asof_price_date"],"financial_period":period,
        "research_candidates":dispatch["eligible_research_count"],
        "high_upside_research_candidates":high_upside,
        "issuer_diagnostics":issuer_reports,
        "stage_counts_for_upside_ge30":dict(sorted(counts.items())),
        "formally_certified_Aplus_in_report":counts["formal_Aplus_total"],
        "durable_original_archive_receipts":original_bundles,
        "durable_original_capture_does_not_certify_a_gate":True,
        "issuer_report_limitations":[
            "Source-collected, original PDF bytes durably archived, numeric-mirror-complete, source-identity-reviewed and signed PASS are distinct stages.",
            f"Current reference-price date {research['asof_price_date']} does not certify original issuer point-in-time disclosure for older financial periods.",
            "Potential upside is conditional research, not a certified trading return.",
            "Reviewed packs are automatically admitted only after all archived bytes, hash, issuer identity, method and dated source predicates verify.",
            "A GitHub reviewer_id is an accountable review record, not an independent cryptographic human signature.",
            "An individual gate can be eligible for PASS while other 12 remain PENDING; A+ requires all original model gates."
        ]}
    if status["formally_certified_Aplus_in_report"]!=research["formal_Aplus_count"]:
        raise ValueError("CURRENT_CERTIFICATION_REPORT_DISAGREES_WITH_MAIN_MODEL")
    return status

def render_md(r, admitted):
    rows=r["issuer_diagnostics"]
    out=["# V8.9.1 A+ 13項證據認證與障礙追蹤","",
      f"模型：{r['model']}；估值：{r['estimate_vintage']}；股價基準：{r['asof_price_date']}。",
      f"研究估值候選：{r['research_candidates']}，潛在漲幅≥30%：{r['high_upside_research_candidates']}；正式A+：**{r['formally_certified_Aplus_in_report']}**。","",
      "本報告區分「來源齊全／數值鏡像／核閱待辦／有效PASS／有效FAIL」，不以蒐集收據冒充正式通過。","",
      "## 個股工作進度（前30檔及指定關注）","",
      "|股票|模型漲幅|正式通過|正式失敗|待驗|目前已有的資料|",
      "|---|---:|---:|---:|---:|---|"]
    keep=rows[:30]+[x for x in rows[30:] if x["code"] in ("6206","9802")]
    for x in keep:
        stages=x["gate_stage"]
        observable=[]
        if stages["original_eight_quarter_statements"]["stage"]=="MIRROR_CAPTURED":
            observable.append("8季財報鏡像")
        if stages["tradability"]["stage"]=="SOURCE_CAPTURED":
            observable.append("20日成交額")
        if stages["fully_diluted_shares"]["stage"]=="REVIEW_PENDING":
            observable.append("CB條款待核")
        if not observable:observable.append("原始證據待補")
        out.append(f"|{x['code']} {x['name'] or ''}|{x['research_upside_pct']:+.1f}%|{len(x['formally_passed_gates'])}/13|{len(x['formally_failed_gates'])}|{len(x['still_pending_gates'])}|{'、'.join(observable)}|")
    out.extend(["","## 外部核閱／證書發行紀錄",""])
    if admitted:
        for entry in admitted:
            out.append(f"- {entry['code']}：{entry['status']}"+("，原因："+entry["rejection"] if entry.get("rejection") else ""))
    else:out.append("未發現已完成有原始檔案位元組與核閱簽認的 review_packs；本輪不能自動產生正式PASS。")
    out+=["","## 安全邊界",""]
    out+=["- "+a for a in r["issuer_report_limitations"]]
    return "\n".join(out)+"\n"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="tw-market-data")
    p.add_argument("--issue-only",action="store_true",
                   help="Before research, admit reviewed source packs without needing current research.")
    args=p.parse_args()
    root=Path(args.data_dir)
    # Certificate expiration and reviewer PIT constraints must be independently
    # checked again by the model at its exact subsequent estimate timestamp.
    asof=dt.datetime.now(dt.timezone.utc)
    latest_manifest=root/"rankings"/"latest_research.json"
    if args.issue_only:
        research=load(latest_manifest)
        reports=emit_certificates(root,asof,research["financial_last_quarter"])
        print(json.dumps(dict(mode="ADMISSION_ONLY",issued=reports),ensure_ascii=False))
        return
    research=load(latest_manifest)
    admitted=emit_certificates(root,asof,research["financial_last_quarter"])
    status=build_progress(root)
    status["review_pack_admissions"]=admitted
    changed1=write_if_changed(root/"rankings"/"v891_gate_progress.json",
                              json.dumps(status,ensure_ascii=False,indent=2)+"\n")
    changed2=write_if_changed(root/"rankings"/"v891_gate_progress.md",
                              render_md(status,admitted))
    print(json.dumps(dict(model=status["model"],upside_ge30=status["high_upside_research_candidates"],
                          certified_Aplus=status["formally_certified_Aplus_in_report"],
                          reviewed_packs=len(admitted),changed=(changed1 or changed2)),
                     ensure_ascii=False))

if __name__=="__main__":
    main()
