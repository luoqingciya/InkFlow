"""版本号一致性检查。

版本号只允许在**一个地方**定义：``packages/inkflow-core/src/inkflow_core/__init__.py``。
其余位置要么从它读取，要么是它的等价写法。

这个脚本存在的意义：版本号漂移是那种「不出事则已，出事很难查」的问题 ——
包里写 0.1.0、桌面端写 0.1.0-dev.0、文档写 0.1.0，谁也没错，
但发出去的安装包版本就是乱的。用机器检查比靠人记靠谱。

    uv run python scripts/check_version.py
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
CORE_INIT = ROOT / "packages" / "inkflow-core" / "src" / "inkflow_core" / "__init__.py"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
PACKAGES_DIR = ROOT / "packages"

VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)

problems: list[str] = []


def fail(message: str) -> None:
    problems.append(message)
    print(f"  [FAIL] {message}")


def ok(message: str) -> None:
    print(f"  [OK]   {message}")


def read_core_version() -> str:
    """读取唯一来源。"""
    match = VERSION_RE.search(CORE_INIT.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"在 {CORE_INIT} 里找不到 __version__ 定义")
    return match.group(1)


def to_semver(pep440: str) -> str:
    """PEP 440 → npm semver 的等价写法。

    只覆盖本项目会用到的形式，不追求完整映射。
    """
    version = Version(pep440)
    base = f"{version.major}.{version.minor}.{version.micro}"

    if version.dev is not None:
        return f"{base}-dev.{version.dev}"
    if version.pre is not None:
        label, number = version.pre
        return f"{base}-{label}.{number}"
    return base


def check_core_format(version: str) -> None:
    """唯一来源必须是合法 PEP 440。"""
    try:
        Version(version)
    except InvalidVersion:
        fail(f"core 的版本号不是合法 PEP 440：{version!r}")
        return
    ok(f"core 版本号 {version} 是合法 PEP 440")


def check_members_are_dynamic() -> None:
    """成员包不允许硬编码 version。"""
    for pyproject in sorted(PACKAGES_DIR.glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        name = project.get("name", pyproject.parent.name)

        if name == "inkflow-core":
            # core 自己持有版本号，但同样应该是 dynamic（从 __init__.py 读）
            pass

        if "version" in project:
            fail(f"{name} 的 pyproject 硬编码了 version，应改为 dynamic + [tool.hatch.version]")
            continue

        dynamic = project.get("dynamic", [])
        if "version" not in dynamic:
            fail(f'{name} 的 pyproject 既没有 version 也没有 dynamic = ["version"]')
            continue

        hatch_version = data.get("tool", {}).get("hatch", {}).get("version", {})
        if not hatch_version.get("path"):
            fail(f"{name} 缺少 [tool.hatch.version] path")
            continue

        ok(f"{name} 使用动态版本（{hatch_version['path']}）")


def check_root_pyproject(version: str) -> None:
    """根 pyproject 的展示版本要与唯一来源一致。"""
    data = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))
    root_version = data.get("project", {}).get("version")
    if root_version != version:
        fail(f"根 pyproject 版本 {root_version!r} 与 core 的 {version!r} 不一致")
    else:
        ok(f"根 pyproject 版本一致（{root_version}）")


def check_desktop(version: str) -> None:
    """桌面端用 semver，需与 PEP 440 版本等价。"""
    data = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
    desktop_version = data.get("version")
    expected = to_semver(version)

    if desktop_version != expected:
        fail(
            f"desktop/package.json 版本 {desktop_version!r} 与预期的 semver 等价写法 "
            f"{expected!r} 不一致（core 为 {version!r}）"
        )
    else:
        ok(f"desktop 版本一致（{desktop_version} ≡ {version}）")


def main() -> int:
    print(f"版本号唯一来源：{CORE_INIT.relative_to(ROOT)}")
    version = read_core_version()
    print(f"当前版本：{version}\n")

    check_core_format(version)
    check_members_are_dynamic()
    check_root_pyproject(version)
    check_desktop(version)

    print()
    if problems:
        print(f"发现 {len(problems)} 处版本号问题", file=sys.stderr)
        return 1

    print("版本号一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
