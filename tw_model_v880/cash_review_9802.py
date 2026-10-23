"""Original H1 cash/working-capital arithmetic; no cash-quality certification."""
import datetime as dt
import hashlib
import math
import re
from pathlib import Path
from .evidence import timestamp
from .footwear_review import amounts

SCHEMA='V8108_9802_ORIGINAL_CASH_WC_REVIEW_V1'
STATUS='ORIGINAL_9802_H1_CASH_AND_WC_ARITHMETIC_RECONCILED_NOT_FULL_CASH_GATE'
PUBLISHERS={'2026-Q2':'https://www.fulgentsun.com/img/Finance/115Q2.pdf',
            '2025-Q2':'https://www.fulgentsun.com/img/Finance/202502_9802_AI1_20250828_155225Q2.pdf'}


def _pattern(label):return r'\s*'.join(re.escape(c) for c in re.sub(r'\s+','',label))


def _numbers(text,count):
    tokens=re.findall(r'\(?\s*\$?\s*(?:\d[\d,]*(?:\.\d+)?|-)\s*\)?',text)
    values=[]
    for token in tokens:
        clean=re.sub(r'[\s$()]','',token)
        values.append(0 if clean=='-' else float(clean.replace(',',''))*(-1 if '(' in token else 1))
    if len(values)!=count:raise ValueError('9802_CASH_COLUMN_COUNT')
    return values


def _between(text,label,next_label,count):
    found=list(re.finditer(_pattern(label),text))
    if len(found)!=1:raise ValueError('9802_CASH_LABEL_NOT_UNIQUE:'+label)
    tail=text[found[0].end():];end=re.search(_pattern(next_label),tail)
    if end is None:raise ValueError('9802_CASH_NEXT_LABEL_MISSING:'+next_label)
    return _numbers(tail[:end.start()],count)


def _balance(page,code,label):
    match=re.search(r'(?ms)^[ \t]*'+re.escape(code)+r'[ \t]*\n(.*?)(?=^[ \t]*[0-9A-Z]{4}[ \t]*\n|\Z)',page)
    if not match:raise ValueError('9802_CASH_BALANCE_CODE_MISSING:'+code)
    item=re.search(_pattern(label),match[1])
    if not item:raise ValueError('9802_CASH_BALANCE_LABEL_MISMATCH:'+code)
    values=_numbers(match[1][item.end():],6)
    return values[::2]


CF_ROWS=(
 ('pretax_profit','本期稅前淨利','調整項目'),
 ('depreciation','折舊費用','攤銷費用'),('amortization','攤銷費用','預期信用減損損失(利益)'),
 ('ecl','預期信用減損損失(利益)','透過損益按公允價值衡量金融資產(負債)之淨損失(利益)'),
 ('fv_loss','透過損益按公允價值衡量金融資產(負債)之淨損失(利益)','利息費用'),
 ('interest_expense','利息費用','利息收入'),('interest_income','利息收入','股份基礎給付酬勞成本'),
 ('share_compensation','股份基礎給付酬勞成本','處分及報廢不動產、廠房及設備利益'),
 ('disposal_gain','處分及報廢不動產、廠房及設備利益','租賃修改利益'),
 ('lease_modification_gain','租賃修改利益','與營業活動相關之資產/負債變動數'),
 ('receivables','應收帳款','其他應收款'),('other_receivables','其他應收款','存貨'),
 ('inventory','存貨','預付款項'),('prepayments','預付款項','其他流動資產'),
 ('other_current_assets','其他流動資產','與營業活動相關之負債之淨變動'),
 ('contract_liabilities','合約負債','應付帳款'),('payables','應付帳款','其他應付款'),
 ('other_payables','其他應付款','其他流動負債'),('other_current_liabilities','其他流動負債','其他非流動負債'),
 ('other_noncurrent_liabilities','其他非流動負債','營運產生之現金流出'),
 ('cash_generated','營運產生之現金流出','收取之利息'),
 ('interest_received','收取之利息','支付之利息'),('interest_paid','支付之利息','支付之所得稅'),
 ('tax_paid','支付之所得稅','營業活動之淨現金流出'))
NONCASH_KEYS=tuple(row[0] for row in CF_ROWS[1:10])
WC_KEYS=tuple(row[0] for row in CF_ROWS[10:20])


