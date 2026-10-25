"""Dated, hash-checked legal conversion inputs. Never substitute a spot FX rate."""
import copy,gzip,hashlib,json,pathlib,re
from html.parser import HTMLParser
from .evidence import timestamp
from .math import number

class _AnnouncementText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,value):
        if not self.hidden:self.parts.append(value)

def parse_twd_reset(raw,issuer,bond):
    """Read one issuer/bond reset paragraph; ignore scripts and related news."""
    parser=_AnnouncementText();parser.feed(raw.decode('utf-8-sig'))
    body=re.sub(r'\s+','',''.join(parser.parts)).split('推薦新聞')[0]
    ordinal={'1':'一','2':'二'}.get(bond[len(issuer):]) if bond.startswith(issuer) else None
    if not ordinal:raise ValueError('CAPITAL_RESET_BOND_RECIPE_UNSUPPORTED')
    # Bond price anti-dilution notices use a different, structured layout from
    # issuer material-information paragraphs. Bind title, body and instrument
    # field, rather than using an unrelated issuer ticker elsewhere on a page.
    title=(r'公告[^()（）:：]{1,80}國內第'+ordinal+r'次無擔保轉換公司債[（(]'
           r'簡稱[：:][^()（）]{1,40}[，,]代碼[：:]'+re.escape(bond)+r'[）)]'
           r'自(\d{3})年(\d{1,2})月(\d{1,2})日起[，,]轉換價格自([\d.]+)元調整為([\d.]+)元')
    titles={m.groups() for m in re.finditer(title,body)}
    if titles:
        measures=(r'因應措施[：:][^:：]{0,500}?故自(\d{3})年(\d{1,2})月(\d{1,2})日起[，,]'
                  r'轉換價格由([\d.]+)元調整為([\d.]+)元')
        paragraphs={m.groups() for m in re.finditer(measures,body)}
        identities=re.findall(r'債券代碼[：:]([0-9A-Z]+)',body)
        dates=re.findall(r'事實發生日起始日[：:](\d{8})',body)
        if len(titles)!=1 or paragraphs!=titles or identities!=[bond] or len(dates)!=1:
            raise ValueError('CAPITAL_RESET_STRUCTURED_FIELDS_CONFLICT')
        year,month,day,old,new=next(iter(titles))
        effective=f'{int(year)+1911:04d}-{int(month):02d}-{int(day):02d}T00:00:00+08:00'
        timestamp(effective)
        if dates[0]!=effective[:10].replace('-','') or float(old)<=0 or float(new)<=0:
            raise ValueError('CAPITAL_RESET_STRUCTURED_DATE_OR_PRICE_INVALID')
        return dict(conversion_price=float(new),previous_conversion_price=float(old),effective_at=effective)
    if not re.search(r'\('+re.escape(issuer)+r'\)',body):raise ValueError('CAPITAL_RESET_ISSUER_NOT_IN_ANNOUNCEMENT')
    pattern=(r'本公司自(\d{3})年(\d{1,2})月(\d{1,2})日.*?本公司國內第'+ordinal+
             r'次無擔保轉換公司債之轉換價格由每股新台幣([\d.]+)元調整為新台幣([\d.]+)元')
    matches=list(re.finditer(pattern,body))
    if len(matches)!=1:raise ValueError('CAPITAL_RESET_PARAGRAPH_NOT_UNIQUE')
    year,month,day,old,new=matches[0].groups()
    effective=f'{int(year)+1911:04d}-{int(month):02d}-{int(day):02d}T00:00:00+08:00'
    timestamp(effective)
    return dict(conversion_price=float(new),previous_conversion_price=float(old),effective_at=effective)

def apply_capital_terms(data,asof):
    root=data.root;cut=timestamp(asof)
    for path in sorted((root/'evidence/v880/capital_terms').glob('[0-9]*.json')):
        try:
            book=json.loads(path.read_text());code=book['code']
            if code!=path.stem:raise ValueError('CAPITAL_ISSUER_MISMATCH')
            if timestamp(book['checked_at'])>cut:raise ValueError('CAPITAL_REVIEW_FROM_FUTURE')
            sources={s['id']:s for s in book['sources']};extracted={};raw_sources={}
            if len(sources)!=len(book['sources']):raise ValueError('CAPITAL_DUPLICATE_SOURCE')
            for source in sources.values():
                if timestamp(source['available_at'])>cut or timestamp(source['fetched_at'])>cut:raise ValueError('CAPITAL_SOURCE_FROM_FUTURE')
                raw_path=data.path(source['path']);packed=raw_path.read_bytes()
                raw=gzip.decompress(packed) if raw_path.suffix=='.gz' else packed
                if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('CAPITAL_SOURCE_HASH_MISMATCH')
                raw_sources[source['id']]=raw
                data.receipt(raw_path,'CAPITAL_LINKED_SOURCE_BYTES_RECHECKED_NOT_FULL_SHARE_CERTIFICATION')
                if source.get('source_record_type')=='NUMERIC_EXTRACTION_AND_CAPTURE_RECEIPT_NOT_ORIGINAL_DOCUMENT_BYTES':
                    record=json.loads(raw);extracted[source['id']]=record['facts']
            # Validate the entire book before mutating any bond in this issuer.
            updated=copy.deepcopy(data.evidence.get('bonds',{}).get(code,[]));by_code={b['code']:b for b in updated}
            if len({t['code'] for t in book['bonds']})!=len(book['bonds']):raise ValueError('CAPITAL_DUPLICATE_BOND_TERM')
            for term in book['bonds']:
                refs=term['source_ids']
                if not refs or any(s not in sources for s in refs):raise ValueError('CAPITAL_INPUT_WITHOUT_SOURCE')
                if timestamp(term['effective_at'])>cut:continue
                bond=by_code.get(term['code'])
                if bond is None:continue  # Redeemed or no longer in the dated official feed.
                fx=number(term.get('fixed_fx_twd'));price=number(term.get('conversion_price'))
                if term['currency']=='TWD':
                    if bond['currency']!='TWD':raise ValueError('CAPITAL_CURRENCY_IDENTITY_MISMATCH')
                    if price is None or price<=0:raise ValueError('INVALID_CONVERSION_PRICE')
                    parsed=[parse_twd_reset(raw_sources[s],code,term['code']) for s in refs
                            if sources[s].get('source_record_type')=='ISSUER_RESET_ANNOUNCEMENT_HTML_REPUBLICATION']
                    if not parsed or any(p['conversion_price']!=price or timestamp(p['effective_at'])!=timestamp(term['effective_at']) for p in parsed):
                        raise ValueError('CAPITAL_RESET_FACT_OR_EFFECTIVE_DATE_MISMATCH')
                    known=bond.get('terms_effective_at')
                    if known and timestamp(known)>timestamp(term['effective_at']):continue
                    if known and timestamp(known)==timestamp(term['effective_at']) and number(bond.get('conversion_price'))!=price:
                        raise ValueError('CAPITAL_RESET_SAME_DATE_CONFLICT')
                    bond.update(conversion_price=price,conversion_price_currency='TWD',price_basis=term['price_basis'],
                                terms_effective_at=term['effective_at'],terms_checked_at=book['checked_at'],
                                current_terms_verified=False,source_ids=refs,source_receipts=[sources[s] for s in refs])
                    continue
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

