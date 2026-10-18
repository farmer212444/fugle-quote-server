#!/usr/bin/env python3
"""Write existing audit outputs from one model engine and one hashed result."""
import argparse,gzip,hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tw_model_v880 import VERSION
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--kind',choices=['risk','cash','shares'],required=True);ap.add_argument('--data-dir',default='tw-market-data');args=ap.parse_args()
    out=pathlib.Path(args.data_dir)/'rankings';meta=json.loads((out/'latest_research.json').read_text());ref=meta['full_results'];blob=(out/ref['path']).read_bytes()
    if hashlib.sha256(blob).hexdigest()!=ref['sha256']:raise ValueError('FULL_RESULTS_HASH_MISMATCH')
    raw=gzip.decompress(blob)
    if hashlib.sha256(raw).hexdigest()!=ref['json_sha256']:raise ValueError('FULL_RESULTS_JSON_HASH_MISMATCH')
    r=json.loads(raw)
    if r['model']!=VERSION:raise ValueError('MODEL_VERSION_MISMATCH')
    rows=[]
    for x in r['all_model_rows']:
        if 'base' not in x:continue
        row={k:x[k] for k in ['code','name','industry','financial_period','status','formal_Aplus','formal_Aplusplus','warning_flags','reference_close','scenario_upside_pct','certification','source_tier']}
        if args.kind=='cash':row.update(cash=x['liquidity'],primary_ttm_cash=x['primary_ttm_cash'])
        elif args.kind=='shares':row.update(share_bridge=x['share_bridge'])
        else:row.update(liquidity=x['liquidity'],business_profile=x['business_profile'],specialist_requirements=x['specialist_model_requirements'])
        rows.append(row)
    stem={'risk':'latest_risk_overlay','cash':'latest_cash_quality','shares':'latest_share_audit'}[args.kind]
    obj=dict(model=VERSION+' '+args.kind+' evidence audit',asof_price_date=r['asof_price_date'],estimate_vintage=r['estimate_vintage'],financial_last_quarter=r['financial_last_quarter'],
      formal_Aplus_count=r['formal_Aplus_count'],formal_Aplusplus_count=r['formal_Aplusplus_count'],source_model_code_sha256=r['model_code_sha256'],rows=rows,
      research_upside_ge25_detail=[{k:x[k] for k in ('code','name','scenario_upside_pct','status','formal_Aplus')} for x in rows if x['scenario_upside_pct'] is not None and x['scenario_upside_pct']>=25],
      interpretation='Unknown evidence is pending; negative OCF is not automatic failure; no trade instruction',backtest=r['backtest'])
    (out/(stem+'.json')).write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n')
    (out/(stem+'.md')).write_text(f"# {obj['model']}\n\n財報 {r['financial_last_quarter']}；價格 {r['asof_price_date']}。\n\n正式A+ {r['formal_Aplus_count']}、A++ {r['formal_Aplusplus_count']}。逐檔證據與未決門檻請見同名JSON。\n")
    print(json.dumps(dict(kind=args.kind,rows=len(rows),model=VERSION)))
if __name__=='__main__':main()
