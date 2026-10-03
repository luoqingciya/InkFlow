"""按需下载浏览器的测试。

**不真下载** —— 270MB 不该出现在测试里。这里验的是「判断得对不对」
与「失败时报错说不说得清」。
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from inkflow_browser_playwright import browser_installed, install_browser
from inkflow_core.browser import BrowserUnavailableError
from inkflow_core.config import BrowserConfig

pytestmark = pytest.mark.unit


# ================================================================ 装没装


def test_not_installed_when_dir_missing(tmp_path: Path) -> None:
    assert browser_installed(BrowserConfig(install_dir=str(tmp_path / "nope"))) is False


def test_installed_when_build_dir_present(tmp_path: Path) -> None:
    """playwright 的目录名形如 ``chromium_headless_shell-1234``。"""
    (tmp_path / "browsers" / "chromium_headless_shell-1234").mkdir(parents=True)

    assert browser_installed(BrowserConfig(install_dir=str(tmp_path / "browsers"))) is True


def test_full_chromium_does_not_count(tmp_path: Path) -> None:
    """装了完整 chromium 不等于装了 headless 外壳 —— 名字对不上就不算。"""
    (tmp_path / "browsers" / "chromium-1234").mkdir(parents=True)

    assert browser_installed(BrowserConfig(install_dir=str(tmp_path / "browsers"))) is False


# ================================================================ 装不了的情况


def test_frozen_build_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """冻结构建里要**明说装不了**，不能给一条用户执行不了的命令。"""
    monkeypatch.setattr("inkflow_browser_playwright.install.is_frozen", lambda: True)

    with pytest.raises(BrowserUnavailableError) as info:
        install_browser(BrowserConfig(install_dir=str(tmp_path)))

    message = str(info.value)
    assert "单文件可执行程序" in message
    assert "没有带浏览器引擎" in message


def test_missing_playwright_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("inkflow_browser_playwright.install.is_frozen", lambda: False)
    monkeypatch.setitem(sys.modules, "playwright", None)  # 让 import 失败

    with pytest.raises(BrowserUnavailableError) as info:
        install_browser(BrowserConfig(install_dir=str(tmp_path)))

    assert "pip install" in str(info.value)


# ================================================================ 装的过程


@pytest.fixture
def _runnable(monkeypatch: pytest.MonkeyPatch) -> None:
    """把「能不能装」的前置条件都摆平 —— 但不碰网络。"""
    monkeypatch.setattr("inkflow_browser_playwright.install.is_frozen", lambda: False)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))


def _record_run(captured: dict[str, Any], *, returncode: int = 0) -> Any:
    def fake_run(command: list[str], *, env: dict[str, str], check: bool) -> Any:
        captured["command"] = command
        captured["env"] = env
        captured["check"] = check
        return subprocess.CompletedProcess(command, returncode)

    return fake_run


def test_install_points_playwright_at_our_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _runnable: None
) -> None:
    """装的时候要把目录**通过环境变量**告诉 playwright —— 装错地方等于白下。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("inkflow_browser_playwright.install.subprocess.run", _record_run(captured))
    messages: list[str] = []

    config = BrowserConfig(
        install_dir=str(tmp_path / "browsers"), download_host="https://mirror.test"
    )
    directory = install_browser(config, on_progress=messages.append)

    assert directory == tmp_path / "browsers"
    assert captured["command"][1:] == ["-m", "playwright", "install", "chromium-headless-shell"]
    assert captured["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(directory)
    assert captured["env"]["PLAYWRIGHT_DOWNLOAD_HOST"] == "https://mirror.test"
    assert captured["check"] is False, "退出码要自己判，不能让 subprocess 抛"
    assert messages, "要给出进度 —— 几分钟的空白用户受不了"


def test_download_host_absent_leaves_env_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _runnable: None
) -> None:
    """没配 download_host 就别设这个变量 —— 让 playwright 走它自己的默认源。"""
    monkeypatch.delenv("PLAYWRIGHT_DOWNLOAD_HOST", raising=False)
    captured: dict[str, Any] = {}
    monkeypatch.setattr("inkflow_browser_playwright.install.subprocess.run", _record_run(captured))

    install_browser(BrowserConfig(install_dir=str(tmp_path / "browsers")))

    assert "PLAYWRIGHT_DOWNLOAD_HOST" not in captured["env"]


def test_install_failure_names_the_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _runnable: None
) -> None:
    """下载失败要报退出码 + 换源办法 + 手动命令，不能只说「失败了」。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "inkflow_browser_playwright.install.subprocess.run", _record_run(captured, returncode=1)
    )

    with pytest.raises(BrowserUnavailableError) as info:
        install_browser(BrowserConfig(install_dir=str(tmp_path / "browsers")))

    message = str(info.value)
    assert "退出码 1" in message
    assert "download_host" in message
    assert "playwright install" in message
