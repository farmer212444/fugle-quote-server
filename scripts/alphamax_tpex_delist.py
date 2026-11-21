#!/usr/bin/env python3
"""Official TPEx terminated-OTC-company historical research probe."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from alphamax.tpex_delist_ledger import capture_tpex_delist

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",type=Path,default=ROOT/"alphamax-tpex-delist-capture")
    parser.add_argument("--page-limit",type=int,default=15)
    args=parser.parse_args()
    report=capture_tpex_delist(args.output_dir,page_limit=args.page_limit)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2))
    # A blocked source probe is an admissible research status, not proof
    # that a live stock-picking system is working.
    return 0

if __name__=="__main__":
    raise SystemExit(main())
