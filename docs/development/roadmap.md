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
10. 显示实时进度                     ✅（WebSocket，手动验证）
11. 失败章节自动重试                 🟡（HTTP 层有重试；任务层重试待补）
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
| 导出（TXT / EPUB / Markdown） | ✅ EPUB 手写，结构已校验 |
| REST API + WebSocket | ✅ |
| CLI（全部命令 + `--json`） | ✅ |
| Electron 骨架（窗口 / 托盘 / 后端管理 / IPC 白名单） | ✅ 代码完成，**未实机运行验证** |
| 测试（108 项） | ✅ |
| 文档 | ✅ |

### M1 待补

| 事项 | 说明 | 优先级 |
|---|---|---|
| 下载任务自动化测试 | 目前只有手动 E2E，缺 CI 保障 | 高 |
| 任务层重试 | HTTP 层已重试，但单章失败后不会重新入队 | 高 |
| 缓存层落地 | `cache` 表已建，`HttpCache` 协议无默认实现 | 中 |
| 日志落盘 | 配置项已定义（轮转 / JSON Lines），实现待补 | 中 |
| 桌面端实机验证 | 需 `npm install` 后跑 `npm run dev` | 中 |
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

### 尚未验证

- 桌面端未实机运行（`npm install` + `npm run dev`）
- WebSocket 进度推送只有手动验证，无自动化测试
- 未对真实网站书源做兼容性验证

---

## 相关文档

- 架构与决策 → [../architecture/overview.md](../architecture/overview.md)
- 测试体系 → [testing.md](testing.md)
