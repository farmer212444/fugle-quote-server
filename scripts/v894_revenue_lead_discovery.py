#!/usr/bin/env python3
"""V8.9.4 revenue-leading discovery layer.

Finds possible operating inflections before quarterly margins are published.
The score orders research only: it never overwrites Base, EPS, PE, evidence
certificates, or formal A+/A++ decisions.
"""
import argparse
import json
import math
import re
from pathlib import Path


def num(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):
        return None


def clamp(value,low=0.0,high=1.0):
    return max(low,min(high,value))


def score_revenue(row,prior_history_months=0):
    """Transparent 100-point research score; missing history earns no credit."""
    monthly=num(row.get("monthly_revenue_k"));prior=num(row.get("prior_month_revenue_k"))
    my=num(row.get("monthly_yoy_pct"));ytd=num(row.get("ytd_yoy_pct"))
    if None in (monthly,prior,my,ytd) or monthly<=0 or prior<=0:
        raise ValueError("INVALID_REVENUE_ROW_"+str(row.get("code","")))
    acceleration=my-ytd
    mom=100*(monthly/prior-1)
    # Approved research emphasis: level 35, acceleration 25, continuity 20,
    # and valuation-unreflected 20. Only the first two plus observable YTD
    # persistence can be earned from the one-month public snapshot.
    level=35*clamp(my/60)
    accel=25*clamp(acceleration/40)
    persistence=10*clamp(ytd/30)
    continuity=10 if prior_history_months>=2 else 0
    risks=[]
    if prior_history_months<2:risks.append("MULTI_MONTH_CONTINUITY_NOT_YET_OBSERVED")
    if ytd<=0:risks.append("YTD_REVENUE_GROWTH_NONPOSITIVE")
    if mom<=-30:risks.append("MONTH_ON_MONTH_REVENUE_DROP_AT_LEAST_30PCT")
    if my<ytd-20:risks.append("MONTHLY_YOY_DECELERATED_AT_LEAST_20PP_VS_YTD")
    return dict(monthly_yoy_pct=round(my,3),ytd_yoy_pct=round(ytd,3),
                acceleration_pp=round(acceleration,3),mom_pct=round(mom,3),
                revenue_level_points=round(level,3),
                acceleration_points=round(accel,3),
                observed_persistence_points=round(persistence,3),
                continuity_points=continuity,revenue_points=round(level+accel+persistence+continuity,3),
                risk_flags=risks)


def valuation_points(model_row):
    if not model_row or not model_row.get("rankable") or not model_row.get("base"):
        return 0.0,"VALUATION_NOT_COMPARABLE"
    upside=num(model_row["base"].get("price_upside_pct"))
    if upside is None:return 0.0,"VALUATION_UPSIDE_MISSING"
    return round(20*clamp(upside/50),3),None


