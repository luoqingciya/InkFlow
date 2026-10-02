"""解析原语：HTML / JSON / Text 三类。

统一输出为 Python 原生类型，规则层不感知底层解析库。
"""

from inkflow_source.parsers import html, json, text

__all__ = ["html", "json", "text"]
