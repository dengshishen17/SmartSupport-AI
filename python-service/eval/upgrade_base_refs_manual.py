# -*- coding: utf-8 -*-
"""为无法从检索评测集映射到章节的 base 用例补上详细 reference。

背景
----
`upgrade_references.py` 靠「query 文本在检索评测集里完全一致」来定位章节，
但 base 30 条里有 3 条政策类用例（退款到账时长 / 退运费承担 / 工单问题类型）
其 query 不在检索评测集里，reference 仍是一句话摘要，导致裁判误判。

这 3 条的对应关系是明确的，直接手工映射到章节即可。

另外 12 条工具类用例（order/refund/ticket/warranty + 订单号）的 reference 描述的是
「工具应返回的真实数据」，本来就不是政策条款，保持原样即可 —— 裁判对这类
用例的判定依据是工具返回值而非政策文本。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from eval.upgrade_references import build_reference, load_sections  # noqa: E402

ANS_BASE = Path(__file__).with_name("answer-eval-cases.json")

# 手工映射：base 用例 id → 知识库章节标题
MANUAL_MAP = {
    "a-refund-02": ["一、退款政策"],        # 退款多久能到账
    "a-refund-03": ["二、退货政策", "七、换货政策"],  # 七天无理由退运费谁承担
    "a-ticket-01": ["五、售后工单问题类型汇总"],      # 工单问题类型有哪些
}


def main():
    sections = load_sections()
    data = json.loads(ANS_BASE.read_text(encoding="utf-8"))
    changed = 0
    for c in data["cases"]:
        secs = MANUAL_MAP.get(c["id"])
        if not secs:
            continue
        body = ""
        for s in secs:
            if s in sections:
                body = sections[s]
                break
        if not body:
            print(f"  ! {c['id']}: 章节 {secs} 不在语料中")
            continue
        ref = build_reference(body)
        if ref:
            c["reference"] = ref
            changed += 1
            print(f"  ✓ {c['id']}  ({len(ref)} 字)")
    ANS_BASE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n更新 {changed} 条")


if __name__ == "__main__":
    main()
