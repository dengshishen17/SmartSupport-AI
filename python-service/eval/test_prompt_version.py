# -*- coding: utf-8 -*-
"""app/prompts.py 版本管理相关单测：注册、查��、隔离、diff。

零 API 消耗。
    python python-service/eval/test_prompt_version.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import prompts  # noqa: E402


def _fresh():
    return prompts.PromptRegistry()


# --------------------------------------------------------------------------
# 注册与查询
# --------------------------------------------------------------------------

def test_register_returns_version():
    r = _fresh()
    pv = r.register("rag_system", "内容A", note="测试")
    assert pv.version == "v1"
    assert pv.note == "测试"
    assert len(pv.hash) == 12


def test_auto_increment_versions():
    r = _fresh()
    assert r.register("rag_system", "内容A").version == "v1"
    assert r.register("rag_system", "内容B").version == "v2"
    assert r.register("rag_system", "内容C").version == "v3"


def test_names_are_isolated():
    """不同用途的 Prompt 各自从 v1 开始，互不冲突。"""
    r = _fresh()
    a = r.register("rag_system", "A")
    b = r.register("fallback_system", "B")
    assert a.version == "v1"
    assert b.version == "v1"
    assert r.get("rag_system", "v1").content == "A"
    assert r.get("fallback_system", "v1").content == "B"


def test_same_content_reuses_version():
    """内容相同则复用旧版本，避免版本号虚增。"""
    r = _fresh()
    v1 = r.register("rag_system", "同样的内容")
    v2 = r.register("rag_system", "同样的内容")
    assert v1.version == v2.version
    assert v1.hash == v2.hash


def test_latest_tracks_registration():
    r = _fresh()
    r.register("rag_system", "A")
    r.register("rag_system", "B")
    assert r.latest("rag_system").content == "B"
    assert r.latest("rag_system").version == "v2"


def test_latest_missing_name_returns_none():
    r = _fresh()
    assert r.latest("不存在的名字") is None


def test_get_missing_returns_none():
    r = _fresh()
    assert r.get("rag_system", "v99") is None


def test_explicit_version_is_respected():
    r = _fresh()
    pv = r.register("rag_system", "内容", version="v5")
    assert pv.version == "v5"
    assert r.get("rag_system", "v5") is not None


def test_list_filters_by_name():
    r = _fresh()
    r.register("rag_system", "A")
    r.register("rag_system", "B")
    r.register("fallback_system", "C")
    assert len(r.list("rag_system")) == 2
    assert len(r.list("fallback_system")) == 1
    assert len(r.list()) == 3


def test_hash_is_stable_for_same_content():
    r = _fresh()
    a = r.register("x", "稳定内容")
    b = r.register("y", "稳定内容")
    assert a.hash == b.hash, "同内容不同 name 也应同 hash（内容哈希，不含 name）"


def test_hash_changes_with_content():
    r = _fresh()
    a = r.register("x", "内容A")
    b = r.register("x", "内容B")
    assert a.hash != b.hash


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

def test_diff_identical():
    r = _fresh()
    v1 = r.register("p", "相同")
    v2 = r.register("p", "相同")
    d = r.diff("p", v1.version, v2.version)
    assert d["ok"] is True
    assert d["identical"] is True


def test_diff_detects_added_lines():
    r = _fresh()
    r.register("p", "第一行\n第二行")
    v2 = r.register("p", "第一行\n第二行\n第三行")
    d = r.diff("p", "v1", v2.version)
    assert d["identical"] is False
    assert d["addedLines"] == 1
    assert d["removedLines"] == 0


def test_diff_detects_removed_lines():
    r = _fresh()
    r.register("p", "第一行\n第二行\n第三行")
    v2 = r.register("p", "第一行\n第三行")
    d = r.diff("p", "v1", v2.version)
    assert d["removedLines"] == 1, "删掉中间一行应识别为 1 处删除"
    assert d["addedLines"] == 0


def test_diff_missing_version_returns_error():
    r = _fresh()
    r.register("p", "A")
    d = r.diff("p", "v1", "v99")
    assert d["ok"] is False
    assert "error" in d


def test_diff_wrong_name_returns_error():
    r = _fresh()
    r.register("p", "A")
    d = r.diff("other", "v1", "v1")
    assert d["ok"] is False


# --------------------------------------------------------------------------
# 内置基线版本
# --------------------------------------------------------------------------

def test_baseline_rag_version_registered():
    assert prompts.BASELINE_RAG_V1.version == "v1"
    assert prompts.BASELINE_RAG_V1.meta.get("name") == "rag_system"
    assert "%s" in prompts.BASELINE_RAG_V1.content


def test_baseline_fallback_version_registered():
    assert prompts.BASELINE_FALLBACK_V1.version == "v1"
    assert prompts.BASELINE_FALLBACK_V1.meta.get("name") == "fallback_system"


def test_global_registry_has_baselines():
    assert prompts.latest_prompt("rag_system") is not None
    assert prompts.latest_prompt("fallback_system") is not None


def test_build_system_uses_template():
    out, hit = prompts.build_system([{"content": "退货政策内容"}])
    assert hit is True
    assert "退货政策内容" in out


def test_build_system_fallback_when_empty():
    out, hit = prompts.build_system([])
    assert hit is False
    assert out == prompts.FALLBACK_SYSTEM


def test_prompt_version_to_dict_shape():
    d = prompts.BASELINE_RAG_V1.to_dict()
    for key in ("version", "hash", "createdAt", "note", "meta"):
        assert key in d


def _run_all():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\ntest_prompt_version: {passed} passed, {failed} failed (total {len(fns)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
