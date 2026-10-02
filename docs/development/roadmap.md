# 里程碑与路线图

## 总览

```text
M0 架构验证        ✅ 已完成
M1 MVP             🟡 进行中（核心链路已通，外围待补）
M2 Legado 兼容      ✅ 已覆盖 L0 + L1
M3 JS Runtime      ⬜ 未开始
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
| Electron 骨架（窗口 / 托盘 / 后端管理 / IPC 白名单） | ✅ 已实机验证 |
| 测试（157 项） | ✅ 含下载链路与 WebSocket 自动化 |
| 文档（17 份） | ✅ |
| CI（测试流水线） | ✅ Ubuntu + Windows 双平台 |
| CD（打包 + 发版） | ✅ 三平台后端 + CLI + 三平台安装包，push tag 自动发布 |
| 数据目录便携化 | ✅ 默认落在运行目录下的 `.inkflow`（ADR-015） |
| CLI 独立分发 | ✅ 单文件可执行程序，不依赖 Python 环境 |

### M1 待补

| 事项 | 说明 | 优先级 |
|---|---|---|
| 缓存层落地 | `cache` 表已建，`HttpCache` 协议无默认实现 | 中 |
| 日志落盘 | 配置项已定义（轮转 / JSON Lines），实现待补 | 中 |
| 代码签名 | Windows SmartScreen 与 macOS Gatekeeper 会告警 | 中 |
| macOS / Linux 打包产物实机验证 | 流水线会产出，但未在真机跑过 | 中 |
| 桌面端只读安装位置的回退分支 | `~/.inkflow` 兜底路径未实机验证 | 低 |
| 封面下载 | `cover_url` 已抓取，未下载图片并写入 EPUB | 低 |
| 资源下载器 | 正文内嵌图片（`ContentResult.images` 已收集，未下载） | 低 |

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

## M3 JS Runtime ⬜

**目标**：支持 `@js:` 规则与 `<js>` 标签，让需要签名 / 加密的书源可用。

设计约束（现在就守住）：

```text
Python Core
      │  JSON-RPC
      ▼
┌─────────────────────┐
│ inkflow-js-runtime   │
│ Node.js sidecar      │
└─────────────────────┘
```

- **JS 不得运行在 Python 主进程里**，走独立 sidecar
- 限制：超时 10~30s、内存上限、请求数上限、响应体积上限、最大重定向
- 禁止：文件系统、`child_process`、shell、native module
- 提供 Legado 兼容的宿主 API（`java.*` 映射、`fetch`、`cookie`、DOM 操作）

`config.toml` 里的 `[js]` 段已预留配置项。

---

## M4 Browser Runtime ⬜

**目标**：支持需要渲染 / 登录 / Cookie 的站点。

- 独立 `BrowserService`，不在 Downloader 里内联
- 引擎：Playwright 或 Electron
- 接口：`open` / `navigate` / `evaluate` / `html` / `cookies` / `close`
- **只在书源明确声明需要时启用**，不作为默认路径

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

### 尚未验证

- Electron 打包产物在 macOS / Linux 上未实机验证（Windows 已验）
- 桌面端只读安装位置（回退到 `~/.inkflow`）的分支未实机验证
- 未对真实网站书源做兼容性验证
- 缓存层与日志落盘尚未实现，因此无测试

---

## 相关文档

- 架构与决策 → [../architecture/overview.md](../architecture/overview.md)
- 测试体系 → [testing.md](testing.md)
