"""pytest 全局夹具。

测试全程使用**临时数据目录 + 内存数据库**，绝不碰真实的 ``~/.inkflow``。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient

from tests.mock_server import MockSite, start_mock_site
from tests.sources_data import NATIVE_SOURCE_TEMPLATE

# ---------------------------------------------------------------- 环境隔离


@pytest.fixture(autouse=True, scope="session")
def _clean_proxy_env() -> Iterator[None]:
    """清除代理环境变量。

    开发机上的 ``http_proxy`` 会把发往 ``127.0.0.1`` 的请求也转出去，
    导致 mock 站点「连不上」—— 看起来像服务没起，其实是代理劫持。
    """
    proxy_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    saved = {key: os.environ.pop(key, None) for key in proxy_keys}
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    yield
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把数据目录指向临时目录。"""
    home = tmp_path / "inkflow-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("INKFLOW_HOME", str(home))
    monkeypatch.delenv("INKFLOW_CONFIG", raising=False)
    return home


# ---------------------------------------------------------------- 服务


@pytest.fixture
def mock_site() -> Iterator[str]:
    """运行中的 mock 书站，返回其 base URL。"""
    site: MockSite = start_mock_site()
    try:
        yield site.url
    finally:
        site.stop()


@pytest.fixture
def state(tmp_path: Path):
    """隔离的应用状态（内存数据库 + 独立注册表）。"""
    from inkflow_api.state import build_state
    from inkflow_core.config import Settings
    from inkflow_core.paths import InkFlowPaths
    from inkflow_core.storage import sqlite_url
    from inkflow_source.loader import SourceLoader
    from inkflow_source.registry import SourceRegistry

    paths = InkFlowPaths(tmp_path / "home").ensure()
    settings = Settings()
    # 测试要访问本机 mock 站点，必须放开内网限制
    settings.source.allow_private_network = True

    # 用临时**文件**而不是 :memory: —— 内存库是「每连接一个独立数据库」，
    # 连接池里换一个连接就看不到表了，症状是随机 OperationalError。
    return build_state(
        settings,
        paths=paths,
        database_url=sqlite_url(paths.database_dir / "test.db"),
        registry=SourceRegistry(),
        loader=SourceLoader(),
        session_token="test-token",
    )


@pytest.fixture
def client(state) -> Iterator[TestClient]:
    """免鉴权的测试客户端。"""
    from inkflow_api.app import create_app

    app = create_app(state=state, require_token=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def library(client: TestClient, mock_site: str) -> _Library:
    """已导入 Mock 书源、「三体」的目录也抓好了的测试客户端。

    下载任务依赖「书籍 + 目录」两样东西齐全，手工走一遍导入 → 搜索 →
    抓目录要三行代码，而几乎每个下载测试都需要，所以在这里备好。

    **注意**：搜索会把 mock 站点的三本书**全部**入库，这里显式抓目录的
    只有「三体」那一本。因此别走 ``/api/v1/books`` 列表拿第一本
    （列表按更新时间倒序，拿到的是「三体 III」，它没有目录）——
    用 ``.book_id``。
    """
    client.post(
        "/api/v1/sources/import",
        json={"content": NATIVE_SOURCE_TEMPLATE.format(base=mock_site)},
    )
    items = client.get("/api/v1/search", params={"q": "三体"}).json()["items"]
    selected = next(item for item in items if item["name"] == "三体")
    selected_id = selected["sources"][0]["book_id"]
    client.get(f"/api/v1/books/{selected_id}/chapters", params={"refresh": True})
    return _Library(client=client, book_id=selected_id)


class _Library(NamedTuple):
    """``library`` 夹具的返回值：客户端 + 那本备好目录的书。"""

    client: TestClient
    book_id: str


@pytest.fixture
def authed_client(state) -> Iterator[TestClient]:
    """带 token 的测试客户端，用于验证鉴权确实生效。"""
    from inkflow_api.app import create_app

    app = create_app(state=state, require_token=True)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {state.session_token}"})
        yield test_client


# ---------------------------------------------------------------- 等待


def wait_for_terminal(
    client: TestClient,
    task_id: str,
    *,
    timeout: float = 20.0,
) -> dict:
    """轮询任务直到进入终态，返回最终的 task 字典。

    下载是异步的 —— ``POST /tasks`` 返回时任务才刚 PENDING。测试里
    与其 ``sleep`` 一个拍脑袋的时长，不如轮询到状态真的定下来。

    Raises:
        AssertionError: 超时仍没进终态。
    """
    from time import monotonic, sleep

    deadline = monotonic() + timeout
    task: dict = {}
    while monotonic() < deadline:
        task = client.get(f"/api/v1/tasks/{task_id}").json()["task"]
        if task["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return task
        sleep(0.05)
    raise AssertionError(
        f"任务 {task_id} 在 {timeout}s 内未进入终态，最后状态 {task.get('status')}"
    )
