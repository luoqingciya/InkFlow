"""领域枚举。"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CompatibilityLevel",
    "ExportFormat",
    "SourceFormat",
    "SourceType",
    "TaskItemStatus",
    "TaskStatus",
]


class SourceType(StrEnum):
    """书源运行方式。"""

    NATIVE = "native"
    """InkFlow 原生书源，规则直接用 Python / YAML 描述。"""

    LEGADO = "legado"
    """Legado 书源，经兼容层编译后执行。"""

    BROWSER = "browser"
    """需要浏览器渲染的书源（Milestone 4）。"""


class SourceFormat(StrEnum):
    """书源文件的物理格式。"""

    NATIVE_YAML = "native-yaml"
    LEGADO_JSON = "legado-json"
    LEGADO_JS = "legado-js"


class CompatibilityLevel(StrEnum):
    """Legado 兼容等级，定义见 docs/source/compatibility-levels.md。"""

    L0 = "L0"
    """能读取 Legado JSON 结构。"""

    L1 = "L1"
    """CSS / XPath / JSONPath / 正则规则可执行。"""

    L2 = "L2"
    """Legado JS Source 可在沙箱中执行。"""

    L3 = "L3"
    """浏览器 / Cookie / 登录环境。"""

    NATIVE = "native"
    """非 Legado 来源，不参与兼容性评分。"""


class TaskStatus(StrEnum):
    """下载任务状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        """终态不可再转换。"""
        return self in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    @property
    def is_active(self) -> bool:
        """处于可被暂停 / 取消的运行态。"""
        return self in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED}


class TaskItemStatus(StrEnum):
    """单个章节的下载状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExportFormat(StrEnum):
    """导出格式。"""

    TXT = "txt"
    EPUB = "epub"
    MARKDOWN = "markdown"
    HTML = "html"
