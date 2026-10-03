# 里程碑与路线图

## 总览

```text
M0 架构验证        ✅ 已完成
M1 MVP             ✅ 已完成（核心链路 + 外围补齐）
M2 Legado 兼容      ✅ 已覆盖 L0 + L1
M3 JS Runtime      ✅ 已覆盖 L2（独立 sidecar）
M4 Browser Runtime ⬜ 未开始
M5 高级功能        ⬜ 未开始
```

---

## M0 架构验证 ✅

**目标**：跑通 `CLI → API → DB` 与 `Desktop → API → DB`，确认分层成立。

已完成：

- uv workspace，6 个包，依赖方向由构建系统强制
- 领域模型、SQLite 表结构、配置系统、路径约定
- FastAPI 应用工厂、统一错误处理、session token 鉴权
- Typer CLI，自动发现服务
- Electron + Vue 3 骨架，主进程负责后端进程管理与端口协商

---

## M1 MVP 🟡

**目标**（规划书 §77 的验收清单）：

```text
1.  启动 InkFlow                    ✅
2.  导入一个 Legado JSON Source      ✅
3.  Source Test 成功                 ✅
4.  搜索「三体」                     ✅
5.  获取书籍                         ✅
6.  获取目录                         ✅
7.  选择章节区间                     ✅
8.  创建下载任务                     ✅
9.  并发下载                         ✅
10. 显示实时进度                     ✅（WebSocket，已有自动化测试）
11. 失败章节自动重试                 ✅（HTTP 层 + 任务层双重重试）
12. 下载完成                         ✅
13. 生成 TXT                         ✅
14. 生成 EPUB                        ✅
15. Desktop 能打开输出目录            ✅（IPC 已实现）
16. CLI 也能完成同样操作             ✅
```

### 已完成

| 模块 | 状态 |
|---|---|
| 书源体系（原生 YAML + Legado JSON） | ✅ L0 + L1 |
| 搜索聚合与去重 | ✅ 多源归并、评分排序 |
| 目录抓取（含分页） | ✅ |
| 正文抓取与清洗（含分页） | ✅ 保留 raw + clean |
| 下载任务（并发 / 暂停 / 恢复 / 取消 / 跳过已下载） | ✅ |
| 任务层失败重试 | ✅ 按轮次重试，退避可配（ADR-016） |
| 导出（TXT / EPUB / Markdown） | ✅ EPUB 手写，结构已校验 |
| REST API + WebSocket | ✅ |
| CLI（全部命令 + `--json`） | ✅ |
| HTTP 缓存 | ✅ SQLite 落盘、LRU 淘汰、只缓存 GET（ADR-017） |
| 日志落盘 | ✅ 轮转 + JSON Lines，uvicorn 日志一并入库（ADR-018） |
| 封面下载 | ✅ 写入 EPUB，缺封面时自动补抓详情页（ADR-019） |
| 正文插图下载 | ✅ 存到 `.inkflow/books/<id>/images/`（EPUB 内嵌待定，见下） |
| 数据目录只读回退 | ✅ 实机验证：运行目录不可写时回退 `~/.inkflow` |
| Electron 骨架（窗口 / 托盘 / 后端管理 / IPC 白名单） | ✅ 已实机验证 |
| 测试（218 项） | ✅ 含下载链路、WebSocket、缓存、日志与资源下载 |
| 文档（17 份） | ✅ |
| CI（测试流水线） | ✅ Ubuntu + Windows 双平台 |
| CD（打包 + 发版） | ✅ 三平台后端 + CLI + 三平台安装包，push tag 自动发布 |
| 数据目录便携化 | ✅ 默认落在运行目录下的 `.inkflow`（ADR-015） |
| CLI 独立分发 | ✅ 单文件可执行程序，不依赖 Python 环境 |

### 搁置 / 明确不做

以下项**明确不做**，直到有实际需求或条件具备：

