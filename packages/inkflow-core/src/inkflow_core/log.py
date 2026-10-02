"""日志配置（规划书 §28）。

**为什么不用 ``logging.basicConfig``。** 它只在 root logger 尚无 handler 时生效。
uvicorn 启动时会抢先装自己的 handler，于是我们的配置被**静默忽略** ——
症状是「配置写了、代码也调了，日志就是没落盘」，且不报任何错。
所以这里显式管理自己的 handler，并在启动 uvicorn 时传 ``log_config=None``，
让它的日志走 root（否则 uvicorn 的 ``propagate=False`` 会把日志截在自己那里）。

**写不进去不抛错。** 日志目录只读（macOS 的 ``.app`` 内部、部分 Linux 安装位置）
时降级为仅控制台输出，服务照常启动 —— 日志是辅助设施，不该带走主流程。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path

from inkflow_core.config import LogConfig

__all__ = ["JsonFormatter", "LOG_FILENAME", "setup_logging"]

LOG_FILENAME = "inkflow.log"

#: LogRecord 自带属性 —— JSON 输出时这些不进「附加字段」
_RESERVED_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys())

#: 已安装的文件 handler。用它做幂等判断，避免重复调用叠加 handler。
_file_handler: logging.Handler | None = None


class JsonFormatter(logging.Formatter):
    """JSON Lines 格式：每行一条独立 JSON，便于日志采集器逐行解析。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # ``logger.info(..., extra={"task_id": ...})`` 传进来的字段一并输出
        for key, value in record.__dict__.items():
            if key not in _RESERVED_FIELDS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(config: LogConfig, logs_dir: Path) -> logging.Handler | None:
    """配置根 logger 的控制台与文件输出。

    幂等：同一进程内重复调用不会叠加 handler。

    Args:
        config: 日志配置。
        logs_dir: 日志目录，不存在时创建。

    Returns:
        文件 handler；目录不可写时为 ``None``（此时只有控制台输出）。
    """
    global _file_handler

    root = logging.getLogger()
    root.setLevel(config.level)

    if _file_handler is not None and _file_handler in root.handlers:
        return _file_handler

    formatter: logging.Formatter = JsonFormatter() if config.json_logs else _text_formatter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = _open_file_handler(logs_dir, config, formatter)
    if file_handler is not None:
        root.addHandler(file_handler)
        _file_handler = file_handler

    return file_handler


def _text_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _open_file_handler(
    logs_dir: Path,
    config: LogConfig,
    formatter: logging.Formatter,
) -> logging.Handler | None:
    """打开轮转日志文件；失败时返回 ``None`` 而不是抛错。"""
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            logs_dir / LOG_FILENAME,
            maxBytes=config.rotate_max_mb * 1024 * 1024,
            backupCount=config.rotate_backups,
            # 必须显式指定：Windows 默认 cp1252，中文日志会乱码甚至抛异常
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None

    handler.setFormatter(formatter)
    return handler
