#!/usr/bin/env python3
"""Refresh official issued shares and bond faces; legal FX/reset prices stay dated."""
import concurrent.futures,datetime as dt,gzip,hashlib,json,math,urllib.request

SOURCES={
 'TWSE_master':'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
 'TPEX_master':'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O',
 'bond_5':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data',
 'bond_6':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD6_data',
 'bond_7':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD7_data',
 'bond_8':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD8_data'}
def num(v):
    try:
        value=float(str(v).replace(',',''))
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):return None
def day(raw):
    raw=str(raw)
    if len(raw)==7:raw=str(int(raw[:3])+1911)+raw[3:]
    return dt.datetime.strptime(raw,'%Y%m%d').date()
def fetch_capital(name,url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as response:raw=response.read(8000000)
    rows=json.loads(raw.decode('utf-8-sig'));now=dt.datetime.now(dt.timezone.utc)
    if not isinstance(rows,list) or not rows:raise ValueError('CAPITAL_SOURCE_EMPTY_OR_INVALID')
    today=now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    dates={day(r.get('Date',r.get('出表日期'))) for r in rows}
    if len(dates)!=1 or max(dates)>today:raise ValueError('CAPITAL_SOURCE_MIXED_OR_FUTURE_DATE')
    if (today-max(dates)).days>7:raise ValueError('CAPITAL_SOURCE_STALE_OVER_7_DAYS')
    if name.endswith('master'):
        valid=[r for r in rows if r.get('公司代號',r.get('SecuritiesCompanyCode')) and (num(r.get('已發行普通股數或TDR原股發行股數',r.get('IssueShares'))) or 0)>0]
        if len(valid)<500:raise ValueError('CAPITAL_MASTER_IMPLAUSIBLY_SMALL_OR_SHARES_MISSING')
        codes=[r.get('公司代號',r.get('SecuritiesCompanyCode')) for r in valid]
        if len(codes)!=len(set(codes)):raise ValueError('CAPITAL_MASTER_DUPLICATE_ISSUER')
    else:
        valid=[r for r in rows if r.get('IssuerCode') and r.get('BondCode')]
        if any((r.get('BondCode') and not r.get('IssuerCode')) or
               (len(str(r.get('IssuerCode','')))==4 and not r.get('BondCode')) for r in rows):raise ValueError('CAPITAL_BOND_IDENTITY_INCOMPLETE')
        if name in ('bond_5','bond_6') and not valid:raise ValueError('EMPTY_BOND_FEED_IS_NOT_PROOF_OF_REDEMPTION')
        if any(num(r.get('OutstandingAmount')) is None or num(r['OutstandingAmount'])<0 for r in valid):raise ValueError('CAPITAL_BOND_FACE_MISSING_OR_INVALID')
        for row in valid:
            day(row['IssueDate']);day(row['MaturityDate'])
            if row.get('Currency') not in ('1','2'):raise ValueError('CAPITAL_BOND_CURRENCY_UNSUPPORTED')
        # Non-listed private issuers can both publish the placeholder code 無.
        # They are distinct issuer/instrument identities, not duplicate debt.
        codes=[(r['IssuerCode'],r['BondCode']) for r in valid]
        if len(codes)!=len(set(codes)):raise ValueError('CAPITAL_FEED_DUPLICATE_BOND')
    receipt=dict(url=url,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=now.isoformat(),date=max(dates).isoformat(),rows=len(rows))
    return name,raw,rows,receipt
def refresh_capital(e,out):
    success=[];failed=[];results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(fetch_capital,n,u):n for n,u in SOURCES.items()}
        for future in concurrent.futures.as_completed(futures):
            name=futures[future]
            try:results.append(future.result())
            except Exception as ex:failed.append(dict(kind=name,error=str(ex),retained_previous_source_date=True))
    # Each successfully parsed source is replaced independently; a failed source
    # never deletes the last known shares or pretends all debt was redeemed.
    for name,raw,rows,receipt in sorted(results):
        if name.endswith('master'):
            market=name.split('_')[0];new={}
            for r in rows:
                code=str(r.get('公司代號',r.get('SecuritiesCompanyCode')));shares=num(r.get('已發行普通股數或TDR原股發行股數',r.get('IssueShares')))
                if not code or shares is None or shares<=0:continue
                new[code]=dict(code=code,name=r.get('公司簡稱',r.get('CompanyAbbreviation')),market=market,issued_shares=shares,
                  industry_code=str(r.get('產業別',r.get('SecuritiesIndustryCode'))).zfill(2),par_value=r.get('普通股每股面額',r.get('ParValueOfCommonStock')),
                  date=r.get('出表日期',r.get('Date')),source_sha256=receipt['sha256'])
            e['master']={c:v for c,v in e.get('master',{}).items() if v['market']!=market};e['master'].update(new)
        else:
            old={b['code']:b for bs in e.get('bonds',{}).values() for b in bs};kind=name[-1];new={}
            for r in rows:
                code=r.get('IssuerCode');face=num(r.get('OutstandingAmount'));bid=r.get('BondCode')
                if not code or not bid or code not in e.get('master',{}) or face is None or face<=0:continue
                if day(r['IssueDate'])>dt.date.fromisoformat(receipt['date']):continue
                price=num(r.get('Conversion/ExchangePriceAtIssuance'));previous=old.get(bid,{})
                bond=dict(code=bid,face=face,currency='TWD' if r['Currency']=='1' else 'FOREIGN_CURRENCY_'+r['Currency'],conversion_price=price,
                  current_terms_verified=False,price_basis='ISSUE_TERMS_NOT_CURRENT_RESET',maturity=r['MaturityDate'],put_date=r.get('PutOptionDate'),
                  snapshot_date=r['Date'],bond_source_kind=kind,source_sha256=receipt['sha256'],face_is_outstanding_not_original_issue=True)
                if previous.get('price_basis') not in (None,'ISSUE_TERMS_NOT_CURRENT_RESET'):
                    for field in ['conversion_price','price_basis','terms_effective_at']: 
                        if field in previous:bond[field]=previous[field]
                # Exchangeables require the identity of the underlying security.
                if kind in ('7','8'):bond['underlying_share_identity_unresolved']=True
                new.setdefault(code,[]).append(bond)
            retained={}
            for c,bs in e.get('bonds',{}).items():
                kept=[b for b in bs if b.get('bond_source_kind',('6' if b['code'].startswith('XS') else '5'))!=kind]
                if kept:retained[c]=kept
            for c,bs in new.items():retained.setdefault(c,[]).extend(bs)
            e['bonds']=retained
        file=out/'raw'/('capital_'+name+'.gz');file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(gzip.compress(raw,mtime=0))
        receipt['path']='evidence/v880/raw/'+file.name;e.setdefault('capital_sources',{})[name]=receipt;success.append(name)
    return dict(successful_sources=success,failed_sources=failed,contract_FX_not_replaced_by_spot=True,issue_conversion_price_is_not_current_reset=True)

