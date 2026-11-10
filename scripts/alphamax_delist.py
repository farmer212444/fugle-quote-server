#!/usr/bin/env python3
"""Archive TWSE historical delisting dates, but never infer past tradability."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.delist_ledger import capture_twse_delist


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, default=ROOT / "alphamax-delist-capture")
    args = p.parse_args()
    report = capture_twse_delist(args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    # Research pipeline must not certify itself simply from exit code zero.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
