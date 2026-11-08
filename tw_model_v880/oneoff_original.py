"""Source-pinned selected one-off gains; never certify remaining earnings quality."""
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re

from .evidence import timestamp

SCHEMA = 'SELECTED_ONEOFF_ORIGINAL_REVIEW_V1'
CONFIG = 'config/oneoff_original_v1.json'
FOLDER = 'evidence/v880/oneoff_original'
URLS = {
    '2483': 'https://www.ece.com.tw/uploads/invest/financial_report/2025/114Q4-IFRS.pdf',
    '6763': 'https://corp.ecpay.com.tw/wp-content/uploads/2026/03/%E8%B2%A1%E5%8B%99%E5%A0%B1%E8%A1%A8%E5%90%88%E4%BD%B5.pdf',
    '2331': 'https://campaign.ecs.com.tw/document/investor/doc/115_procedure_TC.pdf',
}
MAX_BYTES = 10_000_000


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def config(root):
    path = Path(root) / CONFIG
    if not path.is_file():
        return None, None
    raw = path.read_bytes()
    obj = json.loads(raw)
    if obj.get('schema') != SCHEMA or obj.get('formal_quality_pass') is not False:
        raise ValueError('ONEOFF_CONFIG_SCHEMA_OR_FALSE_CERTIFICATION')
    seen = set()
    for case in obj['cases']:
        code = case['code']
        if code in seen or code not in URLS or case['source_url'] != URLS[code]:
            raise ValueError('ONEOFF_SOURCE_OR_ISSUER_NOT_ALLOWLISTED')
        if not re.fullmatch(r'20\d{2}-Q4', case['anchor_period']):
            raise ValueError('ONEOFF_FULL_YEAR_ANCHOR_REQUIRED')
        if case.get('units') != 'TWD_THOUSANDS' or not re.fullmatch('[a-f0-9]{64}', case['pdf_sha256']):
            raise ValueError('ONEOFF_REVIEW_UNITS_OR_SHA_INVALID')
        if case.get('selected_page_visual_review') is not True:
            raise ValueError('ONEOFF_SELECTED_PAGE_REVIEW_REQUIRED')
        timestamp(case['reviewed_at'])
        seen.add(code)
    return obj, sha(raw)


def number_in_box(page, field):
    import fitz
    box = fitz.Rect(field['bbox'])
    if box.is_empty or not page.rect.contains(box):
        raise ValueError('ONEOFF_SELECTED_RECT_OUTSIDE_PAGE')
    # PDF glyph boxes can overlap the adjacent row. Select whole words by
    # their centres so a neighbouring expense's parentheses cannot invert a
    # positive subtotal when get_text(clip=...) intersects those glyphs.
    words = [w[4] for w in page.get_text('words')
             if box.contains(fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))]
    text = ' '.join(words)
    tokens = re.findall(r'[-+]?\d[\d,]*(?:\.\d+)?', text)
    if len(tokens) != 1:
        raise ValueError('ONEOFF_SELECTED_AMOUNT_AMBIGUOUS')
    value = float(tokens[0].replace(',', ''))
    if '(' in text or '（' in text:
        value = -abs(value)
    expected = field['expected_value']
    if isinstance(expected, bool) or not isinstance(expected, (int, float)) or not math.isfinite(expected):
        raise ValueError('ONEOFF_SELECTED_AMOUNT_NOT_FINITE')
    if value != expected:
        raise ValueError('ONEOFF_SELECTED_AMOUNT_CHANGED')
    return value


