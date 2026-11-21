# -*- coding: utf-8 -*-
"""Prompt 回归比对：同一评测集上跑多个 Prompt 版本，对比质量指标。

要解决的问题
------------
Prompt 是 LLM 应用里最易变、也最难回归的部分：
- 改一句话可能让忠实度掉 5pt，也可能涨 5pt
- 但 LLM-as-Judge 本身有 3~7pt 的随机波动（temperature=0 也不完全确定）

所以「改完 prompt 跑一次，看分数涨没涨」是不可靠的。本脚本做三件事：

1. **固定评测集 + 固定随机源**：同一批用例、同一顺序
2. **多轮交错执行**（round-robin），而不是「A 跑完再跑 B」——
   避免「B 跑得晚，模型服务状态变好/变差」造成的系统性偏差
3. **取中位数 + 给出噪声区间**：单轮差异小于噪声带宽时，判定为「无显著差异」

判定规则
--------
    delta = median(candidate) - median(baseline)
    noise = max(noiseBaseline, noiseCandidate)   # 各自多轮的标准差

    |delta| <= noise          → 无显著差异（NO_SIGNIFICANT_CHANGE）
    delta >  noise            → 显著提升（IMPROVED）
    delta < -noise            → 显著退化（REGRESSED）

用法
----
    # 对比 rag_system 的 v1（基线）与 v2（候选）
    python -m eval.eval_prompt_regression --baseline=rag_system:v1 --candidate=rag_system:v2

    # 多轮（默认 3 轮）
    python -m eval.eval_prompt_regression --baseline=rag_system:v1 --candidate=rag_system:v2 --rounds=3

    # 查看已注册的 Prompt 版本
    python -m eval.eval_prompt_regression --list

成本
----
每轮 = 用例数 × (1 次生成 + 1 次裁判) 次 DeepSeek 调用。
30 条 × 3 轮 × 2 版本 = 180 次调用，约 0.3 元。
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import agent, config, prompts, workflow  # noqa: E402
from eval import eval_answer  # noqa: E402

CASES_FILE = Path(__file__).with_name("answer-eval-cases.json")
CASES_EXT_FILE = Path(__file__).resolve().parents[2].joinpath(
    "backend", "src", "main", "resources", "eval", "answer-eval-cases-extended.json")


# --------------------------------------------------------------------------
# Prompt 注入
#
# app.agent.build_system 用的是 prompts.RAG_SYSTEM_TEMPLATE 模块常量。
# 为了让「版本」能真正生效，这里用「补丁式」替换：
# 运行时把模块常量指向注册表里对应版本的内容。
# --------------------------------------------------------------------------


def _resolve(spec: str) -> tuple[str, str, prompts.PromptVersion]:
    """解析 "name:version" 形式的版本标识。"""
    if ":" not in spec:
        raise ValueError(f"版本标识必须形如 name:version，收到：{spec}")
    name, version = spec.split(":", 1)
    pv = prompts.get_prompt(name, version)
    if pv is None:
        avail = [f"{p.meta.get('name')}:{p.version}" for p in prompts.list_prompts(name)]
        raise ValueError(f"找不到 Prompt 版本 {spec}；已注册：{avail}")
    return name, version, pv


def _apply(pv: prompts.PromptVersion) -> None:
    """把指定版本的内容应用到运行时。

    通过改写 prompts.ACTIVE_RAG_VERSION 生效 —— build_system 每次都会
    从注册表按该版本号取内容，因此不需要替换模块常量。
    """
    name = pv.meta.get("name")
    if name == "rag_system":
        prompts.ACTIVE_RAG_VERSION = pv.version
    elif name == "fallback_system":
        agent.prompts.FALLBACK_SYSTEM = pv.content
    else:
        raise ValueError(f"未知的 Prompt 用途：{name}")


def _restore() -> None:
    """恢复到默认生效版本。"""
    prompts.ACTIVE_RAG_VERSION = "v2"
    agent.prompts.FALLBACK_SYSTEM = prompts.FALLBACK_SYSTEM


# --------------------------------------------------------------------------
# 指标计算
# --------------------------------------------------------------------------


def _metrics(rows: list[dict]) -> dict:
    """从一轮的结果里算汇总指标。"""
    ok = [r for r in rows if r.get("success")]
    n = len(rows)
    if not n:
        return {}

    faithful = sum(1 for r in ok if r.get("judge", {}).get("faithful") == 1)
    tool_ok = sum(1 for r in ok if r.get("toolRuleOk"))
    refused_ok = sum(1 for r in ok if r.get("refusedOk"))
    lat = [r.get("latencyMs", 0) for r in ok]

    return {
        "total": n,
        "executed": len(ok),
        "successRate": round(len(ok) / n, 4),
        "faithfulRate": round(faithful / len(ok), 4) if ok else 0.0,
        "toolRuleRate": round(tool_ok / len(ok), 4) if ok else 0.0,
        "refusedRate": round(refused_ok / len(ok), 4) if ok else 0.0,
        "avgLatencyMs": round(sum(lat) / len(lat), 1) if lat else 0.0,
    }


def _run_round(cases: list[dict], mode: str, pv: prompts.PromptVersion) -> dict:
    """跑一轮（指定 Prompt 版本已生效的前提下）。"""
    _apply(pv)
    rows = []
    try:
        for c in cases:
            r = eval_answer.run_case(c, mode)
            rows.append(r)
            j = r.get("judge", {})
            print(f"    {r['id']:<16} ok={r.get('success')} "
                  f"faithful={j.get('faithful')} toolRule={r.get('toolRuleOk')} "
                  f"lat={r.get('latencyMs')}ms")
            # 致命错误（余额不足）立即中止
            if r.get("fatal"):
                print(f"    [FATAL] {r.get('error')} —— 中止本轮")
                break
    finally:
        _restore()
    return {"metrics": _metrics(rows), "rows": rows}


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def main():
    rounds = 3
    baseline_spec = "rag_system:v1"
    candidate_spec = "rag_system:v2"
    mode = "rag"
    cases_opt = "base"

    for a in sys.argv[1:]:
        if a.startswith("--baseline="):
            baseline_spec = a.split("=", 1)[1]
        elif a.startswith("--candidate="):
            candidate_spec = a.split("=", 1)[1]
        elif a.startswith("--rounds="):
            rounds = int(a.split("=", 1)[1])
        elif a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif a.startswith("--cases="):
            cases_opt = a.split("=", 1)[1]
        elif a == "--list":
            _list_versions()
            return

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    if cases_opt == "ext" and CASES_EXT_FILE.exists():
        cases = json.loads(CASES_EXT_FILE.read_text(encoding="utf-8"))["cases"]
    elif cases_opt == "both" and CASES_EXT_FILE.exists():
        cases = cases + json.loads(CASES_EXT_FILE.read_text(encoding="utf-8"))["cases"]

    try:
        b_name, b_ver, b_pv = _resolve(baseline_spec)
        c_name, c_ver, c_pv = _resolve(candidate_spec)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return

    if b_name != c_name:
        print(f"[ERROR] 两个版本必须属于同一 Prompt 用途：{b_name} vs {c_name}")
        return

    diff = prompts.diff_prompt(b_name, b_ver, c_ver)
    if diff.get("identical"):
        diff_desc = "无"
    else:
        diff_desc = f"+{diff.get('addedLines', 0)} 行 / -{diff.get('removedLines', 0)} 行"
    print(f"Prompt 回归比对：{b_name} {b_ver} → {c_ver}")
    print(f"  基线版本 {b_pv.version} hash={b_pv.hash} note={b_pv.note}")
    print(f"  候选版本 {c_pv.version} hash={c_pv.hash} note={c_pv.note}")
    print(f"  差异：{diff_desc}")
    print(f"  用例数 {len(cases)}，轮数 {rounds}，模式 {mode}")
    print()

    baseline_rounds: list[dict] = []
    candidate_rounds: list[dict] = []

    for r in range(1, rounds + 1):
        print(f"[第 {r}/{rounds} 轮] 基线 {b_ver} ...")
        baseline_rounds.append(_run_round(cases, mode, b_pv))
        print(f"[第 {r}/{rounds} 轮] 候选 {c_ver} ...")
        candidate_rounds.append(_run_round(cases, mode, c_pv))
        print()

    report = _compare(baseline_rounds, candidate_rounds, b_pv, c_pv, mode)

    out = Path(__file__).with_name("eval-prompt-regression-result.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")


def _list_versions() -> None:
    """列出所有已注册的 Prompt 版本。"""
    items = prompts.list_prompts()
    if not items:
        print("（没有已注册的 Prompt 版本）")
        return
    print(f"{'用途':<18}{'版本':<8}{'hash':<14}{'说明'}")
    print("-" * 72)
    for p in items:
        print(f"{p.meta.get('name', ''):<18}{p.version:<8}{p.hash:<14}{p.note}")


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    """样本标准差；样本数 < 2 时返回 0。"""
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _compare(baseline_rounds: list[dict], candidate_rounds: list[dict],
             b_pv, c_pv, mode: str) -> dict:
    """对比两组多轮结果，判定是否有显著差异。"""
    def series(rounds: list[dict], key: str) -> list[float]:
        return [r["metrics"].get(key, 0.0) for r in rounds if r.get("metrics")]

    report: dict = {
        "mode": mode,
        "baseline": {"name": b_pv.meta.get("name"), "version": b_pv.version,
                     "hash": b_pv.hash, "note": b_pv.note},
        "candidate": {"name": c_pv.meta.get("name"), "version": c_pv.version,
                      "hash": c_pv.hash, "note": c_pv.note},
        "rounds": len(baseline_rounds),
        "metrics": {},
        "verdict": {},
    }

    keys = ["faithfulRate", "toolRuleRate", "refusedRate", "successRate", "avgLatencyMs"]
    for k in keys:
        bs = series(baseline_rounds, k)
        cs = series(candidate_rounds, k)
        b_med, c_med = _median(bs), _median(cs)
        noise = max(_stdev(bs), _stdev(cs))
        delta = c_med - b_med

        # 延迟是「越小越好」，方向相反
        lower_is_better = k == "avgLatencyMs"
        if lower_is_better:
            verdict = ("IMPROVED" if delta < -noise else
                       "REGRESSED" if delta > noise else "NO_SIGNIFICANT_CHANGE")
        else:
            verdict = ("IMPROVED" if delta > noise else
                       "REGRESSED" if delta < -noise else "NO_SIGNIFICANT_CHANGE")

        report["metrics"][k] = {
            "baselineRounds": bs,
            "candidateRounds": cs,
            "baselineMedian": round(b_med, 4),
            "candidateMedian": round(c_med, 4),
            "delta": round(delta, 4),
            "noise": round(noise, 4),
            "verdict": verdict,
        }
        report["verdict"][k] = verdict

    # 综合判定：以忠实度为主指标
    primary = report["verdict"].get("faithfulRate", "NO_SIGNIFICANT_CHANGE")
    regressions = [k for k, v in report["verdict"].items() if v == "REGRESSED"]
    report["summary"] = {
        "primaryMetric": "faithfulRate",
        "primaryVerdict": primary,
        "regressedMetrics": regressions,
        "conclusion": (
            "候选版本在忠实度上有显著提升" if primary == "IMPROVED" and not regressions else
            "候选版本在忠实度上显著退化" if primary == "REGRESSED" else
            f"忠实度无显著差异，但以下指标退化：{', '.join(regressions)}" if regressions else
            "两版无显著差异（改动落在噪声范围内）"
        ),
    }

    print("=" * 78)
    print(f"{'指标':<18}{'基线中位':>12}{'候选中位':>12}{'Δ':>10}{'噪声':>10}  判定")
    print("-" * 78)
    for k, v in report["metrics"].items():
        print(f"{k:<18}{v['baselineMedian']:>12.4f}{v['candidateMedian']:>12.4f}"
              f"{v['delta']:>+10.4f}{v['noise']:>10.4f}  {v['verdict']}")
    print("-" * 78)
    print(f"结论：{report['summary']['conclusion']}")
    print("=" * 78)

    return report


if __name__ == "__main__":
    main()
