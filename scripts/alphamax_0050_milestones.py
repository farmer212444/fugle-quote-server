#!/usr/bin/env python3
"""Publish isolated, non-investable 0050 source-checked price-unit milestones."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alphamax.benchmark_0050_milestone_audit import audit_0050_milestones_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--price-root", type=Path, required=True)
    p.add_argument("--notice-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = audit_0050_milestones_json(a.price_root, a.notice_root, a.output)
    print(json.dumps({
        "status": result["status"],
        "notices_rechecked": result["notices_rechecked"],
        "aligned_milestones": result["aligned_milestones"],
        "missing": result["missing_or_unverified_milestones"],
        "investor_total_return_certified": result["investor_total_return_certified"],
        "verified_oos_cohorts": result["verified_12m_after_cost_oos_cohorts"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
