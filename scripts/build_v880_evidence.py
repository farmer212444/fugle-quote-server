#!/usr/bin/env python3
"""Build a compact, dated model seed from frozen public original evidence.

The audit workspace is an explicit offline input. This does not retry the
protected MOPS historical endpoint or promote original capture to certification.
"""
import argparse,collections,concurrent.futures,csv,datetime as dt,gzip,hashlib,io,json,pathlib,re,urllib.request
def read(p):return json.loads(pathlib.Path(p).read_text())
def sha(b):return hashlib.sha256(b).hexdigest()
def num(v):
    try:return float(str(v).replace(',',''))
    except (ValueError,TypeError):return None
def component(j,ctx):
    def fact(code):
        a={f['value']/1000 for f in j['facts'] if f.get('account_code')==code and f.get('context')==ctx and f.get('unit')=='TWD'}
        if len(a)>1:raise ValueError('CONFLICTING_PRIMARY_FACT:'+code)
        return next(iter(a)) if a else None
    pre= fact('7900');op=fact('6900');items={}
    for f in j['facts']:
        if f.get('context')==ctx and f.get('unit')=='TWD' and re.search('外幣兌換|公允價值|處分|廉價購買',f.get('label','')) and f.get('account_code','').startswith('N'):
            items[f['account_code']]=dict(value_k=f['value']/1000,label=f['label'])
    return dict(reported_gap_k=pre-op if None not in (pre,op) else None,zeroed_observed_components=items,
      sensitivity_gap_ex_volatile_k=pre-op-sum(x['value_k'] for x in items.values()) if None not in (pre,op) else None,
      impairment_retained=True,missing_optional_disclosures_are_not_verified_zero=True)
