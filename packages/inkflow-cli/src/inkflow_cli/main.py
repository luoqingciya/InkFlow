"""``inkflow`` 命令行入口（规划书 §30）。

    CLI  →  API Client  →  InkFlow API

CLI **不是**第二个业务系统：它不解析网页、不下载、不写数据库。
每一条命令都对应一个 HTTP 请求。
"""

import asyncio
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from inkflow_cli.client import ApiError, InkFlowClient
from inkflow_cli.discovery import ServerLocation, discover, handshake_path
from inkflow_cli.output import (
    console,
    print_book_detail,
    print_books,
    print_chapters,
    print_error,
    print_export_result,
    print_health,
    print_json,
    print_progress_event,
    print_search_results,
    print_source_test,
    print_sources,
    print_system_info,
    print_task,
    print_task_items,
    print_tasks,
)

__all__ = ["app", "main"]

app = typer.Typer(
    name="inkflow",
    help="InkFlow —— API-First 小说资源聚合与下载平台（命令行客户端）",
    no_args_is_help=True,
    add_completion=False,
)
book_app = typer.Typer(help="书籍：详情、目录、正文", no_args_is_help=True)
task_app = typer.Typer(help="下载任务：查看、暂停、恢复、取消", no_args_is_help=True)
sources_app = typer.Typer(help="书源：列表、导入、测试、删除", no_args_is_help=True)

app.add_typer(book_app, name="book")
app.add_typer(task_app, name="task")
app.add_typer(sources_app, name="sources")


@dataclass
class CliContext:
    """命令间共享的上下文。"""

    location: ServerLocation
    json_output: bool
    verbose: bool


@app.callback()
def _callback(
    ctx: typer.Context,
    url: str = typer.Option(None, "--url", help="服务地址，默认自动发现"),
    token: str = typer.Option(None, "--token", help="session token，默认自动发现"),
    json_output: bool = typer.Option(False, "--json", help="输出机器可读的 JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示连接详情"),
) -> None:
    """InkFlow 命令行客户端。

    需要先启动服务：``uv run inkflow-server``
    """
    location = discover(url=url, token=token)
    ctx.obj = CliContext(location=location, json_output=json_output, verbose=verbose)
    if verbose:
        console.print(
            f"[dim]连接 {location.base_url}（来源：{location.origin}）"
            f"{'，已带 token' if location.token else '，无 token'}[/]"
        )


def _run(ctx: typer.Context, coro: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """执行异步请求并统一处理错误。

    Raises:
        typer.Exit: 请求失败时以退出码 1 结束。
    """
    cli_ctx: CliContext = ctx.obj
    try:
        return asyncio.run(coro())
    except ApiError as err:
        if cli_ctx.json_output:
            print_json(
                {
                    "error": {
                        "code": err.code,
                        "message": err.message,
                        "details": err.details,
                        "trace_id": err.trace_id,
                    }
                }
            )
        else:
            print_error(err)
            if err.code == "CONNECTION_REFUSED":
                console.print(f"[dim]握手文件：{handshake_path()}（不存在说明服务没在跑）[/]")
        raise typer.Exit(1) from err
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/]")
        raise typer.Exit(130) from None


def _emit(ctx: typer.Context, data: Any, render: Callable[[Any], None]) -> None:
    """按输出模式渲染结果。"""
    cli_ctx: CliContext = ctx.obj
    if cli_ctx.json_output:
        print_json(data)
    else:
        render(data)


# ================================================================ 系统


@app.command()
def health(ctx: typer.Context) -> None:
    """检查服务是否就绪。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location, timeout=10) as client:
            return await client.health()

    _emit(ctx, _run(ctx, run), print_health)


@app.command()
def info(ctx: typer.Context) -> None:
    """显示运行概况（书源数、书籍数、任务数等）。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.system_info()

    _emit(ctx, _run(ctx, run), print_system_info)


# ================================================================ 搜索


