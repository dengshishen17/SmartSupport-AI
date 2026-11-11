"""Python 版 RAG 检索评测：与 Java 版 RagEvalService 同一口径。
ground truth=章节标题(## 开头)，指标 Hit@1/3/5 + MRR + 延迟，只读 vector_store。
用法：python -m eval.eval_rag  （需 PG + 百炼 Key 可用）
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import vectorstore  # noqa: E402

CASES = Path(__file__).resolve().parents[1].joinpath(
    "..", "backend", "src", "main", "resources", "eval", "rag-eval-cases.json")


def load_cases():
    data = json.loads(Path(CASES).read_text(encoding="utf-8"))
    ans = [c for c in data["cases"] if c.get("expectedSections")]
    oos = [c for c in data["cases"] if not c.get("expectedSections")]
    return ans, oos


def run_config(ans, oos, top_k: int, threshold: float):
    hit1 = hit3 = hit5 = 0
    mrr = 0.0
    lat_sum = 0.0
    lat_max = 0.0
    rows = []
    for c in ans:
        t0 = time.perf_counter()
        docs = vectorstore.similarity_search(c["query"], top_k=top_k, threshold=threshold)
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
        rows.append({"id": c["id"], "rank": rank,
                     "retrieved": [{"rank": i + 1, "section": s, "score": round(d["score"], 4)}
                                   for i, (s, d) in enumerate(zip(secs, docs))],
                     "latencyMs": round(dt, 1)})
    n = len(ans)
    oos_rows = []
    for c in oos:
        docs = vectorstore.similarity_search(c["query"], top_k=top_k, threshold=threshold)
        top = docs[0]["score"] if docs else 0.0
        oos_rows.append({"id": c["id"], "query": c["query"], "topScore": round(top, 4),
                         "topSection": vectorstore.section_of(docs[0]["content"]) if docs else None})
    return {
        "topK": top_k, "threshold": threshold,
        "hitRateAt1": round(hit1 / n, 4), "hitRateAt3": round(hit3 / n, 4),
        "hitRateAt5": round(hit5 / n, 4), "mrr": round(mrr / n, 4),
        "avgLatencyMs": round(lat_sum / n, 1), "maxLatencyMs": round(lat_max, 1),
        "oosAvgTopScore": round(sum(r["topScore"] for r in oos_rows) / len(oos_rows), 4) if oos_rows else None,
        "cases": rows, "oos": oos_rows,
    }


if __name__ == "__main__":
    ans, oos = load_cases()
    print(f"cases: answerable={len(ans)} oos={len(oos)}")
    results = []
    for tk in (1, 3, 5, 8):
        for th in (0.0, 0.5, 0.7):
            r = run_config(ans, oos, tk, th)
            results.append(r)
            print(f"topK={tk} th={th} Hit@1={r['hitRateAt1']:.1%} Hit@3={r['hitRateAt3']:.1%} "
                  f"MRR={r['mrr']:.4f} avgLat={r['avgLatencyMs']}ms oosTop={r['oosAvgTopScore']}")
    out = Path(__file__).with_name("eval-py-result.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
