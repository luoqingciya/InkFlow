"""pytest 全局夹具。

测试全程使用**临时数据目录 + 内存数据库**，绝不碰真实的 ``~/.inkflow``。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.mock_server import MockSite, start_mock_site

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
def authed_client(state) -> Iterator[TestClient]:
    """带 token 的测试客户端，用于验证鉴权确实生效。"""
    from inkflow_api.app import create_app

    app = create_app(state=state, require_token=True)
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {state.session_token}"})
        yield test_client
