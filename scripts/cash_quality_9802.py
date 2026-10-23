#!/usr/bin/env python3
"""Publish original-source cash diagnostics after the current model run."""
import datetime as dt,gzip,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_research_pipeline import atomic_json
from tw_model_v880.cash_review_9802 import STATUS


def build_report(full):
    row=next((r for r in full['all_model_rows'] if r['code']=='9802'),{})
    review=row.get('working_capital_original_subcheck')
    report=dict(schema='V8108_9802_CASH_REPORT_V1',model=full['model'],estimate_vintage=full['estimate_vintage'],
                price_date=full['asof_price_date'],code='9802',income_period=row.get('financial_period'),
                cashflow_period=row.get('cashflow_financial_period'),research_only=True,
                changes_eps_or_target_price=False,grants_quality_certification=False,
                formal_Aplus=row.get('formal_Aplus',False),original_cash_review=review,full_put_sensitivity=None)
    if not review or review.get('status')!=STATUS:
        return dict(report,status='WAITING_ORIGINAL_CASH_REVIEW')
    report['status']='ORIGINAL_CASH_REVIEW_AVAILABLE_CURRENT_FUNDING_UNVERIFIED'
    bonds=[b for b in row.get('share_bridge',{}).get('bonds',[]) if b['code']=='98026']
    if len(bonds)==1:
        bond=bonds[0];snapshot=bond.get('snapshot_date','');put=bond.get('put_date','')
        try:snapshot_valid=dt.datetime.strptime(snapshot,'%Y%m%d').date()<=dt.date.fromisoformat(full['estimate_vintage'][:10])
        except (ValueError,TypeError):snapshot_valid=False
        if (bond.get('currency')=='TWD' and isinstance(bond.get('face'),(int,float)) and
            math.isfinite(bond['face']) and bond['face']>=0 and snapshot_valid and len(snapshot)==8 and
            put==review['cb_put_anniversary'].replace('-','')):
            amount=bond['face']/1000*review['cb_put_redemption_factor']
            report['full_put_sensitivity']=dict(outstanding_face_k=bond['face']/1000,outstanding_snapshot_date=snapshot,
                put_anniversary=review['cb_put_anniversary'],redemption_factor=review['cb_put_redemption_factor'],
                assumed_full_put_cash_k=amount,old_reported_cash_less_full_put_k=review['current_h1']['balances_k']['cash'][0]-amount,
                assumes_full_put_not_a_prediction=True,actual_exercise_or_settlement_verified=False,
                cash_balance_date=review['balance_sheet_date'],post_balance_date_cashflows_not_included=True,
                historical_unused_bank_lines_not_added_to_cash=True,not_an_actual_current_funding_gap=True)
        else:report['full_put_sensitivity_error']='BOND_SNAPSHOT_OR_PUT_TERMS_NOT_RECONCILED'
    else:report['full_put_sensitivity_error']='CURRENT_OUTSTANDING_BOND_NOT_UNIQUE_OR_NOT_PRESENT'
    return report


