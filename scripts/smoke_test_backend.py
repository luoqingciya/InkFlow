"""打包产物冒烟测试。

CI 里打包完立刻启动一次并请求 ``/health``。

为什么值得单独写一个脚本：PyInstaller 的失败模式往往是**静默**的 ——
构建成功、产物存在，但一运行就 `ModuleNotFoundError` 或直接退出。
只看「构建通过」会把这些漏到用户手里。

    uv run python scripts/smoke_test_backend.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
READY_PREFIX = "INKFLOW_READY"
TIMEOUT = 60.0


def binary_path() -> Path:
    """定位打包产物。"""
    name = "inkflow-server.exe" if sys.platform == "win32" else "inkflow-server"
    path = DIST / name
    if not path.is_file():
        raise SystemExit(f"找不到打包产物：{path}")
    return path


def read_ready(process: subprocess.Popen[str]) -> tuple[str, int]:
    """从 stdout 读取握手行，返回 (token, port)。"""
    deadline = time.monotonic() + TIMEOUT
    assert process.stdout is not None

    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise SystemExit(f"后端在就绪前退出（code={process.returncode}）\n{stderr[-2000:]}")
            continue

        line = line.strip()
        print(f"  [后端] {line}")

        if line.startswith(READY_PREFIX):
            parts = dict(
                item.split("=", 1) for item in line[len(READY_PREFIX) :].split() if "=" in item
            )
            return parts.get("token", ""), int(parts["port"])

    raise SystemExit(f"等待后端就绪超时（{TIMEOUT:g}s）")


def check_health(port: int) -> None:
    """请求 /health。

    显式禁用代理：CI 与开发机上若设了 http_proxy，
    发往 127.0.0.1 的请求会被转出去，看起来像「服务没起来」。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/health"

    last_error: Exception | None = None
    for _ in range(30):
        try:
            with opener.open(url, timeout=3) as response:
                body = response.read().decode("utf-8")
                print(f"  [健康检查] {body}")
                if '"status":"ok"' in body.replace(" ", ""):
                    return
                raise SystemExit(f"/health 返回异常内容：{body}")
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(0.5)

    raise SystemExit(f"无法访问 /health：{last_error}")


def main() -> int:
    exe = binary_path()
    print(f"冒烟测试：{exe}")

    with tempfile.TemporaryDirectory() as home:
        env = {
            **os.environ,
            "INKFLOW_HOME": home,
            # 冒烟测试不需要代理
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env.pop(key, None)

        process = subprocess.Popen(
            [str(exe), "--port", "0", "--quiet"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        try:
            _token, port = read_ready(process)
            print(f"后端已就绪，端口 {port}")
            check_health(port)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    print("冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
