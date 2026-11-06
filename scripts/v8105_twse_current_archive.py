#!/usr/bin/env python3
"""Verify source response hashes then archive immutable TWSE current OpenAPI vintage.

Current investor/issued shares snapshot cannot be backfilled as historical
issuer point-in-time proof. This deliberately does not change formal gate.
"""
import argparse
import gzip
import hashlib
import json
import pathlib
import re
import shutil


def archive(source, destination, tag):
    source, destination = pathlib.Path(source), pathlib.Path(destination)
    if not re.fullmatch(r"run_[0-9]{6,14}_[0-9]{1,3}", tag):
        raise ValueError("INVALID_SOURCE_VINTAGE_ID")
    summary = json.loads((source/"summary.json").read_bytes())
    if summary.get("schema") != "TWSE_TWO_CURRENT_OFFICIAL_HOLDINGS_PROBES_V1":
        raise ValueError("WRONG_SOURCE_MANIFEST")
    expected = {"t187ap11_L", "t187ap03_L"}
    records = summary.get("records")
    if not isinstance(records, list) or {r.get("source_family") for r in records} != expected:
        raise ValueError("WRONG_ENDPOINT_SET")
    for receipt in records:
        family = receipt["source_family"]
        check = json.loads((source/family/"receipt.json").read_bytes())
        if check != receipt:
            raise ValueError("SRC_RECEIPT_CONFLICT")
        if receipt["formal_13_gate_passed"] is not False or receipt["historical_publication_month_reconstructed"] is not False:
            raise ValueError("UNAUTHORIZED_CERTIFICATION")
        raw_path = source/family/"original_response.gz"
        if receipt["original_response_sha256"] is not None:
            if not raw_path.exists():
                raise ValueError("MISSING_OFFICIAL_BYTES")
            raw = gzip.decompress(raw_path.read_bytes())
            if hashlib.sha256(raw).hexdigest() != receipt["original_response_sha256"]:
                raise ValueError("CURRENT_SOURCE_RESPONSE_HASH_MISMATCH")
        elif raw_path.exists():
            raw = gzip.decompress(raw_path.read_bytes())
            if hashlib.sha256(raw).hexdigest() != receipt.get("original_response_sha256"):
                raise ValueError("SOURCE_WITHOUT_SHA")
    dest=destination/tag
    if dest.exists():
        raise ValueError("NO_OVERWRITE_SOURCE_VINTAGE")
    shutil.copytree(source, dest)
    (dest/"archive_evidence_scope.json").write_text(json.dumps({
        "schema": "TWSE_CURRENT_STOCK_HOLDINGS_IMMUTABLE_VINTAGE_V1",
        "date_and_source_are_observed_not_reconstructed": True,
        "snapshot_only_not_monthly_trade_data": True,
        "historical_2026_07_08_publication_certified": False,
        "market_buying_signals_upgraded": False,
        "formal_Aplus_changed": False,
        "source_vintage": tag,
    }, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    return dest


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--destination", required=True)
    p.add_argument("--tag", required=True)
    args=p.parse_args()
    print(str(archive(args.source,args.destination,args.tag)))


if __name__ == "__main__":
    main()
