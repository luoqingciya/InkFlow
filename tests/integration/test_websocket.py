"""WebSocket 进度通道测试（规划书 §28）。

这一层此前只有手动验证。手动验证的通病是：改坏了没人知道，
而 Desktop 的进度条是**唯一**依赖它的消费者 —— 所以必须自动化。

**为什么用两套驱动方式**

``TestClient`` 有个关键特性：每个 HTTP 请求都会新起一个 anyio portal
（即一个全新的事件循环），请求返回后循环即销毁；WebSocket 会话也跑在
自己的 portal 里。于是「用 REST 启动任务、再用 WebSocket 收进度」这种
真实用法在 ``TestClient`` 下**永远收不到事件** —— 下载协程所在的循环
和 WS 所在的循环不是同一个。

所以：

* 静态部分（快照形状、鉴权、任务不存在、连接关闭）用 ``TestClient``，
  便宜且足够。
* 流式部分（真的收到 progress / completed / status）用**真实 uvicorn
  服务器 + 真实 websocket 客户端**，这才是线上跑的样子。
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _Library, wait_for_terminal

pytestmark = pytest.mark.integration

WS_TIMEOUT = 30.0


# ================================================================ TestClient 部分


def _create_task(library: _Library, **overrides) -> str:
    payload = {"book_id": library.book_id, "output_format": "txt", **overrides}
    return library.client.post("/api/v1/tasks", json=payload).json()["id"]


def test_snapshot_is_sent_first(library: _Library) -> None:
    """连接建立后第一帧必须是 snapshot —— 客户端据此初始化进度条。

    不先给快照的话，客户端要么显示 0%，要么得额外发一次 REST 请求，
    而那个请求和 WebSocket 之间必然存在竞态。
    """
    task_id = _create_task(library, auto_start=False)

    with library.client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        first = ws.receive_json()

    assert first["type"] == "snapshot"
    assert first["task_id"] == task_id
    assert first["total"] == 6
    assert first["status"] == "PENDING"


def test_snapshot_has_full_progress_shape(library: _Library) -> None:
    """快照字段与 progress 事件保持一致，客户端可以共用一套解析逻辑。"""
    task_id = _create_task(library, auto_start=False)

    with library.client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        first = ws.receive_json()

    for key in ("task_id", "status", "completed", "failed", "total", "percent", "speed"):
        assert key in first, f"snapshot 缺少字段 {key}"


def test_terminal_task_closes_connection_immediately(library: _Library) -> None:
    """已完成的任务：发完 snapshot 就关连接，不让客户端干等。"""
    task_id = _create_task(library)
    wait_for_terminal(library.client, task_id)

    with library.client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["status"] == "COMPLETED"
        assert ws.receive()["type"] == "websocket.close"


def test_unknown_task_returns_4404(client: TestClient) -> None:
    """任务不存在时给 4404，而不是开一个永远没消息的连接。"""
    with client.websocket_connect("/ws/tasks/task_nope") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "TASK_NOT_FOUND"

        closed = ws.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4404


def test_auth_required_over_websocket(state) -> None:
    """鉴权开着时，匿名 WebSocket 连接应被 4401 拒掉。

    浏览器的 WebSocket API 不支持自定义头，所以 token 只能走查询参数 ——
    这条路径容易被漏掉，而漏掉的后果是**进度接口裸奔**。

    注意：拒绝发生在**握手阶段**，所以 ``websocket_connect`` 本身就抛
    ``WebSocketDisconnect``，而不是先进去再收一条错误消息。
    """
    from starlette.websockets import WebSocketDisconnect

    from inkflow_api.app import create_app

    app = create_app(state=state, require_token=True)
    with TestClient(app) as authed_off:
        with (
            pytest.raises(WebSocketDisconnect) as excinfo,
            authed_off.websocket_connect("/ws/tasks/task_anything"),
        ):
            pass  # pragma: no cover - 握不上手，进不来
        assert excinfo.value.code == 4401


def test_auth_accepts_token_via_query_param(state) -> None:
    """Token 走 ``?token=`` 时应放行（走到业务逻辑，而不是被 4401 拦掉）。"""
    from inkflow_api.app import create_app

    app = create_app(state=state, require_token=True)
    with TestClient(app) as authed_on:
        url = f"/ws/tasks/task_nope?token={state.session_token}"
        with authed_on.websocket_connect(url) as ws:
            message = ws.receive_json()
            # 能读到业务错误说明鉴权已通过
            assert message["code"] == "TASK_NOT_FOUND"


# ================================================================ Broker 语义


def test_broker_drops_oldest_event_when_queue_full() -> None:
    """队列满时丢最旧事件而不是阻塞下载器。

    进度是快照型数据，落后的事件没有价值；阻塞下载器则是真的会拖死任务。
    """
    from inkflow_api.services.downloader import ProgressBroker

    broker = ProgressBroker()
    queue = broker.subscribe("task_x", maxsize=3)

    for index in range(10):
        broker.publish("task_x", {"type": "progress", "completed": index})

    assert queue.qsize() == 3
    values = [queue.get_nowait()["completed"] for _ in range(3)]
    assert values == [7, 8, 9]


def test_unsubscribe_removes_subscriber() -> None:
    from inkflow_api.services.downloader import ProgressBroker

    broker = ProgressBroker()
    queue = broker.subscribe("task_y")
    assert broker.subscriber_count("task_y") == 1

    broker.unsubscribe("task_y", queue)
    assert broker.subscriber_count("task_y") == 0


def test_publish_without_subscribers_is_noop() -> None:
    """没有订阅者时 publish 不应报错（任务可能根本没人在看）。"""
    from inkflow_api.services.downloader import ProgressBroker

    broker = ProgressBroker()
    broker.publish("task_z", {"type": "progress"})


def test_subscribers_are_isolated_per_task() -> None:
    """订阅按 task_id 分组，不会串台。"""
    from inkflow_api.services.downloader import ProgressBroker

    broker = ProgressBroker()
    queue_a = broker.subscribe("task_a")
    queue_b = broker.subscribe("task_b")

    broker.publish("task_a", {"type": "progress", "completed": 1})

    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 0


# ================================================================ 真实服务器部分


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class LiveServer:
    """真实跑起来的 InkFlow 后端。"""

    base: str
    ws_base: str
    state: Any
    token: str


@pytest.fixture
def live_server(state) -> Iterator[LiveServer]:
    """在后台线程里起一个真实 uvicorn。

    这样 REST 与 WebSocket 共享同一个事件循环，下载产生的进度事件
    才能真的推到 WebSocket 上。
    """
    import uvicorn

    from inkflow_api.app import create_app

    port = _free_port()
    app = create_app(state=state, require_token=False)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:  # pragma: no cover
        raise RuntimeError("uvicorn 未能在 20s 内启动")

    base = f"http://127.0.0.1:{port}"
    try:
        yield LiveServer(
            base=base,
            ws_base=f"ws://127.0.0.1:{port}",
            state=state,
            token=state.session_token,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _run_in_thread(coro):
    """在独立线程里跑协程。

    测试函数本身是同步的，而 websockets 客户端是异步 API；
    再叠上 pytest-asyncio 的循环会让「同一循环」的假设变得含糊，
    所以干脆自己起一个干净的循环。
    """
    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # 原样回传给主线程
            result["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=90)
    if thread.is_alive():  # pragma: no cover
        raise AssertionError("协程超时未结束")
    if "error" in result:
        raise result["error"]
    return result["value"]


class _Session:
    """一次「导入书源 → 搜索 → 抓目录 → 建任务」的 HTTP 会话。"""

    def __init__(self, live: LiveServer, template: str) -> None:
        self.live = live
        self.template = template

    async def prepare(self) -> tuple[Any, str]:
        """返回 (httpx 客户端, book_id)。"""
        import httpx

        client = httpx.AsyncClient(base_url=self.live.base, timeout=30)
        await client.post("/api/v1/sources/import", json={"content": self.template})
        search = (await client.get("/api/v1/search", params={"q": "三体"})).json()
        selected = next(item for item in search["items"] if item["name"] == "三体")
        book_id = selected["sources"][0]["book_id"]
        await client.get(f"/api/v1/books/{book_id}/chapters", params={"refresh": True})
        return client, book_id

    async def collect(
        self,
        client: Any,
        book_id: str,
        *,
        auto_start: bool,
        limit: int = 200,
    ) -> tuple[list[dict], str]:
        """建任务 → 连 WS → （必要时）启动 → 收事件。"""
        import websockets

        task_id = (
            await client.post(
                "/api/v1/tasks",
                json={
                    "book_id": book_id,
                    "output_format": "txt",
                    "concurrency": 1,
                    "auto_start": auto_start,
                },
            )
        ).json()["id"]

        events: list[dict] = []
        async with websockets.connect(
            f"{self.live.ws_base}/ws/tasks/{task_id}", open_timeout=20
        ) as ws:
            events.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)))

            if not auto_start:
                # 先连上再启动，保证一条进度都不丢 —— 这正是新增 /start 端点的用途
                response = await client.post(f"/api/v1/tasks/{task_id}/start")
                assert response.status_code == 200, response.text

            while len(events) < limit:
                raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                event = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                events.append(event)
                if event["type"] in {"completed", "error"}:
                    break
                if event.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
                    break

        return events, task_id


def test_progress_events_stream_until_completion(live_server: LiveServer, mock_site: str) -> None:
    """完整事件流：snapshot → progress… → completed，且一条都不丢。"""
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    session = _Session(live_server, NATIVE_SOURCE_TEMPLATE.format(base=mock_site))

    async def scenario() -> tuple[list[dict], str]:
        client, book_id = await session.prepare()
        try:
            return await session.collect(client, book_id, auto_start=False)
        finally:
            await client.aclose()

    events, _ = _run_in_thread(scenario())
    types = [event["type"] for event in events]

    assert types[0] == "snapshot"
    assert "progress" in types, f"没有 progress 事件，实际序列 {types}"
    assert types[-1] == "completed", f"最后一条不是 completed，实际序列 {types}"

    completed = events[-1]
    assert completed["completed"] == 6
    assert completed["failed"] == 0
    assert completed["output_path"]


def test_progress_is_monotonic(live_server: LiveServer, mock_site: str) -> None:
    """completed 计数单调不减 —— 进度条不能往回跳。"""
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    session = _Session(live_server, NATIVE_SOURCE_TEMPLATE.format(base=mock_site))

    async def scenario() -> list[dict]:
        client, book_id = await session.prepare()
        try:
            events, _ = await session.collect(client, book_id, auto_start=False)
            return events
        finally:
            await client.aclose()

    events = _run_in_thread(scenario())
    progress = [e for e in events if e["type"] == "progress"]

    assert progress, "没有收到 progress 事件"
    counts = [e["completed"] for e in progress]
    assert counts == sorted(counts), f"completed 出现回退：{counts}"
    assert all(0 <= e["percent"] <= 100 for e in progress)
    assert progress[-1]["current"]


def test_progress_carries_chapter_name(live_server: LiveServer, mock_site: str) -> None:
    """progress 事件带当前章节名 —— 进度条旁边的文案靠它。"""
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    session = _Session(live_server, NATIVE_SOURCE_TEMPLATE.format(base=mock_site))

    async def scenario() -> list[dict]:
        client, book_id = await session.prepare()
        try:
            events, _ = await session.collect(client, book_id, auto_start=False)
            return events
        finally:
            await client.aclose()

    events = _run_in_thread(scenario())
    progress = [e for e in events if e["type"] == "progress"]

    assert progress
    names = {e["current"] for e in progress}
    assert names, "章节名为空"
    assert all(e["speed"].endswith("ch/s") for e in progress)
    assert all(e["index"] >= 0 for e in progress)


def test_skip_notice_is_published_on_second_run(live_server: LiveServer, mock_site: str) -> None:
    """重跑已下载的书时，要推一条「跳过 N 个已下载章节」的提示。"""
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    session = _Session(live_server, NATIVE_SOURCE_TEMPLATE.format(base=mock_site))

    async def scenario() -> list[dict]:
        client, book_id = await session.prepare()
        try:
            # 第一遍：全部下载
            first, _ = await session.collect(client, book_id, auto_start=False)
            assert first[-1]["type"] == "completed"

            # 第二遍：应全部跳过
            events, _ = await session.collect(client, book_id, auto_start=False)
            return events
        finally:
            await client.aclose()

    events = _run_in_thread(scenario())
    messages = [e.get("message", "") for e in events if e["type"] == "progress"]

    assert any("跳过" in message for message in messages), f"没有跳过提示，实际 {messages}"


def test_paused_status_is_published(live_server: LiveServer, mock_site: str) -> None:
    """暂停时推一条 status=PAUSED，客户端据此把按钮切回「继续」。"""
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    session = _Session(live_server, NATIVE_SOURCE_TEMPLATE.format(base=mock_site))

    async def scenario() -> list[dict]:
        import websockets

        client, book_id = await session.prepare()
        try:
            task_id = (
                await client.post(
                    "/api/v1/tasks",
                    json={
                        "book_id": book_id,
                        "output_format": "txt",
                        "concurrency": 1,
                        "auto_start": False,
                    },
                )
            ).json()["id"]

            events: list[dict] = []
            async with websockets.connect(
                f"{live_server.ws_base}/ws/tasks/{task_id}", open_timeout=20
            ) as ws:
                events.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)))
                await client.post(f"/api/v1/tasks/{task_id}/start")

                await client.post(f"/api/v1/tasks/{task_id}/pause")

                while len(events) < 200:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    event = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                    events.append(event)
                    if event["type"] == "status" and event.get("status") == "PAUSED":
                        break
                    if event["type"] in {"completed", "error"}:
                        break

            # 收尾：别把任务挂在那儿
            await client.post(f"/api/v1/tasks/{task_id}/cancel")
            return events
        finally:
            await client.aclose()

    events = _run_in_thread(scenario())
    statuses = [e.get("status") for e in events if e["type"] == "status"]

    assert "PAUSED" in statuses, f"没有 PAUSED 事件，实际 {statuses}"


def test_multiple_subscribers_both_get_snapshot(live_server: LiveServer, mock_site: str) -> None:
    """两个客户端同时订阅同一任务，各自都能拿到独立快照。

    ProgressBroker 用 set 存订阅者，实现不当容易出现「后连的把先连的踢掉」。
    """
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    session = _Session(live_server, NATIVE_SOURCE_TEMPLATE.format(base=mock_site))

    async def scenario() -> list[dict]:
        import websockets

        client, book_id = await session.prepare()
        try:
            task_id = (
                await client.post(
                    "/api/v1/tasks",
                    json={
                        "book_id": book_id,
                        "output_format": "txt",
                        "auto_start": False,
                    },
                )
            ).json()["id"]

            snapshots = []
            async with (
                websockets.connect(f"{live_server.ws_base}/ws/tasks/{task_id}") as ws_a,
                websockets.connect(f"{live_server.ws_base}/ws/tasks/{task_id}") as ws_b,
            ):
                snapshots.append(
                    json.loads(await asyncio.wait_for(ws_a.recv(), timeout=WS_TIMEOUT))
                )
                snapshots.append(
                    json.loads(await asyncio.wait_for(ws_b.recv(), timeout=WS_TIMEOUT))
                )
            return snapshots
        finally:
            await client.aclose()

    snapshots = _run_in_thread(scenario())

    assert len(snapshots) == 2
    assert all(snapshot["type"] == "snapshot" for snapshot in snapshots)
    assert snapshots[0]["task_id"] == snapshots[1]["task_id"]
