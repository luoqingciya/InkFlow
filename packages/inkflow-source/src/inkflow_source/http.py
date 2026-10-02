"""统一 HTTP 引擎（规划书 §16）。

**Source Adapter 不得自行创建 HTTP 客户端。** 所有出站请求都经过这里，
才能保证超时、重试、限速、安全校验、缓存、日志口径一致。

设计要点：

* 默认 ``follow_redirects=True`` —— 站点 302 跳转是常态，
  忘记跟随会得到空正文这种「看起来解析失败其实没拿到页面」的假故障。
* 重试只针对**可恢复**错误：连接错误、超时、429、5xx。
  4xx（除 429）直接失败，重试只是浪费配额。
* 退避带抖动，避免多个 worker 在同一时刻集体重试。
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Protocol

import httpx

from inkflow_core.errors import ErrorCode, SourceError
from inkflow_core.models import BookSource
from inkflow_source.limiter import RequestGate
from inkflow_source.security import check_url

__all__ = ["DEFAULT_USER_AGENT", "HttpCache", "HttpClient", "HttpResponse"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: 可重试的 HTTP 状态码
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})

_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE
)
_CONTENT_TYPE_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?([a-zA-Z0-9_\-]+)", re.IGNORECASE)

#: 中文站点常见的非 UTF-8 编码，按命中概率排序
_FALLBACK_ENCODINGS = ("utf-8", "gb18030", "big5", "shift_jis", "latin-1")


class HttpCache(Protocol):
    """HTTP 缓存接口。由调用方注入，未注入则不缓存。"""

    async def get(self, key: str) -> HttpResponse | None:
        """取缓存，未命中返回 ``None``。"""
        ...

    async def set(self, key: str, response: HttpResponse, *, ttl: int | None = None) -> None:
        """写缓存。"""
        ...


@dataclass(slots=True)
class HttpResponse:
    """统一的响应对象。

    不直接暴露 ``httpx.Response``，是为了让缓存层可以原样存取，
    也避免调用方依赖 httpx 的内部行为。
    """

    url: str
    status: int
    headers: dict[str, str]
    content: bytes
    elapsed: float = 0.0
    from_cache: bool = False
    encoding: str | None = None
    _text: str | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        """按探测出的编码解码正文。"""
        if self._text is None:
            self._text = self.content.decode(self.detected_encoding, errors="replace")
        return self._text

    @property
    def detected_encoding(self) -> str:
        """编码探测：Content-Type → meta 标签 → 逐候选试解 → latin-1 兜底。"""
        if self.encoding:
            return self.encoding

        content_type = self.headers.get("content-type", "")
        header_match = _CONTENT_TYPE_CHARSET_RE.search(content_type)
        if header_match:
            self.encoding = header_match.group(1)
            return self.encoding

        # 注意与上面的匹配分开命名：一个匹配 str，一个匹配 bytes
        head = self.content[:4096]
        meta_match = _META_CHARSET_RE.search(head)
        if meta_match:
            self.encoding = meta_match.group(1).decode("ascii", errors="ignore")
            return self.encoding

        for candidate in _FALLBACK_ENCODINGS:
            try:
                self.content.decode(candidate)
            except (UnicodeDecodeError, LookupError):
                continue
            self.encoding = candidate
            return candidate

        self.encoding = "latin-1"
        return self.encoding

    def json(self) -> Any:
        """解析 JSON 正文。"""
        import json as _json

        return _json.loads(self.text)


class HttpClient:
    """带限速、重试与安全校验的异步 HTTP 客户端。

    Args:
        timeout: 单次请求超时（秒）。
        retry: 失败重试次数（不含首次）。
        backoff: 退避基数，第 n 次重试等待 ``backoff * 2**(n-1)`` 秒再叠加抖动。
        gate: 三级限流闸门；省略则不限速（仅测试场景）。
        allow_private_network: 是否允许请求内网地址，默认否。
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retry: int = 3,
        backoff: float = 1.0,
        headers: dict[str, str] | None = None,
        gate: RequestGate | None = None,
        allow_private_network: bool = False,
        proxy: str | None = None,
        cache: HttpCache | None = None,
        cache_ttl: int | None = None,
    ) -> None:
        self.timeout = timeout
        self.retry = retry
        self.backoff = backoff
        self.gate = gate
        self.allow_private_network = allow_private_network
        self.cache = cache
        self.cache_ttl = cache_ttl

        default_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if headers:
            default_headers.update(headers)

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers=default_headers,
            follow_redirects=True,
            proxy=proxy,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )

    @classmethod
    def from_source(
        cls,
        source: BookSource,
        *,
        allow_private_network: bool = False,
        global_concurrency: int = 16,
        domain_concurrency: int = 6,
        cache: HttpCache | None = None,
        **overrides: Any,
    ) -> HttpClient:
        """按书源配置创建客户端。

        书源的并发 / 速率只会**收紧**全局值，不会放宽 —— 一个写得激进的
        书源不应该能拖垮整个进程。
        """
        config = source.request
        kwargs: dict[str, Any] = {
            "timeout": config.timeout,
            "retry": config.retry,
            "headers": dict(config.headers),
            "gate": RequestGate(
                global_concurrency=global_concurrency,
                domain_concurrency=domain_concurrency,
                source_concurrency=config.concurrency,
                requests_per_second=config.requests_per_second,
            ),
            "allow_private_network": allow_private_network,
            "cache": cache,
        }
        if config.user_agent:
            kwargs["headers"]["User-Agent"] = config.user_agent
        kwargs.update(overrides)
        return cls(**kwargs)

    # -- 请求 --------------------------------------------------------------

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
        json: Any = None,
        cookies: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> HttpResponse:
        """发起请求。

        Raises:
            UrlBlockedError: URL 未通过安全校验。
            SourceError: 重试耗尽后仍然失败。
        """
        await check_url(url, allow_private_network=self.allow_private_network)

        # 只缓存 GET：POST 之类有副作用，复用旧响应会得到错误结果
        cache = self.cache if (use_cache and method.upper() == "GET") else None
        cache_key = self._cache_key(method, url, params)

        if cache is not None:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        last_error: Exception | None = None
        for attempt in range(self.retry + 1):
            started = monotonic()
            try:
                if self.gate is not None:
                    async with self.gate.slot(url):
                        response = await self._client.request(
                            method,
                            url,
                            params=params,
                            headers=headers,
                            data=data,
                            json=json,
                            cookies=cookies,
                        )
                else:
                    response = await self._client.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        data=data,
                        json=json,
                        cookies=cookies,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < self.retry:
                    await self._sleep_backoff(attempt)
                    continue
                raise SourceError(
                    f"请求超时或连接失败：{url}",
                    code=ErrorCode.SOURCE_TIMEOUT,
                    details={"url": url, "attempts": attempt + 1, "error": str(exc)},
                ) from exc

            elapsed = monotonic() - started

            if response.status_code in RETRYABLE_STATUS and attempt < self.retry:
                last_error = SourceError(
                    f"服务端返回 {response.status_code}",
                    details={"url": url, "status": response.status_code},
                )
                await self._sleep_backoff(attempt, status=response.status_code)
                continue

            result = HttpResponse(
                url=str(response.url),
                status=response.status_code,
                headers={k.lower(): v for k, v in response.headers.items()},
                content=response.content,
                elapsed=elapsed,
            )

            if cache is not None and result.ok:
                await cache.set(cache_key, result, ttl=self.cache_ttl)

            return result

        # 理论不可达：循环内要么 return 要么 raise
        raise SourceError(
            f"请求失败：{url}",
            details={"url": url, "error": str(last_error)},
        )

    async def get(self, url: str, **kwargs: Any) -> HttpResponse:
        """GET 请求。"""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> HttpResponse:
        """POST 请求。"""
        return await self.request("POST", url, **kwargs)

    # -- 生命周期 ----------------------------------------------------------

    async def aclose(self) -> None:
        """关闭底层连接池。"""
        await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- 内部 --------------------------------------------------------------

    @staticmethod
    def _cache_key(method: str, url: str, params: dict[str, Any] | None) -> str:
        """缓存键 = sha256(method + url + 排序后的参数)。"""
        import hashlib

        raw = method.upper() + "|" + url + "|"
        if params:
            raw += "&".join(f"{k}={params[k]}" for k in sorted(params))
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _sleep_backoff(self, attempt: int, status: int | None = None) -> None:
        """指数退避 + 抖动。

        429 额外尊重 ``Retry-After`` 语义（这里用固定较长时间近似）。
        """
        delay = self.backoff * (2**attempt)
        if status == 429:
            delay = max(delay, 5.0)
        delay += random.uniform(0, delay * 0.25)
        await asyncio.sleep(delay)
