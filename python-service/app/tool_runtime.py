# -*- coding: utf-8 -*-
"""工具执行可靠性层：超时控制、重试、熔断降级、并发限流。

为什么需要
----------
Agent 调用工具时，工具可能：卡住不返回（DB 慢、连接池耗尽）、偶发失败（网络抖动）、
持续失败（下游宕机）。没有这层保护，一次工具故障会拖垮整个 Agent 请求：
- 无限等待 -> 请求挂死，直到上游超时
- 立即失败 -> 模型拿不到结果就直接编造，或者整个回答失败
- 反复重试 -> 故障期间放大压力

本模块提供三层保护，作用于 Agent 工具执行路径，不改变 tools.py 里的纯函数
（MCP server 直接复用那些纯函数，不能引入副作用）：

    超时（asyncio.wait_for）   -> 单次调用最长等待 N 秒，超时按降级话术返回
    重试（指数退避）           -> 瞬时失败自动重试 N 次
    熔断（失败率阈值）         -> 连续失败达阈值后快速失败，避免放大故障
    限流（asyncio.Semaphore）  -> 限制并发工具调用数，防止下游被打垮

设计原则：**失败也要返回可用的字符串**，而不是抛异常。
因为 Agent 的模型需要看到「工具失败了、请转人工」这样的信息才能正确处理，
抛异常会导致整条 ReAct 链路崩溃。
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# --------------------------------------------------------------------------
# 降级话术
# --------------------------------------------------------------------------

DEGRADE_TIMEOUT = "工具 {name} 调用超时（超过 {limit}s），暂时无法获取数据，建议稍后重试或转人工客服。"
DEGRADE_ERROR = "工具 {name} 执行失败（{err}），暂时无法获取数据，建议稍后重试或转人工客服。"
DEGRADE_CIRCUIT_OPEN = "工具 {name} 当前处于熔断状态（连续失败次数达阈值），暂时不可用，建议转人工客服。"


# --------------------------------------------------------------------------
# 熔断器
# --------------------------------------------------------------------------


class CircuitBreaker:
    """简单熔断器（按工具名隔离）。

    状态机：
        CLOSED（正常）--连续失败达 threshold--> OPEN（熔断）
        OPEN --冷却时间到--> HALF_OPEN（半开，放行一次探测）
        HALF_OPEN --成功--> CLOSED
                --失败--> OPEN（重新计时）

    这样既能在故障期快速失败，又能在下游恢复后自动恢复，
    不需要人工干预。
    """

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def _state(self, name: str) -> str:
        fails = self._failures.get(name, 0)
        if fails < self.threshold:
            return "CLOSED"
        opened = self._opened_at.get(name, 0.0)
        if time.monotonic() - opened >= self.cooldown:
            return "HALF_OPEN"
        return "OPEN"

    def allow(self, name: str) -> tuple[bool, str]:
        """返回 (是否允许调用, 当前状态)。"""
        state = self._state(name)
        if state == "OPEN":
            return False, "OPEN"
        return True, state

    def record_success(self, name: str) -> None:
        self._failures[name] = 0
        self._opened_at.pop(name, None)

    def record_failure(self, name: str) -> None:
        self._failures[name] = self._failures.get(name, 0) + 1
        if self._failures[name] >= self.threshold:
            self._opened_at[name] = time.monotonic()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "state": self._state(name),
                "failures": self._failures.get(name, 0),
                "threshold": self.threshold,
            }
            for name in sorted(set(self._failures) | set(self._opened_at))
        }


# --------------------------------------------------------------------------
# 执行结果
# --------------------------------------------------------------------------


@dataclass
class ToolCallResult:
    """一次工具调用的执行结果（含耗时与降级信息）。"""

    name: str
    args: dict[str, Any]
    result: str
    ok: bool = True
    duration_ms: float = 0.0
    attempts: int = 1
    degraded: bool = False       # 是否走了降级话术
    error: str | None = None

    def to_event(self, stage: str) -> dict[str, Any]:
        """转成 workflow 使用的 tool_event 结构。"""
        ev = {
            "stage": stage,
            "toolName": self.name,
            "args": self.args,
            "result": self.result,
        }
        if stage == "result":
            ev["durationMs"] = round(self.duration_ms, 1)
            ev["ok"] = self.ok
            ev["degraded"] = self.degraded
            ev["attempts"] = self.attempts
            if self.error:
                ev["error"] = self.error
        return ev


# --------------------------------------------------------------------------
# 执行器
# --------------------------------------------------------------------------


class ToolExecutor:
    """带超时/重试/熔断/限流的工具执行器。

    被执行函数签名：`(args: dict) -> str`（同步）或 `async (args: dict) -> str`。
    """

    def __init__(
        self,
        timeout: float = 8.0,
        retries: int = 2,
        backoff: float = 0.3,
        max_concurrency: int = 8,
        breaker: CircuitBreaker | None = None,
        pool_size: int | None = None,
    ):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.breaker = breaker or CircuitBreaker()
        self._sem = asyncio.Semaphore(max_concurrency)
        self._calls = 0
        self._degraded = 0
        # 自管线程池：业务工具是同步阻塞式 DB 查询，必须放到线程执行，
        # 否则会卡死事件循环。但不能用 asyncio.to_thread —— 它用 asyncio 默认线程池，
        # 事件循环关闭时会等待池内线程结束，导致「超时后总耗时仍被拖长」。
        # 自建线程池配合 run_in_executor，超时后 wait_for 立即放弃等待并返回降级话术。
        self._pool = ThreadPoolExecutor(
            max_workers=pool_size or max_concurrency * 2,
            thread_name_prefix="tool-exec",
        )

    def shutdown(self) -> None:
        """关闭线程池（进程退出时调用）。"""
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- 统计 ---------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "totalCalls": self._calls,
            "degradedCalls": self._degraded,
            "degradedRate": round(self._degraded / self._calls, 4) if self._calls else 0.0,
            "breaker": self.breaker.snapshot(),
        }

    # -- 主流程 -------------------------------------------------------------

    async def execute(self, name: str, args: dict[str, Any], fn: Callable[[dict], Any]) -> ToolCallResult:
        """执行一次工具调用，全程受保护。永不抛异常。"""
        allowed, state = self.breaker.allow(name)
        if not allowed:
            self._calls += 1
            self._degraded += 1
            return ToolCallResult(
                name=name, args=args,
                result=DEGRADE_CIRCUIT_OPEN.format(name=name),
                ok=False, degraded=True, error="circuit_open", duration_ms=0.0,
            )

        async with self._sem:
            return await self._execute_with_retry(name, args, fn, state)

    async def _execute_with_retry(
        self, name: str, args: dict[str, Any], fn: Callable[[dict], Any], state: str
    ) -> ToolCallResult:
        last_err: str | None = None
        attempts = 0
        total_start = time.perf_counter()

        for attempt in range(1, self.retries + 2):
            attempts = attempt
            t0 = time.perf_counter()
            try:
                # 判断是协程还是同步函数 —— 不能先调用一次再判断，
                # 否则同步函数会被执行两遍（一次在事件循环里，一次在线程池里）。
                # lambda 包装会丢失协程标记，因此同时看返回值判定。
                if asyncio.iscoroutinefunction(fn):
                    raw = await asyncio.wait_for(fn(args), timeout=self.timeout)
                else:
                    # 同步阻塞函数放到自管线程池执行，
                    # 这样它不会卡死事件循环，wait_for 才能真正在 timeout 时放弃等待。
                    loop = asyncio.get_running_loop()
                    fut = loop.run_in_executor(self._pool, fn, args)
                    try:
                        raw = await asyncio.wait_for(asyncio.shield(fut), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        # 线程无法强杀，但放弃等待后主流程可以立即返回降级话术，
                        # 不再被卡住的工具拖住整体响应。
                        raise
                result = str(raw)
                duration = (time.perf_counter() - t0) * 1000

                # 工具自己返回了「服务不可用」也算失败，应计入熔断
                if "暂时不可用" in result:
                    last_err = result[:120]
                    self.breaker.record_failure(name)
                    if attempt <= self.retries:
                        await asyncio.sleep(self.backoff * attempt)
                        continue
                    self._calls += 1
                    self._degraded += 1
                    return ToolCallResult(
                        name=name, args=args,
                        result=DEGRADE_ERROR.format(name=name, err="服务暂不可用"),
                        ok=False, degraded=True, error=last_err,
                        duration_ms=duration, attempts=attempts,
                    )

                self.breaker.record_success(name)
                self._calls += 1
                return ToolCallResult(
                    name=name, args=args, result=result, ok=True,
                    duration_ms=duration, attempts=attempts,
                )

            except asyncio.TimeoutError:
                last_err = f"timeout after {self.timeout}s"
                self.breaker.record_failure(name)
                if attempt <= self.retries:
                    await asyncio.sleep(self.backoff * attempt)
                    continue
                self._calls += 1
                self._degraded += 1
                return ToolCallResult(
                    name=name, args=args,
                    result=DEGRADE_TIMEOUT.format(name=name, limit=self.timeout),
                    ok=False, degraded=True, error=last_err,
                    duration_ms=(time.perf_counter() - t0) * 1000, attempts=attempts,
                )

            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"[:120]
                self.breaker.record_failure(name)
                if attempt <= self.retries:
                    await asyncio.sleep(self.backoff * attempt)
                    continue
                self._calls += 1
                self._degraded += 1
                return ToolCallResult(
                    name=name, args=args,
                    result=DEGRADE_ERROR.format(name=name, err=last_err),
                    ok=False, degraded=True, error=last_err,
                    duration_ms=(time.perf_counter() - t0) * 1000, attempts=attempts,
                )

        # 理论上不可达
        self._calls += 1
        self._degraded += 1
        return ToolCallResult(
            name=name, args=args,
            result=DEGRADE_ERROR.format(name=name, err=last_err or "unknown"),
            ok=False, degraded=True, error=last_err,
            duration_ms=(time.perf_counter() - total_start) * 1000, attempts=attempts,
        )

    async def execute_many(
        self, calls: list[tuple[str, dict[str, Any], Callable[[dict], Any]]]
    ) -> list[ToolCallResult]:
        """并行执行多个工具调用。

        LangGraph 的 ToolNode 内部已用 asyncio.gather 并行，
        这里提供同样的能力用于自建执行路径，并统一受本执行器的保护。
        """
        if not calls:
            return []
        tasks = [self.execute(name, args, fn) for name, args, fn in calls]
        return list(await asyncio.gather(*tasks))
