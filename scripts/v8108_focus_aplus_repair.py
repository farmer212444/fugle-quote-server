#!/usr/bin/env python3
"""First-certification repair packet for 6206 and margin hurdle for 9802.

Verified original bytes and numerical arithmetic are NOT a reviewed formal
certificate. This never writes to evidence/v880/review_packs, trades or the
V8.10.8 valuation/configuration and never assumes human review occurred.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0,str(PROJECT))
from tw_model_v880.evidence import GATES
from scripts.run_research_pipeline import atomic_json

SCHEMA="V8108_FOCUS_CERTIFICATION_REPAIR_V1"
PRIORITY=("original_eight_quarter_statements","cash_and_working_capital",
          "fully_diluted_shares","forecast_bridge","auditor_scope",
          "nonoperating_components","tradability","point_in_time",
          "insider_claims","matched_peers_and_cycle","management_promises",
          "dividend_window","out_of_sample_validation")

def require(condition,reason):
    if not condition:
        raise ValueError("FOCUS_REPAIR_"+reason)

def load(root,path):
    p=Path(root)/path
    payload=p.read_bytes()
    require(len(payload)>0,"EMPTY_INPUT_"+p.name)
    return json.loads(payload),hashlib.sha256(payload).hexdigest()

def number(x):
    return type(x) in (float,int) and math.isfinite(x)

def full_6206_starter(root,triage,lanes,manifest):
    require(manifest.get("issuer")=="6206" and
            manifest.get("schema")=="V896_DURABLE_ORIGINAL_PDF_NOT_CERTIFIED",
            "ORIGINAL_MANIFEST_ID")
    originals=[]
    seen=set()
    for doc in manifest.get("documents",[]):
        require(doc.get("issuer")=="6206" and
                doc.get("document_kind")=="presentation",
                "ORIGINAL_SOURCE_WRONG_ISSUER")
        relative=doc.get("archive_path")
        require(isinstance(relative,str),"ORIGINAL_PATH_MISSING")
        rel=Path(relative)
        require(not rel.is_absolute() and ".." not in rel.parts,
                "ORIGINAL_UNSAFE_PATH")
        actual=(Path(root)/rel).resolve()
        base=Path(root).resolve()
        require(base in actual.parents and actual.is_file(),
                "ORIGINAL_PDF_BYTES_MISSING")
        digest=hashlib.sha256(actual.read_bytes()).hexdigest()
        require(digest==doc.get("sha256"),
                "ORIGINAL_PDF_HASH_MISMATCH")
        require(relative not in seen,"ORIGINAL_DUPLICATED")
        seen.add(relative)
        originals.append(dict(period=doc["document_date"],
                              url=doc["source_url"],sha256=digest,
                              archive_path=relative,
                              captured_at_utc=doc.get("captured_at_utc"),
                              origin_authenticated=False,
                              available_at=None,
                              formal_gate_pass=False))
    require(originals and triage.get("issuer")=="6206",
            "ORIGINALS_OR_TRIAGE_MISSING")
    require(len(triage.get("gates",[]))==len(GATES),
            "TRIAGE_13_GATES_REQUIRED")
    bygate={g["gate"]:g for g in triage["gates"]}
    require(set(bygate)==set(GATES),"TRIAGE_GATES_MISMATCH")
    require(lanes["code"]=="6206" and
            lanes["company_gates_passed"]==0 and
            lanes["company_gates_pending"]==12 and
            lanes["formal_Aplus"] is False,"CERTIFICATION_CONFLICT")
    starter={}
    for gate in GATES:
        tri=bygate[gate]
        require(tri["formal_status"]=="PENDING" and
                tri.get("automatically_certified") is False,
                "FORGED_TRIAGE_CERTIFICATION")
        relevant=originals if gate in (
            "management_promises","forecast_bridge","dividend_window") else []
        starter[gate]=dict(
            issuer="6206",financial_period=lanes["valuation_period"],
            status="PENDING",review_completed=False,reviewer_id=None,
            checked_at=None,available_at=None,expires_at=None,method=None,
            review_note=None,source_identity_reviewed=False,
            sources=relevant,next_action=tri["next_action"],
            source_coverage=tri["source_coverage"],
            reviewer_signoff_required=True,
            source_capture_is_not_formal_review=True)
    return dict(schema="V8108_6206_13_GATE_REVIEW_STARTER_NOT_CERTIFICATE",
        code="6206",financial_period=lanes["valuation_period"],
        reviewed_financial_period=lanes["reviewed_period"],
        estimate_vintage=triage["estimate_vintage"],
        originals_sha256_checked=len(originals),presentations=originals,
        gate_review_starter=starter,
        original_eight_quarter_full_pdf_count_verified=0,
        original_pdf_presentations_are_not_quarterly_statements=True,
        issuer_publication_PIT_verified=False,
        named_reviewer_complete=False,review_packs_written=False,
        passes_issued=0,formal_Aplus=False,
        original_13_gate_definitions_unchanged=True)

def gm_hurdle(base,reference,threshold=0.30):
    """Recompute exact GM hurdle holding all OTHER main-model inputs fixed."""
    required=("revenue_k","gross_margin","opex_ratio","opex_k",
              "nonoperating_k","pretax_k","tax_rate","parent_fraction",
              "parent_profit_k","shares","eps","pe","target_price")
    require(all(number(base.get(k)) for k in required),"MARGIN_BASE_FIELDS_MISSING")
    require(0<base["gross_margin"]<1 and 0<base["tax_rate"]<1
            and base["parent_fraction"]>0 and base["shares"]>0
            and base["revenue_k"]>0 and base["pe"]>0 and reference>0,
            "MARGIN_BASE_INVALID")
    require(math.isclose(base["eps"]*base["pe"],base["target_price"],rel_tol=1e-8),
            "MARGIN_PRICE_NOT_RECONCILED")
    require(math.isclose(base["gross_margin"]*base["revenue_k"],base["gross_profit_k"],
                         rel_tol=1e-8) and
            math.isclose(base["opex_ratio"]*base["revenue_k"],base["opex_k"],
                         rel_tol=1e-8),"MARGIN_OPERATING_BRIDGE_CONFLICT")
    required_eps=reference*(1+threshold)/base["pe"]
    desired_parent_k=required_eps*base["shares"]/1000.
    pretax_k=desired_parent_k/(1-base["tax_rate"])/base["parent_fraction"]
    gross_profit_k=pretax_k-base["nonoperating_k"]+base["opex_k"]
    gm=gross_profit_k/base["revenue_k"]
    per_pp=0.01*base["revenue_k"]*(1-base["tax_rate"])*base["parent_fraction"]*1000./base["shares"]
    require(per_pp>0 and math.isclose(base["eps"]+(gm-base["gross_margin"])*per_pp*100,
                                      required_eps,abs_tol=0.02),
            "MARGIN_EPS_SENSITIVITY_NOT_RECONCILED")
    return dict(reference_close=round(reference,2),
        base_gross_margin_pct=round(base["gross_margin"]*100,4),
        main_base_eps=round(base["eps"],4),
        main_base_target=round(base["target_price"],2),
        main_base_upside_pct=round((base["target_price"]/reference-1)*100,2),
        eps_per_1pp_margin=round(per_pp,4),
        required_2027_eps_for_30pct=round(required_eps,4),
        required_2027_gm_pct_for_30pct=round(gm*100,4),
        required_margin_lift_pp=round((gm-base["gross_margin"])*100,4),
        required_2027_target_for_30pct=round(reference*1.30,2),
        holds_other_revenue_cost_tax_parent_shares_pe_fixed=True,
        required_margin_is_not_forecast_or_quality_PASS=True)

def cost_bridge(cost):
    require(cost.get("issuer")=="9802" and
            cost.get("kind")=="PUBLISHED_GROUP_COST_OF_SALES_COMPOSITION",
            "9802_COST_SOURCE_ID")
    source=cost["source"]
    require(source.get("in_repository_original_pdf_archived") is False,
            "COST_PDF_PROVENANCE_FLAGS_MISMATCH")
    a,b=(cost["figures"][key] for key in ("2025-Q2","2026-Q2"))
    ret={}
    for field in ("direct_materials_million","direct_labor_million",
                  "manufacturing_overhead_million"):
        x=100*a[field]/a["revenue_million"]
        y=100*b[field]/b["revenue_million"]
        ret[field]=dict(prior_revenue_pct=round(x,3),
                        latest_revenue_pct=round(y,3),
                        gross_margin_contribution_pp=round(x-y,3))
    before=100*a["gross_profit_million"]/a["revenue_million"]
    after=100*b["gross_profit_million"]/b["revenue_million"]
    require(abs(sum(v["gross_margin_contribution_pp"] for v in ret.values())-(after-before))<0.15,
            "COST_ITEMS_NOT_RECONCILED")
    return dict(prior_quarter="2025-Q2",latest_quarter="2026-Q2",
        prior_gm_pct_from_rounded_issuer_figures=round(before,3),
        latest_gm_pct_from_rounded_issuer_figures=round(after,3),
        margin_change_pp=round(after-before,3),
        contributors=ret,
        issuer_pdf_url=source["issuer_publication_url"],
        issuer_pdf_archive_in_repository=False,
        plant_level_utilization_verified=False,
        cost_normalization_to_2027_verified=False,
        source_alone_cannot_lift_margin_forecast=True)

def build(root):
    root=Path(root)
    triage,h1=load(root,"rankings/v891_6206_gate_triage.json")
    official,h2=load(root,"rankings/latest_aplus_decision_lanes.json")
    footwear,h3=load(root,"rankings/latest_footwear_review.json")
    early,h4=load(root,"rankings/v886_9802_early_q3.json")
    manifest,h5=load(root,"evidence/v880/originals/6206/manifest.json")
    cogs,h6=load(root,"evidence/v880/factory_ramp/9802_disclosed_cogs.json")
    vintage=official.get("estimate_vintage")
    date=official.get("asof_price_date")
    require(all(x==vintage for x in (
        triage.get("estimate_vintage"),footwear.get("estimate_vintage"),
        early.get("estimate_vintage")),"INPUT_ESTIMATE_VINTAGE_MISMATCH")
    require(all(x==date for x in (triage.get("price_date"),
                                 footwear.get("asof_price_date"))),
            "INPUT_REFERENCE_PRICE_DATE_MISMATCH")
    rows={x["code"]:x for x in official["issuers"] if x.get("code") in ("6206","9802")}
    require(set(rows)=={"6206","9802"},"MISSING_FOCUS_COMPANIES")
    for code in rows:
        require(rows[code]["company_gates_pending"]==12 and
                rows[code]["company_gates_passed"]==0 and
                rows[code]["strategy_validation_lane"]=="STRATEGY_PIT_OOS_PENDING",
                "FORMAL_QUALITY_STATE_CHANGED_REVIEW_REQUIRED")
    starter=full_6206_starter(root,triage,rows["6206"],manifest)
    quarter=footwear.get("companies",[])
    shoe=next((c for c in quarter if c.get("code")=="9802"),None)
    require(shoe is not None and early.get("code")=="9802"
            and early.get("quarter")=="2026-Q3"
            and early.get("status")=="MAIN_RESEARCH_REBASED_ON_ISSUER_SELF_REPORT",
            "9802_Q3_EVIDENCE_MISSING")
    require(shoe["reference_close"]>0 and
            math.isclose(shoe["production_base_eps"],early["new"]["eps"],rel_tol=1e-8)
            and math.isclose(shoe["production_base_price"],early["new"]["target_price"],rel_tol=1e-8),
            "9802_MAIN_MODEL_FORECAST_NOT_RECONCILED")
    hurdle=gm_hurdle(early["new"],shoe["reference_close"])
    bridge=cost_bridge(cogs)
    require(rows["9802"]["price_lane"]=="PRICE_HURDLE_NOT_MET"
            and rows["6206"]["price_lane"]=="A_PLUS_PRICE_CANDIDATE_UNVERIFIED",
            "FOCUS_PRICE_LANE_UNEXPECTED")
    priority_list=[]
    for rank,name in enumerate(PRIORITY,1):
        p=starter["gate_review_starter"][name]
        priority_list.append(dict(priority=rank,gate=name,
            status=p["status"],evidence=p["source_coverage"],
            next_action=p["next_action"],owner_signoff="NOT_RECORDED",
            issuer_original_PDFs_for_this_gate=len(p["sources"])))
    return dict(schema=SCHEMA,model=official["model"],
        asof_price_date=date,estimate_vintage=vintage,
        formal_Aplus_count_unchanged=0,formal_pass_added=0,
        no_trading_or_position_changes=True,
        review_source_hashes=dict(triage=h1,aplus_lanes=h2,footwear=h3,
            self_report_q3=h4,flytech_original_manifest=h5,footwear_cost_bridge=h6),
        first_review_candidate=dict(code="6206",name="飛捷",
            research_upside_pct=rows["6206"]["research_upside_pct"],
            company_gates_pending=12,strategy_pit_oos="PENDING",
            current_h1_ocf_reconciliation_still_pending=True,
            all_13_original_gates_preserved=True,
            verified_presentation_pdf_count=starter["originals_sha256_checked"],
            review_priority=priority_list),
        review_starter=starter,
        second_focus=dict(code="9802",name="鈺齊-KY",
            main_price_lane=rows["9802"]["price_lane"],
            operating_hurdle=hurdle,cost_composition=bridge,
            q3_source_kind="ISSUER_SELF_REPORTED_UNAUDITED",
            margin_gate="PENDING_ISSUER_PLANT_AND_PERIOD_COST_EVIDENCE",
            base_forecast_changed=False,
            formal_pass_created=False),
        strategy_gate="PENDING_PIT_WALK_FORWARD_AND_TRANSACTION_COSTS",
        review_pack_not_written=True,
        assessment="EVIDENCE_PREPARED_NOT_SIGNED_OR_CERTIFIED")

def markdown(doc):
    a=doc["first_review_candidate"]
    b=doc["second_focus"]
    h=b["operating_hurdle"]
    c=b["cost_composition"]
    lines=["# V8.10.8｜6206正式A+審查準備＋9802毛利率門檻（不核發PASS）",
       "", "股價基準："+doc["asof_price_date"]+"；形成："+doc["estimate_vintage"],
       "**正式新增A+：0；正式新增PASS：0。** 資料勾稽與正式核閱不可混為一談。",
       "", "## 6206 飛捷：先完成12項公司品質＋獨立第13項",
       "", "2027 Base研究潛在漲幅：%+.2f%%；三份公司法說PDF已重新核對原檔SHA256：%d份。"%
       (a["research_upside_pct"],a["verified_presentation_pdf_count"]),
       "注意：法說PDF不是八季完整四表，發行時間與閱卷簽認也未取得正式認證。",
       "", "|優先|原始品質關卡|來源觀察|下一步|",
       "|---:|---|---|---|"]
    for row in a["review_priority"]:
        lines.append("|%d|%s|%s|%s|"%(row["priority"],row["gate"],
             row["evidence"],row["next_action"]))
    lines+=["","這是審查準備清單；無人員署名、簽核時間或完整證據時，不建立review_packs，不能產生PASS。",
       "", "## 9802 鈺齊-KY：反推2027毛利率，不調高正式預測",
       "", "|敏感度|數值|","|---|---:|",
       "|目前股價|%.2f元|"%h["reference_close"],
       "|原模型2027毛利率|%.2f%%|"%h["base_gross_margin_pct"],
       "|原模型2027 EPS|%.2f元|"%h["main_base_eps"],
       "|原模型2027 Base價|%.2f元|"%h["main_base_target"],
       "|A+價格30%%所需2027 EPS|%.2f元|"%h["required_2027_eps_for_30pct"],
       "|A+價格30%%所需2027毛利率|%.2f%%|"%h["required_2027_gm_pct_for_30pct"],
       "|較原模型必須增加毛利率|+%.2f個百分點|"%h["required_margin_lift_pp"],
       "", "此毛利率僅固定2027營收、費用、業外、稅率、歸母、稀釋股數及PE的機械反推，不是2027財測。",
       "", "### 公司披露的2025Q2→2026Q2成本橋接（四捨五入）",
       "", "|成本項目|對毛利變化影響|","|---|---:|"]
    for key,caption in (("direct_materials_million","直接材料"),
                        ("direct_labor_million","直接人工"),
                        ("manufacturing_overhead_million","製造費用")):
        lines.append("|%s|%+.2fpp|"%(caption,
              c["contributors"][key]["gross_margin_contribution_pp"]))
    lines+=["","**成本資料並無可在GitHub重驗的原始PDF**；本次只重新驗算已登錄的公司披露整數表，不能用來認證廠別稼動率或直接上修2027 Base。",
       "新增A+所需：公司別正式財報、成本、產能及2027橋接證據；PIT+扣成本樣本外研究完成後另審第13關。",
       "","**本次修正不放寬13項門檻、不改EPS／估值、不下單。**",""]
    return "\n".join(lines)

def publish(root):
    result=build(root)
    out=Path(root)/"rankings"
    atomic_json(out/"latest_focus_aplus_repair.json",result)
    atomic_json(out/"6206_gate_review_starter_latest.json",result["review_starter"])
    (out/"latest_focus_aplus_repair.md").write_text(markdown(result),encoding="utf-8")
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-root",default="tw-market-data")
    args=ap.parse_args()
    r=publish(args.data_root)
    print(json.dumps(dict(date=r["asof_price_date"],flytech_sources=
        r["first_review_candidate"]["verified_presentation_pdf_count"],
        footwear_required_margin_pct=
        r["second_focus"]["operating_hurdle"]["required_2027_gm_pct_for_30pct"],
        new_quality_pass=0,new_Aplus=0),ensure_ascii=False))

if __name__=="__main__":
    main()
