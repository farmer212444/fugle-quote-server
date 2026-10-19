"""Dated, hash-checked legal conversion inputs. Never substitute a spot FX rate."""
import copy,gzip,hashlib,json,pathlib
from .evidence import timestamp
from .math import number

def apply_capital_terms(data,asof):
    root=data.root;cut=timestamp(asof)
    for path in sorted((root/'evidence/v880/capital_terms').glob('[0-9]*.json')):
        try:
            book=json.loads(path.read_text());code=book['code']
            if code!=path.stem:raise ValueError('CAPITAL_ISSUER_MISMATCH')
            if timestamp(book['checked_at'])>cut:raise ValueError('CAPITAL_REVIEW_FROM_FUTURE')
            sources={s['id']:s for s in book['sources']};extracted={}
            for source in sources.values():
                if timestamp(source['available_at'])>cut or timestamp(source['fetched_at'])>cut:raise ValueError('CAPITAL_SOURCE_FROM_FUTURE')
                raw_path=data.path(source['path']);packed=raw_path.read_bytes()
                raw=gzip.decompress(packed) if raw_path.suffix=='.gz' else packed
                if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('CAPITAL_SOURCE_HASH_MISMATCH')
                if source.get('source_record_type')=='NUMERIC_EXTRACTION_AND_CAPTURE_RECEIPT_NOT_ORIGINAL_DOCUMENT_BYTES':
                    record=json.loads(raw);extracted[source['id']]=record['facts']
            # Validate the entire book before mutating any bond in this issuer.
            updated=copy.deepcopy(data.evidence.get('bonds',{}).get(code,[]));by_code={b['code']:b for b in updated}
            for term in book['bonds']:
                refs=term['source_ids']
                if not refs or any(s not in sources for s in refs):raise ValueError('CAPITAL_INPUT_WITHOUT_SOURCE')
                if timestamp(term['effective_at'])>cut:continue
                bond=by_code.get(term['code'])
                if bond is None:continue  # Redeemed or no longer in the dated official feed.
                fx=number(term.get('fixed_fx_twd'));price=number(term.get('conversion_price'))
                if term['currency']!='USD' or bond['currency'] not in ('FOREIGN_CURRENCY_2','USD'):raise ValueError('CAPITAL_CURRENCY_IDENTITY_MISMATCH')
                if fx is None or fx<=0 or price is None or price<=0:raise ValueError('INVALID_CONTRACT_FX_OR_PRICE')
                if any(s in extracted for s in refs):
                    facts=[f for s in refs for f in extracted.get(s,[]) if f.get('issuer')==code and f.get('bond')==term['code']]
                    if not any(number(f.get('fixed_fx_twd_per_usd'))==fx for f in facts) or not any(number(f.get('conversion_price_twd'))==price for f in facts):raise ValueError('CAPITAL_FACT_ISSUER_BOND_OR_VALUE_MISMATCH')
                bond.update(currency='USD',fx_twd=fx,fx_basis='CONTRACT_FIXED_NOT_SPOT',conversion_price=price,conversion_price_currency='TWD',
                  price_basis=term['price_basis'],terms_effective_at=term['effective_at'],terms_checked_at=book['checked_at'],
                  current_terms_verified=False,source_ids=refs,source_receipts=[sources[s] for s in refs])
            data.evidence.setdefault('bonds',{})[code]=updated
            data.receipt(path,'DATED_LEGAL_FX_AND_CONVERSION_PRICE_RESEARCH_INPUT_NOT_FULL_SHARE_CERTIFICATION')
        except (KeyError,ValueError,OSError,TypeError) as ex:
            data.errors.append(dict(source=str(path.relative_to(root)),error=str(ex),issuer_terms_not_applied=True))

