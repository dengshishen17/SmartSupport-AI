# -*- coding: utf-8 -*-
"""把回答评测集的 reference 换成「从知识库章节正文提炼的详细要点」。

为什么必须重做
--------------
基线 30 条用例的 reference 是一句话摘要，例如：

    a-return-01 的 reference = 「创建售后工单选退货，经审核后退货」

但模型的实际回答会详细说明「七天无理由为签收后 7 个自然日、运费客户承担；
质量问题 15 日、运费我方承担……」这些**正确的**条款细节。
裁判拿一句话摘要去核对，模型答得越详细反而越像「出现了参考里没有的数字」，
于是被打成 faithful=0 —— 上一轮 114 条评测里 35 条 HALLUCINATION 全部是这个原因。

用完整章节正文重做 reference 后，同一条回答判为 faithful=1（已验证）。

做法
----
1. 从 pgvector 载入全部 chunk，按 metadata.section 归组
2. 对每条可答用例：
   - 用 expectedSections（回答集没有这个字段时用 id 语义匹配）找对应章节
   - 提炼该章节正文的多个要点作为 reference
3. 保留基线用例原有的 category / expected_tool / should_refuse 等字段，只换 reference

说明
----
回答评测集与检索评测集是同一套语料语义，因此可以直接复用检索评测集的
expectedSections 映射。匹配键：query 文本完全一致。

用法：python eval/upgrade_references.py
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
RAG_BASE = ROOT / "backend" / "src" / "main" / "resources" / "eval" / "rag-eval-cases.json"
ANS_BASE = Path(__file__).with_name("answer-eval-cases.json")
ANS_EXT = ROOT / "backend" / "src" / "main" / "resources" / "eval" / "answer-eval-cases-extended.json"

MAX_POINTS = 10
MAX_CHARS = 900


def clean(text: str) -> str:
    t = re.sub(r"^#+\s*", "", text, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s*", "", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def split_points(text: str) -> list[str]:
    """把章节正文切成要点句。"""
    t = clean(text)
    # 先按行/列表项切，再按句号切
    raw = re.split(r"[\n；;]|(?<=[。！？])", t)
    out: list[str] = []
    for p in raw:
        p = p.strip()
        if not p:
            continue
        if len(p) < 4:      # 太短的多半是标题碎片
            continue
        out.append(p)
    return out


def build_reference(body: str, max_chars: int | None = None,
                    query: str = "") -> str:
    """从章节正文提炼多条要点。

    query 非空时优先挑选与 query 关键词重合的要点 —— FAQ 这类章节里
    混着几十个问答，与问题无关的问答会把 reference 撑得很长却稀释信号。
    """
    limit = MAX_CHARS if max_chars is None else max_chars
    points = split_points(body)

    if query:
        scored = [(p, _match_score(p, query)) for p in points]
        # 有匹配的排前面（保持原有相对顺序），其余保持原序追加
        matched = [p for p, s in scored if s > 0]
        unmatched = [p for p, s in scored if s == 0]
        points = matched + unmatched

    picked: list[str] = []
    total = 0
    for p in points:
        if total + len(p) > limit and picked:
            break
        picked.append(p)
        total += len(p)
        if len(picked) >= MAX_POINTS:
            break
    return "；".join(picked)[:limit]


def _match_score(point: str, query: str) -> int:
    """要点与 query 的关键词重合度。"""
    q_chars = set(re.findall(r"[一-鿿]", query))
    p_chars = set(re.findall(r"[一-鿿]", point))
    if not q_chars:
        return 0
    return len(q_chars & p_chars)


def load_sections() -> dict[str, str]:
    """载入语料，返回 {章节标题: 该章节全部正文}。

    关键细节
    --------
    语料里有两类 chunk：
    1. 带 `metadata.section` 的（扩展语料 §7~§15 写入时带了这个字段）
    2. 只在正文首行有 `## 标题` 的（基础 6 章）
    3. **既没有 metadata.section、正文也没有 `## ` 标题的续接 chunk**
       —— 例如「1.3 退款金额口径」是「一、退款政策」的第 3 个分块，
       正文首行是 `### 1.3 ...`，只有 `###` 没有 `##`。

    如果只按 chunk 独立取标题，第 3 类会被直接丢掉，导致
    「退款金额怎么算」这类问题的 reference 里少了 1.3 的答案口径，
    裁判就会把模型的正确回答误判为编造。

    正确做法：按语料顺序遍历，**记住当前所处的 `## ` 章节**，
    后续没有新 `## ` 的 chunk 归入当前章节。
    """
    out: dict[str, str] = {}
    current = ""
    for content, meta in vectorstore.load_corpus():
        sec = (meta or {}).get("section")
        if not sec:
            # 正文里找 "## " 级标题；有则切换当前章节
            for line in (content or "").split("\n"):
                s = line.strip()
                if s.startswith("## "):
                    sec = s[3:].strip()
                    break
        if sec:
            # 显式章节 → 切换当前章节（后续无标题 chunk 归这里）
            current = sec
        elif current:
            # 续接 chunk → 归入当前章节
            sec = current
        if not sec:
            continue
        out[sec] = (out.get(sec, "") + "\n" + (content or "")).strip()
    return out


def load_query_to_sections() -> dict[str, list[str]]:
    """query → expectedSections 映射（合并 base 与 extended 两份检索评测集）。"""
    m: dict[str, list[str]] = {}
    for p in (RAG_BASE, RAG_EXT):
        if not p.exists():
            continue
        for c in json.loads(p.read_text(encoding="utf-8"))["cases"]:
            if c.get("expectedSections"):
                m[c["query"]] = c["expectedSections"]
    return m


# query 关键词 → 补充章节（检索评测集里没列，但回答确实会用到）
# 目的：让 reference 覆盖回答里引用的所有条款，避免裁判把「引用了别的章节的正确条款」
#       误判成编造。
EXTRA_SECTIONS_BY_KEYWORD = [
    (("发票", "开票"), "八、开票与发票政策"),
    (("优惠券", "叠加", "满减", "活动价", "秒杀"), "九、优惠券与活动规则"),
    (("价保", "保价", "降价"), "十、价格保护与价保规则"),
    (("运费", "配送", "自营", "邮费"), "十四、渠道与自营配送政策"),
    (("工单", "问题类型"), "五、售后工单问题类型汇总"),
    (("保修", "维修", "质保"), "四、保修规则"),
    (("换货",), "七、换货政策"),
    (("时效", "响应", "升级", "SLA"), "十二、服务等级与响应时效"),
]


def sections_for_query(query: str, expected: list[str]) -> list[str]:
    """给定 query 与期望章节，返回应该纳入 reference 的全部章节。

    排序原则：**政策正文优先，FAQ/归纳类靠后**。
    因为 FAQ 是对政策正文的复述，如果排在前面，裁判会把正文里的权威条款
    当成「参考里没有」而误判为编造。
    """
    out = list(expected)
    for keywords, sec in EXTRA_SECTIONS_BY_KEYWORD:
        if sec in out:
            continue
        if any(k in query for k in keywords):
            out.append(sec)

    def is_secondary(sec: str) -> bool:
        return any(m in sec for m in ("FAQ", "常见问题", "误区", "澄清", "快速参考", "小结", "汇总"))

    return sorted(out, key=lambda s: is_secondary(s))


def main():
    sections = load_sections()
    qmap = load_query_to_sections()
    print(f"语料章节 {len(sections)} 个；可映射 query {len(qmap)} 条")

    for path in (ANS_BASE, ANS_EXT):
        if not path.exists():
            print(f"跳过（不存在）: {path.name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = 0
        no_section = 0
        for c in data["cases"]:
            if c.get("should_refuse"):
                c["reference"] = ""
                continue
            exp = qmap.get(c["question"])
            if not exp:
                no_section += 1
                continue
            # 合并「期望章节」与「关键词命中的补充章节」，
            # 让 reference 覆盖回答里可能引用的全部条款
            secs = sections_for_query(c["question"], exp)
            bodies = [sections[s] for s in secs if s in sections]
            if not bodies:
                no_section += 1
                continue
            # 每章取前若干要点，合并成一条 reference
            refs = []
            total = 0
            for body in bodies:
                part = build_reference(body, max_chars=400, query=c["question"])
                if not part:
                    continue
                if total + len(part) > MAX_CHARS:
                    part = part[: max(0, MAX_CHARS - total)]
                if not part:
                    break
                refs.append(part)
                total += len(part)
                if total >= MAX_CHARS:
                    break
            new_ref = "；".join(refs)
            if new_ref and new_ref != c.get("reference"):
                c["reference"] = new_ref
                changed += 1
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {path.name}: 更新 reference {changed} 条；"
              f"无法定位章节（保留原 reference）{no_section} 条；"
              f"总用例 {len(data['cases'])}")


if __name__ == "__main__":
    main()