def extract_h1(pages,year):
    cover=re.sub(r'\s+','',pages[0])
    if not all(t in cover for t in ('9802',str(year-1911),'第二季')):raise ValueError('9802_CASH_ORIGINAL_IDENTITY_OR_PERIOD_MISMATCH')
    if '新台幣仟元' not in re.sub(r'\s+','',pages[7]):raise ValueError('9802_CASH_ORIGINAL_UNIT_MISMATCH')
    income=pages[9].split('8710')[0]
    balances={key:_balance(pages[index],code,label) for key,index,code,label in (
        ('cash',7,'1100','現金及約當現金'),('receivables_net',7,'1170','應收帳款淨額'),
        ('inventory',7,'130X','存貨'),('current_assets',7,'11XX','流動資產合計'),
        ('payables',8,'2170','應付帳款'),('current_liabilities',8,'21XX','流動負債合計'))}
    return dict(year=year,days_in_h1=(dt.date(year,7,1)-dt.date(year,1,1)).days,balances_k=balances,
        revenue_k=amounts(income,'營業收入',4)[2],cogs_k=amounts(income,'營業成本',4)[2],
        parent_profit_k=amounts(income,'母公司業主',4)[2])


def _cycle(facts):
    balances=facts['balances_k'];days=facts['days_in_h1']
    average=lambda key:(balances[key][0]+balances[key][1])/2
    dso=average('receivables_net')/facts['revenue_k']*days
    dio=average('inventory')/facts['cogs_k']*days
    dpo=average('payables')/facts['cogs_k']*days
    return dict(dso_proxy_days=dso,inventory_proxy_days=dio,payables_proxy_days=dpo,
                cash_conversion_cycle_proxy_days=dso+dio-dpo,
                method='AVERAGE_BEGIN_END_NET_BALANCES_DIVIDED_BY_H1_SALES_OR_COGS_TIMES_ACTUAL_H1_DAYS',
                credit_sales_and_purchases_not_separately_verified=True)