@app.command()
def search(
    ctx: typer.Context,
    keyword: str = typer.Argument(..., help="搜索关键词"),
    limit: int = typer.Option(50, "--limit", "-n", help="返回条数上限"),
    page: int = typer.Option(1, "--page", help="页码"),
    sources: str = typer.Option(None, "--sources", help="限定书源 ID，逗号分隔"),
) -> None:
    """跨书源搜索。

    示例：``inkflow search 三体``
    """
    cli_ctx: CliContext = ctx.obj
    source_ids = [s.strip() for s in sources.split(",")] if sources else None

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.search(keyword, page=page, limit=limit, sources=source_ids)

    _emit(ctx, _run(ctx, run), print_search_results)


@app.command()
def books(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit", "-n"),
    offset: int = typer.Option(0, "--offset"),
) -> None:
    """列出已入库的书籍。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.list_books(limit=limit, offset=offset)

    _emit(ctx, _run(ctx, run), print_books)


# ================================================================ 书籍


@book_app.command("info")
def book_info(ctx: typer.Context, book_id: str = typer.Argument(..., help="书籍 ID")) -> None:
    """查看书籍详情。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.get_book(book_id)

    _emit(ctx, _run(ctx, run), print_book_detail)


@book_app.command("chapters")
def book_chapters(
    ctx: typer.Context,
    book_id: str = typer.Argument(..., help="书籍 ID"),
    refresh: bool = typer.Option(False, "--refresh", help="重新从书源抓取目录"),
    limit: int = typer.Option(30, "--limit", "-n", help="显示条数"),
) -> None:
    """查看目录。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.get_chapters(book_id, refresh=refresh)

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        print_chapters(data, limit=limit)


@book_app.command("content")
def book_content(
    ctx: typer.Context,
    book_id: str = typer.Argument(..., help="书籍 ID"),
    chapter_id: str = typer.Argument(..., help="章节 ID"),
    refresh: bool = typer.Option(False, "--refresh", help="强制重新抓取"),
) -> None:
    """查看单章正文。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.get_chapter_content(book_id, chapter_id, refresh=refresh)

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        content = data.get("content", {})
        console.rule(data.get("chapter", {}).get("name", ""))
        console.print(content.get("clean_content", ""))


# ================================================================ 下载


