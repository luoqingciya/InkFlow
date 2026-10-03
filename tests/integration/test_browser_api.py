"""浏览器运行时的 API：状态查询与按需下载。

**不真下载** —— 把下载函数换掉。这里验的是路由、错误码与响应形状。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inkflow_core.browser import BrowserUnavailableError

pytestmark = pytest.mark.integration


def test_status_reports_engine_and_install_state(client: TestClient) -> None:
    response = client.get("/api/v1/browser/status")

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "playwright"
    assert body["engine_available"] is True
    assert body["enabled"] is False, "默认不启用 —— 浏览器要按需下载"
    assert body["install_dir"]


def test_install_returns_directory(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "inkflow_browser_playwright.install_browser",
        lambda config: tmp_path / "browsers",
    )

    response = client.post("/api/v1/browser/install")

    assert response.status_code == 200
    body = response.json()
    assert body["installed"] is True
    assert body["install_dir"] == str(tmp_path / "browsers")


def test_install_failure_maps_to_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """装不了要报 503 + 稳定的错误码，客户端才能分支。"""

    def boom(config: object) -> None:
        raise BrowserUnavailableError("下载浏览器失败（退出码 1）")

    monkeypatch.setattr("inkflow_browser_playwright.install_browser", boom)

    response = client.post("/api/v1/browser/install")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "BROWSER_INSTALL_FAILED"
    assert "退出码 1" in error["message"]
