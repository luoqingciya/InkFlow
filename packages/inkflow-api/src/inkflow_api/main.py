"""``inkflow-server`` 命令行入口。

启动后会在 stdout 打印一行机器可读的握手信息::

    INKFLOW_READY port=53421 token=xxxxx

Desktop 的主进程正是靠解析这一行拿到端口与 token 的（规划书 §34）。
端口用 ``0`` 时由系统分配，所以**不能**靠配置文件猜实际端口。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

import uvicorn

from inkflow_api.app import create_app
from inkflow_core.config import get_settings
from inkflow_core.log import LOG_FILENAME, setup_logging
from inkflow_core.paths import get_paths

__all__ = ["build_parser", "main"]

READY_PREFIX = "INKFLOW_READY"


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="inkflow-server",
        description="启动 InkFlow HTTP API 服务",
    )
    parser.add_argument("--host", default=None, help="监听地址（默认取配置，通常 127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口；0 表示由系统分配空闲端口")
    parser.add_argument(
        "--no-token", action="store_true", help="关闭 session token 鉴权（仅本机调试用）"
    )
    parser.add_argument("--log-level", default=None, help="日志级别：DEBUG/INFO/WARNING/ERROR")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重载")
    parser.add_argument("--quiet", action="store_true", help="不打印启动横幅")
    return parser


def _actual_port(server: uvicorn.Server) -> int:
    """从 uvicorn 已绑定的 socket 读取实际端口。"""
    for bound in getattr(server, "servers", []):
        for sock in bound.sockets:
            return int(sock.getsockname()[1])
    return 0


async def _serve(
    app: object,
    *,
    host: str,
    port: int,
    log_level: str,
    token: str,
    quiet: bool,
) -> None:
    """启动服务并在就绪后打印握手行。"""
    config = uvicorn.Config(
        app,  # type: ignore[arg-type]
        host=host,
        port=port,
        log_level=log_level.lower(),
        access_log=False,
        # 关闭 uvicorn 自带的信号处理，避免与 asyncio.run 冲突
        loop="asyncio",
        # 让 uvicorn 不要装自己的 handler：它的 logger 是 propagate=False，
        # 会把日志截在自己那里，root 上的文件 handler 就永远收不到
        log_config=None,
    )
    server = uvicorn.Server(config)
    runner = asyncio.create_task(server.serve())

    while not server.started:
        if runner.done():
            await runner  # 抛出真实异常，而不是静默退出
            return
        await asyncio.sleep(0.05)

    actual = _actual_port(server)
    _write_server_file(host, actual, token)

    if not quiet:
        print(f"  InkFlow API  http://{host}:{actual}")
        print(f"  接口文档      http://{host}:{actual}/docs")
    # 这一行必须保持固定格式：Desktop 依赖它做进程间握手
    print(f"{READY_PREFIX} port={actual} token={token}", flush=True)

    try:
        await runner
    except asyncio.CancelledError:
        server.should_exit = True
        raise
    finally:
        _remove_server_file()


def _write_server_file(host: str, port: int, token: str) -> None:
    """把监听地址与 token 写到数据目录下的 ``server.json``。

    CLI 靠这个文件找到正在运行的服务 —— 端口是系统分配的，
    命令行没法猜。文件权限收紧到仅当前用户可读。
    """
    import json
    import os

    path = get_paths().handshake_file
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"host": host, "port": port, "token": token, "pid": os.getpid()}),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):  # Windows 上 chmod 语义有限
            path.chmod(0o600)
    except OSError:
        pass  # 写不进去只影响 CLI 自动发现，服务本身照常工作


def _remove_server_file() -> None:
    """服务退出时清理握手文件。"""
    with contextlib.suppress(OSError):
        get_paths().handshake_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Returns:
        进程退出码。
    """
    args = build_parser().parse_args(argv)
    settings = get_settings()
    paths = get_paths().ensure()

    host = args.host or settings.server.host
    port = args.port if args.port is not None else settings.server.port
    if args.log_level:
        settings.log.level = args.log_level.upper()
    log_level = settings.log.level

    # 日志要先于其它组件配好：否则启动阶段的失败信息落不了盘，
    # 而「服务起不来」正是最需要日志的时候
    log_file = setup_logging(settings.log, paths.logs_dir)

    app = create_app(settings, require_token=False if args.no_token else None)
    if args.no_token and not args.quiet:
        print("  警告：已关闭 session token 鉴权，任何本机进程都可访问该端口")

    if not args.quiet:
        print("InkFlow —— API-First 小说资源聚合与下载平台")
        print(f"  数据目录      {paths.home}")
        print(f"  配置文件      {paths.config_file}")
        if log_file is not None:
            print(f"  日志文件      {paths.logs_dir / LOG_FILENAME}")

    if args.reload:
        # reload 模式交给 uvicorn 自己管理进程，此时无法打印实际端口
        uvicorn.run(
            "inkflow_api.app:app",
            host=host,
            port=port,
            log_level=log_level.lower(),
            reload=True,
        )
        return 0

    try:
        asyncio.run(
            _serve(
                app,
                host=host,
                port=port,
                log_level=log_level,
                token=app.state.inkflow.session_token,
                quiet=args.quiet,
            )
        )
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
