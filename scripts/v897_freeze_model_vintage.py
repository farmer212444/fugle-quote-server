#!/usr/bin/env python3
"""V8.9.7 prospective immutable research-vintage archive.

Preserves the exact *as-generated* valuation and market-universe records.
Does NOT backfill 2025/2026 with a modern model, prove announcement PIT,
establish an investment backtest, or change the 13 formal quality gates.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
from pathlib import Path

SCHEMA="V897_PROSPECTIVE_SNAPSHOT_NOT_PIT_CERTIFIED"
TAIPEI=dt.timezone(dt.timedelta(hours=8))
SOURCES=("prices/latest_manifest.json","fundamentals/latest_scan.json",
         "latest_manifest.json","evidence/v880/manifest.json")
FILES=(("research","latest_research.json"),("full","full_results.json.gz"),
       ("reference_price","reference_prices.json"))


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def aware(value):
    ts=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if ts.tzinfo is None:
        raise ValueError("VINTAGE_TIMEZONE_MISSING")
    return ts


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def path_inside_root(root, raw):
    p=Path(raw)
    if p.parts and p.parts[0]==root.name:
        p=Path(*p.parts[1:])
    result=(root/p).resolve()
    if p.is_absolute() or ".." in p.parts or root not in result.parents:
        raise ValueError("UNSAFE_FROZEN_INPUT_PATH")
    return result


def load_inputs(root, now, code_version):
    root=Path(root).resolve()
    research_path=root/"rankings/latest_research.json"
    research_blob=research_path.read_bytes()
    research=json.loads(research_blob)
    vintage=aware(research["estimate_vintage"])
    if vintage>now:
        raise ValueError("MODEL_VINTAGE_FROM_FUTURE")
    if (now-vintage).total_seconds()>7*86400:
        raise ValueError("STALENESS_VINTAGE_EXCEEDS_SEVEN_DAYS")
    market_date=dt.date.fromisoformat(research["asof_price_date"])
    if market_date>vintage.astimezone(TAIPEI).date():
        raise ValueError("FUTURE_PRICE_ARCHIVE_RELATIVE_TO_ESTIMATE")
    if research.get("model")!=code_version:
        raise ValueError("RESEARCH_MODEL_DIFFERS_FROM_MAIN_VERSION")
    if not isinstance(research.get("data_scope",{}).get("model_rows"),int):
        raise ValueError("MODEL_UNIVERSE_COUNT_MISSING")

    manifest={}
    manifest_bytes={}
    for name in SOURCES:
        raw=(root/name).read_bytes()
        manifest_bytes[name]=raw
        manifest[name]=json.loads(raw)
    price_manifest=manifest[SOURCES[0]]
    fin_manifest=manifest[SOURCES[1]]
    revenue_manifest=manifest[SOURCES[2]]
    if price_manifest["date"]!=research["asof_price_date"]:
        raise ValueError("PRICE_MANIFEST_NOT_FROM_RESEARCH_VINTAGE")
    if fin_manifest["last_eligible_quarter"]!=research["financial_last_quarter"]:
        raise ValueError("FINANCIAL_MANIFEST_NOT_FROM_RESEARCH_VINTAGE")
    if revenue_manifest["period"]!=research["revenue_month"]:
        raise ValueError("REVENUE_MANIFEST_NOT_FROM_RESEARCH_VINTAGE")
    price_file=path_inside_root(root,price_manifest["path"])
    price_blob=price_file.read_bytes()
    if sha(price_blob)!=price_manifest["normalized_sha256"]:
        raise ValueError("REFERENCE_QUOTE_ORIGINAL_SNAPSHOT_HASH_MISMATCH")
    full_manifest=research.get("full_results",{})
    full_path=full_manifest.get("path")
    if not isinstance(full_path,str) or Path(full_path).name!="v880_full_results.json.gz":
        raise ValueError("FULL_ISSUER_UNIVERSE_PATH_INVALID")
    full_blob=(root/"rankings"/"v880_full_results.json.gz").read_bytes()
    if sha(full_blob)!=full_manifest.get("sha256"):
        raise ValueError("FULL_MARKET_RESEARCH_GZIP_HASH_MISMATCH")
    raw_full=gzip.decompress(full_blob)
    if sha(raw_full)!=full_manifest.get("json_sha256"):
        raise ValueError("FULL_MARKET_RESEARCH_CONTENT_HASH_MISMATCH")
    full=json.loads(raw_full)
    rows=full.get("all_model_rows")
    if not isinstance(rows,list) or len(rows)!=research["data_scope"]["model_rows"]:
        raise ValueError("FROZEN_MARKET_UNIVERSE_NOT_IDENTICAL_TO_RESEARCH")
    if full.get("estimate_vintage")!=research["estimate_vintage"]:
        raise ValueError("FULL_AND_COMPACT_RESEARCH_VINTAGE_MISMATCH")
    return dict(root=root,research=research,vintage=vintage,
                payloads=dict(research=research_blob,full=full_blob,
                              reference_price=price_blob),
                price_source_path=price_file.relative_to(root).as_posix(),
                raw_manifests=manifest_bytes,
                market_rows=len(rows))


def _ensure_immutable(path,blob):
    if path.exists():
        if path.read_bytes()!=blob:
            raise ValueError("FROZEN_VINTAGE_IMMUTABILITY_CONFLICT_"+path.name)
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(blob)
    return True


def freeze(root,now,version,source_git_commit=None):
    src=load_inputs(root,now,version)
    vintage=src["vintage"]
    day=vintage.astimezone(TAIPEI).date().isoformat()
    # A same-day rerun may use identical printed valuations but different
    # source-mirror vintages. Distinguish the complete input identity, never
    # silently reuse an old receipt for newly captured source data.
    identity_parts=[sha(src["payloads"][k]) for k,_ in FILES]
    identity_parts.extend(sha(src["raw_manifests"][k]) for k in SOURCES)
    short=sha(("|".join(identity_parts)).encode())[:20]
    folder=src["root"]/"pit_vintages"/day/short
    receipt_path=folder/"receipt.json"
    if receipt_path.exists():
        verify_frozen_receipt(receipt_path)
        return dict(status="VINTAGE_ALREADY_ARCHIVED",day=day,
                    research_digest=sha(src["payloads"]["research"]),
                    path=receipt_path.relative_to(src["root"]).as_posix(),
                    issuer_count=src["market_rows"],formal_PIT_certification=False)
    if folder.exists():
        raise ValueError("HALF_PUBLISHED_VINTAGE_REQUIRES_MANUAL_RECOVERY")
    receipt={
        "schema":SCHEMA,
        "archived_at_utc":now.astimezone(dt.timezone.utc).isoformat(),
        "issuer_market_reference_date":src["research"]["asof_price_date"],
        "estimate_vintage":src["research"]["estimate_vintage"],
        "financial_last_quarter":src["research"]["financial_last_quarter"],
        "revenue_month":src["research"]["revenue_month"],
        "model":version,
        "model_code_sha256":src["research"].get("model_code_sha256"),
        "model_repo_commit_before_generated_files":source_git_commit,
        "model_issuer_universe_count":src["market_rows"],
        "source_manifest_digests":{
            name:sha(raw) for name,raw in src["raw_manifests"].items()
        },
        "referenced_price_archive_path":src["price_source_path"],
        "reference_quote_is_unadjusted":True,
        "files":{
            key:{"file":name,"sha256":sha(src["payloads"][key]),
                 "bytes":len(src["payloads"][key])}
            for key,name in FILES
        },
        "full_results_are_current_runtime_only":True,
        "historical_original_filing_PIT_verified":False,
        "historic_issuer_universe_PIT_verified":False,
        "future_return_total_share_actions_verified":False,
        "out_of_sample_trading_backtest_verified":False,
        "formal_point_in_time_gate_pass":False,
        "formal_out_of_sample_gate_pass":False,
        "formal_Aplus_count_unmodified":src["research"].get("formal_Aplus_count"),
        "limitations":[
            "The record freezes this model run; it does NOT retroactively certify prior models.",
            "Time first seen by the model is not proof of historic issuer announcement time.",
            "Unadjusted closes omit dividends, splits, delistings, fees, spreads and actual execution.",
            "Future out-of-sample investment returns require subsequent dated prices and a formal PIT audit."
        ]
    }
    folder.mkdir(parents=True,exist_ok=False)
    for key,filename in FILES:
        _ensure_immutable(folder/filename,src["payloads"][key])
    _ensure_immutable(receipt_path,(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n").encode())
    verify_frozen_receipt(receipt_path)
    return dict(status="FROZEN_NEW_VINTAGE_NOT_PIT_CERTIFIED",day=day,
                research_digest=sha(src["payloads"]["research"]),
                path=receipt_path.relative_to(src["root"]).as_posix(),
                issuer_count=src["market_rows"],formal_PIT_certification=False)


def verify_frozen_receipt(receipt_path):
    receipt_path=Path(receipt_path)
    receipt=read(receipt_path)
    if receipt.get("schema")!=SCHEMA or any(receipt.get(k) is not False for k in (
        "historical_original_filing_PIT_verified",
        "historic_issuer_universe_PIT_verified","out_of_sample_trading_backtest_verified",
        "formal_point_in_time_gate_pass","formal_out_of_sample_gate_pass"
    )):
        raise ValueError("FALSE_PIT_BACKTEST_CERTIFICATION")
    for key,filename in FILES:
        item=receipt["files"].get(key)
        if (item is None or item.get("file")!=filename
                or not re.fullmatch(r"[a-f0-9]{64}",item.get("sha256",""))):
            raise ValueError("FROZEN_VINTAGE_FILE_MANIFEST_INVALID")
        body=(receipt_path.parent/filename).read_bytes()
        if sha(body)!=item["sha256"] or len(body)!=item["bytes"]:
            raise ValueError("FROZEN_VINTAGE_BYTES_TAMPERED")
    compact=json.loads((receipt_path.parent/"latest_research.json").read_bytes())
    full_bytes=gzip.decompress((receipt_path.parent/"full_results.json.gz").read_bytes())
    full=json.loads(full_bytes)
    if (compact.get("estimate_vintage")!=receipt.get("estimate_vintage")
            or full.get("estimate_vintage")!=receipt.get("estimate_vintage")
            or len(full.get("all_model_rows",[]))!=receipt.get("model_issuer_universe_count")):
        raise ValueError("FROZEN_VINTAGE_INTERNAL_MISMATCH")
    return receipt


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-root",default="tw-market-data")
    ap.add_argument("--git-source-sha",default=None)
    args=ap.parse_args()
    root=Path(args.data_root).resolve()
    now=dt.datetime.now(dt.timezone.utc)
    version=(root.parent/"VERSION").read_text(encoding="utf-8").strip()
    result=freeze(root,now,version,args.git_source_sha)
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
