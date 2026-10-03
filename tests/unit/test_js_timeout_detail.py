"""JS 超时报错里的诊断信息。

光说「无响应」没法查：得知道**进程起没起来**、这次是不是**冷启动**。
侧车启动会往 stderr 写「sidecar 就绪」—— 那行在不在，指向完全不同的
两个方向（进程没跑起来 vs 进程跑起来了但没回话）。

这里**直接测私有方法**：要走到这条路径得让侧车既不回话又不退出，
构造起来比测的东西本身还复杂。它是一段纯拼字符串的逻辑，直接测更清楚。
"""

from __future__ import annotations

import time

import pytest

from inkflow_core.config import JsConfig
from inkflow_js_runtime import JsRuntime

pytestmark = pytest.mark.unit


def _runtime() -> JsRuntime:
    # 只构造不启动 —— 这里测的是拼诊断信息，不需要真起进程
    return JsRuntime(JsConfig(enabled=True, timeout=5.0))


def test_reports_wait_and_spawn_age() -> None:
    runtime = _runtime()
    runtime._spawned_at = time.monotonic() - 3.0

    detail = runtime._timeout_detail(10.0)

    assert "已等待 10.0s" in detail
    assert "距进程启动" in detail


def test_empty_stderr_points_at_process_startup() -> None:
    """没有日志要**明说**「进程可能根本没跑起来」—— 那是最要紧的一条线索。"""
    detail = _runtime()._timeout_detail(10.0)

    assert "没有任何日志" in detail


def test_stderr_tail_is_included() -> None:
    """有「就绪」就说明进程起来了，问题在别处 —— 日志必须带出来。"""
    runtime = _runtime()
    runtime._stderr_tail.append("[sidecar] sidecar 就绪 node=v22.0.0 pid=1")

    detail = runtime._timeout_detail(10.0)

    assert "sidecar 就绪" in detail


def test_only_last_lines_are_kept() -> None:
    """只留末尾几行 —— 报错信息不该被几百行日志淹没。"""
    runtime = _runtime()
    for index in range(50):
        runtime._stderr_tail.append(f"第 {index} 行")

    detail = runtime._timeout_detail(10.0)

    assert "第 49 行" in detail
    assert "第 0 行" not in detail
