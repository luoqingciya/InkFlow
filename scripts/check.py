"""一键检查：lint + 类型 + 测试。

CI 与本地用同一个入口，避免「本地过了 CI 挂」这类口径不一致。

    uv run python scripts/check.py           # 全部
    uv run python scripts/check.py --fast    # 跳过 mypy（快）
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认可能是 cp936 / cp1252，直接打印中文会 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent


def run(label: str, command: list[str]) -> bool:
    """执行一条检查命令，返回是否通过。"""
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        print(f"[FAIL] {label}", file=sys.stderr)
        return False
    print(f"[OK] {label}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="InkFlow 代码检查")
    parser.add_argument("--fast", action="store_true", help="跳过 mypy")
    args = parser.parse_args()

    checks: list[tuple[str, list[str]]] = [
        ("版本号一致性", [sys.executable, "scripts/check_version.py"]),
        ("ruff check", ["ruff", "check", "."]),
        ("ruff format --check", ["ruff", "format", "--check", "."]),
    ]
    if not args.fast:
        checks.append(("mypy", ["mypy", "."]))
    checks.append(("pytest", ["pytest", "-q"]))

    # 前端类型检查。没装 node_modules 就跳过 —— 纯后端开发不该被它挡住，
    # 但装了就一定要跑：TS 的错误只有 tsc 能发现，Python 侧检查覆盖不到。
    npm = shutil.which("npm")
    if npm and (ROOT / "desktop" / "node_modules").is_dir():
        checks.append(("desktop typecheck", [npm, "--prefix", "desktop", "run", "typecheck"]))

    failed: list[str] = []
    for label, command in checks:
        if not run(label, command):
            failed.append(label)

    print(f"\n{'=' * 60}")
    if failed:
        print(f"未通过：{', '.join(failed)}", file=sys.stderr)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
