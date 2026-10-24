#!/usr/bin/env python3
"""V8.10.8: evaluate 2027 operating bridges for 2317/2376/3305, research only.

Published 2026 H1 figures vs separately archived conditional 2027 scenarios.
Never converts a H1 annualization or shareholder dilution plan into a forecast.
"""
import gzip
import hashlib
import json
import math
from pathlib import Path

# Thousands of NT dollars, except EPS. Source statements published before
# 2026-10-24. Original issuer filing timestamps and all footnotes not certified.
DATA={
 "2317":dict(name="鴻海",rev=4645427824,gp=285513881,op=170451721,
             parent=109893220,eps=7.84,rev9m=7669772000,
             financial_source="https://www.foxconn.com.tw/zh-tw/press-center/press-releases/latest-news/2094",
             revenue_source="https://www.foxconn.com/zh-tw/investor-relations/financial-information/reports?category=monthly"),
 "2376":dict(name="技嘉",rev=249271763,gp=26487759,op=15533953,
             parent=11874816,eps=17.73,rev9m=403982432,
             financial_source="https://m.moneydj.com/f1a.aspx?a=1f67316b-b2ae-44e0-b5e8-e387c1cd1a58&c=MB06",
             revenue_source="https://tw.stock.yahoo.com/news/%E5%85%AC%E5%91%8A-%E6%8A%80%E5%98%89-2026%E5%B9%B49%E6%9C%88%E5%90%88%E4%BD%B5%E7%87%9F%E6%94%B6630-99%E5%84%84%E5%85%83-%E5%B9%B4%E5%A2%9E125-073350856.html",
             outstanding_shares_reference=669888886,
             gdr_approved_min=40000000,gdr_approved_max=50000000,
             gdr_source="https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=c7046fc9-ec90-4f0d-b654-d46b4820ef19"),
 "3305":dict(name="昇貿",rev=7960699,gp=1476635,op=914628,
             parent=537541,eps=3.84,rev9m=12214929,
             financial_source="https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=89244ba0-44fe-4a55-957e-0503cdde617d",
             revenue_source="https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=3033f1cf-b539-4585-9f64-3dccf77d3bb1",
             h1_cfo_k=-1204516,h1_ecl_k=238144,
             cfo_source="https://ww2.money-link.com.tw/TWStock/StockBasic.aspx?SymId=3305&TWMId=Basic_IIAM5",
             company_9m_revenue_explanation="原料價格上漲")
}
def pct(n,d):
    return round(100*n/d,2)
def price_scenario(eps,pe,close):
    return dict(eps=round(eps,2),pe=round(pe,2),
                target=round(eps*pe,2),upside_pct=pct(eps*pe/close-1,1))