def markdown(report):
    lines=['# 鈺齊現金流、存貨與融資核對','',f"模型 {report['model']}；估值形成 {report['estimate_vintage']}。",'',
           f"損益期：{report['income_period']}；現金流期：{report['cashflow_period']}。本報告不改 EPS、情境價或品質認證。",'']
    review=report.get('original_cash_review')
    if not review or report['status']=='WAITING_ORIGINAL_CASH_REVIEW':return '\n'.join(lines+['原件核對尚未可用；不以缺值推論資金缺口。',''])
    cf=review['cashflow_signed_k'];current=review['current_h1'];prior=review['prior_h1'];e8=lambda value:value/100000
    lines+=['金額單位：億元。2026H1 原件為查核財報；只核對本報告指定項目，未完成全部附註或八季品質認證。','',
            '| H1 現金橋 | 2026 | 2025 |','|---|---:|---:|']
    for label,values in [('稅前淨利及非現金調整後、營運資金變動前',review['cash_before_working_capital_k']),
                         ('營運資金現金變動合計',review['working_capital_cash_change_k']),
                         ('應收帳款現金變動',cf['receivables']),('存貨現金變動',cf['inventory']),
                         ('應付帳款現金變動',cf['payables']),('營業現金流',cf['ocf']),('購置不動產、廠房設備',cf['ppe']),
                         ('現金股利實際支付',cf['dividends_paid']),('期末現金',[current['balances_k']['cash'][0],prior['balances_k']['cash'][0]])]:
        lines.append(f'| {label} | {e8(values[0]):+.3f} | {e8(values[1]):+.3f} |')
    lines+=['','上表應收、存貨、應付帳款列為營運資金合計的組成，不能再與合計相加。期初期末現金亦已按營業、投資、籌資及匯率影響核對。','',
            '| 週轉代理值（天） | 2026H1 | 2025H1 |','|---|---:|---:|']
    for label,key in [('應收帳款','dso_proxy_days'),('存貨','inventory_proxy_days'),('應付帳款','payables_proxy_days'),('現金循環','cash_conversion_cycle_proxy_days')]:
        lines.append(f"| {label} | {review['current_h1_cycle_proxy'][key]:.1f} | {review['prior_h1_cycle_proxy'][key]:.1f} |")
    lines+=['','週轉代理值使用期初期末平均淨額、H1 營收／銷貨成本與該年 H1 天數；不是已核實的逐筆收款或採購付款天數。',
            f"逾期超過90天的應收帳款占應收總額約 {review['ar_over_90_days_pct']:.2f}%。是否已收回與存貨能否順利去化仍待後續原件。",'',
            f"**2026/6/30 現金 {e8(current['balances_k']['cash'][0]):.2f} 億；財報列示同一基準日的未動用借款額度 {e8(review['reported_unused_bank_lines_k'][0]):.2f} 億。** 額度不等同現金，未核實目前額度、各子公司／幣別可調度性、擔保與契約限制。",'']
    sensitivity=report.get('full_put_sensitivity')
    if sensitivity:
        lines+=[f"依 {sensitivity['outstanding_snapshot_date']} 在外本金，全數 CB 按 {sensitivity['redemption_factor']*100:.4f}% 賣回的假設現金支出約 {e8(sensitivity['assumed_full_put_cash_k']):.2f} 億；以六月底現金扣此假設約餘 {e8(sensitivity['old_reported_cash_less_full_put_k']):.2f} 億。",
                '此為跨日期靜態壓測，未包含六月底以後收付款、配息及其他到期債務；未確認實際賣回申請或交割日，不能當成目前可支配現金或實際資金缺口。','']
    else:lines+=[f"CB 壓測待核：{report.get('full_put_sensitivity_error')}。",'']
    lines+=['帳面應收、存貨、應付的增減與現金流變動尚有未分配差額，完整數值見 JSON；未直接歸因為匯率，也未強制調平。',
            '目前缺口：六月底以後現金與收款（含待公布的九月底現金流）、存貨去化、銀行額度可動用條件、CB 實際賣回與後續融資。負現金流需要續驗，不自動判為 FAIL，也不授予 PASS。','',
            '原件：']
    for source in review['original_sources']:lines.append(f"- [{source['period']}]({source['source_url']})；SHA256 {source['sha256']}")
    return '\n'.join(lines)+'\n'


def main():
    rankings=ROOT/'tw-market-data/rankings';full=json.loads(gzip.decompress((rankings/'v880_full_results.json.gz').read_bytes()))
    report=build_report(full);atomic_json(rankings/'latest_9802_cash_review.json',report)
    (rankings/'latest_9802_cash_review.md').write_text(markdown(report))
    print(json.dumps(dict(status=report['status'],changes_eps_or_target_price=False,formal_Aplus_created=0)))
    return 0

if __name__=='__main__':raise SystemExit(main())