| 事项 | 为什么不做 |
|---|---|
| 代码签名 | 需要购买证书（Windows 代码签名证书 / Apple Developer 账号）。当前是预发布阶段，SmartScreen 与 Gatekeeper 的告警可接受；等准备正式分发时再处理（2026-10-02 决定） |
| macOS / Linux 打包产物实机验证 | 流水线已能产出安装包，但手上没有真机。**这是真实缺口，不是「已验证」** —— 用户报告问题前无法确认它们能跑（2026-10-02 决定） |
| EPUB 内嵌正文插图 | 图片**已经下载到本地**（`.inkflow/books/<id>/images/`），但不嵌入 EPUB。要让插图出现在阅读器里，得让正文**保留图片位置**，而当前 `clean_content` 是纯文本 —— 这是「正文格式」的架构改动，会影响三个导出器与 normalizer 的契约。插图对小说阅读的收益不足以支撑这个改动（2026-10-03 决定） |

### 刻意不做

规划书 §75 明确砍掉的功能，M1 一律不碰：

```text
在线阅读器、账号系统、云同步、AI、社交、评论、推荐、
WebDAV、MCP、插件市场
```

先把 `Search / Source / Book / Chapter / Download / Export / API / CLI / Desktop`
跑稳定。

---

## M2 Legado 兼容 ✅（L0 + L1）

- 书源 JSON 结构解析（未知字段保留、破损 header 容错）
- 规则 DSL → AST 编译（CSS / XPath / JSONPath / 正则 / 替换 / 备选链）
- 适配器执行（搜索 / 详情 / 目录 / 正文，含分页）
- 兼容等级自动判定
- Source Debugger（`GET /sources/{id}/rules`）

详见 [compatibility-levels.md](../source/compatibility-levels.md)。

---

## M3 JS Runtime ✅（L2）

支持 `@js:` 规则，让需要签名 / 加密的书源可用。

```text
Python (Legado 适配器)
      │  JSON-RPC over stdio
      ▼
┌──────────────────────────┐
│ inkflow-js-runtime        │
│ Node.js sidecar（零依赖） │
└──────────────────────────┘
```

已实现：

- 独立 Node sidecar（`packages/inkflow-js-runtime/src/.../sidecar/`），
  **零 npm 依赖** —— 只用 Node 内置模块，不需要 `npm install`
- 同步 stdio 协议：`java.ajax` 是同步语义（书源不会写 `await`），
  sidecar 用 `fs.readSync` 阻塞等响应
- **网络请求回调 Python**：`java.ajax` 走反向 RPC 回 `HttpClient`，
  SSRF 防护 / 限速 / 缓存全部照旧生效
- 宿主 API：
  - 网络：`ajax`（GET）/ `post` / `ajaxAll`（**串行**，见下）
  - 取值：`getString` —— 用规则从当前上下文取值，**走反向 RPC 复用 Python 编译器**
  - 变量：`put` / `get` —— **书源级**变量，跨规则、跨请求共享（**`get` 是取变量，不是 HTTP GET**）
  - 编码 / 摘要：`base64Encode/Decode`、`md5Encode` / `md5Encode16`、
    `hexEncode/Decode`、`digestHex`
  - 其它：`timeFormat`、`toNumChapter`（中文数字转阿拉伯数字）、`log`
- 四层限制：进程内存（`--max-old-space-size`）、沙箱超时、
  Python 兜底超时（超时即丢弃进程）、**单次规则执行的网络请求数**
  （`max_requests`，只数网络请求；`0` = 不限制。见 [ADR-023](../architecture/decisions.md)）
- 未启用时**明确报错并把解法写进 message**，不静默返回空
- 一个 sidecar 服务所有书源（每书源一个进程太浪费）

**安全边界（重要）**：`node:vm` **不是**权限沙箱，它只隔离全局变量与
超时。真正的边界是「独立进程 + 进程里没有敏感数据」。
详见 [ADR-020](../architecture/decisions.md)。

`config.toml` 的 `[js]` 段已生效（默认 `enabled = false`）。

### 尚未覆盖的 L2 细节

