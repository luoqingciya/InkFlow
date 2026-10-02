"""JSON 解析原语（JSONPath）。"""

from __future__ import annotations

import json
from typing import Any

from jsonpath_ng.ext import parse as jsonpath_parse

__all__ = ["as_text", "loads", "query", "query_first", "query_string", "query_strings"]


def loads(source: str | bytes | Any) -> Any:
    """解析 JSON；已是 Python 对象时原样返回。"""
    if isinstance(source, (dict, list)):
        return source
    if isinstance(source, bytes):
        source = source.decode("utf-8", errors="replace")
    return json.loads(source)


def query(data: str | bytes | Any, expr: str) -> list[Any]:
    """执行 JSONPath，返回全部匹配值。

    Raises:
        ValueError: JSON 无法解析或 JSONPath 语法错误。
    """
    document = loads(data)
    try:
        matches = jsonpath_parse(expr).find(document)
    except Exception as exc:  # jsonpath_ng 的异常类型不稳定，统一收敛
        raise ValueError(f"JSONPath 语法错误: {expr!r} ({exc})") from exc
    return [match.value for match in matches]


def query_first(data: str | bytes | Any, expr: str, *, default: Any = None) -> Any:
    """取第一个匹配值。"""
    matches = query(data, expr)
    return matches[0] if matches else default


def as_text(value: Any) -> str | None:
    """把任意 JSON 值转成字符串。

    字符串原样返回；数字 / 布尔转字面量；容器转 JSON 文本。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def query_string(data: str | bytes | Any, expr: str, *, default: str | None = None) -> str | None:
    """执行 JSONPath 并返回字符串结果。"""
    value = query_first(data, expr)
    text = as_text(value)
    return text if text is not None else default


def query_strings(data: str | bytes | Any, expr: str) -> list[str]:
    """执行 JSONPath 并返回字符串列表。"""
    return [text for value in query(data, expr) if (text := as_text(value)) is not None]
