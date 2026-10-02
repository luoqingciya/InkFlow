# 架构总览

## 一句话

**业务核心只有一个，入口可以有很多个。**

CLI 与桌面端都不实现搜索、解析、下载 —— 它们是同一套 HTTP API 的两个客户端。

---

## 分层

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
              │Book Core │      │ Task Core │      │Downloader │
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

---

## 包与依赖方向

```text
inkflow-core  ←  inkflow-source  ←  inkflow-legado
      ↑                ↑                  ↑
      │                │                  │
inkflow-export   inkflow-api ─────────────┘
      ↑                ↑
      │                │
      └──────────  inkflow-cli
```

依赖是**单向**的，反向 import 视为架构破坏：

| 包 | 职责 | 允许依赖 |
|---|---|---|
| `inkflow-core` | 领域模型、配置、路径约定、SQLite 表定义、归一化 | 无（第三方库除外） |
| `inkflow-source` | 适配器协议、注册表、HTTP 引擎、限流、解析原语、正文清洗、搜索聚合 | core |
| `inkflow-legado` | Legado 格式解析、规则编译、AST 执行 | core, source |
| `inkflow-export` | TXT / EPUB / Markdown 导出 | core |
| `inkflow-api` | FastAPI 应用、路由、仓储、任务调度 | core, source, legado, export |
| `inkflow-cli` | Typer 命令行（纯 HTTP 客户端） | core, httpx, typer, rich |

**`inkflow-source` 不认识 Legado。** 各书源类型由自己的包通过
`SourceRegistry.register_factory()` 注册进来，这就是「外层隔离」的落地方式。

---

## 关键抽象

### 1. SourceAdapter —— 书源系统的收口点

```python
class SourceAdapter(Protocol):
    source: BookSource

    async def search(self, keyword: str, page: int = 1) -> list[BookResult]: ...
    async def book_info(self, book_url: str) -> BookResult: ...
    async def chapters(self, book_url: str) -> list[ChapterResult]: ...
    async def content(self, chapter_url: str) -> ContentResult: ...
    async def aclose(self) -> None: ...
```

无论书源是原生 YAML、Legado JSON、Legado JS 还是浏览器渲染，
业务层只认识这四个方法。新增一种格式 = 新增一个实现，**不改既有代码**。

### 2. Rule AST —— Legado 规则不直接执行

```text
Legado DSL  →  LegadoRuleCompiler  →  Rule（统一 AST）  →  执行器
```

好处是业务代码里永远不会出现 `if legado_xxx: ...` 这种分支，
而且规则可以在执行前被检查、被展示（Source Debugger）、被单测。

### 3. DownloadTask —— 下载是一等公民

下载被建模为任务而非循环：

```text
DownloadTask
     ↓
TaskScheduler
     ↓
Worker Pool（并发受全局 / 域名 / 书源三级约束）
     ↓
Chapter Downloader → Normalizer → Storage → Exporter
```

状态机在**领域层**（`DownloadTask.transition_to`），非法转换在模型层就被拒绝，
而不是等到调度器出现诡异行为才发现。

### 4. LibraryService —— 唯一的持久化映射点

领域模型与 SQLAlchemy 行之间的转换只发生在这一个文件里。
其他代码只跟 `inkflow_core.models` 打交道，将来换存储不影响业务代码。

---

## 一次搜索的数据流

```text
GET /api/v1/search?q=三体
   │
   ├─ SearchAggregator.search_detailed()
   │     ├─ registry.resolve()        → 取可用适配器（按优先级排序）
   │     ├─ asyncio.gather(...)       → 并行查询各书源，单源失败不影响整体
   │     └─ merge()                   → 按 (归一化书名, 归一化作者) 归并去重
   │
   ├─ _persist()                      → 各来源写入 books 表，回填 book_id
   │
   └─ 返回 { items, source_errors, total }
```

**去重但不合并**：同一本书在三个来源命中时只返回一条结果，
但 `sources` 数组里保留全部三个来源 —— 不同来源的更新速度、章节数、
正文质量都不同，选择权属于用户。

---

## 一次下载的数据流

```text
POST /api/v1/tasks { book_id, start_chapter, end_chapter }
   │
   ├─ DownloadTaskManager.create_task()
   │     ├─ 校验书籍与目录存在
   │     ├─ 按区间筛选章节，建 task + task_items
   │     └─ 启动后台协程 _run()
   │
   ├─ _execute()
   │     ├─ 跳过已下载章节（恢复任务时不重复抓取）
   │     ├─ asyncio.Semaphore(concurrency) 控制并发
   │     └─ 每章：adapter.content() → ChapterContent → 落库 → 广播进度
   │
   ├─ 全部完成后：Exporter 导出 → 更新 output_path
   │
   └─ 进度经 ProgressBroker → WebSocket /ws/tasks/{id}
```

设计取舍：

- **暂停用 `asyncio.Event` 而不是取消协程** —— 取消会丢掉已经拿到的正文。
- **单章失败不中断任务** —— 只累计 `failed` 并记入明细表，最后统一呈现。
- **终态由状态机把关** —— 暂停中的任务不会被误标为 COMPLETED。

---

## 目录约定

所有运行时数据集中在 `~/.inkflow`（可用 `INKFLOW_HOME` 重定向）：

```text
~/.inkflow/
├── config/       运行时配置
├── database/     inkflow.db（WAL 模式）
├── cache/        HTTP 响应与正文缓存
├── downloads/    下载中间产物
├── books/        按书籍归档
├── exports/      导出的 TXT / EPUB
├── logs/
├── sources/      用户导入的书源
└── server.json   后端握手信息（端口 + token），退出时删除
```

---

## 相关文档

- 为什么这么设计 → [decisions.md](decisions.md)
- 书源系统细节 → [../source/overview.md](../source/overview.md)
- 安全边界 → [../development/security.md](../development/security.md)