- `<js>` 标签写法（当前只支持 `@js:` 前缀）
- DOM 操作（Legado 的 `org.jsoup` 映射）：`java.getElements` / `java.getStringList`
- 加解密：`java.aesBase64DecodeToString` / `java.base64DecodeToByteArray`
- cookie 管理（`java.getCookie` / `setCookie`）
- `java.getWebViewUA` 等与浏览器环境相关的 API

### 已知限制

- `java.ajaxAll` 是**串行**实现 —— 语义与 Legado 一致，但没有并发收益。
  sidecar 是同步阻塞模型，一次只能等一条响应；要并发需 Python 侧支持
  同时挂起多个 host 请求（当前协议是一请求一响应）。真实书源里只用 4 处，
  **先保证正确，暂不优化**。取舍见 [ADR-022](../architecture/decisions.md)。

---

## M4 Browser Runtime ⬜

**目标**：支持需要渲染 / 登录 / Cookie 的站点（L3）。

**需求规模**：1363 条真实书源里 **L3 占 5.0%（68 条）** —— 真实，但不大。

**引擎已定**（[ADR-024](../architecture/decisions.md)）：

- **接口在 core，引擎由外层注册** —— `BrowserProvider` 协议
  （`open` / `navigate` / `evaluate` / `html` / `cookies` / `close`），
  与 `SourceRegistry.register_factory()` 同一套思路
- **默认分发不带浏览器**，首次启用时按需下载 headless 浏览器
- **未安装时明确报错并把解法写进 message**，不静默降级

**为什么不是内嵌**：实测 Playwright 包 105 MB + headless Chromium 271 MB
≈ **376 MB**，而后端现在是 **28 MB 单文件 exe** —— 13 倍量级。
为 5% 的书源让 100% 的用户多下这么多，不划算。

**动工前要先定**：CI 怎么验（下 270 MB 太重）、下载源与镜像、
下载物放哪（数据目录 vs 系统缓存）。

`config.toml` 里的 `[browser]` 段已预留配置项。

---

## M5 高级功能 ⬜

规划书 §64 列出的候选：

```text
自动更新章节、定时任务、批量下载、下载队列、代理、
WebDAV、云同步、书架、阅读器、全文搜索、插件系统、MCP
```

其中**插件系统**（§65）值得优先：把书源、导出器、清洗器、下载器都做成可插拔的，
当前的工厂注册机制已经为它留好了位置。

---

## 开发顺序建议

规划书 §78 的结论：**不要先做 Electron**。

```text
Phase 1  项目骨架         ✅
Phase 2  Core Model       ✅
Phase 3  Source Engine    ✅
Phase 4  Legado JSON      ✅
Phase 5  API              ✅
Phase 6  CLI              ✅
Phase 7  Downloader       ✅
Phase 8  Exporter         ✅
Phase 9  Electron         🟡 代码完成，待实机验证
Phase 10 Legado JS        ⬜
```

---

## 验收记录

### 2026-10-02 · M0 + M1 核心链路

用 mock 书站（`tests/mock_server.py`）跑通完整流程，非模拟、非推测：

```text
$ uv run inkflow info
  书源 0 / 0 启用   书籍 0   任务 0
  导出格式 epub, markdown, txt
  书源格式 legado-json, native-yaml

$ uv run inkflow sources import sources/test/mock-site.yaml
已导入 Mock 书站 (src_72b0e86b156f08eb)  兼容等级 native

$ uv run inkflow sources test src_72b0e86b156f08eb --kind search --keyword 三体
通过  kind=search  耗时 27.7ms  结果数 3
│ 三体              │ 刘慈欣 │ http://127.0.0.1:8765/book/1 │ 第三章 死神永生 │

$ uv run inkflow book chapters <book_id> --refresh
目录（共 6 章）   ← 第一页 4 章 + 第二页 2 章，分页生效

$ uv run inkflow download <book_id> --start 0 --end 5 --format epub
任务 task_a3d874faa551438b 已创建

$ uv run inkflow task show <task_id>
状态 COMPLETED   进度 6/6 (100.0%)  失败 0
输出 .e2e-home/exports/三体.epub
```

