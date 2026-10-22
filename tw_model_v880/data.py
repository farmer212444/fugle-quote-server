"""Dynamic periods, source receipts, and isolated issuer/source failures."""
import datetime as dt,gzip,hashlib,json,pathlib
from .evidence import timestamp
from .math import number,quarter_key,quarter_end,previous_periods
def read(p):return json.loads(pathlib.Path(p).read_text())
def sha(b):return hashlib.sha256(b).hexdigest()
SOURCE_JSON_PATTERNS=('evidence/v880/certificates/*.json','evidence/v880/issuer_bridges/*.json',
    'evidence/v880/matched_peers/*.json','evidence/v880/capital_terms/*.json',
    'evidence/v880/originals/*/manifest.json')

def source_ledgers(root):
    return sorted({p for pattern in SOURCE_JSON_PATTERNS for p in root.glob(pattern)})

def nested_records(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from nested_records(child)
    elif isinstance(value,list):
        for child in value:yield from nested_records(child)

def model_source_state(root):
    """Inventory dynamic inputs and linked bytes, including currently missing files.

    Old consumption receipts alone cannot discover a newly added statement or a
    repaired source that the previous run could not consume.
    """
    root=pathlib.Path(root).resolve()
    required=('prices/latest_manifest.json','fundamentals/latest_scan.json','latest_manifest.json','evidence/v880/manifest.json')
    state={name:sha((root/name).read_bytes()) for name in required}
    paths=set(source_ledgers(root))
    for pattern in ('financial_history/*/*_income_shard*.json','*-12/revenue_*.json'):
        paths.update(root.glob(pattern))
    paths.update(p for p in (root/'fundamentals').glob('*/*_*.json')
                 if p.name in ('TWSE_income.json','TPEX_income.json','TWSE_cashflow.json','TPEX_cashflow.json'))
    for ledger in source_ledgers(root):
        try:document=read(ledger)
        except (ValueError,OSError):continue  # Content hash still invalidates the cache; loader isolates the error.
        for item in nested_records(document):
            rel=item.get('archive_path') or (item.get('path') if 'sha256' in item else None)
            if not isinstance(rel,str) or not rel:continue
            rel=pathlib.Path(rel)
            if rel.parts and rel.parts[0]==root.name:rel=pathlib.Path(*rel.parts[1:])
            target=(root/rel).resolve()
            if rel.is_absolute() or '..' in rel.parts or root not in target.parents:
                raise ValueError('SOURCE_STATE_UNSAFE_ARCHIVE_PATH')
            paths.add(target)
    for path in sorted(paths):
        state[path.relative_to(root).as_posix()]=sha(path.read_bytes()) if path.is_file() else None
    return state
def ensure_vintage(e,asof):
    cut=timestamp(asof)
    if timestamp(e['snapshot_available_at'])>cut:raise ValueError('EVIDENCE_VINTAGE_FROM_FUTURE')
    times=[e.get('last_public_refresh',{}).get('at')]+[v.get('fetched_at') for v in e.get('official_current_bulk',{}).values()]+[v.get('fetched_at') for v in e.get('capital_sources',{}).values()]
    if any(timestamp(t)>cut for t in times if t):raise ValueError('EVIDENCE_COMPONENT_VINTAGE_FROM_FUTURE')
class MarketData:
    def __init__(self,root,asof):
        self.root=pathlib.Path(root).resolve();self.asof=dt.date.fromisoformat(asof[:10]);self.errors=[];self.input_receipts=[]
        self.fm=read(self.root/'fundamentals/latest_scan.json');self.period=self.fm['last_eligible_quarter']
        if quarter_end(self.period)>self.asof:raise ValueError('FUTURE_FINANCIAL_PERIOD')
        self.required_periods=previous_periods(self.period)
        self.pm=read(self.root/'prices/latest_manifest.json');self.price_date=self.pm['date']
        if self.price_date>asof[:10]:raise ValueError('FUTURE_REFERENCE_PRICE')
        if (self.asof-dt.date.fromisoformat(self.price_date)).days>7:raise ValueError('REFERENCE_PRICE_STALE_OVER_7_DAYS')
        prices=self.checked(self.pm['path'],self.pm['normalized_sha256'])
        if not prices or any(p['date']!=self.price_date for p in prices):raise ValueError('MIXED_PRICE_DATES')
        self.prices={(r['market'],r['code']):r for r in prices}
        self.rm=read(self.root/'latest_manifest.json');self.revenue_month=self.rm['period']
        if self.revenue_month>asof[:7]:raise ValueError('FUTURE_REVENUE_MONTH')
        self.revenue={};self.annual_monthly={}
        for s in self.rm['shards']:
            try:
                for r in self.checked(s['path'],s['sha256']):self.revenue[r['code']]=r
            except (ValueError,OSError) as e:self.errors.append(dict(source=s['path'],error=str(e)))
        for p in self.root.glob('*-12/revenue_*.json'):
            try:
                year=int(p.parent.name[:4])
                if year>=self.asof.year:continue
                self.receipt(p,'DATED_DECEMBER_MONTHLY_REVENUE_BRIDGE_NOT_AUDITED_ANNUAL')
                for row in read(p):
                    d=str(row.get('batch_date',''));release=f'{int(d[:3])+1911}-{d[3:5]}-{d[5:7]}' if len(d)==7 else d
                    if release and release<=asof[:10] and str(row.get('report_month','')).endswith('12'):
                        value=number(row.get('ytd_revenue_k'))
                        if value is not None:self.annual_monthly[(row['code'],year)]=value
            except (ValueError,OSError,TypeError):continue
        self.history={};self.cash={}
        for p in sorted((self.root/'fundamentals').glob('*/*_*.json')):
            if p.name not in ('TWSE_income.json','TPEX_income.json','TWSE_cashflow.json','TPEX_cashflow.json'):continue
            try:
                self.receipt(p,'NORMALIZED_MIRROR_NOT_INDEPENDENT_ORIGIN_PROOF');j=read(p);period=j['period'];market=j['market']
                if quarter_end(period)>self.asof:continue
                if p.parent.name!=period or not p.name.startswith(market+'_'):raise ValueError('STATEMENT_IDENTITY_MISMATCH')
                target=self.cash if j['kind']=='cashflow' else self.history;seen=set();batch=[]
                for row in j['rows']:
                    key=(market,str(row['code']))
                    if key in seen:raise ValueError('DUPLICATE_ISSUER_PERIOD')
                    seen.add(key);batch.append((key,row))
                for key,row in batch:target.setdefault(key,{})[period]=row
            except (ValueError,KeyError,OSError) as e:self.errors.append(dict(source=str(p.relative_to(self.root)),error=str(e)))
        self.evidence={};self.bulk={};self.detailed={}
        manifest=self.root/'evidence/v880/manifest.json'
        if manifest.exists():
            m=read(manifest);packed=self.path(m['path']).read_bytes()
            if sha(packed)!=m['gzip_sha256']:raise ValueError('EVIDENCE_SNAPSHOT_HASH_MISMATCH')
            raw=gzip.decompress(packed)
            if sha(raw)!=m['json_sha256']:raise ValueError('EVIDENCE_JSON_HASH_MISMATCH')
            self.evidence=json.loads(raw)
            ensure_vintage(self.evidence,asof);self.receipt(self.path(m['path']),'HASHED_ORIGINAL_EVIDENCE_ADAPTER_NOT_FULL_CERTIFICATION')
            for name,obj in self.evidence.get('official_current_bulk',{}).items():
                if obj['period']!=self.period:continue
                market,kind=name.split('_')
                for r in obj['rows']:
                    ry=int(r['年度']);ry=ry+1911 if ry<1911 else ry
                    if f"{ry}-Q{int(r['季別'])}"!=self.period:raise ValueError('OFFICIAL_ROW_PERIOD_MISMATCH')
                    self.bulk[(market,r['公司代號'],kind)]=r
        for p in sorted((self.root/'financial_history').glob('*/*_income_shard*.json')):
            y,q=quarter_key(p.parent.name);period=f'{y}-Q{q}';market=p.name.split('_')[0]
            if quarter_end(period)>self.asof:continue
            self.receipt(p,'RAW_UNVERIFIED_HISTORICAL_DETAIL')
            for row in read(p).get('rows',[]):
                if len(row.get('headers',[]))!=len(row.get('cells',[])):continue
                key=(market,row['code'],period)
                if key not in self.detailed:self.detailed[key]=dict(zip(row['headers'],row['cells']))
        for folder,target in [('certificates','certificates'),('issuer_bridges','issuer_operating_bridges'),('matched_peers','matched_peers')]:
            for p in sorted((self.root/'evidence/v880'/folder).glob('[0-9]*.json')):
                try:
                    obj=read(p);code=obj['code']
                    if p.stem!=code:raise ValueError('EVIDENCE_LEDGER_ISSUER_MISMATCH')
                    if target=='certificates':
                        from .evidence import verify_certificate_archives
                        verify_certificate_archives(obj,self.root)
                        for item in obj['gates'].values():
                            for source in item['sources']:
                                self.receipt(self.path(source['archive_path']),'CERTIFICATE_ORIGINAL_BYTES_RECHECKED')
                    self.receipt(p,'DATED_ISSUER_LEDGER_WITH_SEPARATE_ORIGINAL_SOURCE_REVIEW')
                    self.evidence.setdefault(target,{})[code]=obj['gates'] if target=='certificates' else obj
                except (ValueError,KeyError,OSError) as ex:self.errors.append(dict(source=str(p),error=str(ex)))
        from .capital import apply_capital_terms
        apply_capital_terms(self,asof)
        from .events import load_earnings_events
        self.earnings_events,self.earnings_event_states=load_earnings_events(self.root,asof,self.period)
        for code,state in self.earnings_event_states.items():
            if state.get('blocks_current_decision'):
                self.errors.append(dict(source='issuer_earnings_event:'+code,error=state.get('reason',state['status'])))
        for event in self.earnings_events.values():
            self.receipt(self.path(event['archive_path']),'ISSUER_SELF_REPORTED_EARNINGS_TABLE_RECONCILED_NOT_AUDITED')
        self.model_source_state=model_source_state(self.root)
    def path(self,s):
        p=pathlib.Path(s)
        if p.parts and p.parts[0]==self.root.name:p=pathlib.Path(*p.parts[1:])
        target=(self.root/p).resolve()
        if not target.is_relative_to(self.root):raise ValueError('INPUT_PATH_OUTSIDE_DATA_ROOT')
        return target
    def checked(self,path,digest):
        b=self.path(path).read_bytes()
        if sha(b)!=digest:raise ValueError('SOURCE_HASH_MISMATCH:'+path)
        self.receipt(self.path(path),'MANIFEST_HASH_CHECK_NOT_INDEPENDENT_ORIGIN_PROOF')
        return json.loads(b)
    def receipt(self,path,meaning):
        self.input_receipts.append(dict(path=str(path.relative_to(self.root)),sha256=sha(path.read_bytes()),meaning=meaning))
    def primary(self,code):
        r=self.evidence.get('primary',{}).get(code)
        return r if r and r['period']==self.period else None
    def detailed_values(self,key,period):
        raw=self.bulk.get((key[0],key[1],'income')) if period==self.period else self.detailed.get((*key,period))
        if not raw:return None
        fields={'revenue_k':'營業收入','gross_profit_k':'營業毛利（毛損）淨額','operating_profit_k':'營業利益（損失）',
          'pretax_profit_k':'稅前淨利（淨損）','net_income_k':'本期淨利（淨損）','parent_net_income_k':'淨利（淨損）歸屬於母公司業主'}
        out={k:number(raw.get(v)) for k,v in fields.items()}
        if out['gross_profit_k'] is None:out['gross_profit_k']=number(raw.get('營業毛利（毛損）'))
        return out
