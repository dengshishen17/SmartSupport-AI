# -*- coding: utf-8 -*-
"""tool_runtime 可靠性层的离线单元测试。

覆盖：超时、重试、熔断、半开恢复、并发限流、并行执行、降级话术。
不调用任何外部服务，零 API 消耗。

运行：python -m eval.test_tool_runtime
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tool_runtime import (  # noqa: E402
    CircuitBreaker,
    ToolCallResult,
    ToolExecutor,
)


def test_success_normal():
    async def main():
        ex = ToolExecutor(timeout=1.0, retries=0)
        r = await ex.execute("ok_tool", {"a": 1}, lambda a: "结果正常")
        assert r.ok is True
        assert r.result == "结果正常"
        assert r.degraded is False
        assert r.attempts == 1
        assert r.duration_ms >= 0

    asyncio.run(main())


def test_timeout_degrades():
    async def main():
        ex = ToolExecutor(timeout=0.2, retries=0)

        async def slow(a):
            await asyncio.sleep(5)

        t0 = time.perf_counter()
        r = await ex.execute("slow_tool", {}, slow)
        elapsed = time.perf_counter() - t0
        assert r.ok is False
        assert r.degraded is True
        assert "超时" in r.result
        assert elapsed < 2.0, f"超时未生效，耗时 {elapsed:.2f}s"

    asyncio.run(main())


def test_sync_blocking_function_is_interrupted_by_timeout():
    """同步阻塞函数也必须被超时打断。

    回归用例：业务工具是同步的阻塞式 DB 查询，若直接调用会卡住事件循环，
    asyncio.wait_for 完全无法中断它（实测 0.5s 超时实际跑了 3s）。
    修正方案：同步函数放到线程池执行（asyncio.to_thread），
    线程无法强杀，但 wait_for 会放弃等待并返回超时降级话术，
    主事件循环得以恢复。
    """
    async def main():
        ex = ToolExecutor(timeout=0.3, retries=0)

        def blocking(a):
            time.sleep(2.0)
            return "不该被拿到"

        t0 = time.perf_counter()
        r = await ex.execute("blocking", {}, blocking)
        elapsed = time.perf_counter() - t0
        assert r.ok is False
        assert r.degraded is True
        assert "超时" in r.result
        assert elapsed < 1.0, f"同步函数超时未生效，耗时 {elapsed:.2f}s"

    asyncio.run(main())


def test_sync_function_result_still_available():
    """同步函数正常执行时结果要能拿到（线程池不能改变语义）。"""
    async def main():
        ex = ToolExecutor(timeout=2.0, retries=0)
        r = await ex.execute("sync_ok", {"x": 1}, lambda a: f"参数{a['x']}")
        assert r.ok is True
        assert r.result == "参数1"

    asyncio.run(main())


def test_retry_then_success():
    async def main():
        ex = ToolExecutor(timeout=1.0, retries=2, backoff=0.01)
        state = {"n": 0}

        def flaky(a):
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("临时抖动")
            return "成功"

        r = await ex.execute("flaky", {}, flaky)
        assert r.ok is True
        assert r.attempts == 3
        assert state["n"] == 3

    asyncio.run(main())


def test_retry_exhausted_degrades():
    async def main():
        ex = ToolExecutor(timeout=1.0, retries=2, backoff=0.01)

        def always_fail(a):
            raise RuntimeError("一直失败")

        r = await ex.execute("bad", {}, always_fail)
        assert r.ok is False
        assert r.degraded is True
        assert r.attempts == 3
        assert "执行失败" in r.result

    asyncio.run(main())


def test_tool_returning_unavailable_counts_as_failure():
    """工具自己返回「暂时不可用」应计入失败并触发熔断计数。"""
    async def main():
        ex = ToolExecutor(timeout=1.0, retries=0)

        def unavailable(a):
            return "订单库暂时不可用（boom）"

        r = await ex.execute("unavail", {}, unavailable)
        assert r.ok is False
        assert r.degraded is True
        assert ex.breaker.snapshot()["unavail"]["failures"] == 1

    asyncio.run(main())


def test_circuit_breaker_opens():
    async def main():
        ex = ToolExecutor(timeout=1.0, retries=0, breaker=CircuitBreaker(threshold=3, cooldown_seconds=60))

        def fail(a):
            raise RuntimeError("x")

        for _ in range(3):
            await ex.execute("cb", {}, fail)

        snap = ex.breaker.snapshot()["cb"]
        assert snap["state"] == "OPEN", snap
        assert snap["failures"] >= 3

        # 熔断后应快速失败，不再真正执行
        called = {"n": 0}

        def track(a):
            called["n"] += 1
            raise RuntimeError("x")

        r = await ex.execute("cb", {}, track)
        assert r.ok is False
        assert "熔断" in r.result
        assert called["n"] == 0, "熔断状态下不应再执行工具"

    asyncio.run(main())


def test_circuit_breaker_half_open_recovers():
    async def main():
        br = CircuitBreaker(threshold=2, cooldown_seconds=0.2)
        br.record_failure("h")
        br.record_failure("h")
        assert br._state("h") == "OPEN"

        await asyncio.sleep(0.25)
        assert br._state("h") == "HALF_OPEN"

        br.record_success("h")
        assert br._state("h") == "CLOSED"
        assert br.snapshot()["h"]["failures"] == 0

    asyncio.run(main())


def test_parallel_execution_is_faster_than_serial():
    """并行执行多个慢工具，耗时应接近单个而不是累加。"""
    async def main():
        ex = ToolExecutor(timeout=2.0, retries=0)

        async def slow(a):
            await asyncio.sleep(0.3)
            return "ok"

        calls = [("t%d" % i, {}, slow) for i in range(5)]
        t0 = time.perf_counter()
        results = await ex.execute_many(calls)
        elapsed = time.perf_counter() - t0

        assert len(results) == 5
        assert all(r.ok for r in results)
        # 串行需 1.5s，并行约 0.3s
        assert elapsed < 1.0, f"并行未生效，耗时 {elapsed:.2f}s"

    asyncio.run(main())


def test_concurrency_limit():
    """并发限流：同时执行的工具数不超过设定上限。"""
    async def main():
        ex = ToolExecutor(timeout=2.0, retries=0, max_concurrency=2)
        active = {"now": 0, "peak": 0}

        async def tracked(a):
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
            await asyncio.sleep(0.15)
            active["now"] -= 1
            return "ok"

        calls = [("t%d" % i, {}, tracked) for i in range(6)]
        await ex.execute_many(calls)
        assert active["peak"] <= 2, f"并发峰值 {active['peak']} 超过上限 2"

    asyncio.run(main())


def test_stats_tracked():
    async def main():
        ex = ToolExecutor(timeout=1.0, retries=0)

        await ex.execute("a", {}, lambda x: "ok")

        def boom(x):
            raise RuntimeError("挂了")

        await ex.execute("b", {}, boom)

        s = ex.stats
        assert s["totalCalls"] == 2
        assert s["degradedCalls"] == 1
        assert s["degradedRate"] == 0.5
        # 失败的工具应出现在熔断器快照里
        assert "b" in s["breaker"]

    asyncio.run(main())


def test_event_shape():
    """to_event 产出的事件结构应含耗时与降级标记。"""
    r = ToolCallResult(name="t", args={"x": 1}, result="ok", ok=True,
                       duration_ms=12.34, attempts=1)
    ev = r.to_event("result")
    assert ev["stage"] == "result"
    assert ev["toolName"] == "t"
    assert ev["durationMs"] == 12.3
    assert ev["ok"] is True
    assert ev["degraded"] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
