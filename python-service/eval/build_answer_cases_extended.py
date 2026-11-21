# -*- coding: utf-8 -*-
"""从检索评测集生成「回答评测集」（answer-eval-cases-extended.json）。

背景
----
检索评测集（rag-eval-cases-extended.json）有 75 条可答用例 + 15 条越界探针，
但只有 query 与 expectedSections，**没有 reference（参考答案）**。
回答评测需要 reference 才能用 LLM-as-Judge 打「忠实度」分。

做法
----
1. 从 pgvector 载入全部 chunk，按 metadata.section 归组
2. 对每条可答用例，把其期望章节的正文提炼成 reference
   （取该章节正文的前 N 个句子，去掉 Markdown 标记）
3. 越界探针：reference 为空、should_refuse=true
4. 保留原有的 30 条标注用例（它们有精心写过的 reference），把扩展集追加进去

产物：backend/src/main/resources/eval/answer-eval-cases-extended.json

用法：python eval/build_answer_cases_extended.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app import vectorstore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAG_EXT = ROOT / "backend" / "src" / "main" / "resources" / "eval" / "rag-eval-cases-extended.json"
ANS_BASE = Path(__file__).with_name("answer-eval-cases.json")
ANS_EXT = ROOT / "backend" / "src" / "main" / "resources" / "eval" / "answer-eval-cases-extended.json"

# 参考答案取前几句
MAX_SENTENCES = 4
MAX_CHARS = 220


def clean(text: str) -> str:
    """去掉 Markdown 标记与多余空白。"""
    t = re.sub(r"^#+\s*", "", text, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s*", "", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；\n])", text)
    return [p.strip() for p in parts if p.strip()]


def load_sections() -> dict[str, str]:
    """载入语料，返回 {章节标题: 正文}。"""
    out: dict[str, str] = {}
    for content, meta in vectorstore.load_corpus():
        sec = (meta or {}).get("section")
        if not sec:
            for line in (content or "").split("\n"):
                if line.strip().startswith("## "):
                    sec = line.strip()[3:].strip()
                    break
        if not sec:
            continue
        # 同一章节可能被切成多段，拼接起来
        out[sec] = (out.get(sec, "") + "\n" + (content or "")).strip()
    return out


def build_reference(section_body: str) -> str:
    """从章节正文提炼参考答案。"""
    t = clean(section_body)
    ss = sentences(t)
    picked: list[str] = []
    total = 0
    for s in ss:
        if total + len(s) > MAX_CHARS and picked:
            break
        picked.append(s)
        total += len(s)
        if len(picked) >= MAX_SENTENCES:
            break
    ref = "".join(picked)
    return ref[:MAX_CHARS]


def main():
    rag = json.loads(RAG_EXT.read_text(encoding="utf-8"))
    base_ans = json.loads(ANS_BASE.read_text(encoding="utf-8"))["cases"]

    sections = load_sections()
    print(f"载入语料章节 {len(sections)} 个")

    # 已有 id 集合，避免与 30 条基线冲突
    existing_ids = {c["id"] for c in base_ans}
    existing_qs = {c["question"] for c in base_ans}

    built: list[dict] = []
    skipped_dup = 0
    for c in rag["cases"]:
        q = c["query"]
        if q in existing_qs:
            skipped_dup += 1
            continue
        exp = c.get("expectedSections") or []
        if not exp:
            # 越界探针
            built.append({
                "id": "x-" + c["id"],
                "category": "out_of_scope",
                "question": q,
                "reference": "",
                "expected_tool": "",
                "should_refuse": True,
            })
            continue
        # 取第一个期望章节的正文做 reference
        body = ""
        for s in exp:
            if s in sections:
                body = sections[s]
                break
        ref = build_reference(body) if body else ""
        built.append({
            "id": "x-" + c["id"],
            "category": _map_category(c.get("category", "")),
            "question": q,
            "reference": ref,
            "expected_tool": "",
            "should_refuse": False,
        })

    print(f"生成 {len(built)} 条（跳过与基线重复的 query {skipped_dup} 条）")

    out = {
        "description": "回答评测扩展集：基线 30 条 + 由检索评测集派生的用例。"
                       "reference 由知识库章节正文自动提炼，用于 LLM-as-Judge 忠实度打分。",
        "version": "extended-1",
        "cases": base_ans + built,
    }
    ANS_EXT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {ANS_EXT}")

    # 统计
    from collections import Counter
    print("类别分布:", dict(Counter(c["category"] for c in out["cases"])))
    no_ref = [c for c in built if not c["reference"] and not c["should_refuse"]]
    print(f"⚠ 无 reference 的可答用例：{len(no_ref)} 条")


def _map_category(cat: str) -> str:
    """把检索评测的类别名映射到回答评测的四类。"""
    c = (cat or "").strip()
    if c == "out_of_scope":
        return "out_of_scope"
    if "口语" in c or "改写" in c:
        return "colloquial"
    return "policy"


if __name__ == "__main__":
    main()