@app.command()
def download(
    ctx: typer.Context,
    book_id: str = typer.Argument(..., help="书籍 ID"),
    start: int = typer.Option(0, "--start", help="起始章节索引"),
    end: int = typer.Option(None, "--end", help="结束章节索引（含）"),
    concurrency: int = typer.Option(None, "--concurrency", "-c", help="并发数"),
    fmt: str = typer.Option(None, "--format", "-f", help="导出格式：txt / epub / markdown"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
    watch: bool = typer.Option(False, "--watch", "-w", help="实时显示下载进度"),
) -> None:
    """创建下载任务。

    示例：``inkflow download <book-id> --start 0 --end 99 --watch``
    """
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            task = await client.create_task(
                book_id,
                start=start,
                end=end,
                concurrency=concurrency,
                fmt=fmt,
                output_path=output,
            )
            if watch and not cli_ctx.json_output:
                console.print(f"[dim]任务 {task['id']} 已创建，开始跟踪进度…[/]")
                async for event in client.watch_task(task["id"]):
                    print_progress_event(event)
            return task

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    elif not watch:
        print_task(data)


@task_app.command("list")
def task_list(ctx: typer.Context) -> None:
    """列出下载任务。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.list_tasks()

    _emit(ctx, _run(ctx, run), print_tasks)


@task_app.command("show")
def task_show(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    """查看任务详情。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.get_task(task_id)

    _emit(ctx, _run(ctx, run), print_task)


@task_app.command("items")
def task_items(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    limit: int = typer.Option(30, "--limit", "-n"),
) -> None:
    """查看任务的章节明细（含失败章节）。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.get_task_items(task_id)

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        print_task_items(data, limit=limit)


@task_app.command("watch")
def task_watch(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    """实时跟踪任务进度（WebSocket）。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            async for event in client.watch_task(task_id):
                if cli_ctx.json_output:
                    print_json(event)
                else:
                    print_progress_event(event)
            return None

    _run(ctx, run)


@task_app.command("pause")
def task_pause(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    """暂停任务。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.pause_task(task_id)

    _emit(ctx, _run(ctx, run), print_task)


@task_app.command("resume")
def task_resume(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    """恢复任务。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.resume_task(task_id)

    _emit(ctx, _run(ctx, run), print_task)


@task_app.command("cancel")
def task_cancel(ctx: typer.Context, task_id: str = typer.Argument(...)) -> None:
    """取消任务。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.cancel_task(task_id)

    _emit(ctx, _run(ctx, run), print_task)


# ================================================================ 书源


@sources_app.command("list")
def sources_list(ctx: typer.Context) -> None:
    """列出书源。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.list_sources()

    _emit(ctx, _run(ctx, run), print_sources)


@sources_app.command("import")
def sources_import(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="书源文件路径或 URL"),
    disabled: bool = typer.Option(False, "--disabled", help="导入后不启用"),
) -> None:
    """导入书源（原生 YAML 或 Legado JSON）。

    示例：``inkflow sources import ./sources/official/example.yaml``
    """
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            if target.startswith(("http://", "https://")):
                return await client.import_source(url=target, enabled=not disabled)
            path = Path(target)
            if not path.is_file():
                raise ApiError("FILE_NOT_FOUND", f"书源文件不存在：{path}")
            return await client.import_source(
                content=path.read_text(encoding="utf-8"),
                enabled=not disabled,
            )

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        source = data.get("source", {})
        action = "已导入" if data.get("created") else "已更新"
        console.print(
            f"[green]{action}[/] {source.get('name')} "
            f"({source.get('id')})  兼容等级 {source.get('compatibility_level')}"
        )


@sources_app.command("test")
def sources_test(
    ctx: typer.Context,
    source_id: str = typer.Argument(..., help="书源 ID"),
    kind: str = typer.Option("search", "--kind", "-k", help="search / info / toc / content"),
    keyword: str = typer.Option("测试", "--keyword", help="搜索关键词"),
    url: str = typer.Option(None, "--url", help="测试 info / toc / content 时的目标地址"),
) -> None:
    """对书源执行一次真实调用，验证规则是否有效。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.test_source(source_id, kind=kind, keyword=keyword, url=url)

    _emit(ctx, _run(ctx, run), print_source_test)


@sources_app.command("rules")
def sources_rules(ctx: typer.Context, source_id: str = typer.Argument(...)) -> None:
    """查看规则编译后的 AST（Source Debugger）。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.inspect_rules(source_id)

    _emit(ctx, _run(ctx, run), lambda data: print_json(data))


@sources_app.command("enable")
def sources_enable(ctx: typer.Context, source_id: str = typer.Argument(...)) -> None:
    """启用书源。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.set_source_enabled(source_id, True)

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        console.print(f"[green]已启用[/] {data.get('name')}")


@sources_app.command("disable")
def sources_disable(ctx: typer.Context, source_id: str = typer.Argument(...)) -> None:
    """停用书源。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.set_source_enabled(source_id, False)

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        console.print(f"[yellow]已停用[/] {data.get('name')}")


@sources_app.command("delete")
def sources_delete(
    ctx: typer.Context,
    source_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """删除书源。"""
    cli_ctx: CliContext = ctx.obj

    if not yes:
        typer.confirm(f"确定删除书源 {source_id}？", abort=True)

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location) as client:
            return await client.delete_source(source_id)

    data = _run(ctx, run)
    if cli_ctx.json_output:
        print_json(data)
    else:
        console.print(f"[green]{data.get('message')}[/]")


# ================================================================ 导出


@app.command()
def export(
    ctx: typer.Context,
    book_id: str = typer.Argument(..., help="书籍 ID"),
    fmt: str = typer.Option("epub", "--format", "-f", help="txt / epub / markdown"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件路径"),
    start: int = typer.Option(0, "--start", help="起始章节索引"),
    end: int = typer.Option(None, "--end", help="结束章节索引（含）"),
) -> None:
    """把已下载的章节导出为文件。"""
    cli_ctx: CliContext = ctx.obj

    async def run() -> Any:
        async with InkFlowClient(cli_ctx.location, timeout=300) as client:
            return await client.export(book_id, fmt=fmt, output_path=output, start=start, end=end)

    _emit(ctx, _run(ctx, run), print_export_result)


# ================================================================ 入口


def main() -> None:
    """``inkflow`` 入口。"""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
