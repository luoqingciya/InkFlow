"""inkflow-legado —— Legado 书源兼容层。

**这是一个隔离的 Compatibility Runtime，不是 Legado 的二次实现。**

它只做三件事：

1. 解析 Legado 书源 JSON 结构（``schema``）
2. 把 Legado 规则 DSL 编译成统一 AST（``compiler`` / ``rules``）
3. 执行 AST 并产出 ``inkflow_core`` 的标准结果（``adapter``）

当前覆盖 **L0 + L1 + L2**：JSON 结构、CSS / XPath / JSONPath / 正则，
以及 ``@js:`` 规则（跑独立 Node sidecar，见 ``inkflow-js-runtime``）。
L3（浏览器）由 ``inkflow-browser-*`` 引擎提供，经 ``webView`` 选项接入。
做不到的写法**明确报错**，不静默失败。

本包不复制 Legado 项目的任何源代码。
"""

from inkflow_core import __version__
from inkflow_legado.adapter import LegadoSourceAdapter, split_url_options
from inkflow_legado.compiler import (
    LegadoRuleCompiler,
    compile_rule,
    default_compiler,
    legado_selector_to_css,
    render_legado_template,
)
from inkflow_legado.register import (
    build_legado_source,
    detect_level,
    register_legado,
    stable_source_id,
)
from inkflow_legado.rules import Replacement, Rule, RuleContext, RuleMode
from inkflow_legado.schema import (
    LegadoBookInfoRule,
    LegadoBookSource,
    LegadoContentRule,
    LegadoSearchRule,
    LegadoTocRule,
)

# __version__ 由 inkflow-core 转发而来，全项目只有一处定义

__all__ = [
    "__version__",
    # schema
    "LegadoBookSource",
    "LegadoSearchRule",
    "LegadoBookInfoRule",
    "LegadoTocRule",
    "LegadoContentRule",
    # rules
    "Rule",
    "RuleMode",
    "RuleContext",
    "Replacement",
    # compiler
    "LegadoRuleCompiler",
    "default_compiler",
    "compile_rule",
    "legado_selector_to_css",
    "render_legado_template",
    # adapter
    "LegadoSourceAdapter",
    "split_url_options",
    # register
    "register_legado",
    "build_legado_source",
    "stable_source_id",
    "detect_level",
]
