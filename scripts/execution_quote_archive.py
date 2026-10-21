"""Preserve original quotes and observed opens for prospective execution research."""
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path


def positive(raw):
    if raw is None or isinstance(raw,bool):return None
    try:value=float(str(raw).replace(',','').strip())
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and value>0 else None


def execution_fields(day,opening):
    dt.date.fromisoformat(day)
    return dict(open=positive(opening),open_at=day+'T09:00:00+08:00',close_at=day+'T13:30:00+08:00',
                fillability_verified=False,
                session_times_are_scheduled_not_broker_fills=True)


def add_execution_fields(row,record,market):
    # Missing original fields stay missing; close is never substituted for open.
    key='OpeningPrice' if market=='TWSE' else 'Open' if market=='TPEX' else None
    if key is None:raise ValueError('UNKNOWN_EXECUTION_QUOTE_MARKET')
    return dict(row,**execution_fields(row['date'],record.get(key)))


def persist_price_originals(output,raw_dir,day,normalized_sha256,raw_hashes,source_urls):
    output,raw_dir=Path(output),Path(raw_dir)
    dt.date.fromisoformat(day)
    identity=dict(date=day,normalized_sha256=normalized_sha256,raw_hashes=raw_hashes,sources=source_urls)
    short=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
    folder=output/'originals'/day
    receipt_path=folder/(short+'.json')
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text())
        if receipt.get('identity')!=identity:raise ValueError('PRICE_ORIGINAL_RECEIPT_IDENTITY_CONFLICT')
        for item in receipt['raw_archives'].values():
            rel=Path(item['path']);original=(output/rel).resolve()
            if rel.is_absolute() or '..' in rel.parts or output.resolve() not in original.parents:
                raise ValueError('PRICE_ORIGINAL_ARCHIVE_UNSAFE_PATH')
            packed=original.read_bytes()
            if hashlib.sha256(gzip.decompress(packed)).hexdigest()!=item['original_sha256']:
                raise ValueError('PRICE_ORIGINAL_ARCHIVE_TAMPERED')
        return receipt_path
    available={hashlib.sha256(p.read_bytes()).hexdigest():p for p in raw_dir.glob('*.json')}
    payloads={}
    for market,digest in raw_hashes.items():
        if digest not in available:raise ValueError('PRICE_ORIGINAL_SOURCE_BYTES_MISSING_'+market)
        raw=available[digest].read_bytes();json.loads(raw.decode('utf-8-sig'))
        payloads[market]=raw
    folder.mkdir(parents=True,exist_ok=True)
    archives={}
    for market,raw in payloads.items():
        digest=raw_hashes[market];path=folder/(market+'_'+digest+'.json.gz')
        packed=gzip.compress(raw,mtime=0)
        if path.exists() and path.read_bytes()!=packed:raise ValueError('PRICE_ORIGINAL_IMMUTABILITY_CONFLICT')
        path.write_bytes(packed)
        archives[market]=dict(path=path.relative_to(output).as_posix(),original_sha256=digest,bytes=len(raw))
    receipt=dict(schema='V810_DURABLE_ORIGINAL_EXCHANGE_QUOTES_NOT_EXECUTION_CERTIFICATE',
                 captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),identity=identity,
                 raw_archives=archives,fillability_verified=False,corporate_actions_verified=False)
    with receipt_path.open('x',encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2);stream.write('\n')
    return receipt_path
