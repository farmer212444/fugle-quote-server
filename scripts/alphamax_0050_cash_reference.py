#!/usr/bin/env python3
"""Write reference-only 0050 quote+unreinvested gross rights (NOT total returns)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alphamax.benchmark_0050_cash_reference import save_cash_reference


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--price-root", type=Path, required=True)
    p.add_argument("--notice-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = save_cash_reference(a.price_root, a.notice_root, a.output)
    print(json.dumps({
        "status": result["status"],
        "source_verified_ex_date_events": result.get("source_verified_ex_date_events", 0),
        "days": result.get("days", 0),
        "last_date": result.get("last_date"),
        "historical_pit_certified": False,
        "investor_total_return_certified": result["investor_total_return_certified"],
        "verified_oos_12m": result["after_cost_12m_cohorts_verified"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
