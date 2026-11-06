#!/usr/bin/env python3
"""Archive original-byte MOPS probe artifacts without overwriting source vintages.

An original HTTP response SHA is NOT a historical publication timestamp,
beneficial-owner identity attestation or validated buy signal.
"""
import argparse
import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil


def verify_and_copy(src, dest, archive_id):
    src, dest = pathlib.Path(src), pathlib.Path(dest)
    if not re.fullmatch(r"[0-9A-Za-z_-]{4,64}", archive_id):
        raise ValueError("UNSAFE_ARCHIVE_ID")
    summary = json.loads((src / "summary.json").read_bytes())
    if summary.get("schema") != "MOPS_INSIDER_SIX_REPORT_PROBE_SUMMARY_V1":
        raise ValueError("UNTRUSTED_SOURCE_SUMMARY")
    attempts = summary.get("records")
    if not isinstance(attempts, list) or not attempts or len(attempts) > 6:
        raise ValueError("UNSUPPORTED_OR_MISSING_ATTEMPTS")
    folder = dest / archive_id
    if folder.exists():
        raise ValueError("ARCHIVE_VINTAGE_ALREADY_EXISTS_NO_OVERWRITE")
    for item in attempts:
        month, code = item["reporting_month"], item["company_code"]
        if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month) or not re.fullmatch(r"[1-9][0-9]{3}", code):
            raise ValueError("UNSAFE_SOURCE_ID")
        receipt = json.loads((src / month / code / "receipt.json").read_bytes())
        if receipt != item or receipt.get("formal_a_plus_or_valuation_change") is not False:
            raise ValueError("ARCHIVE_RECEIPT_MISMATCH_OR_PROMOTION")
        name = receipt.get("original_response_archive")
        if name:
            raw_path = src / name
            if not raw_path.resolve().is_relative_to(src.resolve()):
                raise ValueError("SOURCE_PATH_TRAVERSAL")
            original = gzip.decompress(raw_path.read_bytes())
            if hashlib.sha256(original).hexdigest() != receipt["original_response_sha256"]:
                raise ValueError("ARCHIVED_RESPONSE_HASH_MISMATCH")
        elif receipt.get("original_response_sha256") is not None:
            raise ValueError("SHA_WITHOUT_ORIGINAL_SOURCE")
    shutil.copytree(src, folder)
    audit = {"schema": "UNCERTIFIED_MOPS_CAPTURE_ARCHIVE_V1",
             "archive_id": archive_id,
             "report_attempts": len(attempts),
             "source_originals_captured": summary.get("original_response_captures"),
             "original_history_publication_proof": False,
             "account_level_roles_reconciled": False,
             "performance_model_pit_eligible": False,
             "formal_a_plus_or_exit_changes": False,
             "source": "MOPS official HTTP bytes in original_http_response.gz"}
    (folder / "archive_manifest.json").write_text(
        json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return folder


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--archive-id", required=True)
    a = p.parse_args()
    dest = verify_and_copy(a.source, a.dest, a.archive_id)
    print(f"Archived immutable original-probe research vintage: {dest}")


if __name__ == "__main__":
    main()
