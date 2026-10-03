"""配置加载。

优先级（从高到低）：

1. 显式传入的 ``Settings(...)`` 参数
2. 环境变量 ``INKFLOW_*``（嵌套用双下划线，如 ``INKFLOW_SERVER__PORT``）
3. ``config.toml``（当前工作目录，或 ``INKFLOW_CONFIG`` 指定的路径）
4. 内置默认值

字段含义见仓库根目录的 ``config.example.toml``。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

__all__ = [
    "BrowserConfig",
    "CacheConfig",
    "DownloadConfig",
    "ExportConfig",
    "JsConfig",
    "LogConfig",
    "ServerConfig",
    "Settings",
    "SourceConfig",
    "get_settings",
    "parse_size",
]

ENV_CONFIG = "INKFLOW_CONFIG"

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?\s*$", re.IGNORECASE)
_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def parse_size(value: str | int) -> int:
    """把 ``"2GB"`` / ``"512 MB"`` / ``1024`` 解析为字节数。

    Raises:
        ValueError: 格式无法识别。
    """
    if isinstance(value, int):
        return value
    match = _SIZE_RE.match(value)
    if match is None:
        raise ValueError(f"无法解析的体积单位: {value!r}")
    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    return int(number * _SIZE_UNITS[unit])


class ServerConfig(BaseModel):
    """HTTP 服务配置。"""

    host: str = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)
    require_token: bool = True

    @field_validator("host")
    @classmethod
    def _warn_public_bind(cls, value: str) -> str:
        # 只做记录，不阻断：容器化部署确实可能绑定 0.0.0.0。
        if value not in {"127.0.0.1", "localhost", "::1"}:
            import warnings

            warnings.warn(
                f"server.host={value!r} 会把本地下载器暴露到网络，请确认这是有意为之",
                stacklevel=2,
            )
        return value


class DownloadConfig(BaseModel):
    """下载行为配置。"""

    concurrency: int = Field(default=4, ge=1, le=64)
    timeout: float = Field(default=20.0, gt=0)
    retry: int = Field(default=3, ge=0, le=10)
    retry_backoff: float = Field(default=1.0, ge=0)
    min_interval: float = Field(default=0.0, ge=0)


class ExportConfig(BaseModel):
    """导出配置。"""

    default_format: str = "epub"
    default_output_dir: str = ""
    filename_template: str = "{name} - {author}"

    @field_validator("default_format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        allowed = {"txt", "epub", "markdown", "md", "html"}
        lowered = value.lower()
        if lowered not in allowed:
            raise ValueError(f"不支持的导出格式: {value!r}，可选 {sorted(allowed)}")
        return lowered


class CacheConfig(BaseModel):
    """缓存配置。"""

    enabled: bool = True
    max_size: str = "2GB"
    http_ttl: int = Field(default=3600, ge=0)

    @property
    def max_size_bytes(self) -> int:
        return parse_size(self.max_size)


class SourceConfig(BaseModel):
    """书源请求层配置。"""

    global_concurrency: int = Field(default=16, ge=1, le=256)
    domain_concurrency: int = Field(default=6, ge=1, le=64)
    requests_per_second: float = Field(default=2.0, gt=0)
    timeout: float = Field(default=20.0, gt=0)
    retry: int = Field(default=3, ge=0, le=10)
    allow_private_network: bool = False


class JsConfig(BaseModel):
    """Legado JS 沙箱配置（Milestone 3 生效）。"""

    enabled: bool = False
    timeout: float = Field(default=15.0, gt=0, le=120)
    max_memory_mb: int = Field(default=128, ge=16)
    max_requests: int = Field(default=50, ge=0)
    max_response_size: str = "8MB"

    @property
    def max_response_bytes(self) -> int:
        return parse_size(self.max_response_size)


class BrowserConfig(BaseModel):
    """浏览器运行时配置（Milestone 4 生效）。"""

    enabled: bool = False
    engine: str = "playwright"
    headless: bool = True
    timeout: float = Field(default=30.0, gt=0)
    #: 浏览器安装目录。留空表示用 ``<数据目录>/browsers``。
    #: 多份安装想共享同一份浏览器时指向同一个目录。
    install_dir: str = ""
    #: 浏览器下载源。留空表示用 playwright 官方 CDN（它自带多级 fallback）。
    #: 官方源不通时填镜像地址 —— 只在下载那一步生效。
    download_host: str = ""


class LogConfig(BaseModel):
    """日志配置。"""

    level: str = "INFO"
    # 不用 ``json`` 作字段名：Pydantic 的 BaseModel 已占用该名字（序列化方法），
    # 同名会产生运行时警告
    json_logs: bool = False
    rotate_max_mb: int = Field(default=10, ge=1)
    rotate_backups: int = Field(default=5, ge=0)

    @field_validator("level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


def default_config_file() -> Path | None:
    """定位 config.toml。"""
    override = os.environ.get(ENV_CONFIG)
    if override:
        candidate = Path(override).expanduser().resolve()
        return candidate if candidate.is_file() else None

    for candidate in (Path.cwd() / "config.toml", Path.cwd() / "config.example.toml"):
        if candidate.is_file():
            return candidate
    return None


class Settings(BaseSettings):
    """InkFlow 全局配置。"""

    model_config = SettingsConfigDict(
        env_prefix="INKFLOW_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    source: SourceConfig = Field(default_factory=SourceConfig)
    js: JsConfig = Field(default_factory=JsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        toml_path = default_config_file()
        if toml_path is not None:
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_path))
        sources.append(file_secret_settings)
        return tuple(sources)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程级配置单例。"""
    return Settings()
