#!/usr/bin/env python3
"""Q2 stand-alone margin universe check; separate original-source plant-cost attribution."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tw_model_v880.factory_ramp import accounting_only, assess_factory_ramp
from tw_model_v880.disclosed_cogs import assess_disclosed_cogs, render_disclosed_cogs

FOCUS = ("9802","2330","9910","6768","6890","6965","1476","6206")
QUARTERS = ("2025-Q1","2025-Q2","2026-Q1","2026-Q2")
FIELDS = ("revenue_ytd_k","gross_profit_ytd_k","operating_profit_ytd_k")
ISSUER_URLS = {
    "9802": "https://www.fulgentsun.com/img/News_Release/FY2026%202Q%20financial%20results%20EN.pdf",
    "2330": "https://investor.tsmc.com/chinese/encrypt/files/encrypt_file/reports/2026-10/eba4fac72873bf546b669bd2b5d973df5c93215d/TSMC%203Q26%20Transcript.pdf"
}


def _time(value):
    t = datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("FACTORY_SOURCE_TIMESTAMP_NO_TIMEZONE")
    return t.astimezone(timezone.utc)


def collect(root, asof):
    cutoff = _time(asof)
    datasets, provenance = {}, {}
    for q in QUARTERS:
        datasets[q], provenance[q] = {}, {}
        for market in ("TWSE","TPEX"):
            file = root/"fundamentals"/q/(market+"_income.json")
            data = json.loads(file.read_text(encoding="utf-8"))
            if (data.get("period"),data.get("kind"),data.get("market")) != (q,"income",market):
                raise ValueError("FACTORY_FINANCIAL_BATCH_ID_INVALID")
            if _time(data.get("capture_utc")) > cutoff:
                raise ValueError("FACTORY_FUTURE_ARCHIVE_BLOCKED")
            rows = data.get("rows")
            if not isinstance(rows,list):
                raise ValueError("FACTORY_MIRROR_ROWS_INVALID")
            items = {}
            for r in rows:
                if (not isinstance(r,dict) or r.get("market")!=market or r.get("period")!=q
                    or r.get("code") in items):
                    raise ValueError("FACTORY_DUPLICATE_OR_MISMATCHED_ISSUER")
                items[r["code"]] = r
            datasets[q][market] = items
            provenance[q][market] = dict(rows=len(rows),captured_at=data["capture_utc"],
                issuer_PIT_original_verified=data.get("company_PIT_verified") is True)
    return datasets, provenance


def standalone(q1,q2):
    if not q1 or not q2 or (q1.get("market"),q1.get("code")) != (q2.get("market"),q2.get("code")):
        raise ValueError("FACTORY_MISSING_MATCHED_QUARTER")
    if q1.get("unit")!="NTD_thousands_except_EPS" or q2.get("unit")!="NTD_thousands_except_EPS":
        raise ValueError("FACTORY_UNIT_INVALID")
    if q1.get("year_to_date_values") is not True or q2.get("year_to_date_values") is not True:
        raise ValueError("FACTORY_Q2_NOT_CUMULATIVE")
    x = {}
    for key in FIELDS:
        a,b = q1.get(key),q2.get(key)
        if (a is None or b is None or isinstance(a,bool) or isinstance(b,bool)
            or not isinstance(a,(int,float)) or not isinstance(b,(int,float))):
            raise ValueError("FACTORY_ACCOUNTING_LINE_MISSING")
        name = key.replace("_ytd_k","_twd")
        x[name] = (b-a)*1000
    if x["revenue_twd"] <= 0:
        raise ValueError("FACTORY_STANDALONE_REVENUE_NONPOSITIVE")
    return x


def build(root, asof):
    db, provenance = collect(root, asof)
    checked, failed, focus = [], [], {}
    for market in ("TWSE","TPEX"):
        for code, q2 in sorted(db["2026-Q2"][market].items()):
            try:
                old = standalone(db["2025-Q1"][market].get(code),db["2025-Q2"][market].get(code))
                new = standalone(db["2026-Q1"][market].get(code),q2)
                item = accounting_only(code,old,new,current_period="2026-Q2",comparable_period="2025-Q2",
                    source="TWSE/TPEx 2026-10 standardized bulk income mirror, not issuer-note-PIT-signed")
                item.update(market=market,name=q2["name"],
                            q2_revenue_twd=new["revenue_twd"],
                            q2_operating_profit_twd=new["operating_profit_twd"])
                case_path = root/"evidence"/"v880"/"factory_ramp"/(code+".json")
                if case_path.exists():
                    try:
                        case=json.loads(case_path.read_text(encoding="utf-8"))
                        if case.get("code")!=code or case.get("periods")!={"prior_comparable":"2025-Q2","current":"2026-Q2"}:
                            raise ValueError("FACTORY_CASE_ISSUER_OR_PERIOD_MISMATCH")
                        result=assess_factory_ramp(case,asof=asof,
                            archive_root=root/"evidence"/"v880"/"factory_ramp"/"originals",
                            accounting=dict(prior_comparable=old,current=new))
                        item["factory_cost_bridge"]=result
                        item["classification_plant_ramp_vs_structural"]=result["status"]
                    except (ValueError,KeyError,TypeError,OSError) as ex:
                        item["factory_cost_bridge"]=dict(status="REJECTED_UNVERIFIED_FACTORY_EVIDENCE",
                            error=str(ex)[:180],base_gm_override_allowed=False)
                else:
                    item["factory_cost_bridge"]=dict(status="NO_ORIGINAL_UNIT_ECONOMICS_ARCHIVE",
                        base_gm_override_allowed=False)
                checked.append(item)
                if code in FOCUS:
                    focus[code]=item
            except (ValueError,KeyError,TypeError) as ex:
                failed.append(dict(market=market,code=code,name=q2.get("name"),error=str(ex)[:180]))
    # 9802 released a consolidated quarterly material/labor/overhead COGS
    # split on 2026-09-17. This permits a *reported burden* decomposition,
    # NOT a factory-level depreciation/learning-curve or permanent-cost claim.
    cost_research = {}
    filing = root/"evidence"/"v880"/"factory_ramp"/"9802_disclosed_cogs.json"
    if "9802" in focus and filing.is_file():
        try:
            e=json.loads(filing.read_text(encoding="utf-8"))
            old_q2=standalone(db["2025-Q1"]["TWSE"].get("9802"),db["2025-Q2"]["TWSE"].get("9802"))
            now_q2=standalone(db["2026-Q1"]["TWSE"].get("9802"),db["2026-Q2"]["TWSE"].get("9802"))
            cost_research["9802"]=assess_disclosed_cogs(e,asof=asof,
                standardized_accounting={"2025-Q2":old_q2,"2026-Q2":now_q2})
            focus["9802"]["disclosed_cogs_review"]=cost_research["9802"]
        except (OSError,KeyError,TypeError,ValueError) as ex:
            cost_research["9802"]={"status":"REPORTED_COGS_EVIDENCE_PENDING",
                                    "reason":str(ex)[:200],
                                    "base_gm_override_allowed":False,
                                    "formal_a_plus_changed":False}
    short=sorted((i for i in checked if i["gm_yoy_change_pp"]<=-1 and i["q2_revenue_twd"]>=1e9),
                 key=lambda x:(x["gm_yoy_change_pp"],x["code"]))
    verified=sum(x.get("factory_cost_bridge",{}).get("accounting_reconciliation_verified") is True for x in checked)
    return dict(model="V8.9.9_FACTORY_MARGIN_CAUSAL_AUDIT_RESEARCH_ONLY",
                estimate_vintage=asof,latest_financial_period="2026-Q2",comparable_period="2025-Q2",
                archive_source=provenance,universe_checked=len(checked),excluded_count=len(failed),
                excluded_issuers=failed,issuer_focus_cases=focus,all_issuer_accounting=checked,
                issuer_disclosed_costs=cost_research,
                top20_margin_decline_not_plant_attribution=short[:20],
                original_factory_unit_cost_bridges_verified=verified,
                formal_Aplus_changes=0,base_eps_pe_target_changes=0,
                known_limits=[
                    "2026Q2 and 2025Q2 gross and operating margins are derived from Q2 YTD less Q1 YTD; standardized batches are not original issuer-note PIT certification.",
                    "Historical GM decline alone does not prove temporary new-factory costs, nor permanent business deterioration.",
                    "9802 management cites both fixed plant learning/depreciation AND raw materials, tariffs and wages; quantitative causal contribution is not published in the referenced Q2 issuer release.",
                    "2330 2026Q3 transcript is a separate date and illustrates offsetting 2nm/overseas dilution; it is not mixed into Q2 income calculations.",
                    "Factory-level unit cost accounting, sales mix, units sold and inventory absorption need original archived documents and matching disclosures.",
                    "No automatic research Base uplift, EPS/PE revision, formal A+ upgrade or Exit from this audit."
                ])


def render(r):
    lines=[
        "# V8.9.9｜新廠爬坡成本 vs 結構性毛利衰退",
        "",
        f"研究形成：{r['estimate_vintage']}；2026Q2與2025Q2單季比較。",
        f"可比上市櫃 {r['universe_checked']} 家，缺漏或錯誤 {r['excluded_count']} 家；具有原件查核單位成本橋接 **{r['original_factory_unit_cost_bridges_verified']} 家**。",
        "",
        "**財報只能證明毛利變化，不能直接歸因新廠；已被新廠稀釋的公司也可能同時實現整體高毛利。**",
        "",
        "|公司|2025Q2 GM|2026Q2 GM|YoY變動|本業利潤率YoY|廠別歸因|",
        "|---|---:|---:|---:|---:|---|"
    ]
    for code in FOCUS:
        a=r["issuer_focus_cases"].get(code)
        if not a:
            lines.append(f"|{code}|待補|待補|待補|待補|無可比資料|")
        else:
            status=("待原始廠別單位成本、產能及存貨成本" if a["classification_plant_ramp_vs_structural"]=="INSUFFICIENT_ORIGINAL_CAUSAL_EVIDENCE"
                    else a["classification_plant_ramp_vs_structural"])
            lines.append(f"|{code} {a['name']}|{a['prior_gm_pct']:.2f}%|{a['current_gm_pct']:.2f}%|{a['gm_yoy_change_pp']:+.2f}pp|{a['operating_margin_yoy_change_pp']:+.2f}pp|{status}|")
    special=r.get("issuer_disclosed_costs",{}).get("9802")
    if special and special.get("status")=="PUBLISHED_CONSOLIDATED_COGS_SPLIT_NOT_PLANT_CAUSALITY":
        lines += ["",render_disclosed_cogs(special)]
    elif special:
        lines += ["", "## 9802成本結構核對狀態："+special.get("status","UNKNOWN"),
                  "未列入已驗證的材料/人工/製造費用拆解："+special.get("reason","來源待補"), ""]
    lines += [
        "","## 9802：公司確有提及新廠，但同時有其他成本",
        "",
        "鈺齊2026/7/23自結公告：Q2毛利率13.94%，2025Q2為18.49%，2026Q1為15.85%。公司指出越南、印尼新廠2025H2試產、2026Q2新產能占比上升；成本壓力同時包含**新廠學習曲線、折舊、關稅、原物料、薪資**。其各項毛利影響的精確百分點未披露。",
        "",
        "原始公告："+ISSUER_URLS["9802"],
        "",
        "## 2330：高毛利也可能受新廠稀釋",
        "",
        "台積電2026Q3法說：2奈米量產爬坡使整體毛利率由Q2的67.7%降至Q3的66.4%；另估2026年海外廠全年稀釋約2pp。此屬**2026Q3獨立案例**，不是Q2同行財報中的同季比較。",
        "",
        "原始法說："+ISSUER_URLS["2330"],
        "",
        "## 其他毛利率下滑候選：僅研究優先順序",
        "",
        "|代碼|公司|2026Q2 YoY GM|Q2營收(億)|",
        "|---|---|---:|---:|"
    ]
    for a in r["top20_margin_decline_not_plant_attribution"][:12]:
        lines.append(f"|{a['code']}|{a['name']}|{a['gm_yoy_change_pp']:+.2f}pp|{a['q2_revenue_twd']/1e8:.2f}|")
    lines += ["","## 尚未完成原因查核","",*("- "+s for s in r["known_limits"]),""]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="tw-market-data")
    p.add_argument("--asof",default=datetime.now().astimezone().isoformat())
    a=p.parse_args()
    root=Path(a.data_dir)
    r=build(root,a.asof)
    out=root/"rankings";out.mkdir(parents=True,exist_ok=True)
    (out/"v899_factory_ramp_audit.json").write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"v899_factory_ramp_audit.md").write_text(render(r)+"\n",encoding="utf-8")
    print(json.dumps(dict(universe=r["universe_checked"],excluded=r["excluded_count"],
        verified_cost_bridges=r["original_factory_unit_cost_bridges_verified"],
        model_val_changes=0,formal_Aplus_changes=0),ensure_ascii=False))

if __name__=="__main__":
    main()
