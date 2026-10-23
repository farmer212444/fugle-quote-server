#!/usr/bin/env python3
"""Rebuild the dated footwear comparison after production valuation."""
import gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tw_model_v880.data import MarketData
from tw_model_v880.footwear_review import build_review,markdown
from scripts.run_research_pipeline import atomic_json

def main():
    root=ROOT/'tw-market-data';rankings=root/'rankings'
    full=json.loads(gzip.decompress((rankings/'v880_full_results.json.gz').read_bytes()))
    data=MarketData(root,full['estimate_vintage'])
    for row in full['all_model_rows']:
        if row['code']=='6890':row['_official_current_values']=data.detailed_values((row['market'],row['code']),data.period)
    config=json.loads((root/'config/footwear_research_v1.json').read_text())
    report=build_review(root,full,config)
    atomic_json(rankings/'latest_footwear_review.json',report)
    (rankings/'latest_footwear_review.md').write_text(markdown(report))
    print(json.dumps({r['code']:{'status':r['status'],'error':r.get('error')} for r in report['companies']},ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
