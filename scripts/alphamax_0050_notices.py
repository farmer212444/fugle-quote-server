#!/usr/bin/env python3
"""Best-effort capture of official 0050 retrospective notices (never PIT admission)."""
import argparse
import json
from pathlib import Path

from alphamax.benchmark_0050_notice_receipts import capture_notices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path,
                        default=Path("alphamax-0050-notice-capture"))
    args = parser.parse_args()
    result = capture_notices(args.output_dir)
    print(json.dumps({
        "status": result["status"],
        "attempted": result["attempted"],
        "receipt_verified_count": result["receipt_verified_count"],
        "asof_publication_snapshot_verified": result["asof_publication_snapshot_verified"],
        "investor_total_return_verified": result["investor_total_return_verified"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
