"""API 集成测试：路由、鉴权、错误格式、书源导入。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from inkflow_api.app import create_app
from tests.sources_data import NATIVE_SOURCE_TEMPLATE

pytestmark = pytest.mark.integration

NATIVE_SOURCE = NATIVE_SOURCE_TEMPLATE


# ---------------------------------------------------------------- 基础


def test_health_is_public(client: TestClient) -> None:
    """健康检查必须免鉴权，否则 Desktop 的启动探测会卡住。"""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_trace_id_header_present(client: TestClient) -> None:
    """每个响应都带 trace_id，便于对日志。"""
    response = client.get("/health")
    assert response.headers.get("x-trace-id")


def test_system_info(client: TestClient) -> None:
    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 0
    assert "txt" in body["export_formats"]
    assert body["data_dir"]


def test_openapi_available(client: TestClient) -> None:
    """OpenAPI 契约必须可导出 —— Desktop 的类型由它生成。"""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/search" in paths
    assert "/api/v1/tasks" in paths


# ---------------------------------------------------------------- 鉴权


def test_protected_route_rejects_without_token(state) -> None:
    app = create_app(state=state, require_token=True)
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/system/info")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_protected_route_accepts_valid_token(authed_client: TestClient) -> None:
    assert authed_client.get("/api/v1/system/info").status_code == 200


def test_protected_route_rejects_wrong_token(state) -> None:
    app = create_app(state=state, require_token=True)
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/system/info", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401


# ---------------------------------------------------------------- 错误格式


def test_not_found_error_shape(client: TestClient) -> None:
    """所有错误都必须是统一结构，客户端按 code 分支。"""
    response = client.get("/api/v1/books/bk_not_exist")
    assert response.status_code == 404

    error = response.json()["error"]
    assert error["code"] == "BOOK_NOT_FOUND"
    assert error["message"]
    assert isinstance(error["details"], dict)
    assert "trace_id" in error


def test_validation_error_shape(client: TestClient) -> None:
    """缺参数时返回 VALIDATION_ERROR 而不是 500。"""
    response = client.get("/api/v1/search")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_search_without_sources_is_actionable(client: TestClient) -> None:
    """没有书源时给出可操作的错误码，而不是空结果。"""
    response = client.get("/api/v1/search", params={"q": "三体"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "SEARCH_NO_SOURCE"


def test_task_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/task_nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# ---------------------------------------------------------------- 书源导入


def test_import_native_source(client: TestClient, mock_site: str) -> None:
    response = client.post(
        "/api/v1/sources/import",
        json={"format": "auto", "content": NATIVE_SOURCE.format(base=mock_site)},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["created"] is True
    assert body["source"]["name"] == "Mock 原生书源"
    assert body["source"]["source_type"] == "native"
    assert body["source"]["enabled_search"] is True


def test_import_is_idempotent(client: TestClient, mock_site: str) -> None:
    """同一书源重复导入应更新而非新增。"""
    content = NATIVE_SOURCE.format(base=mock_site)
    first = client.post("/api/v1/sources/import", json={"content": content}).json()
    second = client.post("/api/v1/sources/import", json={"content": content}).json()

    assert first["created"] is True
    assert second["created"] is False
    assert first["source"]["id"] == second["source"]["id"]

    listed = client.get("/api/v1/sources").json()
    assert listed["total"] == 1


def test_import_rejects_garbage(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sources/import",
        json={"content": "这不是一个书源"},
    )
    assert response.status_code >= 400
    assert response.json()["error"]["code"] in {"SOURCE_INVALID", "VALIDATION_ERROR"}


def test_import_requires_content_or_url(client: TestClient) -> None:
    response = client.post("/api/v1/sources/import", json={"format": "auto"})
    assert response.status_code >= 400


def test_source_toggle_and_delete(client: TestClient, mock_site: str) -> None:
    source_id = client.post(
        "/api/v1/sources/import", json={"content": NATIVE_SOURCE.format(base=mock_site)}
    ).json()["source"]["id"]

    disabled = client.patch(f"/api/v1/sources/{source_id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    assert client.delete(f"/api/v1/sources/{source_id}").status_code == 200
    assert client.get("/api/v1/sources").json()["total"] == 0


def test_import_rejects_private_network_url(client: TestClient) -> None:
    """远程导入同样要走 SSRF 校验。"""
    response = client.post(
        "/api/v1/sources/import",
        json={"url": "http://127.0.0.1:1/source.json"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SOURCE_BLOCKED"


# ---------------------------------------------------------------- 设置


def test_settings_snapshot(client: TestClient) -> None:
    body = client.get("/api/v1/settings").json()
    assert body["server"]["host"] == "127.0.0.1"
    assert "default_format" in body["export"]


def test_settings_patch_whitelist(client: TestClient) -> None:
    """只允许白名单内的键 —— 不能通过 API 改掉监听地址。"""
    ok = client.patch("/api/v1/settings", json={"download_concurrency": 8})
    assert ok.status_code == 200
    assert ok.json()["download"]["concurrency"] == 8

    rejected = client.patch("/api/v1/settings", json={"server": {"host": "0.0.0.0"}})
    assert rejected.status_code == 422
