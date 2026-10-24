#!/usr/bin/env python3
"""0056 2027 EPS/PE pressure and original H1 run-rate plausibility audit.

This is NOT an independently calibrated 2027 return probability and NOT a
forecast revision. 20% reductions to both EPS and PE are a predeclared
counterfactual, preserving all official model Base and A+ decisions.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from scripts.v8b4_0056_forward_top10 import load_inputs,filter_top10

EPS_FACTOR=0.80
PE_FACTOR=0.80
STRESS_NAME='EPS_MINUS20PCT_AND_PE_MINUS20PCT_NONPROBABILISTIC'
H1_PERIOD='2026-Q2'


def _number(value):
    return (type(value) in (int,float) and math.isfinite(value))


def audit_0056(root):
    root=Path(root)
    holdings,compact,full=load_inputs(root)
    selected=filter_top10(holdings,full)
    rows=json.loads((root/'fundamentals'/H1_PERIOD/'TWSE_income.json').read_text(encoding='utf-8'))['rows']
    eps_mirror={}
    for row in rows:
        code=row.get('code')
        if code in eps_mirror:
            raise ValueError('0056_DUPLICATE_OFFICIAL_Q2_ISSUER')
        eps_mirror[code]=row
    examined=[]
    for model in selected['all_ranked']:
        code=model['code']
        earning=eps_mirror.get(code) or {}
        if (earning.get('market')!='TWSE' or
            earning.get('period')!=H1_PERIOD or
            earning.get('year_to_date_values') is not True or
            not _number(earning.get('basic_eps_ytd')) or
            earning['basic_eps_ytd']<=0):
            raise ValueError('0056_H1_EPS_MISSING_OR_INCONSISTENT_'+code)
        if not all(_number(model.get(k)) for k in (
                'price_ntd','forward_2027_eps','reasonable_pe','base_target_ntd',
                'potential_price_upside_pct')):
            raise ValueError('0056_MODEL_PRICE_EPS_PE_NOT_FINITE_'+code)
        close=model['price_ntd']
        eps=model['forward_2027_eps']
        pe=model['reasonable_pe']
        if eps<=0 or pe<=0 or close<=0:
            raise ValueError('0056_ZERO_OR_NEGATIVE_BASE_'+code)
        if abs(eps*pe-model['base_target_ntd'])>0.025:
            raise ValueError('0056_EPS_PE_PRICE_IDENTITY_FAIL_'+code)
        h1_eps=earning['basic_eps_ytd']
        annualized=2*h1_eps
        stretch_pct=100*(eps/annualized-1)
        both_price=eps*EPS_FACTOR*pe*PE_FACTOR
        one_upside=100*((eps*EPS_FACTOR*pe)/close-1)
        pe_upside=100*((eps*pe*PE_FACTOR)/close-1)
        both_upside=100*(both_price/close-1)
        examined.append(dict(**model,
            h1_2026_basic_eps=h1_eps,
            h1_annualized_2026_eps_reference=annualized,
            base_2027_eps_vs_h1_annualized_pct=stretch_pct,
            base_2027_eps_above_h1_runrate_by_30pct=stretch_pct>=30,
            base_2027_eps_above_h1_runrate_by_50pct=stretch_pct>=50,
            eps_minus20_upside_pct=one_upside,
            pe_minus20_upside_pct=pe_upside,
            combined_eps_pe_minus20_price_ntd=both_price,
            combined_eps_pe_minus20_upside_pct=both_upside,
            issuer_2026_h1_statement_source=earning.get('source'),
            issuer_2026_h1_statement_PIT_verified=bool(earning.get('company_PIT_verified')),
            yearly_seasonality_normalized=False,
            2027_earnings_bridge_independently_certified=False,
            EPS_PE_stress_is_not_a_probability=True,
            no_formal_Aplus_promotion=True))
    assert len(examined)==selected['rankable_count']
    return dict(schema='0056_2027_EPS_PE_COUNTERFACTUAL_V1_NO_FORMAL_CERTIFICATION',
        holdings_date=selected['etf_holdings_date'],
        estimate_vintage=selected['estimate_vintage'],
        reference_close_date=selected['asof_price_date'],target_date=selected['target_date'],
        model_version=selected['model'],
        model_full_binary_sha256=compact['full_results']['sha256'],
        official_H1_income_file_sha256=hashlib.sha256(
            (root/'fundamentals'/H1_PERIOD/'TWSE_income.json').read_bytes()).hexdigest(),
        tracked_etf_holdings_count=selected['holdings_count'],
        base_price_rankable_count=selected['rankable_count'],
        not_rankable_count=selected['unrankable_count'],
        not_rankable=selected['unrankable'],
        stress_name=STRESS_NAME,eps_factor=EPS_FACTOR,pe_factor=PE_FACTOR,
        higher_than_h1_annualized_by_30pct_count=sum(x['base_2027_eps_above_h1_runrate_by_30pct'] for x in examined),
        top10=examined[:10],all_34_ranked=examined,
        original_base_ranking_and_targets_unchanged=True,
        no_formal_gate_pass_granted=True,full_13_gates_not_signed=True,
        not_complete_0056_comparable_ranking=True,
        source_membership_is_public_secondary_snapshot_not_confirmed_official_daily_PCF=True,
        all_h1_eps_reference_not_a_2026_full_year_forecast=True,
        2027_earnings_bridge_and_pe_revalidation_still_required=True,
        dividends_and_fees_unmodeled=True,
        strategy_outperformance_vs_0056_not_tested=True)


def write_report(data,path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.json':
        content=json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    else:
        lines=[
            '# 0056 2027 潛在價差 TOP10 — 獲利基準與EPS/PE雙降壓力測試','',
            f"成分日期：{data['holdings_date']}；參考收盤：{data['reference_close_date']}；"
            f"模型形成：{data['estimate_vintage']}；預估至 {data['target_date']}。",'',
            f"0056持股 {data['tracked_etf_holdings_count']} 檔；"
            f"可比估值 {data['base_price_rankable_count']} 檔；"
            f"排除待補 {data['not_rankable_count']} 檔。",'',
            '**研究情境，不是目標報酬率或交易建議。**'
            '壓力測試僅將原模型2027 EPS和合理PE各下修20%，'
            '不估算發生機率，也不自動修改Base、股票排序與品質門檻。','',
            '|排名|股票|2026 H1 EPS|H1簡單年化|2027 Base EPS|相對年化|合理PE|2027 Base價|Base價差|雙降20%價|雙降20%價差|原始當期數字|',
            '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for i,r in enumerate(data['top10'],1):
            lines.append(
                f"|{i}|{r['code']} {r['name']}|{r['h1_2026_basic_eps']:.2f}|"
                f"{r['h1_annualized_2026_eps_reference']:.2f}|"
                f"{r['forward_2027_eps']:.2f}|{r['base_2027_eps_vs_h1_annualized_pct']:+.1f}%|"
                f"{r['reasonable_pe']:.2f}|{r['base_target_ntd']:.2f}|"
                f"{r['potential_price_upside_pct']:+.1f}%|"
                f"{r['combined_eps_pe_minus20_price_ntd']:.2f}|"
                f"{r['combined_eps_pe_minus20_upside_pct']:+.1f}%|"
                f"{'是' if r['original_current_issuer_numeric_checked'] else '否'}|")
        lines+=['',f"34檔可比股中，2027 Base EPS 高於2026上半年EPS簡單年化30%以上："
                f"{data['higher_than_h1_annualized_by_30pct_count']} 檔。",
                '「簡單年化」未校正季節性，不能視為正式2026全年預測。'
                '公司原始主表、年度量價利潤橋接、股本稀釋及正式PE同業驗證仍需逐檔複核。',
                '另外16檔因銀行ROE/PB、特殊營運假設或財報缺件暫未可比，'
                '不可將其視為低報酬；未知股利及成本亦未計入。','',
                '來源：本GitHub封存的0056成分名單、2026-Q2官方標準化TWSE財報鏡像、'
                'SHA檢查的2027完整模型情境。完整原始MOPS公告PIT尚未核實。',
                '正式A+沒有新增。沒有獨立樣本外報酬回測結果。','']
        content='\n'.join(lines)
    path.write_text(content,encoding='utf-8')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('tw-market-data'))
    p.add_argument('--out',type=Path)
    p.add_argument('--print-json',action='store_true')
    a=p.parse_args()
    result=audit_0056(a.root)
    if a.out:
        write_report(result,a.out)
        write_report(result,a.out.with_suffix('.md'))
    if a.print_json:
        print('BEGIN_0056_STRESS_V1='+json.dumps({
            'base_rankable':result['base_price_rankable_count'],
            'greater_than_30_pct_eps_stretch':result['higher_than_h1_annualized_by_30pct_count'],
            'rows':[{k:r[k] for k in (
                'code','name','h1_2026_basic_eps','h1_annualized_2026_eps_reference',
                'forward_2027_eps','base_2027_eps_vs_h1_annualized_pct',
                'potential_price_upside_pct','combined_eps_pe_minus20_upside_pct',
                'original_current_issuer_numeric_checked')}
                for r in result['top10']]},ensure_ascii=False,separators=(',',':')))


if __name__=='__main__':
    main()
