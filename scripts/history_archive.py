"""Immutable historical exchange bytes, observed OHLC and capture clocks.

Retrieving a dated quote today proves the returned historical quote, not an
issuer's original filing time, a contemporaneous universe, or an actual fill.
"""
import datetime as dt
import gzip
import hashlib
import json
import re
import zlib
from pathlib import Path

from scripts.execution_quote_archive import execution_fields, positive

SCHEMA = 'HISTORICAL_EXCHANGE_ORIGINAL_V1'
HOST_PREFIXES = {'TWSE': 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?',
                 'TPEX': 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?'}


def outstanding_benchmark_codes(root,market):
    """Collection priority only; never substitute it for a PIT selection universe."""
    path=Path(root)/'rankings/latest_benchmark_validation.json'
    codes=[]
    rows=[]
    if path.exists():
        doc=json.loads(path.read_text())
        if doc.get('schema')!='TOP30_VS_TAIEX_TR_V1':
            raise ValueError('UNKNOWN_BENCHMARK_COLLECTION_QUEUE_SCHEMA')
        rows.extend(doc['collection_queue'])
    # The primary monthly/0050 experiment has a different selection rule from
    # the broad TAIEX diagnostic. Collect both without mixing their outcomes.
    for selection in frozen_forward_selections(root):
        rows.extend(selection['research_top30'])
    for row in rows:
        if row.get('market')!=market:continue
        code=row.get('code')
        if not isinstance(code,str) or not re.fullmatch(r'\d{4}',code):
            raise ValueError('INVALID_BENCHMARK_COLLECTION_ISSUER')
        if code not in codes:codes.append(code)
    return codes


def frozen_forward_selections(root):
    """Read immutable monthly picks, even after an issuer leaves today's quotes.

    These are collection obligations, not evidence of listing, fills or PIT.
    Keep all cohorts until a separately verified outcome can retire them.
    """
    from scripts.v8a8_forward_top30_0050 import CONFIG, OUT, SCHEMA, verify_locked, aware
    root=Path(root)
    paths=sorted((root/OUT/'monthly').glob('*.json'))
    if not paths:return []
    policy=json.loads((root/CONFIG).read_text())
    selections=[]
    for path in paths:
        doc=verify_locked(json.loads(path.read_text()),policy)
        if (doc.get('schema')!=SCHEMA or doc.get('month')!=path.stem
                or not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',path.stem)):
            raise ValueError('FROZEN_FORWARD_SELECTION_IDENTITY_MISMATCH')
        signal=aware(doc['archive_eligible_signal_at'])
        committed=aware(doc['selection_committed_at_utc'])
        entry=aware(doc['next_eligible_open_only_after'])
        if signal>committed or entry<committed:
            raise ValueError('FROZEN_FORWARD_SELECTION_CLOCK_MISMATCH')
        seen=set()
        for row in doc['research_top30']:
            key=(row.get('market'),row.get('code'))
            if (key[0] not in HOST_PREFIXES or not isinstance(key[1],str)
                    or not re.fullmatch(r'\d{4}',key[1]) or key in seen):
                raise ValueError('FROZEN_FORWARD_SELECTION_SECURITY_MISMATCH')
            seen.add(key)
        selections.append(doc)
    return selections


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()


def observed_ohlc(row, opening, high, low):
    return dict(row, high=positive(high), low=positive(low),
                **execution_fields(row['date'], opening))


def safe_path(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    result = (root / rel).resolve()
    if rel.is_absolute() or '..' in rel.parts or root not in result.parents:
        raise ValueError('HISTORY_ORIGINAL_UNSAFE_PATH')
    return result


def verify_original(root, reference):
    if not isinstance(reference, dict):
        raise ValueError('HISTORY_ORIGINAL_RECEIPT_MISSING')
    receipt = json.loads(safe_path(root, reference['receipt_path']).read_text())
    if receipt != {k: v for k, v in reference.items() if k != 'receipt_path'}:
        raise ValueError('HISTORY_ORIGINAL_RECEIPT_MISMATCH')
    if (receipt.get('schema') != SCHEMA or receipt.get('market') not in HOST_PREFIXES
            or not str(receipt.get('source_url', '')).startswith(HOST_PREFIXES[receipt['market']])):
        raise ValueError('HISTORY_ORIGINAL_SOURCE_IDENTITY_MISMATCH')
    instant = dt.datetime.fromisoformat(receipt['captured_at_utc'])
    if instant.tzinfo is None:
        raise ValueError('HISTORY_ORIGINAL_CAPTURE_TIMEZONE_REQUIRED')
    try:
        original = gzip.decompress(safe_path(root, receipt['archive_path']).read_bytes())
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError('HISTORY_ORIGINAL_COMPRESSION_CORRUPT') from exc
    if len(original) != receipt['bytes'] or digest(original) != receipt['original_response_sha256']:
        raise ValueError('HISTORY_ORIGINAL_BYTES_MISMATCH')
    json.loads(original.decode('utf-8-sig'))
    return original


def archive_original(root, market, identity, source_url, original, parsed):
    if (market not in HOST_PREFIXES or not source_url.startswith(HOST_PREFIXES[market])
            or not re.fullmatch(r'[0-9-]{4,32}', identity)):
        raise ValueError('HISTORY_ORIGINAL_INVALID_IDENTITY')
    json.loads(original.decode('utf-8-sig'))
    raw_hash, parsed_hash = digest(original), digest(canonical(parsed))
    key = digest(canonical(dict(market=market, identity=identity, source_url=source_url,
                                raw_hash=raw_hash, parsed_hash=parsed_hash)))
    folder = Path(root) / 'prices/originals/history' / market / identity
    receipt_path, archive_path = folder / (key + '.json'), folder / (raw_hash + '.json.gz')
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        reference = dict(receipt, receipt_path=receipt_path.relative_to(root).as_posix())
        if (receipt.get('original_response_sha256') != raw_hash or
                receipt.get('parsed_rows_sha256') != parsed_hash or
                receipt.get('source_url') != source_url or receipt.get('identity') != identity):
            raise ValueError('HISTORY_ORIGINAL_IMMUTABILITY_CONFLICT')
        if verify_original(root, reference) != original:
            raise ValueError('HISTORY_ORIGINAL_RECAPTURE_MISMATCH')
        return reference
    folder.mkdir(parents=True, exist_ok=True)
    packed = gzip.compress(original, mtime=0)
    if archive_path.exists() and archive_path.read_bytes() != packed:
        raise ValueError('HISTORY_ORIGINAL_IMMUTABILITY_CONFLICT')
    archive_path.write_bytes(packed)
    receipt = dict(schema=SCHEMA, market=market, identity=identity, source_url=source_url,
                   captured_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   archive_path=archive_path.relative_to(root).as_posix(),
                   original_response_sha256=raw_hash, parsed_rows_sha256=parsed_hash,
                   bytes=len(original), issuer_publication_pit_verified=False,
                   contemporaneous_universe_verified=False, fillability_verified=False)
    with receipt_path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return dict(receipt, receipt_path=receipt_path.relative_to(root).as_posix())


def quote_source_ready(root, record, verified_sources=None):
    try:
        source = record['original_archive']
        if source['original_response_sha256'] != record['original_response_sha256']:
            return False
        rows = record.get('rows') or [record.get('row', {})]
        if not rows or not all('open' in r and 'high' in r and 'low' in r for r in rows):
            return False
        key=(str(Path(root).resolve()),digest(canonical(source)))
        if verified_sources is None or key not in verified_sources:
            verify_original(root, source)
            if verified_sources is not None:verified_sources.add(key)
        return True
    except (ValueError, KeyError, TypeError, OSError, EOFError, AttributeError):
        return False