def build(research,revenue_rows,history_months=0):
    if research.get("model") not in ("V8.8.2","V8.10.0","V8.10.1"):raise ValueError("MODEL_REQUIRES_REVIEW")
    candidates={}
    for key in ("top30_provisional","top48_primary_research","early_recovery_watch"):
        for row in research.get(key,[]):candidates[str(row.get("code"))]=row
    seen=set();out=[];excluded=[];manual_review=[]
    for row in revenue_rows:
        code=str(row.get("code",""))
        if code in seen:raise ValueError("DUPLICATE_CODE_"+code)
        seen.add(code)
        if not re.fullmatch(r"\d{4}",code):
            excluded.append(dict(code=code,name=row.get("name"),market=row.get("market"),
                                 reason="NON_COMMON_STOCK_CODE_REQUIRES_IDENTITY_MODEL"))
            continue
        try:signal=score_revenue(row,history_months)
        except ValueError as exc:
            excluded.append(dict(code=code,name=row.get("name"),market=row.get("market"),
                                 reason=str(exc)))
            continue
        vp,vflag=valuation_points(candidates.get(code))
        flags=list(signal.pop("risk_flags"))
        if vflag:flags.append(vflag)
        # Project handovers and extreme low-base ratios are real observations,
        # but they are not comparable recurring-revenue momentum.  Preserve
        # them for issuer-specific review instead of letting capped percentages
        # crowd ordinary issuers out of the discovery ranking.
        quality_flags=[]
        if row.get("industry")=="建材營造":
            quality_flags.append("LUMPY_PROJECT_RECOGNITION_REQUIRES_ISSUER_BRIDGE")
        if signal["monthly_yoy_pct"]>500 or signal["ytd_yoy_pct"]>500:
            quality_flags.append("EXTREME_GROWTH_RATIO_REQUIRES_BASE_EFFECT_REVIEW")
        eligible=not quality_flags
        total=round(signal["revenue_points"]+vp,3)
        item=dict(code=code,name=row.get("name"),market=row.get("market"),industry=row.get("industry"),
                        report_month=str(row.get("report_month")),lead_score=total,
                        valuation_unreflected_points=vp,formal_grade_changed=False,
                        early_layout_only=True,eligible_for_lead_ranking=eligible,
                        data_quality_flags=quality_flags,risk_flags=flags,**signal)
        out.append(item)
        if not eligible:manual_review.append(item)
    out.sort(key=lambda x:(not x["eligible_for_lead_ranking"],-x["lead_score"],-x["monthly_yoy_pct"],x["code"]))
    ranked=[x for x in out if x["eligible_for_lead_ranking"]]
    return dict(status="REVENUE_LEADING_DISCOVERY_NOT_FORMAL_CERTIFICATION",
                source_model=research["model"],source_model_code_sha256=research.get("model_code_sha256"),
                estimate_vintage=research.get("estimate_vintage"),price_date=research.get("asof_price_date"),
                revenue_month=research.get("revenue_month"),issuer_count=len(out),
                excluded_invalid_revenue_count=len(excluded),excluded_invalid_revenue=excluded,
                weights=dict(monthly_yoy_level=35,acceleration_vs_ytd=25,
                             observed_ytd_persistence=10,multi_month_continuity=10,
                             valuation_unreflected=20),
                formal_Aplus_count_unchanged=research.get("formal_Aplus_count"),
                formal_Aplusplus_count_unchanged=research.get("formal_Aplusplus_count"),
                manual_review_count=len(manual_review),manual_review=manual_review,
                ranking=out,top20=ranked[:20],
                limits=["The score is a research-ordering heuristic, not a probability or trading signal.",
                        "A single monthly snapshot cannot prove multi-month continuity; missing history receives zero points.",
                        "Revenue can surface a candidate early but does not establish margin conversion, EPS, cash flow, dilution or fair value.",
                        "Lumpy project recognition and extreme base effects are retained in manual review, not the comparable Top20.",
                        "Base/EPS/PE and all 13 evidence gates remain unchanged."])


def render(report):
    lines=["# V8.9.4 營收領先發掘榜","",
           f"估計形成：{report.get('estimate_vintage')}；營收月份：{report.get('revenue_month')}；價格日：{report.get('price_date')}。","",
           "**用營收提早發現、用財報修正估值；本榜不改寫正式A+、EPS、PE或Base。**","",
           "|序|股票|月營收YoY|YTD YoY|加速度|MoM|領先分|尚缺證據|",
           "|---:|---|---:|---:|---:|---:|---:|---|"]
    for i,row in enumerate(report["top20"],1):
        gaps="、".join(row["risk_flags"][:2]) or "仍須正式品質驗證"
        lines.append(f"|{i}|{row['code']} {row.get('name') or ''}|{row['monthly_yoy_pct']:+.1f}%|{row['ytd_yoy_pct']:+.1f}%|{row['acceleration_pp']:+.1f}pp|{row['mom_pct']:+.1f}%|{row['lead_score']:.1f}|{gaps}|")
    lines += ["","## 邊界","",*["- "+x for x in report["limits"]],""]
    return "\n".join(lines)


def load_revenue(root,month):
    folder=root/month
    files=sorted(folder.glob("revenue_*.json"))
    if not files:raise FileNotFoundError("REVENUE_SHARDS_MISSING_"+month)
    rows=[]
    for path in files:
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data,list):raise ValueError("INVALID_REVENUE_SHARD_"+path.name)
        rows.extend(data)
    return rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--data-dir",default="tw-market-data");args=ap.parse_args()
    root=Path(args.data_dir);rank=root/"rankings"
    research=json.loads((rank/"latest_research.json").read_text(encoding="utf-8"))
    report=build(research,load_revenue(root,research["revenue_month"]),history_months=0)
    (rank/"v894_revenue_lead_discovery.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (rank/"v894_revenue_lead_discovery.md").write_text(render(report),encoding="utf-8")
    print(json.dumps(dict(status=report["status"],issuers=report["issuer_count"],
                          top=[(x["code"],x["lead_score"]) for x in report["top20"][:10]],
                          formal_grade_changes=0),ensure_ascii=False))


if __name__=="__main__":main()
