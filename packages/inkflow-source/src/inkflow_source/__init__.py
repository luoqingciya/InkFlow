"""inkflow-source —— 书源引擎。

职责：定义书源适配器契约、管理书源注册表、提供统一 HTTP 引擎与解析原语。

本包**不认识 Legado**。Legado 兼容层在 ``inkflow-legado`` 中实现，
并通过 ``SourceRegistry.register_factory`` 把工厂注入进来。
"""

from inkflow_source.adapter import BaseSourceAdapter, SourceAdapter
from inkflow_source.aggregator import SearchAggregator, SourceOutcome, score_book
from inkflow_source.http import DEFAULT_USER_AGENT, HttpCache, HttpClient, HttpResponse
from inkflow_source.limiter import ConcurrencyLimiter, RequestGate, TokenBucket
from inkflow_source.loader import (
    FormatParser,
    SourceLoader,
    build_native_source,
    default_loader,
    detect_format,
)
from inkflow_source.native import NativeSourceAdapter, NativeSourceSpec
from inkflow_source.normalizer import DEFAULT_RULES, ContentNormalizer, NormalizeRules
from inkflow_source.parsers import html, json, text
from inkflow_source.registration import register_native
from inkflow_source.registry import (
    HttpFactory,
    SourceFactory,
    SourceRegistry,
    default_registry,
)
from inkflow_source.security import UrlBlockedError, check_url, check_url_sync

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # adapter
    "SourceAdapter",
    "BaseSourceAdapter",
    # native
    "NativeSourceAdapter",
    "NativeSourceSpec",
    # loader
    "SourceLoader",
    "FormatParser",
    "default_loader",
    "detect_format",
    "build_native_source",
    # registry
    "SourceRegistry",
    "SourceFactory",
    "HttpFactory",
    "default_registry",
    "register_native",
    # http
    "HttpClient",
    "HttpResponse",
    "HttpCache",
    "DEFAULT_USER_AGENT",
    # limiter
    "RequestGate",
    "TokenBucket",
    "ConcurrencyLimiter",
    # normalizer
    "ContentNormalizer",
    "NormalizeRules",
    "DEFAULT_RULES",
    # aggregator
    "SearchAggregator",
    "SourceOutcome",
    "score_book",
    # parsers
    "html",
    "json",
    "text",
    # security
    "check_url",
    "check_url_sync",
    "UrlBlockedError",
]