导出的 EPUB 结构校验：

```text
条目数        : 12
首条目        : mimetype
首条目压缩方式: 0 (STORED)        ← 符合 EPUB 规范要求
mimetype 内容 : application/epub+zip

结构: mimetype / META-INF/container.xml / OEBPS/{style.css, content.opf,
      nav.xhtml, toc.ncx, text/chapter-0001..0006.xhtml}

OPF 含书名    : True
OPF 含作者    : True
第1章标题     : <h1>第一章 科学边界</h1>
第1章段落数   : 7
正文含广告    : False              ← 清洗生效
```

测试与静态检查：

```text
$ uv run pytest -q
108 passed

$ uv run ruff check .
All checks passed!
```

### 2026-10-02 · CI/CD 上线

仓库：https://github.com/luoqingciya/InkFlow

```text
$ uv run pyinstaller packaging/inkflow-server.spec --noconfirm
...
59036 INFO: Build complete! The results are available in: D:\Project\InkFlow\dist

dist/inkflow-server.exe   28.2 MB

$ uv run python scripts/smoke_test_backend.py
冒烟测试：D:\Project\InkFlow\dist\inkflow-server.exe
  [后端] INKFLOW_READY port=63648 token=s8Tm1GTniKyi4ArJysfrkCvMrBQcNFUq57piagXBBUQ
后端已就绪，端口 63648
  [健康检查] {"status":"ok","version":"0.1.0.dev0","uptime_seconds":0.11}
冒烟测试通过
```

打包产物**真的能启动**，握手协议正常，版本号也一致。

### 2026-10-02 · 便携化与 CLI 打包（v0.1.0-dev1）

把两个打包产物拷到**独立目录**运行，验证数据目录确实落在运行目录下：

```text
$ ls .e2e-portable/
inkflow-server.exe   inkflow.exe

$ cd .e2e-portable && ./inkflow-server.exe --port 8899

$ ls -la
drwxr-xr-x  .inkflow          ← 数据目录就在运行目录下
-rwxr-xr-x  inkflow-server.exe
-rwxr-xr-x  inkflow.exe

$ ./inkflow.exe -v health
连接 http://127.0.0.1:8899（来源：握手文件
  D:\...\.e2e-portable\.inkflow\server.json），已带 token
| 状态 ok | 版本 0.1.0.dev1 |

$ ./inkflow.exe info
| 数据目录  D:\Project\InkFlow\.e2e-portable\.inkflow |

$ ./inkflow.exe search 三体
| 三体 | 刘慈欣 | Mock 书站 | 第三章 死神永生 |

$ ./inkflow.exe download <book-id> --start 0 --end 5 --format epub
任务 COMPLETED  进度 6/6 (100.0%)  失败 0
输出 D:\Project\InkFlow\.e2e-portable\.inkflow\exports\三体.epub
```

产物大小：CLI 18.9 MB / 后端 28.2 MB。

### 2026-10-02 · 下载链路与 WebSocket 测试补齐

M1 待补清单里两个「高」优先级项落地：

```text
$ uv run pytest -q
157 passed

$ uv run ruff check .
All checks passed!

$ uv run mypy .
Success: no issues found in 87 source files
```

> 本机复现测试时，若全量 `pytest` 报 exit 1 却看不到任何 `F`，
> 是环境的批量删除保护拦下了 pytest 的临时目录清理，**不是测试失败**。
> 稳妥跑法见 [testing.md](testing.md) 的「踩过的坑」。

新增两个集成测试文件，共 49 项：

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `tests/integration/test_download.py` | 33 | 任务创建与区间裁剪、并发下载、正文入库、EPUB 结构合法性、逐章明细、跳过已下载、失败隔离、按轮次重试、暂停/恢复/取消、`/start` 端点 |
| `tests/integration/test_websocket.py` | 16 | snapshot 首帧与字段形状、事件流、终态关闭、4404/4401、Broker 语义、多订阅者 |

