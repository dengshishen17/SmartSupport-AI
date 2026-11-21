# -*- coding: utf-8 -*-
"""给评测集补上结构化的 distractorSections 字段。

背景
----
扩展评测集里的 `distractor` 字段是**自由文本描述**，人读得懂但程序用不了 —— 
NDCG 需要结构化的「哪些章节是干扰项」。

自由文本里的章节引用有两种写法：
    1. 全称形式：退货政策(二、退货政策)     → 直接包含标准标题
    2. 简写形式：保修(四)、换货(七)、FAQ(十一) → 只有序号

第 2 种是主要形式，序号与中文数字/阿拉伯数字的对应靠标题前缀（如「四、保修规则」
的序号是「四」）。因此本脚本做两步解析：

步骤 A：建立「序号 → 标准标题」映射
    扫全部语料章节标题，抽出前缀序号（「四」/「4」）与完整标题。
    序号归一化：中文数字与阿拉伯数字统一映射到 0..99 的整数。

步骤 B：在自由文本里找序号引用
    扫描形如「(四)」「（七）」「(二、退货政策)」「(11)」的括号引用，
    取出序号 → 反查标准标题；括号里带完整标题的直接用。

只做一次性数据补全，跑完幂等（已有 distractorSections 的用例不覆盖）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "backend" / "src" / "main" / "resources" / "eval" / "rag-eval-cases.json"
EXT = ROOT / "backend" / "src" / "main" / "resources" / "eval" / "rag-eval-cases-extended.json"

# 中文数字 → 阿拉伯数字
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
              "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13,
              "十四": 14, "十五": 15}

# 标题前缀：「四、保修规则」/「12. 快速参考表」/「（三）物流查询」
_PREFIX_RE = re.compile(r"^\s*[（(]?\s*([一二三四五六七八九十]+|\d{1,2})\s*[）)、.．:：]?\s*")
# 括号引用：「(四)」「（七）」「(二、退货政策)」「(11)」
_REF_RE = re.compile(r"[（(]\s*([^（()）]{1,20}?)\s*[）)]")


def norm_num(s: str) -> int | None:
    """把中文数字或阿拉伯数字统一成整数。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    return _CN_DIGITS.get(s)


def parse_section(title: str) -> tuple[int | None, str]:
    """拆出章节的序号与主体文字。"""
    m = _PREFIX_RE.match(title)
    if not m:
        return None, title.strip()
    num = norm_num(m.group(1))
    core = title[m.end():].strip()
    return num, core


def collect_sections(paths: list[Path]) -> tuple[list[str], dict[int, str]]:
    """返回 (标准标题列表, 序号→标题映射)。"""
    titles: set[str] = set()
    for p in paths:
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for c in data.get("cases", []):
            for s in c.get("expectedSections") or []:
                titles.add(s)

    by_num: dict[int, str] = {}
    for t in sorted(titles):
        num, _core = parse_section(t)
        if num is not None and num not in by_num:
            by_num[num] = t
    return sorted(titles), by_num


def resolve_refs(text: str, titles: list[str], by_num: dict[int, str]) -> list[str]:
    """从自由文本里解析出被引用的标准章节标题。"""
    found: list[str] = []

    # 1) 括号里带完整标题的：直接匹配标准标题
    for raw in _REF_RE.findall(text):
        raw = raw.strip()
        for t in titles:
            if raw == t or (len(raw) >= 3 and raw in t):
                if t not in found:
                    found.append(t)
        # 2) 括号里只有序号：反查
        num = norm_num(raw)
        if num is not None and num in by_num and by_num[num] not in found:
            found.append(by_num[num])

    # 3) 正文里裸写的序号引用：「保修(四)与换货(七)易混」已被上面覆盖；
    #    这里补「与FAQ(十一)」这类括号外的形式
    for raw in re.findall(r"(?:与|和|、|是)\s*([一二三四五六七八九十]{1,3})(?![章节项条])", text):
        num = norm_num(raw)
        if num is not None and num in by_num and by_num[num] not in found:
            found.append(by_num[num])

    return found


def enrich(path: Path, titles: list[str], by_num: dict[int, str]) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for c in data.get("cases", []):
        if c.get("distractorSections"):
            continue
        txt = c.get("distractor") or ""
        if not txt:
            continue
        hits = resolve_refs(txt, titles, by_num)
        expected = set(c.get("expectedSections") or [])
        # 期望章节本身不算干扰项
        hits = [h for h in hits if h not in expected]
        if hits:
            c["distractorSections"] = hits
            changed += 1
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main():
    titles, by_num = collect_sections([BASE, EXT])
    print(f"已知章节标题 {len(titles)} 个")
    print(f"序号映射 {len(by_num)} 条：")
    for num in sorted(by_num):
        print(f"  {num:>2} -> {by_num[num]}")

    for p in (BASE, EXT):
        if not p.exists():
            print(f"  跳过（不存在）：{p}")
            continue
        n = enrich(p, titles, by_num)
        print(f"  {p.name}: 补充 distractorSections 的用例数 = {n}")


if __name__ == "__main__":
    main()
