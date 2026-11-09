#!/usr/bin/env python3
"""Capture only reviewed, pinned issuer PDF sources before one-off adjustments."""
import argparse
import concurrent.futures
import datetime as dt
import gzip
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.early_bulk_earnings import fetch_bytes
from scripts.run_research_pipeline import atomic_json
from tw_model_v880.oneoff_original import (FOLDER, MAX_BYTES, SCHEMA, config,
                                           case_sha, inspect_pdf, load, sha, verify_receipt)


def capture(root, case, previous):
    old = next((x for x in previous if x['code'] == case['code'] and x['pdf_sha256'] == case['pdf_sha256']), None)
    if old:
        # Reparse the pinned original before upgrading a legacy receipt. A
        # review amendment may change the case hash, never the capture clock.
        existing = dict(old)
        existing.pop('review_case_sha256', None)
        verify_receipt(root, case, existing)
        return dict(existing, review_case_sha256=case_sha(case))
    request = urllib.request.Request(case['source_url'], headers={'User-Agent': 'Mozilla/5.0 (financial original review)'})
    raw = fetch_bytes(request, MAX_BYTES + 1, 25, expected_url=case['source_url'])
    inspect_pdf(raw, case)
    packed = gzip.compress(raw, mtime=0)
    path = root / FOLDER / case['code'] / (sha(raw) + '.pdf.gz')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(packed)
    receipt = dict(code=case['code'], source_url=case['source_url'], pdf_sha256=sha(raw),
                   gzip_sha256=sha(packed), bytes=len(raw), archive_path=path.relative_to(root).as_posix(),
                   captured_at=dt.datetime.now(dt.timezone.utc).isoformat())
    receipt['review_case_sha256'] = case_sha(case)
    verify_receipt(root, case, receipt)
    return receipt


def verify_offline(root, asof):
    reviews, states, errors = load(root, asof)
    incomplete = bool(errors or any(x.get('blocks_current_decision') for x in states.values()))
    return dict(status='SELECTED_ONEOFF_ORIGINALS_INCOMPLETE' if incomplete else 'SELECTED_ONEOFF_ORIGINALS_CHECKED_NO_CERTIFICATES_ISSUED',
                verified_issuers=sorted(reviews), states=states, errors=errors,
                formal_quality_pass=False), int(incomplete)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT / 'tw-market-data')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    doc, digest = config(root)
    if doc is None:
        print('NO_SELECTED_ONEOFF_REVIEW_CONFIG')
        return 0
    path = root / FOLDER / 'manifest.json'
    old = json.loads(path.read_bytes()) if path.is_file() else {}
    if args.offline:
        report, status = verify_offline(root, dt.datetime.now(dt.timezone.utc).isoformat())
        print(json.dumps(report))
        return status
    captures, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(capture, root, c, old.get('captures', [])): c for c in doc['cases']}
        for job, case in jobs.items():
            try:
                captures.append(job.result())
            except Exception as exc:
                errors.append(dict(code=case['code'], error=str(exc)))
    if errors:
        print(json.dumps(dict(status='ONEOFF_CAPTURE_FAILED_PREVIOUS_MANIFEST_RETAINED', errors=errors)))
        return 1
    atomic_json(path, dict(schema=SCHEMA, config_sha256=digest, captures=captures,
                           formal_quality_pass=False, historical_PIT_verified=False))
    print(json.dumps(dict(status='SELECTED_ONEOFF_ORIGINALS_CAPTURED', issuers=len(captures), formal_Aplus_added=0)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