过程中的两个发现：

1. **API 缺口**：`auto_start=false` 建出的任务**没有任何端点能启动它**
   —— `resume` 只接受 `PAUSED`。补了 `POST /api/v1/tasks/{id}/start`
   与对应的 CLI 命令 `inkflow task start`。
2. **TestClient 收不到 WebSocket 流式事件**：它每个 HTTP 请求都新起一个
   anyio portal，请求返回后循环即销毁；WS 会话又在自己那个循环里。
   于是「REST 启动任务 → WS 收进度」这种真实用法在 TestClient 下**必然挂死**。
   改为后台线程跑真实 uvicorn + `websockets` 客户端才验证得动，
   细节记进了 [testing.md](testing.md)。

任务层重试的设计取舍见 [ADR-016](../architecture/decisions.md)。

### 2026-10-02 · HTTP 缓存落地

`HttpCache` 协议与 `http_cache` 表早就建好了，`HttpClient` 里的读写逻辑
也齐了 —— 唯独没有默认实现，所以缓存从未真正生效。这次补上。

```text
$ uv run pytest -q
189 passed

$ uv run ruff check .
All checks passed!

$ uv run mypy .
Success: no issues found in 89 source files
```

- **实现**：`inkflow-api/services/cache.py` 的 `SqliteHttpCache`。
  放装配层而非 source —— 缓存要落 SQLite，而书源引擎不依赖 sqlalchemy。
- **只缓存 GET**：POST 有副作用，复用旧响应等于返回错误结果。
- **LRU 淘汰**：依据 `hit_at`，从未命中的按 `created_at` 排。
- **过期惰性删除**：读到就扔，不引入后台清扫任务。
- **可观测**：`/api/v1/system/info` 新增 `cache` 字段（条目数 / 体积 / 过期数）。

新增 `tests/integration/test_cache.py`（32 项）。其中一个测试是
**把 mock 站点关掉之后再取一次** —— 只断言 `from_cache` 不够，
那个标志是自己设的；断掉网络还能拿到内容，才证明真的没走网络。

取舍见 [ADR-017](../architecture/decisions.md)。

### 2026-10-02 · 日志落盘

`log` 配置段（级别 / JSON Lines / 轮转）与 `logs_dir` 早就定义好了，
但**没有任何代码安装 handler** —— 日志从来没落过盘。那两处
`getLogger("inkflow.api")` 实际走的是 Python 的 last-resort handler，
只在 stderr 打一条无格式消息，进程一退就没了。

```text
$ uv run pytest -q
208 passed

$ uv run ruff check .
All checks passed!

$ uv run mypy .
Success: no issues found in 91 source files
```

- **实现**：`inkflow_core/log.py` 的 `setup_logging()` —— 挂 root handler，
  文件（轮转）+ 控制台双输出。
- **不用 `basicConfig`**：它只在 root 尚无 handler 时生效，会被 uvicorn 抢先，
  然后**静默失效**。
- **uvicorn 传 `log_config=None`**：它的 logger 是 `propagate=False`，
  不这样处理日志会截在 uvicorn 自己那里，永远到不了文件。
- **写不进去不抛错**：目录只读时降级为仅控制台输出，服务照常启动。
- **端到端验证**：真起一次服务，确认 `logs/inkflow.log` 里出现了
  uvicorn 的启动日志，且用的是我们的格式 —— 不只是「单测绿了」。

新增 `tests/unit/test_log.py`（19 项）。取舍见 [ADR-018](../architecture/decisions.md)。

### 顺带修掉的导出时序缺陷

跑全量时 `test_custom_output_path_is_respected` 偶发失败，查下来是**真缺陷**：
`_execute` 先把任务置为 `COMPLETED` 并落库，**之后**才导出文件。
于是轮询 REST 的客户端会看到 `COMPLETED`，拿到 `output_path` 却读不到文件。