def analyze(root="tw-market-data"):
    root=Path(root)
    compact=json.loads((root/"rankings/latest_research.json").read_text())
    raw=gzip.decompress((root/"rankings/v880_full_results.json.gz").read_bytes())
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=compact["full_results"]["json_sha256"]:raise ValueError("MODEL_HASH_MISMATCH")
    full=json.loads(raw)
    if compact["model"]!="V8.10.8" or compact["asof_price_date"]!="2026-10-22":
        raise ValueError("PRICE_OR_MODEL_VINTAGE_MISMATCH")
    rows={r["code"]:r for r in full["all_model_rows"] if r["code"] in DATA}
    if len(rows)!=3:raise ValueError("ISSUER_MISSING")
    results=[]
    for code,h in DATA.items():
        r=rows[code]; b=r["base"];shares=b["shares"];close=r["reference_close"]
        if not r["rankable"] or any(not isinstance(b[x],(float,int)) or not math.isfinite(b[x])
           for x in ("revenue_k","gross_margin","opex_ratio","nonoperating_k","tax_rate","parent_fraction","parent_profit_k","shares","eps","pe")):
            raise ValueError("BASE_INVALID_"+code)
        if abs(b["parent_profit_k"]*1000/shares-b["eps"])>0.01 or abs(b["eps"]*b["pe"]-b["target_price"])>0.02:
            raise ValueError("BASE_PROFIT_OR_PRICE_BRIDGE_MISMATCH_"+code)
        actual_gm=h["gp"]/h["rev"]
        actual_opex=(h["gp"]-h["op"])/h["rev"]
        def from_margins(gm,opex):
            net_k=(b["revenue_k"]*(gm-opex)+b["nonoperating_k"])*(1-b["tax_rate"])*b["parent_fraction"]
            return price_scenario(net_k*1000/shares,b["pe"],close) if net_k>0 else None
        def at_revenue(revenue_k):
            # Counterfactual: freeze model unit profitability/tax/shares,
            # but do not presume extra 2027 revenue beyond simple 2026 9M x 4/3.
            p=(revenue_k*(b["gross_margin"]-b["opex_ratio"])+b["nonoperating_k"])*(1-b["tax_rate"])*b["parent_fraction"]
            return price_scenario(p*1000/shares,b["pe"],close) if p>0 else None
        if abs(from_margins(b["gross_margin"],b["opex_ratio"])["eps"]-b["eps"])>0.03:
            raise ValueError("FULL_OPERATING_BRIDGE_NOT_REPRODUCED_"+code)
        row=dict(code=code,name=h["name"],reference_close=close,source=h["financial_source"],
                 revenue_source=h["revenue_source"],
                 published_2026_H1=dict(revenue_100m=round(h["rev"]/100000,2),
                    gross_margin_pct=pct(h["gp"],h["rev"]),
                    op_margin_pct=pct(h["op"],h["rev"]),
                    opex_ratio_pct=pct(h["gp"]-h["op"],h["rev"]),
                    parent_net_margin_pct=pct(h["parent"],h["rev"]),
                    eps=h["eps"]),
                 published_2026_9m_revenue_100m=round(h["rev9m"]/100000,2),
                 model_2027=dict(revenue_100m=round(b["revenue_k"]/100000,2),
                    gross_margin_pct=round(b["gross_margin"]*100,2),
                    opex_ratio_pct=round(b["opex_ratio"]*100,2),
                    parent_profit_100m=round(b["parent_profit_k"]/100000,2),
                    shares=round(shares),eps=round(b["eps"],2),pe=round(b["pe"],2),
                    target=round(b["target_price"],2),
                    upside_pct=pct(b["target_price"]/close-1,1),
                    revenue_vs_2026_9m_naively_annualized_pct=pct(
                        b["revenue_k"]/(h["rev9m"]*4/3)-1,1),
                    parent_profit_vs_double_H1_pct=pct(
                        b["parent_profit_k"]/(2*h["parent"])-1,1)),
                 eps_pe_each_minus20pct=price_scenario(b["eps"]*.8,b["pe"]*.8,close),
                 counterfactual_2027_revenue_equal_2026_9m_simple_annualized=at_revenue(h["rev9m"]*4/3),
                 counterfactual_is_not_a_revenue_forecast=True,
                 model_revenue_using_2026_H1_gm_and_model_opex=from_margins(actual_gm,b["opex_ratio"]),
                 model_revenue_using_2026_H1_gm_and_H1_opex=from_margins(actual_gm,actual_opex),
                 formal_Aplus=False,original_full_issuer_notes_verified=False,
                 annualization_is_not_a_2027_forecast=True,
                 source_tier=r.get("source_tier"),warning_flags=r.get("warning_flags",[]))
        if code=="2376":
            low=h["outstanding_shares_reference"]+h["gdr_approved_min"]
            high=h["outstanding_shares_reference"]+h["gdr_approved_max"]
            row["gdr"]=dict(plan_source=h["gdr_source"],
                issued_2026_10_24= "NOT_VERIFIED",
                approval_effective_2026_10_08_not_proof_of_issuance=True,
                announced_new_shares_range=[h["gdr_approved_min"],h["gdr_approved_max"]],
                share_basis_2026_10_reference=h["outstanding_shares_reference"],
                model_shares=round(shares),
                model_denominator_at_least_max_proposed_shares=shares>=high,
                mechanical_eps_range_if_model_base_shares_unadjusted=[
                   round(b["eps"]*shares/max(shares, n),2) for n in (low,high)],
                full_diluted_shares_gate_pass=False)
        if code=="3305":
            row["cash_and_ecl_alert"]=dict(
                reported_cfo_H1_100m=round(h["h1_cfo_k"]/100000,2),
                parent_profit_H1_100m=round(h["parent"]/100000,2),
                cfo_minus_parent_profit_H1_100m=round((h["h1_cfo_k"]-h["parent"])/100000,2),
                reported_ecl_H1_100m=round(h["h1_ecl_k"]/100000,2),
                ecl_pct_operating_profit=pct(h["h1_ecl_k"],h["op"]),
                ecl_pct_gross_profit=pct(h["h1_ecl_k"],h["gp"]),
                revenue_growth_explanation=h["company_9m_revenue_explanation"],
                cfo_source=h["cfo_source"],risk_review="HIGH_PRIORITY_VERIFY_COLLECTIONS_ECL_AND_PRICE_PASS_THROUGH",
                not_a_proven_permanent_bad_debt=True)
        results.append(row)
    return dict(schema="V8108_2027_TOP3_OPERATING_BRIDGE_V1",model=compact["model"],
                price_date=compact["asof_price_date"],estimate_vintage=compact["estimate_vintage"],
                full_results_sha256=digest,research_only=True,orders_created=False,
                formal_Aplus_unchanged=True,rows=results)
if __name__=="__main__":
    output=analyze()
    path=Path("/tmp/0050-2027/three_issuer_operating_bridge.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(output,ensure_ascii=False))
