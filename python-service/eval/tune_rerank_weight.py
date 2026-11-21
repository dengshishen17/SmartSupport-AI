# -*- coding: utf-8 -*-
"""重排权重调参：用 dev/test 分割避免过拟合。

问题
----
rerank 有四个信号权重（向量 / 关键词 / 章节 / 权威度）。
如果在全部评测用例上反复调权重，再在同一份数据上报告指标，
就等于把评测集当训练集用了 —— 得到的 Hit@1 会虚高，泛化能力无法保证。

做法
----
把评测集按 id 哈希稳定分成 dev / test 两半：
- dev：只用来搜权重
- test：只在选定权重后看一次，用于报告泛化效果

用法：
    python -m eval.tune_rerank_weight          # 搜索并在 test 上验证
    python -m eval.tune_rerank_weight --full   # 用全部数据搜索（仅用于生成参考曲线）

结果落盘 eval/rerank-weight-tuning.json
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import retrieval  # noqa: E402
from app.retrieval.rerank import RuleReranker  # noqa: E402
from eval.eval_retrieval import (  # noqa: E402
    CASES,
    CASES_EXT,
    load_cases,
    section_of_doc,
)

OUT = Path(__file__).with_name("rerank-weight-tuning.json")

# 搜索空间：四个信号的权重组合（总和为 1）
# 向量权重最高，向量/关键词/章节/权威度逐档递减
GRID = [
    (wv, wk, ws, wa)
    for wv in (0.40, 0.45, 0.50, 0.55, 0.60)
    for wk in (0.10, 0.15, 0.20, 0.25)
    for ws in (0.10, 0.15, 0.20)
    for wa in (0.05, 0.10, 0.15, 0.20)
    if abs((wv + wk + ws + wa) - 1.0) < 1e-6
]


def stable_split(cases: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 id 哈希稳定二分：同一份用例每次划分一致。"""
    dev, test = [], []
    for c in cases:
        h = int(hashlib.md5(c["id"].encode()).hexdigest(), 16)
        (dev if h % 2 == 0 else test).append(c)
    return dev, test


def make_reranker(base, wv, wk, ws, wa):
    return RuleReranker(base, w_vector=wv, w_keyword=wk, w_section=ws, w_authority=wa)


def eval_weights(base, cases: list[dict], top_k: int = 5) -> dict:
    """在给定权重下计算 Hit@1 / Hit@3 / MRR。"""
    hit1 = hit3 = 0
    mrr = 0.0
    for c in cases:
        rr = make_reranker(base, *weights_of.current)
        # 用 reranker 直接对 dense 召回池重排
        docs = base.recall(c["query"], top_k * 4)
        if not docs:
            continue
        out = rr.rerank(c["query"], docs, top_k)
        secs = [section_of_doc(d.to_dict()) for d in out]
        rank = 0
        for i, s in enumerate(secs):
            if s in c["expectedSections"]:
                rank = i + 1
                break
        if rank:
            hit1 += rank <= 1
            hit3 += rank <= 3
            mrr += 1.0 / rank
    n = len(cases) or 1
    return {
        "hitRateAt1": round(hit1 / n, 4),
        "hitRateAt3": round(hit3 / n, 4),
        "mrr": round(mrr / n, 4),
        "n": len(cases),
    }


class _WeightsHolder:
    current = (0.55, 0.20, 0.15, 0.10)


weights_of = _WeightsHolder()


def main():
    full = False
    for a in sys.argv[1:]:
        if a == "--full":
            full = True

    base_ans, _ = load_cases()
    ext_ans, _ = load_cases(CASES_EXT)
    all_ans = base_ans + ext_ans

    if full:
        dev, test = all_ans, []
        split_desc = "full"
    else:
        dev, test = stable_split(all_ans)
        split_desc = "dev/test"

    print(f"cases: total={len(all_ans)} dev={len(dev)} test={len(test)} split={split_desc}")
    if test:
        print(f"dev  类别分布: {sorted({c.get('category') for c in dev})}")
        print(f"test 类别分布: {sorted({c.get('category') for c in test})}")

    from app.retrieval.dense import DenseRetriever
    base = DenseRetriever()

    print(f"\n搜索 {len(GRID)} 组权重（每组在 dev 上跑 {len(dev)} 条用例）...")
    t0 = time.time()
    results = []
    for w in GRID:
        weights_of.current = w
        m = eval_weights(base, dev)
        results.append({"weights": dict(zip(["w_vector", "w_keyword", "w_section", "w_authority"], w)), **m})
    print(f"搜索完成，耗时 {time.time() - t0:.1f}s")

    results.sort(key=lambda r: (r["mrr"], r["hitRateAt1"]), reverse=True)
    print("\ntop 10（按 dev MRR 排序）：")
    for r in results[:10]:
        w = r["weights"]
        print("  vec=%.2f kw=%.2f sec=%.2f auth=%.2f | dev H@1=%.1f%% H@3=%.1f%% MRR=%.4f" % (
            w["w_vector"], w["w_keyword"], w["w_section"], w["w_authority"],
            r["hitRateAt1"] * 100, r["hitRateAt3"] * 100, r["mrr"]))

    best = results[0]
    bw = best["weights"]
    weights_of.current = (bw["w_vector"], bw["w_keyword"], bw["w_section"], bw["w_authority"])

    print("\n选定权重: %s" % bw)
    print("dev  : %s" % {k: v for k, v in best.items() if k != "weights"})

    out = {"split": split_desc, "best": best, "grid": results}
    if test:
        test_m = eval_weights(base, test)
        print("test : %s" % test_m)
        out["test"] = test_m
        # 与当前默认权重对比
        cur = (0.55, 0.20, 0.15, 0.10)
        weights_of.current = cur
        out["currentDefaultOnTest"] = eval_weights(base, test)
        print("当前默认权重在 test 上: %s" % out["currentDefaultOnTest"])

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {OUT}")


if __name__ == "__main__":
    main()