更糟的是导出失败时：任务已是终态，兜底逻辑因「已是终态」而不改状态，
却仍然发出 `FAILED` 事件 —— 状态与事实不符。

改为**先导出、再置终态**。导出失败会向上抛，由兜底置为 FAILED ——
「拿不到产物就不该算完成」。

### 2026-10-02 · 封面 / 插图下载 + 版本 dev2

把 M1 剩下的低优先级项做掉，两项中优先级**明确搁置**。

```text
$ uv run pytest -q
218 passed

$ uv run ruff check .          → All checks passed!
$ uv run mypy .                → Success: no issues found in 91 source files
$ uv run python scripts/check_version.py → 版本号一致（0.1.0.dev2）
```

**封面下载**：`ExportRequest` 与 EPUB 导出器**早就支持封面**，
缺的只是「下载并填入」。过程中发现一个更根本的问题 ——
**封面只存在于详情页规则里，搜索结果里没有**，所以不补抓详情页的话，
这个功能永远不会生效。已在导出前补上（仅当缺封面时）。

**插图下载**：`ContentResult.images` 之前被直接丢弃。现在从 `raw_content`
提取地址（清洗后的正文是纯文本，不含 `<img>`），下载到
`.inkflow/books/<id>/images/`，用相对地址去重。

**只读回退实机验证**：把运行目录下的 `.inkflow` 做成文件（挡住 `mkdir`），
确认正确回退到 `~/.inkflow`：

```text
候选路径：
    C:\Users\...\Temp\rotest\.inkflow     ← 被文件阻挡，不可写
    C:\Users\Luoqingci\.inkflow           ← 回退到这里
最终解析结果：C:\Users\Luoqingci\.inkflow
```

**搁置**：代码签名（要买证书）、macOS / Linux 实机验证（没有真机）。
后者是**真实缺口**，已在 roadmap 里标明「不是已验证」。

新增 `tests/integration/test_assets.py`（10 项），mock 站点补了图片端点。
取舍见 [ADR-019](../architecture/decisions.md)。

### 2026-10-03 · M3 JS Runtime

```text
$ uv run pytest -q
254 passed          （218 → 254）

$ uv run ruff check .          → All checks passed!
$ uv run mypy .                → Success: no issues found in 96 source files
```

新增 `packages/inkflow-js-runtime`（Python 客户端 + Node sidecar）。

**三个技术难点与解法**：

1. **`java.ajax` 是同步语义。** 书源是给 Rhino 写的，不会写 `await`。
   解法：sidecar 内部用 `fs.readSync` 阻塞等响应 —— 单线程、无 worker。
   因为 Python 是独立进程，阻塞期间它能正常处理请求，不会死锁。
2. **网络不能由 sidecar 发。** 否则 SSRF 防护、限速、缓存全部绕过了。
   解法：`java.ajax` 走反向 JSON-RPC 回到 Python 的 `HttpClient`。
3. **编译器没保存剥离前缀后的 JS 代码。** `Rule.raw` 带着 `@js:` 前缀，
   直接喂给 JS 引擎会语法错误。解法：`Rule` 加 `code` 字段存剥离后的代码。

**顺带修掉一个静默失败**：原先 `RuleMode.JS` 规则在 `_field` 里直接
返回 `None` —— 字段解析出来是空的，用户以为「这个网站没这个字段」。
现在明确报错，并把「怎么启用」写进 message。

**安全边界**：`node:vm` 不是权限沙箱（见 [ADR-020](../architecture/decisions.md)），
真正的边界是「独立进程 + 进程里没有敏感数据」。

新增测试：`tests/integration/test_js_runtime.py`（27 项，含沙箱隔离与超时）、
`tests/source/test_legado_js.py`（9 项，含 `@js:` 书源端到端）。

### 2026-10-03 · 用真实书源校准兼容层

洛清辞提供了一份 1363 条的真实 Legado 书源集合。拿它做体检，发现
**37% 的规则根本跑不起来** —— 而此前所有测试都是围绕自己写的 mock 书源，
证明不了对真实书源的兼容性。

