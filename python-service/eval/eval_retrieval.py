# -*- coding: utf-8 -*-
"""检索策略对比评测：dense / bm25 / hybrid / rerank 在同一评测集上的横向对比。

与 eval_rag.py 的区别：
- eval_rag.py 固定走 vectorstore.similarity_search()（纯向量），做 topK × threshold 参数扫描
- 本脚本走 app.retrieval 抽象层，支持多种召回策略横向对比

全程只读生产向量库，不调用 LLM，零 API 消耗，结果确定性可复现。

用法：python -m eval.eval_retrieval [--modes dense,bm25,hybrid,rerank] [--topk 5]
结果落盘 eval/eval-retrieval-result.json
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import retrieval, vectorstore  # noqa: E402

CASES = Path(__file__).resolve().parents[2].joinpath(
    "backend", "src", "main", "resources", "eval", "rag-eval-cases.json")


def load_cases():
    data = json.loads(CASES.read_text(encoding="utf-8"))
    ans = [c for c in data["cases"] if c.get("expectedSections")]
    oos = [c for c in data["cases"] if not c.get("expectedSections")]
    return ans, oos


def evaluate(mode: str, ans, oos, top_k: int = 5, threshold: float = 0.0) -> dict:
    """跑一轮检索评测，返回该策略下的全部指标。"""
    hit1 = hit3 = hit5 = 0
    mrr = 0.0
    lat_sum = 0.0
    lat_max = 0.0
    rows = []

    for c in ans:
        t0 = time.perf_counter()
        docs = retrieval.retrieve(c["query"], top_k=top_k, threshold=threshold, mode=mode)
        dt = (time.perf_counter() - t0) * 1000
        lat_sum += dt
        lat_max = max(lat_max, dt)
        secs = [vectorstore.section_of(d["content"]) for d in docs]
        rank = 0
        for i, s in enumerate(secs):
            if s in c["expectedSections"]:
                rank = i + 1
                break
        if rank:
            mrr += 1.0 / rank
            hit1 += rank <= 1
            hit3 += rank <= 3
            hit5 += rank <= 5
        rows.append({
            "id": c["id"], "rank": rank,
            "retrieved": [{"rank": i + 1, "section": s, "score": round(d["score"], 4)}
                          for i, (s, d) in enumerate(zip(secs, docs))],
            "latencyMs": round(dt, 1),
        })

    n = len(ans)
    oos_rows = []
    for c in oos:
        docs = retrieval.retrieve(c["query"], top_k=top_k, threshold=threshold, mode=mode)
        top = docs[0]["score"] if docs else 0.0
        oos_rows.append({"id": c["id"], "query": c["query"], "topScore": round(top, 4),
                         "topSection": vectorstore.section_of(docs[0]["content"]) if docs else None})

    return {
        "mode": mode, "topK": top_k, "threshold": threshold,
        "hitRateAt1": round(hit1 / n, 4), "hitRateAt3": round(hit3 / n, 4),
        "hitRateAt5": round(hit5 / n, 4), "mrr": round(mrr / n, 4),
        "avgLatencyMs": round(lat_sum / n, 1), "maxLatencyMs": round(lat_max, 1),
        "oosAvgTopScore": round(sum(r["topScore"] for r in oos_rows) / len(oos_rows), 4) if oos_rows else None,
        "cases": rows, "oos": oos_rows,
    }


def main():
    modes = ["dense", "bm25", "hybrid", "rerank"]
    top_k = 5
    for a in sys.argv[1:]:
        if a.startswith("--modes="):
            modes = [m.strip() for m in a.split("=", 1)[1].split(",") if m.strip()]
        elif a.startswith("--topk="):
            top_k = int(a.split("=", 1)[1])

    ans, oos = load_cases()
    print(f"retrieval-eval: modes={modes} topK={top_k} cases={len(ans)}+{len(oos)}")

    results = []
    print(f"\n{'模式':<10}{'Hit@1':>9}{'Hit@3':>9}{'Hit@5':>9}{'MRR':>10}{'平均延迟':>12}{'越界top':>10}")
    print("-" * 70)
    for mode in modes:
        try:
            r = evaluate(mode, ans, oos, top_k=top_k)
        except Exception as exc:
            print(f"{mode:<10} ERROR {type(exc).__name__}: {str(exc)[:120]}")
            continue
        results.append(r)
        print(f"{mode:<10}{r['hitRateAt1']:>9.1%}{r['hitRateAt3']:>9.1%}{r['hitRateAt5']:>9.1%}"
              f"{r['mrr']:>10.4f}{str(r['avgLatencyMs']) + 'ms':>12}{str(r['oosAvgTopScore']):>10}")

    out = Path(__file__).with_name("eval-retrieval-result.json")
    out.write_text(json.dumps({"topK": top_k, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
