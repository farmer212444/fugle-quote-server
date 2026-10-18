#!/usr/bin/env python3
"""Fail-closed gate for legacy research rankings, pending V8.7.9 issuer PIT certification.

This does not replace the V8.7.9 shadow scenario or certify an A+.
"""
import argparse
import json
from pathlib import Path

LEGACY_BAD_5511_EPS = 13.16
LEGACY_BAD_5511_UPSIDE = 89.4

def validate(payload):
    errors = []
    if not isinstance(payload, dict):
        return ["ranking root must be an object"]
    if payload.get("formal_Aplus_count", 0) or payload.get("formal_Aplusplus_count", 0):
        errors.append("legacy research must not publish certified A+/A++")
    for group in ("top30_provisional", "top30_quality_priority", "top30_audit_required", "case_evidence_review"):
        for row in payload.get(group, []):
            if str(row.get("code")) == "5511":
                eps = row.get("eps_2027_base_scenario")
                upside = row.get("scenario_upside_pct")
                if eps is not None and abs(float(eps) - LEGACY_BAD_5511_EPS) < 0.01:
                    errors.append(f"{group}: 5511 obsolete mixed-share EPS 13.16")
                if upside is not None and abs(float(upside) - LEGACY_BAD_5511_UPSIDE) < 0.1:
                    errors.append(f"{group}: 5511 obsolete +89.4% upside")
    return errors

def self_test():
    assert validate({"formal_Aplus_count": 1})
    assert validate({"top30_quality_priority": [{"code": "5511", "scenario_upside_pct": 89.4}]})
    assert not validate({"formal_Aplus_count": 0, "formal_Aplusplus_count": 0,
                         "top30_quality_priority": [{"code": "5511", "scenario_upside_pct": 18.0}]})
    print("SELF_TEST_OK")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("json_file", nargs="?")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.json_file:
            p.error("json_file is required unless --self-test")
        errors = validate(json.loads(Path(args.json_file).read_text(encoding="utf-8")))
        if errors:
            raise SystemExit("REJECTED: " + "; ".join(errors))
        print("PASS: legacy research guard only; not a formal A+ certification")