```text
$ uv run pytest -q
268 passed

$ uv run ruff check .          → All checks passed!
$ uv run mypy .                → Success: no issues found in 96 source files
```

**体检结果（修复前 → 修复后）**：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 结构解析（L0） | 100% | 100% |
| 规则编译 | 0 失败 | 0 失败 |
| **选择器求值** | **37.0% 失败** | **5.50% 失败** |

**补的四种真实写法**（详见 [ADR-021](../architecture/decisions.md)）：

- `$.xxx` —— 隐式 JSONPath（不写 `@json:`），1400+ 条
- `!N` / `!N:M` / `.N` / `.-1` —— 下标与切片，443+ 条
- `{{...}}` —— 模板（不是选择器）
- `[attr=og:x:y]` —— 属性值没加引号（书源不规范，但 Legado 容忍）

**两次自己挖的坑**：体检脚本先是用 `html_parser.select` 绕过下标解析、
后来只用 `compile()` 漏掉选择器语法 —— **两次都是脚本自身的问题**，
不是被测代码的问题。教训：体检工具必须走和线上完全一样的路径。

**剩余 5.50%** 未覆盖，多是书源本身写得不规范（`?` 在属性值里、
`!` 在开头、模板嵌在中间）。边际收益递减，**暂时不再逐条追**。

### 2026-10-03 · 补齐宿主 API（M3 收尾）

上一节的真实书源体检顺带统计了宿主 API 的调用频次，暴露了 M3 的缺口：
**最常用的 `java.getString`（75 次）根本没实现**，`java.put`（27 次）也没有。
—— 又是「mock 书源证明不了真实覆盖度」的一个例证。

```text
$ uv run pytest -q
275 passed          （254 → 275）

$ uv run ruff check .          → All checks passed!
$ uv run mypy .                → Success: no issues found in 96 source files
```

补齐 / 修正的宿主 API：

| API | 语义 | 实现要点 |
|---|---|---|
| `java.getString(rule)` | 用规则从**当前上下文**取值 | **反向 RPC 回 Python 求值**，复用编译器（不在 JS 侧重造一套） |
| `java.put` / `java.get(key)` | **书源级**变量 | 存 adapter 实例 → 按书源天然隔离，跨规则 / 跨请求共享 |
| `java.ajaxAll(urls)` | 批量请求 | 返回 `[{body: () => text}]`；**串行**（见「已知限制」） |
| `java.toNumChapter(text)` | 中文数字转阿拉伯数字 | 「一千零二十四」→ 1024 |

**踩到的两个坑（都已修）**：

1. **`_variables` 字段名撞上同名方法** —— adapter 里本就有个
   `_variables(**extra)` **方法**（模板变量），新加的实例字段把它覆盖了 →
   `TypeError: 'dict' object is not callable`，**连原有测试都挂**。
   改名 `_js_variables`。
2. **`java.get` 语义冲突** —— 我原先写的 `get(url, headers)` 是 HTTP GET，
   但 **Legado 里 `java.get` 是取变量**（HTTP GET 用 `java.ajax`）。
   同名导致 `java.get('bid')` 走进了网络分支，报「不支持的协议 ''」。
   错误的 `get(url, headers)` 已删除。

取舍见 [ADR-022](../architecture/decisions.md)。`tests/source/test_legado_js.py` 9 → 18 项。

### 尚未验证

- Electron 打包产物在 macOS / Linux 上未实机验证（Windows 已验）—— **已搁置**
- 未对真实网站书源做兼容性验证
- 缓存未在真实站点上跑过长期运行（容量淘汰只在测试里验证过）
- 日志未在「长时间运行 + 轮转多次」的真实场景下验证过
- 正文插图**只下载到本地，未嵌入 EPUB**（需先定「正文是否保留图片位置」）

---

## 相关文档

- 架构与决策 → [../architecture/overview.md](../architecture/overview.md)
- 测试体系 → [testing.md](testing.md)
