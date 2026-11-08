#!/usr/bin/env python3
"""Fail-closed check of generated 2330/2317 reports before publishing.

The verifier does not fetch evidence, issue certificates, or alter documents.
It checks whether the pipeline output is synchronized with its source ledger.
"""
import argparse
import hashlib
import json
from pathlib import Path

FOCUS_CODES=("2330", "2317")
HEADING="## 2330 台積電／2317 鴻海：雙軌正式證據追蹤（非發證）"


def verify(data_root):
    root=Path(data_root)/"rankings"
    source=(root/"v891_gate_progress.json").read_bytes()
    report=json.loads((root/"latest_research_work_queue.json").read_text(encoding="utf-8"))
    markdown=(root/"latest_research_work_queue.md").read_text(encoding="utf-8")
    if report.get("source_progress_sha256")!=hashlib.sha256(source).hexdigest():
        raise ValueError("DUAL_PUBLICATION_SOURCE_LEDGER_SHA_MISMATCH")
    if report.get("model") not in markdown or report.get("estimate_vintage") not in markdown:
        raise ValueError("DUAL_PUBLICATION_MODEL_VINTAGE_MISMATCH")
    if HEADING not in markdown:
        raise ValueError("DUAL_PUBLICATION_SECTION_MISSING")
    lanes=report.get("dual_focus_status")
    if not isinstance(lanes,list) or tuple(row.get("code") for row in lanes)!=FOCUS_CODES:
        raise ValueError("DUAL_PUBLICATION_LANE_LIST_INCOMPLETE")
    section=markdown.split(HEADING,1)[1].split("\n## ",1)[0]
    jobs={job["code"]:job for job in report["issuer_jobs"]}
    for lane in lanes:
        code=lane["code"]
        if lane.get("diagnostic_status")=="NOT_IN_CURRENT_DIAGNOSTIC":
            if code in jobs or f"|{code}|—|不在本次診斷名單|" not in section:
                raise ValueError("DUAL_PUBLICATION_MISSING_DIAGNOSTIC_MISMATCH")
            continue
        if lane.get("diagnostic_status")!="IN_CURRENT_DIAGNOSTIC" or code not in jobs:
            raise ValueError("DUAL_PUBLICATION_DIAGNOSTIC_MISMATCH")
        job=jobs[code]
        if lane.get("formal_Aplus") is not job.get("formal_Aplus"):
            raise ValueError("DUAL_PUBLICATION_FORMAL_STATUS_MISMATCH")
        if lane.get("original_quarter_coverage")!=job.get("original_quarter_coverage"):
            raise ValueError("DUAL_PUBLICATION_ARCHIVE_COVERAGE_MISMATCH")
        if lane.get("company_gates_passed")!=len(
                [name for name in ("original_eight_quarter_statements",
                  "cash_and_working_capital","nonoperating_components","fully_diluted_shares",
                  "matched_peers_and_cycle","management_promises","auditor_scope",
                  "tradability","forecast_bridge","insider_claims","dividend_window",
                  "point_in_time") if name not in {item["gate"] for item in job["work"]}]):
            raise ValueError("DUAL_PUBLICATION_GATE_COUNT_MISMATCH")
        title=f"|{code} {lane.get('name') or ''}|"
        if title not in section:
            raise ValueError("DUAL_PUBLICATION_FOCUS_MARKDOWN_MISSING")
        detail=next((line for line in section.splitlines() if line.startswith(title)),None)
        if f"{lane['company_gates_passed']}/12" not in detail:
            raise ValueError("DUAL_PUBLICATION_PASS_COUNT_MISMATCH")
        if "|"+("是" if lane["formal_Aplus"] else "否")+"|" not in detail:
            raise ValueError("DUAL_PUBLICATION_FORMAL_MARKDOWN_MISMATCH")
    return dict(source_sha256=report["source_progress_sha256"],
                validated_focus_codes=list(FOCUS_CODES),
                formal_aplus_count=sum(bool(lane.get("formal_Aplus")) for lane in lanes),
                verified_report_sync=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",default="tw-market-data")
    args=parser.parse_args()
    print(json.dumps(verify(args.data_root),ensure_ascii=False))


if __name__=="__main__":
    main()