def fetch(source):
    with urllib.request.urlopen(urllib.request.Request(source['url'],headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:
        if r.status!=200:raise ValueError('UNEXPECTED_HTTP_STATUS')
        raw=r.read(8000000)
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:text=raw.decode('cp950')
    rows=json.loads(text) if text.lstrip().startswith('[') else list(csv.DictReader(io.StringIO(text)))
    if not isinstance(rows,list) or len(rows)<500:raise ValueError('UNEXPECTED_OFFICIAL_BULK_ROWS')
    periods={str(int(x['年度'])+1911 if int(x['年度'])<1911 else int(x['年度']))+'-Q'+str(int(x['季別'])) for x in rows}
    if len(periods)!=1:raise ValueError('MIXED_BULK_PERIODS')
    return source,raw,dict(period=next(iter(periods)),rows=rows,source=source['url'],sha256=sha(raw),fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),unit='TWD_THOUSANDS_EXCEPT_EPS')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--audit-workspace',required=True);ap.add_argument('--data-dir',default='tw-market-data');args=ap.parse_args()
    workspace=pathlib.Path(args.audit_workspace);r=workspace/'verification_20261018';r2=workspace/'verification_20261018_round2'
    data=pathlib.Path(args.data_dir);out=data/'evidence/v880';(out/'raw').mkdir(parents=True,exist_ok=True)
    fallback=workspace.parent/'verification_20261018'
    def original(name):return r/name if (r/name).exists() else fallback/name
    now=dt.datetime.now(dt.timezone.utc).isoformat();e=dict(schema='V880_PUBLIC_EVIDENCE_V1',snapshot_date=now[:10],snapshot_available_at=now,
      primary={},master={},bonds={},pe_history={},peers={},weighted_diluted_disclosed={'5511':136427000},primary_cash_eight_quarters={},certificates={},issuer_operating_bridges={})
    for market in ('TWSE','TPEX'):
        path=original('security_master_'+market+'.json');raw=path.read_bytes()
        for row in json.loads(raw):
            code=str(row.get('公司代號',row.get('SecuritiesCompanyCode')))
            e['master'][code]=dict(code=code,name=row.get('公司簡稱',row.get('CompanyAbbreviation')),market=market,
              issued_shares=num(row.get('已發行普通股數或TDR原股發行股數',row.get('IssueShares'))),industry_code=str(row.get('產業別',row.get('SecuritiesIndustryCode'))).zfill(2),
              par_value=row.get('普通股每股面額',row.get('ParValueOfCommonStock')),date=row.get('出表日期',row.get('Date')),source_sha256=sha(raw))
    for path in sorted((r/'parsed_ifrs').glob('*/2026Q2.json')):
        j=read(path);code=j['code'];fy_path=path.with_name('2025Q4.json');fy=read(fy_path) if fy_path.exists() else None
        if not j['fiscal_identity_verified'] or not j['units_verified_from_ix']:raise ValueError('PRIMARY_IDENTITY_OR_UNIT_FAILURE:'+code)
        prepaid=[f['value']/1000 for f in j['facts'] if f.get('account_code')=='B07100' and f['context']=='From20260101To20260630' and f['unit']=='TWD']
        e['primary'][code]=dict(period='2026-Q2',values=j['values'],prior_full_year=fy['values'] if fy else None,
          nonop_current=component(j,'From20260101To20260630'),nonop_prior_ytd=component(j,'From20250101To20250630'),
          nonop_prior_fy=component(fy,'From20250101To20251231') if fy else None,qualified_review=j.get('qualified_review_flag')=='Y',
          equipment_prepaid_signed_k=prepaid[0] if prepaid else None,
          business_description=' '.join(n['text'] for n in j['notes'] if 'HistoryAndOrganization' in n['name']),
          source=dict(url=j['source_url'],sha256=j['sha256'],fetched_at=j['fetched_at_utc'],origin_authenticated=True))
    for path in sorted(original('pe_history').glob('*.json')):
        if path.name=='receipts.json':continue
        j=read(path);tab=j['tables'][0] if j.get('tables') else j;ix=tab['fields'].index('本益比')
        for row in tab['data']:
            pe=num(row[ix])
            if pe and 0<pe<150:e['pe_history'].setdefault(str(row[0]),[]).append(dict(pe=pe,snapshot=path.stem,raw_sha256=sha(path.read_bytes())))
    current={}
    for row in read(original('market_original/TWSE_PE.json'))['data']:current[row[0]]=num(row[5])
    for row in read(original('market_original/tpex_mainboard_peratio_analysis.json')):current[row['SecuritiesCompanyCode']]=num(row['PriceEarningRatio'])
    for code,pe in current.items():
        if code in e['master'] and pe and 0<pe<100:e['peers'].setdefault(e['master'][code]['industry_code'],[]).append(dict(code=code,pe=pe,date='2026-10-16'))
    known={'12561':182.5,'36173':274.3,'98026':104.1}
    for name in ('bond_ISSBD5_data','bond_ISSBD6_data','bond_ISSBD7_data','bond_ISSBD8_data'):
        for b in read(original('market_original/'+name+'.json')):
            code=b['IssuerCode'];face=num(b.get('OutstandingAmount'));price=known.get(b['BondCode'],num(b.get('Conversion/ExchangePriceAtIssuance')))
            if code not in e['master'] or not face or b.get('IssueDate','')>'20261018':continue
            e['bonds'].setdefault(code,[]).append(dict(code=b['BondCode'],face=face,currency='TWD' if b['Currency']=='1' else 'FOREIGN_CURRENCY_'+b['Currency'],
              conversion_price=price,current_terms_verified=False,price_basis='DATED_PRIMARY_OR_ANNOUNCEMENT_REPUBLICATION' if b['BondCode'] in known else 'ISSUE_TERMS_NOT_CURRENT_RESET',
              maturity=b['MaturityDate'],put_date=b['PutOptionDate'],snapshot_date=b['Date']))
    for row in read(r2/'eightq_cash_bridge.json')['issuer']:e['primary_cash_eight_quarters'][row['code']]=row
    e['issuer_events']={'9802':dict(cash_balance_date='2026-06-30',dividend=dict(per_share=3.1,scheduled_payment='2026-10-15',actual_completion_verified=False,indicative_cash_twd=200991673*3.1),
      convertible_put=dict(contract_date='2026-11-15',full_exercise_sensitivity_twd=999800000*1.010025,actual_requests_verified=False))}
    e['official_current_bulk']={};sources=read(data/'financial/latest_manifest.json')['sources']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for source,raw,obj in pool.map(fetch,sources):
            e['official_current_bulk'][source['kind']]=obj;(out/'raw'/(source['kind']+'.gz')).write_bytes(gzip.compress(raw,mtime=0))
    matches=0
    fields={'revenue_k':'營業收入','gross_profit_k':'營業毛利（毛損）淨額','operating_profit_k':'營業利益（損失）','pretax_profit_k':'稅前淨利（淨損）','net_income_k':'本期淨利（淨損）','parent_net_income_k':'淨利（淨損）歸屬於母公司業主'}
    for code,p in e['primary'].items():
        rows=e['official_current_bulk'][e['master'][code]['market']+'_income']['rows'];row=next(x for x in rows if x['公司代號']==code)
        for k,label in fields.items():
            v=num(row.get(label));v=num(row.get('營業毛利（毛損）')) if k=='gross_profit_k' and v is None else v
            if v is None or abs(p['values'][k]-v)>1:raise ValueError('PRIMARY_BULK_RECONCILIATION:'+code+':'+k)
            matches+=1
    e['qa']=dict(financial_period='2026-Q2',checked_at=now,primary_to_official_bulk_core_matches=matches,primary_issuers=len(e['primary']),full_notes_audit_is_complete=False)
    e['snapshot_available_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    raw=json.dumps(e,ensure_ascii=False,separators=(',',':')).encode();packed=gzip.compress(raw,mtime=0)
    (out/'snapshot.json.gz').write_bytes(packed);(out/'manifest.json').write_text(json.dumps(dict(model='V8.8.0',path='evidence/v880/snapshot.json.gz',gzip_sha256=sha(packed),json_sha256=sha(raw),available_at=now,qa=e['qa']),indent=2)+'\n')
    print(json.dumps(dict(primary=len(e['primary']),master=len(e['master']),official_core_matches=matches,snapshot_bytes=len(packed))))
if __name__=='__main__':main()
