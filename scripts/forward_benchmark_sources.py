#!/usr/bin/env python3
"""Collect original 0050 quotes for frozen forward cohorts, never infer returns.

Uses the existing TWSE history schedule. Unadjusted daily OHLC and total daily
turnover do not establish opening-auction capacity or dividend/split coverage.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:sys.path.insert(0,str(PACKAGE_ROOT))

from scripts.benchmark_sources import month_range
from scripts.history_archive import (archive_original, canonical, digest,
                                     frozen_forward_selections, verify_original)
from scripts.run_research_pipeline import atomic_json
from scripts.tw_history_backfill import historical_url, parse, request

SCHEMA='OFFICIAL_0050_UNADJUSTED_QUOTE_SOURCE_V1'
TAIPEI=dt.timezone(dt.timedelta(hours=8))
OUT='benchmarks/0050'


def verify_month(root,doc,month,now):
    if (doc.get('schema')!=SCHEMA or doc.get('benchmark_id')!='0050'
            or doc.get('month')!=month or doc.get('market')!='TWSE'):
        raise ValueError('ETF_QUOTE_IDENTITY_MISMATCH')
    original=doc['original_archive']
    if (original.get('identity')!='0050-'+month or original.get('market')!='TWSE'
            or original.get('source_url')!=historical_url('0050',month)):
        raise ValueError('ETF_ORIGINAL_IDENTITY_MISMATCH')
    captured=dt.datetime.fromisoformat(original['captured_at_utc'])
    if captured.tzinfo is None or captured>now:
        raise ValueError('ETF_SOURCE_CAPTURE_AFTER_ASOF_OR_NAIVE')
    checked=dt.datetime.fromisoformat(doc.get('last_source_checked_at_utc',original['captured_at_utc']))
    if checked.tzinfo is None or checked<captured or checked>now:
        raise ValueError('ETF_SOURCE_CHECK_CLOCK_INVALID')
    rows=parse(verify_original(root,original),'0050',month)
    if digest(canonical(rows))!=original['parsed_rows_sha256'] or rows!=doc.get('rows'):
        raise ValueError('ETF_NORMALIZED_ROWS_DIFFER_FROM_ORIGINAL')
    if any(dt.datetime.fromisoformat(row['close_at'])>captured for row in rows):
        raise ValueError('ETF_CLOSE_AFTER_SOURCE_CAPTURE')
    return rows


def source_current(doc,month,asof):
    if month==asof[:7]:
        return any(row['date']==asof for row in doc['rows'])
    captured=dt.datetime.fromisoformat(doc.get('last_source_checked_at_utc',
                                              doc['original_archive']['captured_at_utc']))
    # Re-fetch a prior partial month once after month end, so a final session
    # missed by the previous schedule cannot stay silently absent forever.
    return captured.astimezone(TAIPEI).strftime('%Y-%m')>month


def refresh(root,max_requests=2,fetcher=request,*,now=None):
    root=Path(root).resolve()
    fixed_clock=now is not None
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or not 0<=max_requests<=8:
        raise ValueError('ETF_INVALID_CLOCK_OR_FETCH_BUDGET')
    manifest=json.loads((root/'prices/latest_manifest.json').read_text())
    asof=manifest['date']
    dt.date.fromisoformat(asof)
    if asof>now.astimezone(TAIPEI).date().isoformat():
        raise ValueError('ETF_FUTURE_REFERENCE_DATE')
    raw=(root/'prices'/(asof+'.json')).read_bytes()
    if digest(raw)!=manifest['normalized_sha256']:
        raise ValueError('ETF_REFERENCE_PRICE_RECEIPT_MISMATCH')
    selections=frozen_forward_selections(root)
    months=set()
    for selection in selections:
        start=dt.datetime.fromisoformat(selection['next_eligible_open_only_after']).astimezone(TAIPEI)
        if start<=now:
            months.update(month_range(start.date().isoformat(),asof))
    required=sorted(months,reverse=True)
    pending_refresh=set(required)
    verified={};errors=[];attempted=0;updated=[];reused=[]
    for month in required:
        path=root/OUT/'months'/(month+'.json')
        if path.exists():
            try:
                cached=json.loads(path.read_text())
                rows=verify_month(root,cached,month,now)
                verified[month]=rows
                if source_current(cached,month,asof):
                    pending_refresh.discard(month)
                    reused.append(month)
                    continue
            except (ValueError,KeyError,TypeError,OSError,EOFError) as exc:
                errors.append(dict(month=month,stage='CACHED_SOURCE_REJECTED',reason=str(exc)))
        if attempted>=max_requests:continue
        attempted+=1
        try:
            url=historical_url('0050',month)
            original_bytes=fetcher(url)
            rows=parse(original_bytes,'0050',month)
            # Capture must follow all returned closes; never save a future quote
            # supplied by a misdated or malformed response as usable evidence.
            captured=dt.datetime.now(dt.timezone.utc)
            if any(dt.datetime.fromisoformat(row['close_at'])>captured for row in rows):
                raise ValueError('ETF_CLOSE_AFTER_SOURCE_CAPTURE')
            original=archive_original(root,'TWSE','0050-'+month,url,original_bytes,rows)
            doc=dict(schema=SCHEMA,benchmark_id='0050',market='TWSE',month=month,
                     last_source_checked_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                     original_archive=original,rows=rows,unadjusted_quotes=True,
                     total_return_verified=False,corporate_actions_verified=False,
                     opening_auction_fillability_verified=False)
            # The collector uses the actual retrieval clock, even in a dated
            # inspection. A future-captured original cannot enter that inspection.
            verify_month(root,doc,month,now if fixed_clock else dt.datetime.now(dt.timezone.utc))
            atomic_json(path,doc)
            verified[month]=rows
            if source_current(doc,month,asof):pending_refresh.discard(month)
            updated.append(month)
        except (ValueError,KeyError,TypeError,OSError,EOFError) as exc:
            errors.append(dict(month=month,stage='SOURCE_UNAVAILABLE',reason=str(exc)))
    reference_covered=any(row['date']==asof for row in verified.get(asof[:7],[]))
    report=dict(schema=SCHEMA,benchmark_id='0050',reference_price_date=asof,
                observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                frozen_monthly_cohorts=len(selections),required_months=required,
                verified_months=sorted(verified),missing_months=sorted(set(required)-set(verified)),
                reference_session_quote_present=reference_covered,
                months_needing_refresh=sorted(pending_refresh),
                verified_sessions_through_reference=sum(sum(r['date']<=asof for r in rows)
                                                        for rows in verified.values()),
                requests_attempted=attempted,updated_months=updated,reused_months=reused,
                source_errors=errors,
                status=('NO_FROZEN_COHORT' if not selections else
                        'QUOTE_SOURCES_COLLECTED_TOTAL_RETURN_PENDING' if len(verified)==len(required)
                        and not errors and reference_covered and not pending_refresh
                        else 'QUOTE_SOURCE_COLLECTION_INCOMPLETE'),
                model_or_benchmark_return_pct=None,verified_trading_results=0,
                missing_evidence=['DIVIDENDS_SPLITS_DELISTING_FULL_WINDOW_REVIEW',
                                  'NEXT_ELIGIBLE_OPEN_AND_FILLABILITY_REVIEW',
                                  'MATURED_MATCHED_NET_TOTAL_RETURN_OUTCOMES'],
                no_orders_created=True)
    atomic_json(root/OUT/'latest_source_status.json',report)
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',default='tw-market-data')
    p.add_argument('--max-requests',type=int,default=2)
    args=p.parse_args()
    print(json.dumps(refresh(args.data_root,args.max_requests),ensure_ascii=False))


if __name__=='__main__':main()
