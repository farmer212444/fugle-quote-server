#!/usr/bin/env python3
"""AlphaMax universe evidence audit; diagnostic output, no buy signal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphamax.universe_audit import audit_history


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=ROOT)
    p.add_argument("--min-sessions", type=int, default=756)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()
    result = audit_history(args.repo_root, min_sessions=args.min_sessions)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
