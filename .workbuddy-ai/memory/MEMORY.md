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

## 仓库与流水线

- GitHub：**https://github.com/luoqingciya/InkFlow**（public，SSH remote）
- **CI**（push / PR）：版本号一致性 → ruff → mypy → pytest，
  矩阵 Ubuntu + Windows；另有桌面端类型检查与构建
- **Release**（push tag `v*`）：三平台 PyInstaller 打包后端 → 冒烟测试 →
  取回对应平台后端 → electron-builder 打安装包 → 创建 Release
- 本地一键检查：`uv run python scripts/check.py`（**含前端类型检查**，
  需先 `npm install`）
- 发版流程见 `docs/development/cicd.md`

**本机环境陷阱（构建后清理、验证桌面端必看）**：

- **WorkBuddy 自身会监视工作区文件并持有句柄**。刚构建出来的产物
  （`desktop/release/`、`desktop/build-*/`、`app.asar` 等）用 `rm -rf` 或
  `Remove-Item` 会报「另一个程序正在使用此文件」，且 `tasklist` 里找不到
  任何 inkflow / electron 进程 —— **占用者就是宿主自己**，不是残留进程。
  应对：先停掉相关进程，等几秒再删；实在删不掉就先留着（`.gitignore` 已覆盖），
  过一会儿重试通常就能删。
  别再往「electron-builder 锁文件」「杀毒软件」「索引服务」方向排查了。

- 环境**预设了 `ELECTRON_RUN_AS_NODE=1`**，会让 Electron 应用退化成 Node 运行
  —— 进程在跑但什么都不做，且 Chromium 参数会报 `bad option`（Node 的错误格式）。
  验证打包的桌面端必须先清掉：
  `env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS ./InkFlow.exe`
- `npx electron .` 在本机不可用（npm 的 allow-scripts 阻止了 Electron 的
  postinstall，二进制没下载）

**CI 上踩过的坑（改代码时留意）**：

- GitHub Actions 的 **Windows runner 控制台是 cp1252**，脚本打印中文会
  `UnicodeEncodeError`。已在脚本入口统一 `reconfigure(encoding="utf-8")`，
  CI 另设 `PYTHONUTF8=1`
- `spawn` 配 `stdio: ['ignore','pipe','pipe']` 时返回类型是
  `ChildProcessByStdio<null, Readable, Readable>`，不是
  `ChildProcessWithoutNullStreams`（stdin 是 null）
- PyInstaller spec 里的**相对路径是相对运行时 cwd**，不是 spec 所在目录，
  要用注入的 `SPECPATH`

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


## 文档

`docs/` 是设计依据，与代码同等重要。改代码时同步改文档。
关键决策记在 `docs/architecture/decisions.md`（ADR 格式，含「代价」一栏）。

## 代码风格

- 中文注释。**注释只说明代码的作用与客观约束，不解释「为什么」**
  —— 设计理由、取舍、踩坑写进 `docs/`。
- 提交信息用英文 Conventional Commits，scope 用模块名
  （`feat(source)` / `fix(api)` / `docs(architecture)`）。
- `__all__` 按「模型 / 配置 / 错误 / 工具」分组，不按字母序（ruff RUF022 已忽略）。

## ⚠️ 本机 pytest 退出码陷阱（重要，别误判）

**两个不同的现象，根因都是宿主的 safe-delete 守门器（`sitecustomize.py`）：**

1. 全量 `pytest` 偶发 exit 1，stdout 里**没有 `F`**、也不打印 summary。
   teardown 删 `%TEMP%\pytest-of-<user>\garbage-*`（累积 100+ 目录）
   触发 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` → `SystemExit(1)`。
2. `--basetemp` 指向**工作区内的目录** → 稳定 `151 errors`（只有 6 passed）。
   守门器把 basetemp 下的 `…current` 符号链接解析成整个工作区，
   报「上千个文件」直接硬退，连 fixture setup 都进不去。

**测试本身是全绿的，不是失败。**

**正确跑法**（basetemp 放工作区之外）：
```bash
uv run pytest -p no:cacheprovider --basetemp="$TEMP/inkflow_pt_$RANDOM"
# 157 passed
```

**判断与处理**：
1. stdout 无 `F` 但 exit≠0 → 先怀疑是清理被拦，不是测试挂
2. stdout / stderr 分开重定向，看 stderr 里的 safe-delete 消息
3. **别用「多跑几次碰运气」查偶发失败**，先从代码语义推理或加诊断断言


