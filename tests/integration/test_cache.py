"""HTTP 缓存测试（规划书 §26）。

缓存的价值全在「省掉一次真实请求」，所以这里不满足于测存取往返 ——
还要测**命中时确实没有走网络**：把 mock 站点关掉之后再取一次，
能拿到内容才算数。
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

import pytest

from inkflow_api.services import SqliteHttpCache
from inkflow_api.state import AppState, build_state
from inkflow_core.config import Settings
from inkflow_core.paths import InkFlowPaths
from inkflow_core.storage import sqlite_url
from inkflow_source.http import HttpClient, HttpResponse
from inkflow_source.loader import SourceLoader
from inkflow_source.registry import SourceRegistry

pytestmark = pytest.mark.integration


def _response(*, body: bytes = b"<html>ok</html>", url: str = "http://x/1") -> HttpResponse:
    return HttpResponse(
        url=url,
        status=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=body,
    )


def _build(settings: Settings, tmp_path) -> AppState:
    """按给定配置装配一个隔离的 AppState。"""
    paths = InkFlowPaths(tmp_path / "home").ensure()
    return build_state(
        settings,
        paths=paths,
        database_url=sqlite_url(paths.database_dir / "test.db"),
        registry=SourceRegistry(),
        loader=SourceLoader(),
    )


@pytest.fixture
def cache(state: AppState) -> SqliteHttpCache:
    """默认配置下的缓存实例（无容量上限、无 TTL）。"""
    assert state.cache is not None
    return state.cache


# ================================================================ 存取往返


async def test_miss_returns_none(cache: SqliteHttpCache) -> None:
    """没有写过的 key 应当返回 None，而不是抛错。"""
    assert await cache.get("nope") is None


async def test_set_then_get_roundtrip(cache: SqliteHttpCache) -> None:
    """状态、响应头、正文都要原样取回。"""
    await cache.set("k", _response())

    hit = await cache.get("k")

    assert hit is not None
    assert hit.status == 200
    assert hit.content == b"<html>ok</html>"
    assert hit.headers["content-type"] == "text/html; charset=utf-8"
    assert hit.url == "http://x/1"


async def test_hit_is_flagged_as_from_cache(cache: SqliteHttpCache) -> None:
    """``from_cache`` 必须为真 —— 调用方靠它区分「拿到的是旧数据」。"""
    await cache.set("k", _response())
    hit = await cache.get("k")

    assert hit is not None
    assert hit.from_cache is True


async def test_first_write_is_not_flagged(cache: SqliteHttpCache) -> None:
    """原始响应（未经缓存）不该带 ``from_cache``。"""
    assert _response().from_cache is False


async def test_overwrite_replaces_previous(cache: SqliteHttpCache) -> None:
    """同一个 key 重复写入应当覆盖，而不是堆出两条。"""
    await cache.set("k", _response(body=b"old"))
    await cache.set("k", _response(body=b"new"))

    hit = await cache.get("k")

    assert hit is not None
    assert hit.content == b"new"
    assert cache.stats()["entries"] == 1


# ================================================================ 过期


async def test_expired_entry_is_not_served(cache: SqliteHttpCache) -> None:
    """TTL 为 0 的条目立刻过期。"""
    await cache.set("k", _response(), ttl=0)

    assert await cache.get("k") is None


async def test_expired_entry_is_removed(cache: SqliteHttpCache) -> None:
    """读到过期条目时顺手删掉，不必等后台清扫。"""
    await cache.set("k", _response(), ttl=0)
    assert cache.stats()["entries"] == 1

    await cache.get("k")

    assert cache.stats()["entries"] == 0


async def test_none_ttl_never_expires(state: AppState) -> None:
    """TTL 为 None 表示不过期 —— 与 0 是两回事。"""
    cache = SqliteHttpCache(state.db, default_ttl=None)
    await cache.set("k", _response())

    hit = await cache.get("k")

    assert hit is not None


async def test_ttl_argument_overrides_default(state: AppState) -> None:
    """调用方传的 TTL 优先于构造时的默认值。"""
    cache = SqliteHttpCache(state.db, default_ttl=3600)
    await cache.set("k", _response(), ttl=0)

    assert await cache.get("k") is None


async def test_default_ttl_applies_when_argument_omitted(state: AppState) -> None:
    cache = SqliteHttpCache(state.db, default_ttl=3600)
    await cache.set("k", _response())

    assert await cache.get("k") is not None


async def test_expiry_is_measured_from_now(state: AppState, monkeypatch) -> None:
    """TTL 到了就失效，没到就还能用。"""
    from inkflow_api.services import cache as cache_module

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    monkeypatch.setattr(cache_module, "utcnow", lambda: clock["now"])

    cache = SqliteHttpCache(state.db, default_ttl=60)
    await cache.set("k", _response())

    clock["now"] += timedelta(seconds=59)
    assert await cache.get("k") is not None

    clock["now"] += timedelta(seconds=2)
    assert await cache.get("k") is None


# ================================================================ 容量淘汰


async def test_no_limit_never_evicts(state: AppState) -> None:
    """不设上限就不淘汰 —— 默认配置是 2GB，正常用不到。"""
    cache = SqliteHttpCache(state.db, max_size_bytes=None)

    for index in range(20):
        await cache.set(f"k{index}", _response(body=b"x" * 100))

    assert cache.stats()["entries"] == 20


async def test_eviction_keeps_total_within_limit(state: AppState, monkeypatch) -> None:
    """写入超过上限时，总量要被压回上限以内。"""
    from inkflow_api.services import cache as cache_module

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    monkeypatch.setattr(cache_module, "utcnow", lambda: clock["now"])

    # 每条 10 字节，上限 25 → 最多容纳 2 条
    cache = SqliteHttpCache(state.db, max_size_bytes=25)

    for index in range(5):
        clock["now"] += timedelta(seconds=1)
        await cache.set(f"k{index}", _response(body=b"x" * 10))

    stats = cache.stats()
    assert stats["entries"] == 2
    assert stats["size_bytes"] <= 25


async def test_lru_evicts_stalest_first(state: AppState, monkeypatch) -> None:
    """淘汰的是最久没被用到的那个，不是最近写入的。"""
    from inkflow_api.services import cache as cache_module

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    monkeypatch.setattr(cache_module, "utcnow", lambda: clock["now"])

    cache = SqliteHttpCache(state.db, max_size_bytes=25)

    for index in range(3):
        clock["now"] += timedelta(seconds=1)
        await cache.set(f"k{index}", _response(body=b"x" * 10))

    assert await cache.get("k0") is None  # 最旧的先走
    assert await cache.get("k1") is not None
    assert await cache.get("k2") is not None


async def test_hit_protects_entry_from_eviction(state: AppState, monkeypatch) -> None:
    """命中过的条目会更晚被淘汰 —— LRU 的「U」在这里体现。"""
    from inkflow_api.services import cache as cache_module

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    monkeypatch.setattr(cache_module, "utcnow", lambda: clock["now"])

    cache = SqliteHttpCache(state.db, max_size_bytes=25)

    clock["now"] += timedelta(seconds=1)
    await cache.set("k0", _response(body=b"x" * 10))
    clock["now"] += timedelta(seconds=1)
    await cache.set("k1", _response(body=b"x" * 10))

    clock["now"] += timedelta(seconds=1)
    await cache.get("k0")  # k0 被用到，比 k1 新鲜

    clock["now"] += timedelta(seconds=1)
    await cache.set("k2", _response(body=b"x" * 10))  # 超限，该淘汰谁？

    assert await cache.get("k1") is None  # 没被用过的 k1 先走
    assert await cache.get("k0") is not None


# ================================================================ 运维接口


async def test_clear_removes_everything(cache: SqliteHttpCache) -> None:
    for index in range(3):
        await cache.set(f"k{index}", _response())

    removed = cache.clear()

    assert removed == 3
    assert cache.stats()["entries"] == 0


async def test_clear_on_empty_cache_is_zero(cache: SqliteHttpCache) -> None:
    assert cache.clear() == 0


async def test_stats_reports_expired_count(cache: SqliteHttpCache) -> None:
    """过期条目在统计里单独计数，便于判断缓存是否在正常周转。"""
    await cache.set("live", _response(), ttl=3600)
    await cache.set("dead", _response(), ttl=0)

    stats = cache.stats()

    assert stats["entries"] == 2
    assert stats["expired_entries"] == 1


async def test_stats_includes_configured_limit(state: AppState) -> None:
    cache = SqliteHttpCache(state.db, max_size_bytes=1024)

    assert cache.stats()["max_size_bytes"] == 1024


async def test_corrupt_headers_fall_back_to_empty(state: AppState) -> None:
    """库里存了坏 JSON 时不该把请求打挂。"""
    cache = SqliteHttpCache(state.db)
    await cache.set("k", _response())

    # 直接把 headers 写坏，模拟旧版本数据或人为损坏
    from inkflow_core.storage.tables import HttpCacheRow

    with state.db.session() as session:
        row = session.get(HttpCacheRow, "k")
        assert row is not None
        row.headers = "{ 这不是 JSON"

    hit = await cache.get("k")

    assert hit is not None
    assert hit.headers == {}


# ================================================================ 装配接线


def test_cache_is_built_by_default(state: AppState) -> None:
    """默认配置开启缓存。"""
    assert state.cache is not None
    assert state.cache_info()["enabled"] is True


def test_disabled_cache_is_not_built(tmp_path) -> None:
    settings = Settings()
    settings.cache.enabled = False

    built = _build(settings, tmp_path)

    assert built.cache is None
    assert built.cache_info()["enabled"] is False


def test_zero_ttl_disables_cache(tmp_path) -> None:
    """TTL 为 0 等于不缓存 —— 写进去立刻过期只会白占空间。"""
    settings = Settings()
    settings.cache.http_ttl = 0

    built = _build(settings, tmp_path)

    assert built.cache is None


def test_cache_info_shape_is_stable_when_disabled(tmp_path) -> None:
    """未启用时字段形状保持一致，客户端不需要分支处理。"""
    settings = Settings()
    settings.cache.enabled = False

    info = _build(settings, tmp_path).cache_info()

    assert set(info) == {
        "enabled",
        "entries",
        "size_bytes",
        "expired_entries",
        "max_size_bytes",
    }


def test_system_info_exposes_cache(state: AppState) -> None:
    info = state.system_info()

    assert "cache" in info
    assert info["cache"]["enabled"] is True  # type: ignore[index]


def test_max_size_comes_from_config(tmp_path) -> None:
    settings = Settings()
    settings.cache.max_size = "1MB"

    built = _build(settings, tmp_path)

    assert built.cache is not None
    assert built.cache.max_size_bytes == 1024 * 1024


# ================================================================ HTTP 客户端策略


class _RecordingCache:
    """记录调用的假缓存，用来观察 HttpClient 的缓存策略。"""

    def __init__(self) -> None:
        self.gets: list[str] = []
        self.sets: list[str] = []

    async def get(self, key: str) -> HttpResponse | None:
        self.gets.append(key)
        return None

    async def set(self, key: str, response: HttpResponse, *, ttl: int | None = None) -> None:
        self.sets.append(key)


async def test_get_consults_cache(mock_site: str) -> None:
    recorder = _RecordingCache()

    async with HttpClient(cache=recorder, allow_private_network=True) as client:
        await client.get(f"{mock_site}/book/1")

    assert len(recorder.gets) == 1
    assert len(recorder.sets) == 1


async def test_post_bypasses_cache(mock_site: str) -> None:
    """POST 有副作用，复用旧响应会得到错误结果 —— 必须绕过缓存。"""
    recorder = _RecordingCache()

    async with HttpClient(cache=recorder, allow_private_network=True) as client:
        await client.post(f"{mock_site}/search")

    assert recorder.gets == []
    assert recorder.sets == []


async def test_use_cache_false_bypasses_cache(mock_site: str) -> None:
    """调用方显式要求不走缓存时（例如强制刷新），一个调用都不该发。"""
    recorder = _RecordingCache()

    async with HttpClient(cache=recorder, allow_private_network=True) as client:
        await client.get(f"{mock_site}/book/1", use_cache=False)

    assert recorder.gets == []
    assert recorder.sets == []


async def test_no_cache_configured_is_noop(mock_site: str) -> None:
    """没注入缓存时照常请求，不该因为「想缓存却没得缓存」而报错。"""
    async with HttpClient(allow_private_network=True) as client:
        response = await client.get(f"{mock_site}/book/1")

    assert response.status == 200


# ================================================================ 端到端：真的省掉了请求


async def test_cache_hit_does_not_touch_network(state: AppState) -> None:
    """把站点关掉之后仍能取到内容 —— 这才叫「省掉了一次请求」。

    只断言 ``from_cache`` 是不够的：那个标志由我们自己设置，
    设错了测试照样绿。断掉网络之后还能拿到内容，才是真的没走网络。
    """
    from tests.mock_server import start_mock_site

    site = start_mock_site()
    cache = SqliteHttpCache(state.db, default_ttl=3600)

    try:
        async with HttpClient(cache=cache, allow_private_network=True) as client:
            first = await client.get(f"{site.url}/book/1")
            assert first.status == 200
            assert first.from_cache is False

            site.stop()  # 站点下线

            second = await client.get(f"{site.url}/book/1")
            assert second.from_cache is True
            assert second.content == first.content
    finally:
        with contextlib.suppress(Exception):
            site.stop()


async def test_different_urls_are_cached_separately(state: AppState) -> None:
    """缓存键含 URL —— 不同地址不能互相串味。"""
    from tests.mock_server import start_mock_site

    site = start_mock_site()
    cache = SqliteHttpCache(state.db, default_ttl=3600)

    try:
        async with HttpClient(cache=cache, allow_private_network=True) as client:
            await client.get(f"{site.url}/book/1")
            await client.get(f"{site.url}/search")

        assert cache.stats()["entries"] == 2
    finally:
        site.stop()
