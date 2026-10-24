#!/usr/bin/env python3
"""0056 constituents intersect frozen current V8.10.x 2027 valuation, no backtest.

The 0056 membership is an explicitly dated public secondary snapshot, NOT
the model's historical point-in-time 0056 eligibility and NOT proof of alpha.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

HOLDING_PATH='config/0056_holdings_2026-10-22.json'
RESEARCH_PATH='rankings/latest_research.json'
FULL_PATH='rankings/v880_full_results.json.gz'
SCHEMA='0056_RESEARCH_SNAPSHOT_FROM_PUBLIC_SECONDARY_SOURCES_V1'


def load_inputs(root):
    root=Path(root)
    cfg=json.loads((root/HOLDING_PATH).read_text(encoding='utf-8'))
    compact=json.loads((root/RESEARCH_PATH).read_text(encoding='utf-8'))
    packed=(root/FULL_PATH).read_bytes()
    digest=hashlib.sha256(packed).hexdigest()
    expected=(compact.get('full_results') or {}).get('sha256')
    if not expected or expected!=digest:
        raise ValueError('0056_FULL_MODEL_BINARY_SHA_OR_VINTAGE_MISMATCH')
    full=json.loads(gzip.decompress(packed).decode('utf-8'))
    if (full.get('estimate_vintage')!=compact.get('estimate_vintage') or
        full.get('asof_price_date')!=compact.get('asof_price_date') or
        full.get('target_date')!='2027-12-31'):
        raise ValueError('0056_MODEL_PERIOD_OR_ARCHIVE_MISMATCH')
    return cfg,compact,full


def filter_top10(cfg,full):
    rows=cfg.get('positions')
    if (cfg.get('schema')!=SCHEMA or cfg.get('etf')!='0056'
        or cfg.get('asof_date')!='2026-10-22' or
        cfg.get('historical_pit_not_certified') is not True
        or not isinstance(rows,list) or len(rows)!=50):
        raise ValueError('0056_HOLDINGS_IDENTITY_OR_COVERAGE_INVALID')
    holdings={}
    for p in rows:
        code=p.get('code');weight=p.get('weight_pct')
        if (not isinstance(code,str) or len(code)!=4 or not code.isdecimal()
            or code in holdings or not isinstance(weight,(int,float))
            or isinstance(weight,bool) or weight<=0):
            raise ValueError('0056_DUPLICATED_OR_BAD_POSITION')
        holdings[code]=p
    stock_records={}
    for row in full.get('all_model_rows',[]):
        code=row.get('code')
        if code in holdings:
            if row.get('market')!='TWSE' or code in stock_records:
                raise ValueError('0056_EXPECTED_SINGLE_LISTED_ISSUER')
            stock_records[code]=row
    matched=[];unrankable=[];absent=[]
    for code,p in holdings.items():
        row=stock_records.get(code)
        if row is None:
            absent.append(dict(code=code,etf_name=p['name']))
            continue
        b=row.get('base') or {}
        close=row.get('reference_close')
        if (not row.get('rankable') or not isinstance(close,(float,int))
            or close<=0 or not all(isinstance(b.get(k),(float,int)) for k in
                                ('eps','pe','target_price','price_upside_pct'))):
            unrankable.append(dict(code=code,name=p['name'],
                reason=row.get('exclusion_reasons'),status=row.get('status')))
            continue
        # Check that 'upside' is a *price* scenario vs official dated close,
        # not a dividend-inclusive or realized return.
        if abs(100*(b['target_price']/close-1)-b['price_upside_pct'])>0.015:
            raise ValueError('0056_BASE_PRICE_UPSIDE_NOT_RECONCILED_'+code)
        matched.append(dict(code=code,name=p['name'],etf_weight_pct=p['weight_pct'],
            price_ntd=close,forward_2027_eps=b['eps'],reasonable_pe=b['pe'],
            base_target_ntd=b['target_price'],potential_price_upside_pct=b['price_upside_pct'],
            model_source_tier=row.get('source_tier'),
            original_current_issuer_numeric_checked=bool(row.get('original_current_issuer_numeric_checked')),
            formal_Aplus=bool(row.get('formal_Aplus')),
            quality_pending_count=len((row.get('certification') or {}).get('gates_pending',[])),
            governance_review_blocked=bool(row.get('recommendation_blocked'))))
    matched.sort(key=lambda x:(-x['potential_price_upside_pct'],x['code']))
    return dict(etf='0056',etf_holdings_date=cfg['asof_date'],
      asof_price_date=full['asof_price_date'],
      estimate_vintage=full['estimate_vintage'],target_date=full['target_date'],
      model=full.get('model'),holdings_count=len(holdings),
      model_matched_count=len(stock_records),rankable_count=len(matched),
      unrankable_count=len(unrankable),absent_count=len(absent),
      top10=matched[:10],all_ranked=matched,unrankable=unrankable,absent=absent,
      is_price_upside_not_total_return=True,
      future_dividends_excluded_not_imputed_zero=True,
      official_primary_holdings_source_not_certified=True,
      price_model_alpha_vs_etf_unverified=True,
      formal_Aplus_count_in_filtered_top10=sum(x['formal_Aplus'] for x in matched[:10]))


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('--root',type=Path,default=Path('tw-market-data'))
    cli.add_argument('--print-json',action='store_true')
    cli.add_argument('--out',type=Path)
    a=cli.parse_args()
    data=filter_top10(*[None,None]) if False else None
    config,_,full=load_inputs(a.root)
    data=filter_top10(config,full)
    if a.out:
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.print_json:
        concise={k:data[k] for k in ('etf','etf_holdings_date','asof_price_date',
          'estimate_vintage','model','holdings_count','model_matched_count',
          'rankable_count','unrankable_count','absent_count','top10','unrankable','absent')}
        print('BEGIN_0056_2027_TOP10='+json.dumps(concise,ensure_ascii=False,separators=(',',':')))
    else:
        for i,r in enumerate(data['top10'],1):
            print(i,r['code'],r['name'],f"{r['forward_2027_eps']:.2f}",
                  f"{r['reasonable_pe']:.2f}",f"{r['base_target_ntd']:.2f}",
                  f"{r['potential_price_upside_pct']:+.1f}%")


if __name__=='__main__':
    main()
