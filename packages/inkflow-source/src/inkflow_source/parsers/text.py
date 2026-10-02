"""文本解析原语（正则 / 模板 / 替换）。

对应规划书 §17 的 Text 分支：正则、替换、归一化。
"""

from __future__ import annotations

import html as html_module
import re
from typing import Any

__all__ = [
    "compile_pattern",
    "regex_all",
    "regex_extract",
    "regex_replace",
    "render_template",
    "strip_tags",
    "unescape_html",
]

#: 模板占位符：{{key}} 或 {key}
_TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}|\{\s*([A-Za-z_][\w.]*)\s*\}")
_TAG_RE = re.compile(r"<[^>]+>")


def compile_pattern(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """编译正则。语法错误时抛出带上下文的 ``ValueError``。"""
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"正则语法错误: {pattern!r} ({exc})") from exc


def regex_extract(
    text: str,
    pattern: str,
    group: int | str = 1,
    *,
    default: str | None = None,
    flags: int = 0,
) -> str | None:
    """提取第一个匹配的分组内容。

    Args:
        group: 分组序号或名称；传 ``0`` 取整个匹配。
    """
    match = compile_pattern(pattern, flags).search(text)
    if match is None:
        return default
    try:
        return match.group(group)
    except (IndexError, re.error) as exc:
        raise ValueError(f"正则分组 {group!r} 不存在: {pattern!r}") from exc


def regex_all(text: str, pattern: str, *, group: int | str = 0, flags: int = 0) -> list[str]:
    """提取全部匹配的分组内容。"""
    return [m.group(group) for m in compile_pattern(pattern, flags).finditer(text)]


def regex_replace(text: str, pattern: str, replacement: str, *, flags: int = 0) -> str:
    """正则替换。``replacement`` 支持 ``\\1`` 形式的分组引用。"""
    return compile_pattern(pattern, flags).sub(replacement, text)


def render_template(template: str, variables: dict[str, Any]) -> str:
    """渲染 ``{{key}}`` 模板。

    支持点号取值（``{{book.name}}``）。未定义的键**原样保留**，
    便于定位书源里写错的变量名，而不是静默变成空串。
    """

    def _lookup(key: str) -> str:
        parts = key.split(".")
        value: Any = variables
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return f"{{{{{key}}}}}"
        return "" if value is None else str(value)

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return _lookup(key)

    return _TEMPLATE_RE.sub(_sub, template)


def strip_tags(text: str) -> str:
    """粗暴剥离 HTML 标签。复杂 HTML 请用 ``parsers.html``。"""
    return _TAG_RE.sub("", text)


def unescape_html(text: str) -> str:
    """解码 HTML 实体（``&nbsp;`` / ``&amp;`` / 数字实体）。"""
    return html_module.unescape(text)
