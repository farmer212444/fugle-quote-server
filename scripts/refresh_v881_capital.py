#!/usr/bin/env python3
"""Refresh official issued shares and bond faces; legal FX/reset prices stay dated."""
import concurrent.futures,datetime as dt,gzip,hashlib,json,math,pathlib,sys,urllib.request

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from tw_model_v880.capital import parse_twd_reset

SOURCES={
 'TWSE_master':'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
 'TPEX_master':'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O',
 'bond_5':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data',
 'bond_6':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD6_data',
 'bond_7':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD7_data',
 'bond_8':'https://www.tpex.org.tw/openapi/v1/bond_ISSBD8_data'}

# An identified issue-price gap, not an assertion that all later legal terms
# have been reviewed. Capture source bytes once; never backdate first capture.
KNOWN_TWD_RESETS=(dict(issuer='5439',bond='54391',
 url='https://news.cnyes.com/news/print/6525876',
 published_at='2026-07-07T18:15:00+08:00',effective_at='2026-07-28T00:00:00+08:00',
 previous_conversion_price=300.0,conversion_price=293.6),)

def capture_known_resets(e,out):
    captured=[];existing=[];failed=[]
    for spec in KNOWN_TWD_RESETS:
        code=spec['issuer'];bid=spec['bond']
        if not any(b.get('code')==bid for b in e.get('bonds',{}).get(code,[])):continue
        folder=out/'capital_terms';ledger=folder/(code+'.json')
        # Preserve any existing issuer review and its actual first-capture clock.
        # Invalid existing receipts are quarantined by the model's normal loader.
        if ledger.exists():existing.append(code);continue
        try:
            request=urllib.request.Request(spec['url'],headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(request,timeout=25) as response:
                if response.status!=200 or response.geturl()!=spec['url']:
                    raise ValueError('CAPITAL_RESET_HTTP_OR_REDIRECT_INVALID')
                raw=response.read(1_000_001)
            if not 100<=len(raw)<=1_000_000:raise ValueError('CAPITAL_RESET_BYTES_EMPTY_OR_OVERSIZED')
            parsed=parse_twd_reset(raw,code,bid)
            if any(parsed[k]!=spec[k] for k in ('effective_at','conversion_price','previous_conversion_price')):
                raise ValueError('CAPITAL_RESET_CAPTURE_EXPECTED_FACTS_MISMATCH')
            now=dt.datetime.now(dt.timezone.utc).isoformat()
            if dt.datetime.fromisoformat(spec['published_at'])>dt.datetime.fromisoformat(now):
                raise ValueError('CAPITAL_RESET_PUBLICATION_FROM_FUTURE')
            digest=hashlib.sha256(raw).hexdigest();name=f"{bid}_{spec['effective_at'][:10]}_{digest}.html.gz"
            archive=folder/'sources'/name;archive.parent.mkdir(parents=True,exist_ok=True)
            if archive.exists():
                if gzip.decompress(archive.read_bytes())!=raw:raise ValueError('CAPITAL_RESET_EXISTING_BYTES_CONFLICT')
            else:
                with archive.open('xb') as handle:handle.write(gzip.compress(raw,mtime=0))
            source=dict(id=bid+'_reset_'+spec['effective_at'][:10],url=spec['url'],
                path='evidence/v880/capital_terms/sources/'+name,sha256=digest,
                published_at=spec['published_at'],available_at=now,fetched_at=now,
                source_record_type='ISSUER_RESET_ANNOUNCEMENT_HTML_REPUBLICATION',
                original_MOPS_filing_PIT_verified=False)
            book=dict(code=code,checked_at=now,sources=[source],formal_share_certification=False,
                bonds=[dict(code=bid,currency='TWD',conversion_price=parsed['conversion_price'],
                    effective_at=parsed['effective_at'],price_basis='DATED_RESET_REPUBLICATION_RESEARCH_ONLY',
                    source_ids=[source['id']])])
            with ledger.open('x') as handle:json.dump(book,handle,ensure_ascii=False,indent=2);handle.write('\n')
            captured.append(code)
        except (OSError,ValueError,KeyError,TypeError) as ex:
            failed.append(dict(issuer=code,bond=bid,error=str(ex),existing_terms_not_replaced=True))
    return dict(captured_issuers=captured,existing_issuer_books_preserved=existing,failed_sources=failed,
                original_filing_PIT_or_full_share_certification_granted=False)
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
    resets=capture_known_resets(e,out)
    return dict(successful_sources=success,failed_sources=failed,contract_FX_not_replaced_by_spot=True,
                issue_conversion_price_is_not_current_reset=True,dated_reset_capture=resets)

