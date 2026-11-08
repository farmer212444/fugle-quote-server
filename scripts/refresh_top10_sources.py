#!/usr/bin/env python3
"""Recheck newly ranked issuers before publishing a bounded current Top10."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tw_model_v880.early_bulk import FOLDER


def reconcile(root, refresh, rerun, max_passes=3):
    if isinstance(max_passes, bool) or not isinstance(max_passes, int) or not 1 <= max_passes <= 5:
        raise ValueError('TOP10_REFRESH_BOUND_INVALID')
    root = Path(root)
    for count in range(max_passes + 1):
        ranking = json.loads((root / 'rankings/latest_research.json').read_bytes())
        codes = {x['code'] for x in ranking['top10_market_research']}
        if not codes:
            raise ValueError('TOP10_EMPTY_CANNOT_VERIFY_SOURCE_SCOPE')
        path = root / FOLDER / 'manifest.json'
        manifest = json.loads(path.read_bytes()) if path.is_file() else {}
        seen = {x['code'] for x in manifest.get('requested_issuers', [])}
        missing = codes - seen
        if not missing:
            return dict(status='CURRENT_TOP10_INCLUDED_IN_CAPTURE_SCOPE', source_refreshes=count,
                        codes=sorted(codes), formal_quality_pass=False,
                        no_match_is_not_proof_of_no_announcement=True)
        if count == max_passes:
            raise ValueError('TOP10_SOURCE_SCOPE_NOT_STABLE_WITHIN_BOUND:' + ','.join(sorted(missing)))
        # Keep every previously observed issuer. Falling out of the Top10 must
        # not erase its admitted quarter and make it re-enter on older numbers.
        refresh(sorted(seen | codes))
        rerun()
    raise AssertionError('unreachable')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-passes', type=int, default=3)
    args = parser.parse_args()
    root = ROOT / 'tw-market-data'
    def refresh(codes):
        subprocess.run([sys.executable, str(ROOT / 'scripts/early_bulk_earnings.py'),
                        '--root', str(root), '--codes', *codes], cwd=ROOT, check=True)
    def rerun():
        subprocess.run([sys.executable, str(ROOT / 'scripts/run_research_pipeline.py'),
                        '--phase', 'core'], cwd=ROOT, check=True)
    result = reconcile(root, refresh, rerun, args.max_passes)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
