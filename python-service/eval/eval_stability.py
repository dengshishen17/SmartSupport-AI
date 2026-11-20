# -*- coding: utf-8 -*-
"""LLM-as-Judge 评测的稳定性验证：同一配置连跑 3 次，看各指标波动幅度。

背景：temperature=0 时 DeepSeek 仍非完全确定性，忠实度在多次运行间有波动。
本脚本跑 N 轮并统计每个指标的 min/中位/max，用于判断某个改动是否真的带来提升。

用法：python -m eval.eval_stability [--rounds 3] [--mode rag|react]
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import eval_answer  # noqa: E402

CASES_FILE = Path(__file__).with_name("answer-eval-cases.json")


def one_round(cases, mode: str) -> dict:
    rows = []
    aborted = False
    for c in cases:
        r = eval_answer.run_case(c, mode)
        rows.append(r)
        if r.get("fatal"):
            print("  [FATAL] %s: %s" % (r["id"], str(r.get("error"))[:120]))
            aborted = True
            break
    ok_rows = [r for r in rows if r.get("success")]
    oos = [r for r in ok_rows if any(c["id"] == r["id"] and c.get("should_refuse") for c in cases)]
    return {
        "mode": mode,
        "total": len(cases),
        "executed": len(rows),
        "success": len(ok_rows),
        "aborted": aborted,
        "faithfulRate": round(sum(r.get("judge", {}).get("faithful", 0) for r in ok_rows) / max(len(ok_rows), 1), 4),
        "toolRuleRate": round(sum(1 for r in ok_rows if r.get("toolRuleOk")) / max(len(ok_rows), 1), 4),
        "refuseRate": round(sum(1 for r in oos if r.get("refusedOk")) / max(len(oos), 1), 4) if oos else None,
        "avgLatencyMs": round(sum(r.get("latencyMs", 0) for r in ok_rows) / max(len(ok_rows), 1), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--mode", default="rag", choices=["rag", "react"])
    args = ap.parse_args()

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    print(f"stability: mode={args.mode} rounds={args.rounds} cases={len(cases)}")

    rounds = []
    for i in range(1, args.rounds + 1):
        r = one_round(cases, args.mode)
        rounds.append(r)
        print(f"  round {i}: {json.dumps(r, ensure_ascii=False)}")
        if r.get("aborted"):
            print("  [FATAL] 本轮因致命错误中止，停止后续轮次。")
            break

    if not rounds or all(r.get("aborted") for r in rounds):
        print("\n[FATAL] 所有轮次均因致命错误中止，无有效结果。请检查 API 余额与 Key。")
        out = Path(__file__).with_name(f"eval-stability-{args.mode}.json")
        out.write_text(json.dumps({"summary": {"mode": args.mode, "rounds": len(rounds),
                                               "aborted": True}, "rounds": rounds},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved: {out}")
        return

    print("\n=== 稳定性汇总 ===")
    summary = {"mode": args.mode, "rounds": args.rounds, "metrics": {}}
    for key in ("success", "faithfulRate", "toolRuleRate", "refuseRate", "avgLatencyMs"):
        vals = [r[key] for r in rounds if r.get(key) is not None]
        if not vals:
            continue
        summary["metrics"][key] = {
            "values": vals,
            "min": min(vals),
            "median": statistics.median(vals),
            "max": max(vals),
            "spread": round(max(vals) - min(vals), 4),
        }
        print(f"  {key:16s} min={min(vals):<10} median={statistics.median(vals):<10} max={max(vals):<10} spread={max(vals)-min(vals)}")

    out = Path(__file__).with_name(f"eval-stability-{args.mode}.json")
    out.write_text(json.dumps({"summary": summary, "rounds": rounds}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
