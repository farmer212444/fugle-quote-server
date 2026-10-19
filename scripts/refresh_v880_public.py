#!/usr/bin/env python3
"""Refresh static official bulk statements; preserve last-good failed sources."""
import argparse,datetime as dt,gzip,hashlib,json,pathlib
from build_v880_evidence import fetch
from refresh_v881_capital import refresh_capital
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',default='tw-market-data');args=ap.parse_args();data=pathlib.Path(args.data_dir);out=data/'evidence/v880'
    path=out/'snapshot.json.gz';mp=out/'manifest.json';m=json.loads(mp.read_text());packed=path.read_bytes()
    if sha(packed)!=m['gzip_sha256']:raise ValueError('EXISTING_SNAPSHOT_HASH_MISMATCH')
    e=json.loads(gzip.decompress(packed));now=dt.datetime.now(dt.timezone.utc).isoformat();failed=[];success=[]
    for src in json.loads((data/'financial/latest_manifest.json').read_text())['sources']:
        try:
            source,raw,obj=fetch(src);e['official_current_bulk'][source['kind']]=obj;(out/'raw'/(source['kind']+'.gz')).write_bytes(gzip.compress(raw,mtime=0));success.append(source['kind'])
        except Exception as ex:failed.append(dict(kind=src['kind'],error=str(ex),retained_previous_source_date=True))
    capital=refresh_capital(e,out)
    e['last_public_refresh']=dict(at=now,successful_sources=success,failed_sources=failed,original_issuer_reports_not_auto_promoted=True,
      capital_refresh=capital,current_CB_reset_terms_require_explicit_dated_evidence=True,PE_peer_snapshot_date='2026-10-16')
    raw=json.dumps(e,ensure_ascii=False,separators=(',',':')).encode();packed=gzip.compress(raw,mtime=0)
    tmp=path.with_suffix('.tmp');tmp.write_bytes(packed);tmp.replace(path);m.update(gzip_sha256=sha(packed),json_sha256=sha(raw),last_public_refresh=now);mp.write_text(json.dumps(m,indent=2)+'\n')
    print(json.dumps(e['last_public_refresh']))
if __name__=='__main__':main()
