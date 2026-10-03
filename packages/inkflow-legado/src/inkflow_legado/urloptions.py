"""Legado 的 ``url,{options}`` 选项解析。

真实书源写的是 **Gson 风格**的宽松 JSON：单引号、小写布尔。标准 ``json``
只认双引号 —— 直接 ``json.loads`` 会失败，于是整段选项被当成 URL 的一部分，
请求打到一个根本不存在的地址上。

实测（1363 条真实书源）：22 条用 ``{'webView': true}`` 这种写法。

所以这里自带一个小解析器，只覆盖 Legado 实际用到的子集。
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["split_url_options", "parse_options"]


def split_url_options(text: str) -> tuple[str, dict[str, Any]]:
    """拆分 ``url,{json}`` 写法。

    Legado 允许在 URL 后追加一段 JSON 描述请求方法、请求体等：

        ``/search,{"method":"POST","body":"key={{key}}"}``
        ``https://x/a,{'webView': true}``

    解析不出来时返回**原文**与空选项 —— 宁可不识别，也不要猜错 URL。
    """
    # 从右往左找第一个「后面确实能解析成选项」的逗号。
    # 不能简单取最后一个逗号 —— 选项 JSON 内部本来就有逗号
    # （``{"method":"POST","body":"..."}``），取错了整段选项会留在 URL 里。
    end = len(text)
    while True:
        index = text.rfind(",", 0, end)
        if index == -1:
            return text, {}
        candidate = text[index + 1 :].strip()
        if candidate.startswith("{"):
            parsed = parse_options(candidate)
            if parsed is not None:
                return text[:index], parsed
        end = index


def parse_options(text: str) -> dict[str, Any] | None:
    """解析选项对象。解析不出来返回 ``None``，不抛 —— 选项坏了不该让整条规则崩。"""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _lenient_load(text)
    return parsed if isinstance(parsed, dict) else None


def _lenient_load(text: str) -> Any:
    try:
        return _LenientParser(text).parse()
    except (ValueError, IndexError):
        return None


class _LenientParser:
    """宽松 JSON 子集解析器。

    覆盖：对象、数组、单/双引号字符串、数字、``true`` / ``false`` / ``null``、
    不带引号的键。这些正是 Legado 选项里会出现的东西。
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def parse(self) -> Any:
        value = self._value()
        self._space()
        if self._pos != len(self._text):
            raise ValueError("选项里有多余内容")
        return value

    # -- 结构 --------------------------------------------------------------

    def _value(self) -> Any:
        self._space()
        char = self._peek()
        if char == "{":
            return self._object()
        if char == "[":
            return self._array()
        if char in "\"'":
            return self._string()
        return self._literal()

    def _object(self) -> dict[str, Any]:
        self._expect("{")
        result: dict[str, Any] = {}
        self._space()
        if self._peek() == "}":
            self._pos += 1
            return result

        while True:
            self._space()
            key = self._string() if self._peek() in "\"'" else self._bare_key()
            self._expect(":")
            result[str(key)] = self._value()
            self._space()
            char = self._peek()
            self._pos += 1
            if char == "}":
                return result
            if char != ",":
                raise ValueError(f"选项里出现意外字符：{char!r}")

    def _array(self) -> list[Any]:
        self._expect("[")
        items: list[Any] = []
        self._space()
        if self._peek() == "]":
            self._pos += 1
            return items

        while True:
            items.append(self._value())
            self._space()
            char = self._peek()
            self._pos += 1
            if char == "]":
                return items
            if char != ",":
                raise ValueError(f"数组里出现意外字符：{char!r}")

    # -- 标量 --------------------------------------------------------------

    def _string(self) -> str:
        quote = self._peek()
        self._pos += 1
        chars: list[str] = []
        while True:
            char = self._peek()
            self._pos += 1
            if char == quote:
                return "".join(chars)
            if char == "\\":
                chars.append(self._unescape())
                continue
            chars.append(char)

    def _unescape(self) -> str:
        char = self._peek()
        self._pos += 1
        if char == "u":
            code = self._text[self._pos : self._pos + 4]
            self._pos += 4
            return chr(int(code, 16))
        return {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(char, char)

    def _bare_key(self) -> str:
        start = self._pos
        while not self._at_end() and self._peek() not in ":,}":
            self._pos += 1
        return self._text[start : self._pos].strip()

    def _literal(self) -> Any:
        start = self._pos
        while not self._at_end() and self._peek() not in ",}]":
            self._pos += 1
        token = self._text[start : self._pos].strip()

        lowered = token.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in ("null", "none", ""):
            return None
        for cast in (int, float):
            try:
                return cast(token)
            except ValueError:
                continue
        return token  # 裸值当字符串

    # -- 基础 --------------------------------------------------------------

    def _peek(self) -> str:
        if self._at_end():
            raise ValueError("选项提前结束")
        return self._text[self._pos]

    def _at_end(self) -> bool:
        return self._pos >= len(self._text)

    def _expect(self, char: str) -> None:
        self._space()
        if self._peek() != char:
            raise ValueError(f"期望 {char!r}，实际 {self._peek()!r}")
        self._pos += 1

    def _space(self) -> None:
        while not self._at_end() and self._text[self._pos].isspace():
            self._pos += 1
