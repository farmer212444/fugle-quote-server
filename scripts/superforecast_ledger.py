#!/usr/bin/env python3
"""Register genuinely new forecasts and score matured outcomes; no order creation."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tw_model_v880.superforecast import issue, resolve, report, parse_time


def markdown(result):
    lines = ["# Superforecast 機率預測紀錄", "",
             f"狀態：{result['status']}",
             f"已事前登錄：{result['issued_count']}；已核對可評分結果：{result['scored_count']}。", "",
             "僅計入到期、附雜湊證據及事先登錄的二元事件。",
             "來源SHA256檢查不等於外部可信時間戳或獨立真偽審定；本模組不產生股票預測機率，也不核發A+。", ""]
    if result.get("reason"):
        lines += [f"拒收原因：{result['reason']}", ""]
    if result.get("brier_score") is None:
        lines += ["Brier與可靠度：有效樣本不足，禁止宣稱預測勝率。"]
    else:
        lines += [f"Brier：{result['brier_score']:.6f}（低者較佳）",
                  f"配對基準Brier：{result['baseline_brier_score']:.6f}" if result.get("baseline_brier_score") is not None else "配對基準Brier：待有效事前基準",
                  f"Brier skill：{result['brier_skill_score']:.6f}" if result.get("brier_skill_score") is not None else "Brier skill：待核對", ""]
    lines += ["投資績效與0050超額報酬仍須另行完整扣成本樣本外回測。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default="tw-market-data")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("issue", "resolve"):
        part = sub.add_parser(name)
        part.add_argument("spec", help="JSON specification. The tool, not JSON, stamps actual current time.")
    scoring = sub.add_parser("report")
    scoring.add_argument("--asof", help="Read-only historical cutoff ISO 8601 with timezone")
    args = parser.parse_args()
    root = Path(args.data_root)
    if args.action in ("issue", "resolve"):
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        result = issue(root, spec) if args.action == "issue" else resolve(root, spec)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    asof = parse_time(args.asof) if args.asof else dt.datetime.now(dt.timezone.utc)
    result = report(root, asof=asof)
    folder = root / "rankings"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "latest_superforecast.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (folder / "latest_superforecast.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps(dict(status=result["status"], issued=result["issued_count"],
                          scored=result["scored_count"], brier=result["brier_score"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
