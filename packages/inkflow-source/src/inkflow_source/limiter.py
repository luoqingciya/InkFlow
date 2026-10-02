"""并发与限速（规划书 §15）。

三级约束，取**最严**的一级生效：

    ┌─ 全局并发上限        （保护本机资源）
    ├─ 域名并发上限        （跨书源共享，保护目标站点）
    └─ 书源并发上限        （书源自带配置）

外加一个令牌桶做请求速率限制。书源配置只能收紧，不能放宽全局值 ——
否则一个写得激进的书源就能把整个进程拖垮。
"""

from __future__ import annotations

import asyncio
from time import monotonic

__all__ = ["ConcurrencyLimiter", "RequestGate", "TokenBucket"]


class TokenBucket:
    """异步令牌桶。

    Args:
        rate: 每秒补充的令牌数。
        capacity: 桶容量（允许的突发量）；省略时等于 ``max(1.0, rate)``。
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate 必须为正数")
        self.rate = rate
        self.capacity = capacity if capacity is not None else max(1.0, rate)
        self._tokens = self.capacity
        self._updated = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """取走令牌，不足时等待。

        等待在锁内进行，因此同速率下的请求严格按到达顺序放行（FIFO），
        不会出现某个请求被反复插队而饿死。
        """
        if tokens > self.capacity:
            tokens = self.capacity
        async with self._lock:
            while True:
                now = monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                await asyncio.sleep((tokens - self._tokens) / self.rate)


class ConcurrencyLimiter:
    """基于信号量的并发上限。"""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit 必须 >= 1")
        self.limit = limit
        self._sem = asyncio.Semaphore(limit)

    async def __aenter__(self) -> ConcurrencyLimiter:
        await self._sem.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._sem.release()

    @property
    def available(self) -> int:
        """当前可用额度。"""
        return self._sem._value


class RequestGate:
    """把三级并发与速率限制合成一个可等待对象。

    用法::

        async with gate.slot(url) as _:
            response = await client.get(url)
    """

    def __init__(
        self,
        *,
        global_concurrency: int = 16,
        domain_concurrency: int = 6,
        source_concurrency: int = 3,
        requests_per_second: float = 2.0,
    ) -> None:
        self.global_limiter = ConcurrencyLimiter(global_concurrency)
        self._domain_limit = domain_concurrency
        self._domain_limiters: dict[str, ConcurrencyLimiter] = {}
        # 单书源内部的并发上限，由调用方传入（每个 gate 实例对应一个书源）
        self.source_limiter = ConcurrencyLimiter(source_concurrency)
        self.bucket = TokenBucket(requests_per_second)

    def _domain_limiter(self, domain: str) -> ConcurrencyLimiter:
        """按域名取（或惰性建）并发限制器。

        域名数量有限，不设淘汰；若将来书源数量级增长再引入 LRU。
        """
        limiter = self._domain_limiters.get(domain)
        if limiter is None:
            limiter = ConcurrencyLimiter(self._domain_limit)
            self._domain_limiters[domain] = limiter
        return limiter

    @staticmethod
    def _domain_of(url: str) -> str:
        from urllib.parse import urlparse

        return (urlparse(url).hostname or "").lower()

    def slot(self, url: str) -> _GateSlot:
        """获取一个请求槽位（异步上下文管理器）。"""
        return _GateSlot(self, self._domain_of(url))


class _GateSlot:
    """``RequestGate.slot()`` 返回的异步上下文管理器。"""

    def __init__(self, gate: RequestGate, domain: str) -> None:
        self._gate = gate
        self._domain = domain
        self._stack: list[ConcurrencyLimiter] = []

    async def __aenter__(self) -> _GateSlot:
        # 顺序固定：全局 → 域名 → 书源 → 速率，避免死锁
        for limiter in (
            self._gate.global_limiter,
            self._gate._domain_limiter(self._domain),
            self._gate.source_limiter,
        ):
            await limiter.__aenter__()
            self._stack.append(limiter)
        await self._gate.bucket.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        # 逆序释放
        while self._stack:
            await self._stack.pop().__aexit__(*exc_info)
