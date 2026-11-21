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
from eval import metrics_ndcg  # noqa: E402

CASES = Path(__file__).resolve().parents[2].joinpath(
    "backend", "src", "main", "resources", "eval", "rag-eval-cases.json")
CASES_EXT = Path(__file__).resolve().parents[2].joinpath(
    "backend", "src", "main", "resources", "eval", "rag-eval-cases-extended.json")


def section_of_doc(doc: dict) -> str | None:
    """取 chunk 的章节标题。

    优先用 retrieval 返回的 section 字段（内部已处理 metadata 优先、
    正文解析兜底），回退到 metadata，再回退到正文解析。
    """
    sec = doc.get("section")
    if sec:
        return sec
    meta = doc.get("metadata") or {}
    sec = meta.get("section")
    if sec:
        return sec
    return vectorstore.section_of(doc.get("content", ""))


def load_cases(path: Path | None = None):
    """加载评测集，返回 (可答用例, 越界探针)。"""
    p = path or CASES
    data = json.loads(p.read_text(encoding="utf-8"))
    ans = [c for c in data["cases"] if c.get("expectedSections")]
    oos = [c for c in data["cases"] if not c.get("expectedSections")]
    return ans, oos


def evaluate(mode: str, ans, oos, top_k: int = 5, threshold: float = 0.0) -> dict:
    """跑一轮检索评测，返回该策略下的全部指标。

    指标体系：
    - Hit@1 / Hit@3 / Hit@5：二值命中
    - MRR：首个相关项倒数排名
    - NDCG@K：分级相关度下的排序质量（政策正文=3，FAQ/归纳=1，干扰=-1）
    - MAP：Average Precision
    """
    hit1 = hit3 = hit5 = 0
    mrr = 0.0
    lat_sum = 0.0
    lat_max = 0.0
    rows = []
    cat_stat: dict[str, dict] = {}
    ndcg_all: list[float] = []
    ap_all: list[float] = []

    for c in ans:
        t0 = time.perf_counter()
        docs = retrieval.retrieve(c["query"], top_k=top_k, threshold=threshold, mode=mode)
        dt = (time.perf_counter() - t0) * 1000
        lat_sum += dt
        lat_max = max(lat_max, dt)
        secs = [section_of_doc(d) for d in docs]

        # ---- 分级相关度：NDCG / MAP ----
        ranked = metrics_ndcg.evaluate_ranking(
            secs,
            expected_sections=c.get("expectedSections") or [],
            distractor_sections=c.get("distractorSections") or [],
            k=top_k,
        )
        ndcg_all.append(ranked["ndcgAtK"])
        ap_all.append(ranked["ap"])

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
        cat = c.get("category", "unknown")
        cs = cat_stat.setdefault(cat, {"total": 0, "hit1": 0, "hit3": 0, "hit5": 0,
                                       "mrr": 0.0, "ndcg": 0.0, "ap": 0.0})
        cs["total"] += 1
        cs["ndcg"] += ranked["ndcgAtK"]
        cs["ap"] += ranked["ap"]
        if rank:
            cs["hit1"] += rank <= 1
            cs["hit3"] += rank <= 3
            cs["hit5"] += rank <= 5
            cs["mrr"] += 1.0 / rank
        rows.append({
            "id": c["id"], "category": cat, "rank": rank,
            "ndcgAtK": round(ranked["ndcgAtK"], 4),
            "ap": round(ranked["ap"], 4),
            "grades": ranked["grades"],
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
                         "topSection": section_of_doc(docs[0]) if docs else None})

    per_category = {}
    for cat, s in sorted(cat_stat.items()):
        t = s["total"]
        per_category[cat] = {
            "total": t,
            "hitRateAt1": round(s["hit1"] / t, 4),
            "hitRateAt3": round(s["hit3"] / t, 4),
            "hitRateAt5": round(s["hit5"] / t, 4),
            "mrr": round(s["mrr"] / t, 4),
            "ndcgAtK": round(s["ndcg"] / t, 4),
            "map": round(s["ap"] / t, 4),
        }

    n = len(ans)
    return {
        "mode": mode, "topK": top_k, "threshold": threshold,
        "hitRateAt1": round(hit1 / n, 4), "hitRateAt3": round(hit3 / n, 4),
        "hitRateAt5": round(hit5 / n, 4), "mrr": round(mrr / n, 4),
        "ndcgAtK": round(sum(ndcg_all) / n, 4),
        "map": round(sum(ap_all) / n, 4),
        "avgLatencyMs": round(lat_sum / n, 1), "maxLatencyMs": round(lat_max, 1),
        "oosAvgTopScore": round(sum(r["topScore"] for r in oos_rows) / len(oos_rows), 4) if oos_rows else None,
        "perCategory": per_category,
        "cases": rows, "oos": oos_rows,
    }


def main():
    modes = ["dense", "bm25", "hybrid", "rerank"]
    top_k = 5
    cases_path: Path | None = None
    label = "base"
    for a in sys.argv[1:]:
        if a.startswith("--modes="):
            modes = [m.strip() for m in a.split("=", 1)[1].split(",") if m.strip()]
        elif a.startswith("--topk="):
            top_k = int(a.split("=", 1)[1])
        elif a.startswith("--cases="):
            key = a.split("=", 1)[1].strip()
            if key == "ext":
                cases_path = CASES_EXT
                label = "extended"
            elif key == "both":
                cases_path = None
                label = "both"
            else:
                cases_path = Path(key)
                label = Path(key).stem

    base_ans, base_oos = load_cases()
    if label == "both":
        ext_ans, ext_oos = load_cases(CASES_EXT)
        ans = base_ans + ext_ans
        oos = base_oos + ext_oos
    else:
        ans, oos = load_cases(cases_path)

    print(f"retrieval-eval: modes={modes} topK={top_k} cases={len(ans)}+{len(oos)} set={label}")

    results = []
    print(f"\n{'模式':<10}{'Hit@1':>9}{'Hit@3':>9}{'Hit@5':>9}{'MRR':>10}{'NDCG@K':>10}{'MAP':>9}{'平均延迟':>12}{'越界top':>10}")
    print("-" * 88)
    for mode in modes:
        try:
            r = evaluate(mode, ans, oos, top_k=top_k)
        except Exception as exc:
            print(f"{mode:<10} ERROR {type(exc).__name__}: {str(exc)[:120]}")
            continue
        results.append(r)
        print(f"{mode:<10}{r['hitRateAt1']:>9.1%}{r['hitRateAt3']:>9.1%}{r['hitRateAt5']:>9.1%}"
              f"{r['mrr']:>10.4f}{r['ndcgAtK']:>10.4f}{r['map']:>9.4f}"
              f"{str(r['avgLatencyMs']) + 'ms':>12}{str(r['oosAvgTopScore']):>10}")

    # 分类别对比
    if results:
        cats = sorted(results[0].get("perCategory", {}).keys())
        if cats:
            print(f"\n分类别 Hit@1（{' / '.join(r['mode'] for r in results)}）：")
            print(f"{'类别':<16}{'条数':>6}" + "".join(f"{r['mode']:>10}" for r in results))
            for cat in cats:
                line = f"{cat:<16}{results[0]['perCategory'][cat]['total']:>6}"
                for r in results:
                    line += f"{r['perCategory'][cat]['hitRateAt1']:>10.1%}"
                print(line)

    out = Path(__file__).with_name(
        "eval-retrieval-result.json" if label != "extended" else "eval-retrieval-result-extended.json")
    out.write_text(json.dumps({"topK": top_k, "caseSet": label, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