def inspect_pdf(raw, case):
    import fitz
    if len(raw) > MAX_BYTES or not raw.startswith(b'%PDF-') or sha(raw) != case['pdf_sha256']:
        raise ValueError('ONEOFF_ORIGINAL_PDF_SHA_OR_SIZE_MISMATCH')
    with fitz.open(stream=raw, filetype='pdf') as doc:
        if len(doc) != case['pdf_pages']:
            raise ValueError('ONEOFF_PDF_PAGE_COUNT_CHANGED')
        # The ECS meeting booklet has broken native CJK glyph mappings. Its
        # issuer, statement heading, units, year and selected CF row were
        # visually reviewed against these exact immutable bytes, not OCR guesses.
        mode = case['issuer_identity_mode']
        if mode == 'NATIVE_COVER_CODE_AND_SELECTED_PAGE_REVIEW':
            if not re.search(r'(?<!\d)' + case['code'] + r'(?!\d)', doc[0].get_text()):
                raise ValueError('ONEOFF_NATIVE_COVER_ISSUER_MISMATCH')
        elif mode != 'ECS_GLYPH_MAPPING_VISUAL_REVIEW' or case['code'] != '2331':
            raise ValueError('ONEOFF_ISSUER_REVIEW_MODE_INVALID')
        values = {}
        for name, field in case['facts'].items():
            page = field['pdf_page']
            if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= len(doc):
                raise ValueError('ONEOFF_SELECTED_PAGE_INVALID')
            values[name] = number_in_box(doc[page - 1], field)
        if values['fiscal_year_roc'] != int(case['anchor_period'][:4]) - 1911:
            raise ValueError('ONEOFF_REVIEW_FISCAL_COLUMN_MISMATCH')
        sign = case['profit_effect_multiplier']
        if sign not in (-1, 1) or isinstance(sign, bool):
            raise ValueError('ONEOFF_CASHFLOW_SIGN_INVALID')
        gain = values['selected_gain_amount'] * sign
        if gain <= 0:
            raise ValueError('ONEOFF_POSITIVE_GAIN_REQUIRED_NO_LOSS_ADDBACK')
        return dict(reported_fy_nonoperating_k=values['reported_fy_nonoperating_k'],
                    excluded_positive_gain_k=gain, selected_raw_amount=values['selected_gain_amount'])


def verify_receipt(root, case, receipt, cut=None):
    root = Path(root).resolve()
    if (receipt['code'] != case['code'] or receipt['source_url'] != case['source_url']
            or receipt['pdf_sha256'] != case['pdf_sha256']):
        raise ValueError('ONEOFF_RECEIPT_IDENTITY_MISMATCH')
    captured = timestamp(receipt['captured_at'])
    available = max(captured, timestamp(case['reviewed_at']))
    if cut is not None and available > timestamp(cut):
        raise ValueError('ONEOFF_SOURCE_AFTER_ESTIMATE')
    rel = Path(receipt['archive_path'])
    path = (root / rel).resolve()
    if rel.is_absolute() or '..' in rel.parts or root not in path.parents:
        raise ValueError('ONEOFF_ARCHIVE_UNSAFE_PATH')
    packed = path.read_bytes()
    if sha(packed) != receipt['gzip_sha256']:
        raise ValueError('ONEOFF_COMPRESSED_SHA_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        raw = stream.read(MAX_BYTES + 1)
    values = inspect_pdf(raw, case)
    return dict(values, code=case['code'], anchor_period=case['anchor_period'],
                label=case['selected_gain_label'], source_url=case['source_url'],
                pdf_sha256=case['pdf_sha256'], archive_path=receipt['archive_path'],
                selected_pdf_page=case['facts']['selected_gain_amount']['pdf_page'],
                available_at=available.isoformat(), formal_quality_pass=False,
                remaining_components_verified=False)


def load(root, asof):
    root = Path(root)
    doc, digest = config(root)
    if doc is None:
        return {}, {}, []
    path = root / FOLDER / 'manifest.json'
    if not path.is_file():
        return {}, {x['code']: dict(status='ORIGINAL_CAPTURE_PENDING', blocks_current_decision=False)
                    for x in doc['cases']}, []
    manifest = json.loads(path.read_bytes())
    if manifest.get('schema') != SCHEMA or manifest.get('formal_quality_pass') is not False:
        raise ValueError('ONEOFF_MANIFEST_SCHEMA_OR_FALSE_CERTIFICATION')
    reviews, states, errors = {}, {}, []
    for case in doc['cases']:
        code = case['code']
        try:
            rows = [x for x in manifest['captures'] if x['code'] == code]
            if len(rows) != 1 or manifest['config_sha256'] != digest:
                raise ValueError('ONEOFF_CAPTURE_OR_REVIEW_VERSION_MISMATCH')
            receipt = rows[0]
            if max(timestamp(receipt['captured_at']), timestamp(case['reviewed_at'])) > timestamp(asof):
                states[code] = dict(status='SOURCE_AVAILABLE_AFTER_ESTIMATE', blocks_current_decision=False)
                continue
            reviews[code] = verify_receipt(root, case, receipt, asof)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, EOFError) as exc:
            states[code] = dict(status='ORIGINAL_ONEOFF_REVIEW_INVALID', blocks_current_decision=True)
            errors.append(dict(source='oneoff_original:' + code, error=str(exc)))
    return reviews, states, errors
