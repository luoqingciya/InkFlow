# InkFlow 项目长期记忆

> 只记「跨会话仍然成立」的事实与约定。日常进展写进 `YYYY-MM-DD.md`。

## 项目定位

**InkFlow** —— API-First 小说资源聚合与下载平台。
CLI 与 Electron 桌面端都只是客户端，业务核心只有一份。

**核心架构原则：内核兼容 + 外层隔离。**
兼容 Legado 的**数据结构与规则语义**，但兼容代码全部关在 `inkflow-legado` 一个包里。

## 已确认的决策

| 议题 | 决定 | 日期 |
|---|---|---|
| 许可证 | **Apache-2.0**（含专利授权；兼容层为独立实现，不复制 Legado 源码） | 2026-10-02 |
| 桌面端框架 | **Vue 3** + electron-vite | 2026-10-02 |
| 骨架深度 | 可运行 MVP：L0/L1 真实现，L2 JS / L3 浏览器只留接口与文档 | 2026-10-02 |
| Python 包管理 | uv workspace，6 个成员包 | 2026-10-02 |
| 数据库 | SQLite（WAL 模式） | 2026-10-02 |
| 版本号 | **PEP 440**，单一来源在 `inkflow_core.__version__`（当前 `0.1.0.dev0`） | 2026-10-02 |

## 版本号（硬约束）

**只在 `packages/inkflow-core/src/inkflow_core/__init__.py` 手写一次。**

- 各成员包 pyproject：`dynamic = ["version"]` + `[tool.hatch.version] path = "../inkflow-core/src/inkflow_core/__init__.py"`
- 各成员包 `__init__.py`：`from inkflow_core import __version__`
- 桌面端用 semver 等价写法（`0.1.0.dev0` → `0.1.0-dev.0`）
- 改完跑 `uv run python scripts/check_version.py`，CI 也会跑
- 副作用：成员包不能脱离 workspace 单独 `pip install`

## 硬约束（改代码时必须守住）

1. **依赖方向单向**：`core ← source ← legado`，`core ← export`，`api`，`cli`。
   反向 import 视为架构破坏。
2. **`inkflow-source` 不认识 Legado。** 各书源类型由自己的包通过
   `SourceRegistry.register_factory()` 注册。
3. **Source Adapter 不得自行创建 HTTP 客户端。** 统一走 `HttpClient`。
4. **书源是不可信输入。** SSRF 防护、协议白名单、资源限额默认开启。
5. **不静默降级。** 拿不到结果就报错，不要返回空列表让调用方以为「本来就没有」。
6. **书源配置只能收紧全局值**，不能放宽。
7. **Renderer 不接触 Node 权限**，只走 preload 的具名接口。

## 命令

```bash
uv sync --all-packages        # 必须带 --all-packages，否则成员包不装
uv run inkflow-server         # 起后端
uv run inkflow <cmd>          # CLI
uv run pytest -q              # 108 passed
uv run mypy .                 # 80 files, no issues
uv run ruff check .            # All checks passed
uv run python scripts/check.py  # 一键全检查
cd desktop && npm run dev     # 桌面端（尚未实机验证）
```

## 环境陷阱（本机特有）

- **代理会劫持 127.0.0.1**：`curl` 要加 `--noproxy '*'`；
  Python 测试要清 `http_proxy` 等环境变量，或设 `NO_PROXY=127.0.0.1,localhost`。
- **`uv sync` 不带 `--all-packages` 不装成员包**（见上）。
- **内存 SQLite 有每连接隔离问题**，测试用临时文件数据库。
- **YAML 双引号里 `\S` 非法**，正则用单引号。

## 文档

`docs/` 是设计依据，与代码同等重要。改代码时同步改文档。
关键决策记在 `docs/architecture/decisions.md`（ADR 格式，含「代价」一栏）。

## 代码风格

- 中文注释。**注释只说明代码的作用与客观约束，不解释「为什么」**
  —— 设计理由、取舍、踩坑写进 `docs/`。
- 提交信息用英文 Conventional Commits，scope 用模块名
  （`feat(source)` / `fix(api)` / `docs(architecture)`）。
- `__all__` 按「模型 / 配置 / 错误 / 工具」分组，不按字母序（ruff RUF022 已忽略）。
