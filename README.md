# InkFlow

[![CI](https://github.com/luoqingciya/InkFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/luoqingciya/InkFlow/actions/workflows/ci.yml)
[![Release](https://github.com/luoqingciya/InkFlow/actions/workflows/release.yml/badge.svg)](https://github.com/luoqingciya/InkFlow/actions/workflows/release.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

> **API-First 小说资源聚合与下载平台**
> 内核兼容 · 外层隔离

InkFlow 把「搜索 → 解析 → 下载 → 导出」做成一个**独立的后端服务**，CLI 和桌面端都只是它的客户端。
业务核心只有一份，入口可以有很多个。

它不是「一个小说下载 GUI」，而是：

> **一个以 API 为核心、支持多种书源运行时的个人数字内容获取与整理平台。**

---

## 为什么不是又一个下载器

传统写法把搜索、请求、解析、下载、GUI 揉在一起，结果是换 GUI 就要重写业务层、书源规则和业务逻辑互相污染、下载任务无法统一管理、也没法给第三方客户端复用。

InkFlow 的切法是**把业务沉到服务里**：

```text
                         ┌──────────────────────┐
                         │      Electron        │
                         │      Desktop         │
                         └──────────┬───────────┘
                                    │ HTTP / WS
                                    ▼
┌──────────────┐           ┌──────────────────────┐
│     CLI      │ ────────▶ │    InkFlow API       │
│    Python    │           │      FastAPI         │
└──────────────┘           └──────────┬───────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              ┌──────────┐      ┌───────────┐      ┌───────────┐
              │ Book Core│      │ Task Core │      │Downloader │
              └─────┬────┘      └─────┬─────┘      └─────┬─────┘
                    │                 │                  │
                    ▼                 ▼                  ▼
              ┌───────────────────────────────────────────────┐
              │                Source Engine                  │
              ├───────────────────────────────────────────────┤
              │ Native Source │ Legado Adapter │ JS Runtime │  │
              └───────────────────────────────────────────────┘
                                      │
                                      ▼
                              ┌────────────────┐
                              │ SQLite / Cache │
                              └────────────────┘
```

**CLI 和 Desktop 都只是客户端，真正的业务核心只有一份。**

---

## 核心设计原则

| 原则 | 含义 |
|---|---|
| **API-First** | 所有核心能力先定义 HTTP 接口，UI 只是消费者。`/api/v1` 从第一版就固定。 |
| **内核兼容 + 外层隔离** | 兼容 Legado 的**数据结构与规则格式**，但兼容代码全部关在 `inkflow-legado` 里。Legado 规则变了，只升级这一个包。 |
| **书源是不可信输入** | 第三方书源 = 第三方代码 + 第三方网络请求。JS 沙箱、SSRF 防护、资源限额默认开启。 |
| **失败要看得见** | 统一错误码 + Trace ID，不静默降级。 |
| **任务化下载** | 下载是一等公民（`DownloadTask`），不是 `for chapter in chapters`。支持暂停 / 恢复 / 取消 / 重试。 |

---

## 仓库结构

```text
InkFlow/
├── packages/                    # Python uv workspace
│   ├── inkflow-core/            # 数据模型、配置、存储抽象（无业务依赖）
│   ├── inkflow-source/          # Source Engine：Adapter 协议、注册表、HTTP 引擎
│   ├── inkflow-legado/          # Legado 兼容层：Schema、Rule Compiler、Adapter
│   ├── inkflow-api/             # FastAPI 服务：REST + WebSocket
│   ├── inkflow-cli/             # Typer CLI（纯 API 客户端）
│   └── inkflow-export/          # 导出器：TXT / EPUB
├── desktop/                     # Electron + Vue 3 桌面端
│   └── src/{main,preload,renderer}
├── runtime/js/                  # Legado JS 沙箱运行时（Milestone 3）
├── sources/                     # 书源：official / community / test
├── tests/                       # unit / integration / source / fixtures
├── docs/                        # 架构、API、书源、开发文档
└── scripts/                     # 开发辅助脚本
```

依赖方向是单向的，不允许反向 import：

```text
inkflow-core  ←  inkflow-source  ←  inkflow-legado
      ↑                ↑
      │                │
inkflow-api  ──────────┘
      ↑
inkflow-cli
```

---

## 快速开始

### 环境要求

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)（Python 依赖与 workspace 管理）
- Node.js **20+**（仅桌面端需要）

### 安装

```bash
uv sync --all-packages
```

> `--all-packages` 不能省。uv workspace 里 `uv sync` 默认只装根项目的依赖，
> 6 个成员包不会被装进虚拟环境。

### 启动后端

```bash
uv run inkflow-server              # 等价于 uvicorn inkflow_api.main:app
uv run inkflow-server --port 8765 # 指定端口（默认 0 = 系统分配）
```

启动后：

- API 文档：<http://127.0.0.1:8765/docs>
- 健康检查：<http://127.0.0.1:8765/health>

### 使用 CLI

```bash
uv run inkflow --help

uv run inkflow search "三体"
uv run inkflow search "三体" --json

uv run inkflow sources list
uv run inkflow sources import ./sources/official/example.json
uv run inkflow sources test example search 三体

uv run inkflow book info <book-id>
uv run inkflow book chapters <book-id>

uv run inkflow download <book-id> --start 1 --end 100
uv run inkflow task list
uv run inkflow task start <task-id>
uv run inkflow task pause <task-id>
uv run inkflow task resume <task-id>
uv run inkflow task cancel <task-id>

uv run inkflow export <book-id> --format epub
```

### 启动桌面端

```bash
cd desktop
npm install
npm run dev
```

桌面端会自动拉起后端进程、协商空闲端口、拿 session token，Renderer 通过 preload 白名单接口访问。

---

## 怎么用

上面那节讲的是**怎么把它跑起来**。这节讲**跑起来之后怎么用**。

### 先说一件最要紧的事：InkFlow 不带书源

书源（抓哪个网站、用什么规则解析）**需要你自己导入**。项目不内置、
不维护、不默认分发任何第三方书源合集 —— 这是刻意的：

- 书源指向的站点会变，内置的书源很快就会失效，维护它没有意义
- 更重要：**分发指向特定站点的书源，性质就变了**

`sources/official/` 里只有**结构模板**，导入进去也不能用（地址是占位的）。
`sources/test/mock-site.yaml` 是给测试用的本地站点，同理。

书源从哪来？两条路：

1. **自己写**。原生书源是声明式 YAML，照 `sources/official/example.yaml`
   的注释改即可，不用写代码。
2. **导入 Legado 书源**。InkFlow 兼容「开源阅读」的书源格式，
   社区里能找到的书源可以直接导入（`inkflow sources import <文件>`）。

使用本书源抓取内容时，你需要自行遵守来源网站的服务条款、版权规定
与所在司法辖区的法律。详见 [许可证与合规](#许可证与合规)。

### 完整流程

```bash
# 1. 起服务（桌面端会自动拉起，命令行用的话手动起）
uv run inkflow-server --port 8765

# 2. 导入一个书源
uv run inkflow sources import ./my-source.yaml
uv run inkflow sources list                 # 确认导入成功、是启用状态
uv run inkflow sources test <id> search 三体 # 先试一下这个书源能不能用

# 3. 搜索
uv run inkflow search "三体"
#    输出里会带上 book-id，下一步要用

# 4. 看目录，确认要下哪些章
uv run inkflow book chapters <book-id>

# 5. 下载（不写区间就是全本）
uv run inkflow download <book-id> --start 1 --end 50

# 6. 导出成 EPUB
uv run inkflow export <book-id> --format epub
```

下载是**异步任务**：`download` 命令提交后立刻返回任务 ID，可以用
`inkflow task list` 看进度，或 `inkflow task pause/resume/cancel` 控制它。

### 桌面端

```bash
cd desktop && npm install && npm run dev
```

界面里的顺序和上面一样：**书源 → 搜索 → 书库 → 下载 → 导出**。
几个和命令行不同的地方：

- 下载进度是**实时推送**的（WebSocket），不用手动刷新
- 下载时可以随时暂停 / 恢复 / 取消
- 已经下载过的章节会自动跳过，重跑不会重复抓

### 文件都放在哪

所有数据都在**一个目录**下，拷走即迁移（见 [ADR-015](docs/architecture/decisions.md)）：

| 内容 | 位置 |
|---|---|
| 数据根目录 | 运行目录下的 `.inkflow/`（不可写时回退到 `~/.inkflow`） |
| 数据库 | `.inkflow/database/inkflow.db` |
| 导出的书 | `.inkflow/exports/` |
| 正文插图 | `.inkflow/books/<书籍ID>/images/` |
| 日志 | `.inkflow/logs/inkflow.log` |
| 后端握手信息 | `.inkflow/server.json`（端口 + token，CLI 靠它找到服务） |

想换位置就设环境变量 `INKFLOW_HOME=/path/to/data`。

### 常见问题

**搜索没结果？** 先 `inkflow sources test <id> search <关键词>` 确认书源本身
能用 —— 站点改版会让书源失效，这与 InkFlow 无关。

**下载很慢？** 默认每域名 2 请求/秒，是为了不对站点造成压力。可以在
`config.toml` 的 `[source]` 段调整，但**不要调得太激进** —— 被限流反而更慢。

**导出的 EPUB 没有封面？** 封面地址在**详情页**规则里，下载时若书库里
还没有封面，InkFlow 会补抓一次详情页。若书源本身没写封面规则，就没有封面。

**EPUB 里为什么没有插图？** 正文插图**会下载到本地**
（`.inkflow/books/<书籍ID>/images/`），但**不嵌进 EPUB**。
要嵌进去得让正文保留图片位置，而正文目前是纯文本 —— 那是「正文格式」的
架构改动，收益不抵改动面。图片文件本身在磁盘上，需要的话可以自己去取。

**想看服务在干什么？** 日志在 `.inkflow/logs/inkflow.log`，
配置里可开 JSON Lines 格式（见 `config.example.toml` 的 `[log]` 段）。

---

## 开发

```bash
uv sync --all-packages        # 安装依赖（必须带 --all-packages）
uv run ruff check .           # 静态检查
uv run ruff format .          # 格式化
uv run mypy .                 # 类型检查
uv run pytest                 # 测试
uv run pytest -m unit         # 只跑单元测试
uv run python scripts/check.py  # 一键：lint + format + mypy + pytest
```

提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)，scope 用模块名：

```text
feat(source): 支持 Legado JSONPath 规则
fix(api): 修正任务暂停后状态未持久化
docs(architecture): 补充兼容等级说明
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture/overview.md](docs/architecture/overview.md) | 总体架构与分层 |
| [docs/architecture/decisions.md](docs/architecture/decisions.md) | 关键设计决策（ADR） |
| [docs/source/legado.md](docs/source/legado.md) | Legado 兼容层设计 |
| [docs/source/compatibility-levels.md](docs/source/compatibility-levels.md) | L0~L3 兼容等级定义 |
| [docs/api/rest-api.md](docs/api/rest-api.md) | REST API 规范 |
| [docs/api/errors.md](docs/api/errors.md) | 错误码规范 |
| [docs/development/setup.md](docs/development/setup.md) | 开发环境搭建 |
| [docs/development/roadmap.md](docs/development/roadmap.md) | 里程碑与路线图 |
| [docs/development/security.md](docs/development/security.md) | 安全设计 |
| [docs/development/licensing.md](docs/development/licensing.md) | 许可证与版权边界 |

---

## 许可证与合规

InkFlow 以 **Apache-2.0** 发布。

关于与 Legado 的关系，需要说清楚：

- InkFlow **不包含** Legado 的任何源代码，兼容层是依据其**公开的规则格式**独立实现的。
- InkFlow **不内置**小说正文数据库，**不维护**盗版内容仓库，**不默认提供**第三方书源合集。
- InkFlow 的定位是**内容获取与个人资料整理工具**，不是内容分发平台。用户自行导入书源、自行选择目标、内容保存到本地。
- 使用本书源抓取内容时，用户需自行遵守来源网站条款、版权规定及所在司法辖区法律。

详见 [docs/development/licensing.md](docs/development/licensing.md)。

---

## 状态

**Milestone 0 — 架构验证（进行中）**

骨架已落地，MVP 目标见 [docs/development/roadmap.md](docs/development/roadmap.md)。