def check_9802_cash_review(record,root,asof,income,cash):
    import pymupdf
    root=Path(root).resolve();cutoff=timestamp(asof)
    if (record.get('schema')!=SCHEMA or record.get('issuer')!='9802' or record.get('market')!='TWSE' or
        record.get('period')!='2026-Q2' or record.get('formal_cash_and_working_capital_gate_pass') is not False or
        record.get('formal_Aplus_addition')!=0 or record.get('issuer_historical_filings_PIT_verified') is not False or
        record.get('full_financial_statements_and_notes_reviewed') is not False):
        raise ValueError('9802_CASH_REVIEW_IDENTITY_OR_FALSE_CERTIFICATION')
    if timestamp(record['reviewed_at'])>cutoff:raise ValueError('9802_CASH_REVIEW_FROM_FUTURE')
    sources=record['sources'];by_period={s['period']:s for s in sources}
    if len(sources)!=2 or set(by_period)!=set(PUBLISHERS):raise ValueError('9802_CASH_SOURCE_PERIOD_SET')
    documents={}
    for period,source in by_period.items():
        if source['source_url']!=PUBLISHERS[period]:raise ValueError('9802_CASH_WRONG_PUBLISHER')
        if timestamp(source['captured_at_utc'])>timestamp(record['reviewed_at']):raise ValueError('9802_CASH_CAPTURE_AFTER_REVIEW')
        relative=Path(source['archive_path']);path=(root/relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or root not in path.parents:raise ValueError('9802_CASH_UNSAFE_ORIGINAL_PATH')
        raw=path.read_bytes()
        if not raw.startswith(b'%PDF-') or hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('9802_CASH_ORIGINAL_HASH_MISMATCH')
        with pymupdf.open(stream=raw,filetype='pdf') as pdf:documents[period]=[p.get_text() for p in pdf]
    current=extract_h1(documents['2026-Q2'],2026);prior=extract_h1(documents['2025-Q2'],2025)
    pages=documents['2026-Q2'];balances=current['balances_k'];cf={k:_between(pages[11],label,end,2) for k,label,end in CF_ROWS}
    cf['ocf']=_between(pages[11],'營業活動之淨現金流出','(續 次 頁)',2)
    for key,label,end in (
        ('ppe','取得不動產、廠房及設備','處分不動產、廠房及設備'),
        ('investing','投資活動之淨現金流出','籌資活動之現金流量'),
        ('dividends_paid','發放現金股利','現金增資'),('financing','籌資活動之淨現金(流出)流入','匯率變動影響數'),
        ('fx','匯率變動影響數','本期現金及約當現金減少數'),
        ('cash_change','本期現金及約當現金減少數','期初現金及約當現金餘額'),
        ('opening_cash','期初現金及約當現金餘額','期末現金及約當現金餘額')):
        cf[key]=_between(pages[12],label,end,2)
    before_wc=[];net_wc=[]
    for col in (0,1):
        before=cf['pretax_profit'][col]+sum(cf[k][col] for k in NONCASH_KEYS);working=sum(cf[k][col] for k in WC_KEYS)
        if (abs(before+working-cf['cash_generated'][col])>1 or
            abs(cf['cash_generated'][col]+cf['interest_received'][col]+cf['interest_paid'][col]+cf['tax_paid'][col]-cf['ocf'][col])>1 or
            abs(cf['ocf'][col]+cf['investing'][col]+cf['financing'][col]+cf['fx'][col]-cf['cash_change'][col])>1):
            raise ValueError('9802_CASH_FLOW_ARITHMETIC_MISMATCH')
        before_wc.append(before);net_wc.append(working)
    if abs(cf['opening_cash'][0]+cf['cash_change'][0]-balances['cash'][0])>1 or abs(cf['opening_cash'][1]+cf['cash_change'][1]-balances['cash'][2])>1:
        raise ValueError('9802_CASH_BALANCE_ROLLFORWARD_MISMATCH')
    if not (income.get('code')=='9802' and income.get('market')=='TWSE' and income.get('period')=='2026-Q2' and
            cash.get('code')=='9802' and cash.get('market')=='TWSE' and cash.get('period')=='2026-Q2'):
        raise ValueError('9802_CASH_OFFICIAL_MIRROR_IDENTITY_MISMATCH')
    for actual,expected in ((income.get('revenue_ytd_k'),current['revenue_k']),
                            (cash.get('operating_cashflow_ytd_k'),cf['ocf'][0])):
        if actual is None or not math.isclose(actual,expected,rel_tol=0,abs_tol=1):raise ValueError('9802_CASH_OFFICIAL_MIRROR_VALUE_MISMATCH')
    for key in balances:
        if balances[key][2]!=prior['balances_k'][key][0]:raise ValueError('9802_CASH_COMPARATIVE_BALANCE_CONFLICT')
    if cf['ocf'][1]!=_between(documents['2025-Q2'][11],'營業活動之淨現金(流出)流入','(續 次 頁)',2)[0]:
        raise ValueError('9802_CASH_COMPARATIVE_OCF_CONFLICT')
    note=pages[19]
    aging={key:_between(note,label,end,3) for key,label,end in (
        ('not_overdue','未逾期','逾期0~90天'),('overdue_0_90','逾期0~90天','逾期91~180天'),
        ('overdue_91_180','逾期91~180天','逾期181天~365天'),('overdue_181_365','逾期181天~365天','逾期365天以上'),
        ('overdue_over_365','逾期365天以上','合計'))}
    ar_gross=[sum(v[i] for v in aging.values()) for i in range(3)]
    ar_note=pages[18].split('(三)')[-1]
    allowance_label=re.search(_pattern('減：備抵損失'),ar_note)
    if not allowance_label:raise ValueError('9802_CASH_AR_ALLOWANCE_NOTE_MISSING')
    # This note emits closing/opening parentheses after amounts in native text.
    # The explicit deduction label fixes the sign; do not borrow a neighbour's bracket.
    allowance_and_net=amounts(ar_note,'減：備抵損失',6)
    allowance=[-v for v in allowance_and_net[:3]]
    if allowance_and_net[3:]!=balances['receivables_net']:raise ValueError('9802_CASH_AR_NOTE_NET_VS_BALANCE_MISMATCH')
    if any(ar_gross[i]+allowance[i]!=balances['receivables_net'][i] for i in range(3)):
        raise ValueError('9802_CASH_AR_AGING_ALLOWANCE_NET_MISMATCH')
    inventory_start=re.search(_pattern('(四)存貨'),pages[19])
    inventory_note=pages[19][inventory_start.end():] if inventory_start else ''
    headers=list(re.finditer(_pattern('成本備抵呆滯及跌價損失帳面價值'),inventory_note))
    if len(headers)!=3:raise ValueError('9802_CASH_INVENTORY_TABLE_SET_MISMATCH')
    inventory_tables=[]
    for index,header in enumerate(headers):
        table=inventory_note[header.end():headers[index+1].start() if index<2 else len(inventory_note)]
        components={key:[abs(v) for v in _between(table,label,end,3)] for key,label,end in (
            ('raw_material','原料','在製品'),('work_in_process','在製品','製成品'),
            ('finished_goods','製成品','在途存貨'),('in_transit','在途存貨','合計'))}
        total=amounts(table,'合計',3)
        if (any(sum(row[col] for row in components.values())!=total[col] for col in range(3)) or
            total[0]-total[1]!=total[2] or total[2]!=balances['inventory'][index]):
            raise ValueError('9802_CASH_INVENTORY_COST_ALLOWANCE_NET_MISMATCH')
        inventory_tables.append(dict(components_cost_allowance_net_k=components,total_cost_allowance_net_k=total))
    compact=re.sub(r'\s+','',pages[46]);unused=re.search(r'未動用之借款額度分別為\$([\d,]+)、\$([\d,]+)及\$([\d,]+)',compact)
    if not unused:raise ValueError('9802_CASH_UNUSED_BANK_LINE_NOTE_MISSING')
    factor=re.search(r'以債券面額之([\d.]+)%',re.sub(r'\s+','',pages[25]))
    if not factor:raise ValueError('9802_CASH_BOND_PUT_PERCENT_MISSING')
    audit=re.sub(r'\s+','',pages[3])
    if not all(t in audit for t in ('會計師查核報告','所有重大方面','查核意見之基礎')):raise ValueError('9802_CASH_CURRENT_AUDIT_TEXT_UNSUPPORTED')
    if any(t in audit for t in ('保留意見','否定意見','無法表示意見')):raise ValueError('9802_CASH_CURRENT_AUDIT_TEXT_UNSUPPORTED')
    deltas={key:balances[key][0]-balances[key][1] for key in ('receivables_net','inventory','payables')}
    residuals={key:deltas[key]+cf['receivables' if key=='receivables_net' else key][0]*(1 if key!='payables' else -1) for key in deltas}
    return dict(code='9802',period='2026-Q2',status=STATUS,balance_sheet_date='2026-06-30',reviewed_at=record['reviewed_at'],
        original_sources=sources,current_h1=current,prior_h1=prior,cashflow_signed_k=cf,
        cash_before_working_capital_k=before_wc,working_capital_cash_change_k=net_wc,
        balance_changes_since_prior_fy_k=deltas,balance_change_vs_cashflow_residual_k=residuals,
        residuals_are_unallocated_not_assumed_all_fx=True,receivables_aging_k=aging,
        receivables_gross_k=ar_gross,receivables_allowance_signed_k=allowance,
        ar_over_90_days_pct=sum(aging[k][0] for k in ('overdue_91_180','overdue_181_365','overdue_over_365'))/ar_gross[0]*100,
        inventory_cost_allowance_and_components=inventory_tables,
        current_h1_cycle_proxy=_cycle(current),prior_h1_cycle_proxy=_cycle(prior),
        reported_unused_bank_lines_k=[float(v.replace(',','')) for v in unused.groups()],
        bank_lines_asof='2026-06-30',unused_lines_are_cash=False,current_facility_drawability_verified=False,
        cb_put_redemption_factor=float(factor[1])/100,cb_put_anniversary='2026-11-15',actual_cb_put_exercise_verified=False,
        current_h1_audit_text_observation='UNMODIFIED_AUDIT_OPINION_TEXT_OBSERVED_NOT_FULL_AUDITOR_GATE',
        cashflow_total_and_cash_balance_arithmetic_reconciled=True,
        collections_inventory_saleability_and_current_funding_unverified=True,
        formal_cash_and_working_capital_gate_pass=False,formal_Aplus_addition=0,issuer_historical_filings_PIT_verified=False)
