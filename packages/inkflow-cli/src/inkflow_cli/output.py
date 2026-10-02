"""CLI 输出渲染（规划书 §31）。

两种模式：

* **人类可读** —— Rich 表格，适合终端里看。
* **机器可读** —— ``--json``，输出与 API 响应一致的 JSON，
  便于脚本 / CI 消费。

同一条命令两种模式共用一份数据，不重复取数。
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from inkflow_cli.client import ApiError

__all__ = [
    "console",
    "print_book_detail",
    "print_books",
    "print_chapters",
    "print_error",
    "print_export_result",
    "print_health",
    "print_json",
    "print_progress_event",
    "print_search_results",
    "print_source_test",
    "print_sources",
    "print_system_info",
    "print_task",
    "print_task_items",
    "print_tasks",
]

console = Console()
err_console = Console(stderr=True)


def print_json(data: Any) -> None:
    """以 JSON 输出（``--json``）。"""
    console.print_json(json.dumps(data, ensure_ascii=False, default=str))


def print_error(err: ApiError) -> None:
    """渲染结构化错误。"""
    lines = [f"[bold red]{err.code}[/]", err.message]
    if err.details:
        lines.append(f"[dim]details: {json.dumps(err.details, ensure_ascii=False)}[/]")
    if err.trace_id:
        lines.append(f"[dim]trace_id: {err.trace_id}[/]")
    err_console.print(Panel("\n".join(lines), title="错误", border_style="red"))


def _table(title: str, columns: list[str]) -> Table:
    table = Table(title=title, header_style="bold cyan", title_style="bold")
    for column in columns:
        table.add_column(column, overflow="fold")
    return table


def print_health(data: dict[str, Any]) -> None:
    """健康检查结果。"""
    console.print(
        Panel(
            f"状态      [green]{data.get('status')}[/]\n"
            f"版本      {data.get('version')}\n"
            f"运行时长  {data.get('uptime_seconds')}s",
            title="InkFlow 服务",
            border_style="green",
        )
    )


def print_system_info(data: dict[str, Any]) -> None:
    """运行概况。"""
    console.print(
        Panel(
            "\n".join(
                [
                    f"版本        {data.get('version')}",
                    f"数据目录    {data.get('data_dir')}",
                    f"运行时长    {data.get('uptime_seconds')}s",
                    f"书源        {data.get('enabled_source_count')} / {data.get('source_count')} 启用",
                    f"书籍        {data.get('book_count')}",
                    f"任务        {data.get('active_task_count')} 进行中 / {data.get('task_count')} 总数",
                    f"导出格式    {', '.join(data.get('export_formats', []))}",
                    f"书源格式    {', '.join(data.get('source_formats', []))}",
                    f"Python      {data.get('python_version')}",
                    f"平台        {data.get('platform')}",
                ]
            ),
            title="运行概况",
            border_style="cyan",
        )
    )


def print_search_results(data: dict[str, Any]) -> None:
    """搜索结果表格（规划书 §31 的示例布局）。"""
    items = data.get("items", [])
    if not items:
        console.print("[yellow]没有找到结果[/]")
    else:
        table = _table(f"搜索「{data.get('keyword')}」", ["#", "书名", "作者", "来源", "最新章节"])
        for index, item in enumerate(items, start=1):
            sources = item.get("sources", [])
            source_names = "、".join(s.get("source_name", "") for s in sources)
            extra = f" (+{len(sources) - 1})" if len(sources) > 1 else ""
            table.add_row(
                str(index),
                item.get("name", ""),
                item.get("author") or "-",
                f"{source_names}{extra}",
                (item.get("sources") or [{}])[0].get("latest_chapter") or "-",
            )
        console.print(table)
        console.print("[dim]提示：用 `inkflow book info <book-id>` 查看详情[/]")

    errors = data.get("source_errors") or {}
    if errors:
        console.print(f"[yellow]有 {len(errors)} 个书源失败：[/]")
        for source_id, message in errors.items():
            console.print(f"  [dim]{source_id}: {message}[/]")


def print_books(data: dict[str, Any]) -> None:
    """书库列表。"""
    items = data.get("items", [])
    if not items:
        console.print("[yellow]书库为空[/]")
        return
    table = _table(f"书库（{data.get('total', len(items))} 本）", ["ID", "书名", "作者", "分类"])
    for item in items:
        table.add_row(
            item.get("id", ""),
            item.get("name", ""),
            item.get("author") or "-",
            item.get("category") or "-",
        )
    console.print(table)


def print_book_detail(data: dict[str, Any]) -> None:
    """书籍详情。"""
    book = data.get("book", {})
    source = data.get("source") or {}
    console.print(
        Panel(
            "\n".join(
                [
                    f"书名      [bold]{book.get('name')}[/]",
                    f"作者      {book.get('author') or '-'}",
                    f"ID        {book.get('id')}",
                    f"来源      {source.get('name') or '-'} "
                    f"({source.get('compatibility_level') or '-'})",
                    f"分类      {book.get('category') or '-'}",
                    f"状态      {book.get('status') or '-'}",
                    f"章节      {data.get('downloaded_count', 0)} 已下载 / "
                    f"{data.get('chapter_count', 0)} 总计",
                    "",
                    (book.get("intro") or "")[:300],
                ]
            ),
            title="书籍详情",
            border_style="cyan",
        )
    )


def print_chapters(data: dict[str, Any], *, limit: int = 30) -> None:
    """目录。"""
    chapters = data.get("chapters", [])
    total = data.get("total", len(chapters))
    if not chapters:
        console.print("[yellow]没有章节，试试加 --refresh 重新抓取目录[/]")
        return

    table = _table(f"目录（共 {total} 章）", ["#", "章节名", "VIP", "已下载"])
    for chapter in chapters[:limit]:
        table.add_row(
            str(chapter.get("index", 0)),
            chapter.get("name", ""),
            "是" if chapter.get("is_vip") else "",
            "✓" if chapter.get("downloaded") else "",
        )
    console.print(table)
    if total > limit:
        console.print(f"[dim]（仅显示前 {limit} 章）[/]")


def print_sources(data: dict[str, Any]) -> None:
    """书源列表。"""
    items = data.get("items", [])
    if not items:
        console.print("[yellow]还没有书源。用 `inkflow sources import <文件>` 导入[/]")
        return
    table = _table(
        f"书源（{data.get('total', len(items))} 个）",
        ["ID", "名称", "类型", "等级", "启用", "搜索"],
    )
    for item in items:
        table.add_row(
            item.get("id", ""),
            item.get("name", ""),
            str(item.get("source_type", "")),
            str(item.get("compatibility_level", "")),
            "✓" if item.get("enabled") else "✗",
            "✓" if item.get("enabled_search") else "✗",
        )
    console.print(table)


def print_source_test(data: dict[str, Any]) -> None:
    """书源测试结果（规划书 §43 的 Source Debugger 输出）。"""
    ok = data.get("ok")
    style = "green" if ok else "red"
    header = (
        f"[bold {style}]{'通过' if ok else '失败'}[/]  "
        f"kind={data.get('kind')}  "
        f"耗时 {data.get('elapsed_ms')}ms  "
        f"结果数 {data.get('count', 0)}"
    )
    console.print(Panel(header, title=f"书源测试 {data.get('source_id')}", border_style=style))

    if data.get("error"):
        console.print(f"[red]{data['error']}[/]")

    preview = data.get("preview") or []
    if preview:
        table = _table("结果预览", list(preview[0].keys()))
        for row in preview:
            table.add_row(*[str(value)[:120] for value in row.values()])
        console.print(table)

    if data.get("debug"):
        console.print_json(json.dumps(data["debug"], ensure_ascii=False))


def print_tasks(data: dict[str, Any]) -> None:
    """任务列表。"""
    items = data.get("items", [])
    if not items:
        console.print("[yellow]没有下载任务[/]")
        return
    table = _table(
        f"任务（{data.get('total', len(items))} 个）",
        ["ID", "状态", "进度", "完成", "失败", "格式"],
    )
    for item in items:
        total = item.get("total", 0)
        completed = item.get("completed", 0)
        percent = f"{completed / total * 100:.1f}%" if total else "-"
        table.add_row(
            item.get("id", ""),
            str(item.get("status", "")),
            f"{completed}/{total} ({percent})",
            str(completed),
            str(item.get("failed", 0)),
            str(item.get("output_format", "")),
        )
    console.print(table)


def print_task(data: dict[str, Any]) -> None:
    """任务详情。"""
    task = data.get("task", data)
    book = data.get("book") or {}
    total = task.get("total", 0)
    completed = task.get("completed", 0)
    percent = (completed / total * 100) if total else 0.0

    console.print(
        Panel(
            "\n".join(
                [
                    f"任务      {task.get('id')}",
                    f"书籍      {book.get('name') or task.get('book_id')}",
                    f"状态      {task.get('status')}",
                    f"进度      {completed}/{total}  ({percent:.1f}%)  失败 {task.get('failed', 0)}",
                    f"区间      第 {task.get('start_chapter')} ~ {task.get('end_chapter')} 章",
                    f"并发      {task.get('concurrency')}",
                    f"输出      {task.get('output_path') or '-'}",
                    *([f"错误      {task['error']}"] if task.get("error") else []),
                ]
            ),
            title="任务详情",
            border_style="cyan",
        )
    )


def print_task_items(data: dict[str, Any], *, limit: int = 30) -> None:
    """任务章节明细。"""
    items = data.get("items", [])
    if not items:
        console.print("[yellow]没有明细记录[/]")
        return
    table = _table(
        f"章节明细（{data.get('total', len(items))} 条）", ["#", "章节", "状态", "重试", "错误"]
    )
    for item in items[:limit]:
        table.add_row(
            str(item.get("chapter_index", "")),
            str(item.get("chapter_name", ""))[:40],
            str(item.get("status", "")),
            str(item.get("attempts", 0)),
            (item.get("error") or "")[:60],
        )
    console.print(table)


def print_export_result(data: dict[str, Any]) -> None:
    """导出结果。"""
    console.print(
        Panel(
            f"格式      {data.get('format')}\n"
            f"章节数    {data.get('chapter_count')}\n"
            f"输出      [bold]{data.get('output_path')}[/]",
            title="导出完成",
            border_style="green",
        )
    )


def print_progress_event(event: dict[str, Any]) -> None:
    """下载进度事件（WebSocket 推送）。"""
    kind = event.get("type")
    if kind == "snapshot":
        console.print(
            f"[dim]当前状态 {event.get('status')} "
            f"{event.get('completed')}/{event.get('total')} ({event.get('percent')}%)[/]"
        )
    elif kind == "progress":
        line = (
            f"{event.get('completed')}/{event.get('total')} "
            f"({event.get('percent')}%)  {event.get('current') or ''}"
        )
        if event.get("error"):
            console.print(f"[yellow]{line}  ← 失败：{event['error']}[/]")
        else:
            console.print(line)
    elif kind == "completed":
        console.print(
            f"[bold green]任务完成[/]  成功 {event.get('completed')} / "
            f"失败 {event.get('failed')}\n输出：{event.get('output_path')}"
        )
    elif kind == "error":
        console.print(f"[bold red]任务失败[/] {event.get('message')}")
    elif kind == "heartbeat":
        pass
    else:
        console.print(f"[dim]{event}[/]")
