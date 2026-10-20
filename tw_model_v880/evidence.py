"""Formal ratings are decisions over evidence, not a score or a constant."""
import datetime as dt,math,re

GATES=('original_eight_quarter_statements','cash_and_working_capital','nonoperating_components','fully_diluted_shares',
 'matched_peers_and_cycle','management_promises','auditor_scope','tradability','forecast_bridge','insider_claims',
 'dividend_window','point_in_time','out_of_sample_validation')
POLICY=dict(Aplus_price_upside_pct=30.,Aplusplus_price_upside_pct=35.,discovery_price_upside_pct=25.,
 stress_eps_factor=.9,stress_pe_factor=.9,stress_min_upside_pct=0.)

def timestamp(s):
    v=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if v.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return v

def gate(status,reason,**kwargs):return dict(status=status,reason=reason,**kwargs)

def certify(code,upside,stressed_upside,gates,asof,financial_period,*,policy=None):
    p=policy or POLICY;cut=timestamp(asof);pending=[];failed=[];passed=[]
    for name in GATES:
        g=gates.get(name,{})
        valid=(g.get('issuer')==code and g.get('financial_period')==financial_period and bool(g.get('sources')) and bool(g.get('method')))
        try:
            checked=timestamp(g['checked_at']);available=timestamp(g['available_at']);expires=timestamp(g['expires_at'])
            valid=valid and available<=checked<=cut<=expires
            valid=valid and all(s.get('url') and re.fullmatch('[0-9a-f]{64}',s.get('sha256','')) and s.get('origin_authenticated') is True
               and timestamp(s['available_at'])<=checked for s in g['sources'])
        except (KeyError,TypeError,ValueError):valid=False
        if not valid or g.get('status') not in ('PASS','FAIL'):pending.append(name)
        elif g['status']=='FAIL':failed.append(name)
        else:passed.append(name)
    quality_complete=not pending and not failed;numeric=upside is not None and math.isfinite(upside)
    aplus=quality_complete and numeric and upside>=p['Aplus_price_upside_pct']
    stress_ok=stressed_upside is not None and math.isfinite(stressed_upside) and stressed_upside>=p['stress_min_upside_pct'] and gates.get('fully_diluted_shares',{}).get('stress_verified') is True
    aplusplus=aplus and upside>=p['Aplusplus_price_upside_pct'] and stress_ok
    status=('QUALITY_REVIEW_FAILED' if failed else 'CERTIFICATION_PENDING' if not quality_complete else 'VALUATION_UNAVAILABLE' if not numeric
      else 'A++' if aplusplus else 'A+' if aplus else 'A_DISCOVERY' if upside>=p['discovery_price_upside_pct'] else 'WATCH')
    return dict(status=status,formal_Aplus=aplus,formal_Aplusplus=aplusplus,gates_passed=passed,gates_pending=pending,
      gates_failed=failed,quality_complete=quality_complete,stress_passed=stress_ok,no_trade_instruction=True)


def verify_certificate_archives(document, data_root):
    """Do not trust directly uploaded PASS/FAIL JSON without local original bytes.

    This is an independently recomputed byte-integrity check, NOT an external
    regulator digital signature or a substitute for documented human review.
    """
    import hashlib
    from pathlib import Path
    root = Path(data_root).resolve()
    code = document.get("code")
    gates = document.get("gates")
    if not isinstance(gates,dict) or not isinstance(code,str):
        raise ValueError("CERTIFICATE_DOCUMENT_INVALID")
    for name, item in gates.items():
        if name not in GATES or not isinstance(item,dict):
            raise ValueError("CERTIFICATE_UNKNOWN_GATE")
        if item.get("status") not in ("PASS","FAIL"):
            raise ValueError("CERTIFICATE_NOT_DECIDED")
        if item.get("issuer")!=code or item.get("reviewed_by") is None:
            raise ValueError("CERTIFICATE_REVIEWER_OR_ISSUER_INVALID")
        if item.get("original_archive_sha256_recomputed") is not True or item.get("human_source_identity_review_documented") is not True:
            raise ValueError("CERTIFICATE_ORIGINAL_REVIEW_NOT_DOCUMENTED")
        sources=item.get("sources")
        if not isinstance(sources,list) or not sources:
            raise ValueError("CERTIFICATE_SOURCES_MISSING")
        for source in sources:
            relpath=source.get("archive_path")
            if not isinstance(relpath,str) or not relpath:
                raise ValueError("CERTIFICATE_SOURCE_ARCHIVE_REQUIRED")
            rel=Path(relpath)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("CERTIFICATE_SOURCE_ARCHIVE_UNSAFE_PATH")
            orig=(root/rel).resolve()
            if orig==root or root not in orig.parents or not orig.is_file():
                raise ValueError("CERTIFICATE_ORIGINAL_BYTES_MISSING")
            digest=source.get("sha256")
            if not isinstance(digest,str) or not re.fullmatch("[0-9a-f]{64}",digest):
                raise ValueError("CERTIFICATE_SOURCE_DIGEST_MISSING")
            if hashlib.sha256(orig.read_bytes()).hexdigest()!=digest:
                raise ValueError("CERTIFICATE_SOURCE_HASH_MISMATCH")
    return True
