# REST API

Base URL：`http://127.0.0.1:<port>`（端口由后端在启动时分配，见 [ADR-013](../architecture/decisions.md)）

交互式文档：`/docs`（Swagger UI）、`/redoc`、`/openapi.json`

---

## 鉴权

除 `/health` 与文档外，所有路由都要求：

```http
Authorization: Bearer <session_token>
```

token 由后端每次启动时生成，通过两种方式获得：

- 后端 stdout 的握手行：`INKFLOW_READY port=53421 token=xxxxx`
- `~/.inkflow/server.json`（服务运行时存在，退出时删除）

未携带或 token 错误时返回 `401` + `UNAUTHORIZED`。

---

## 端点总览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（免鉴权） |
| GET | `/api/v1/system/info` | 运行概况 |
| GET | `/api/v1/search` | 聚合搜索 |
| GET | `/api/v1/books` | 书库列表 |
| GET | `/api/v1/books/{book_id}` | 书籍详情 |
| GET | `/api/v1/books/{book_id}/chapters` | 目录 |
| GET | `/api/v1/books/{book_id}/chapters/{chapter_id}` | 章节正文 |
| POST | `/api/v1/books/{book_id}/export` | 导出书籍 |
| GET | `/api/v1/sources` | 书源列表 |
| POST | `/api/v1/sources/import` | 导入书源 |
| GET | `/api/v1/sources/{source_id}` | 书源详情 |
| PATCH | `/api/v1/sources/{source_id}` | 启用 / 停用 |
| DELETE | `/api/v1/sources/{source_id}` | 删除书源 |
| POST | `/api/v1/sources/{source_id}/test` | 书源测试 |
| GET | `/api/v1/sources/{source_id}/rules` | 查看编译后的规则 |
| POST | `/api/v1/tasks` | 创建下载任务 |
| GET | `/api/v1/tasks` | 任务列表 |
| GET | `/api/v1/tasks/{task_id}` | 任务详情 |
| GET | `/api/v1/tasks/{task_id}/items` | 任务章节明细 |
| POST | `/api/v1/tasks/{task_id}/pause` | 暂停 |
| POST | `/api/v1/tasks/{task_id}/resume` | 恢复 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消 |
| GET | `/api/v1/settings` | 读取设置 |
| PATCH | `/api/v1/settings` | 更新设置 |
| WS | `/ws/tasks/{task_id}` | 任务进度推送 |

---

## 系统

### `GET /health`

免鉴权，供 Desktop 启动时做就绪探测。

```json
{ "status": "ok", "version": "0.1.0", "uptime_seconds": 21.14 }
```

### `GET /api/v1/system/info`

```json
{
  "version": "0.1.0",
  "data_dir": "C:\\Users\\you\\.inkflow",
  "uptime_seconds": 21.14,
  "source_count": 3,
  "enabled_source_count": 2,
  "book_count": 12,
  "task_count": 5,
  "active_task_count": 1,
  "export_formats": ["epub", "markdown", "txt"],
  "source_formats": ["legado-json", "native-yaml"],
  "python_version": "3.12.13",
  "platform": "Windows-11-10.0.26300-SP0"
}
```

---

## 搜索

### `GET /api/v1/search`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `q` | string | 必填 | 搜索关键词 |
| `page` | int | 1 | 页码 |
| `limit` | int | 50 | 返回条数上限（1~200） |
| `sources` | string | — | 限定书源 ID，逗号分隔 |

```json
{
  "keyword": "三体",
  "items": [
    {
      "name": "三体",
      "author": "刘慈欣",
      "intro": null,
      "cover_url": null,
      "category": "科幻",
      "status": null,
      "score": 61.3,
      "sources": [
        {
          "source_id": "src_72b0e86b156f08eb",
          "source_name": "Mock 书站",
          "book_id": "bk_a3fb6385d2424dd4",
          "book_url": "http://127.0.0.1:8765/book/1",
          "latest_chapter": "第三章 死神永生",
          "score": 61.3
        }
      ]
    }
  ],
  "source_errors": { "src_broken": "搜索超时（>30s）" },
  "total": 1
}
```

**要点**

- 同一本书在多个书源命中时只返回一条，但 `sources` 保留全部来源。
- 搜索结果会**自动入库**，`sources[].book_id` 可直接用于后续接口。
- `source_errors` 让客户端能解释「为什么结果变少了」。
- 没有可用书源时返回 `502` + `SEARCH_NO_SOURCE`。

---

## 书籍

### `GET /api/v1/books`

| 参数 | 默认 | 说明 |
|---|---|---|
| `limit` | 50 | 1~200 |
| `offset` | 0 | 分页偏移 |

```json
{ "items": [ /* Book[] */ ], "total": 12, "limit": 50, "offset": 0 }
```

### `GET /api/v1/books/{book_id}`

```json
{
  "book": { "id": "bk_...", "name": "三体", "author": "刘慈欣", "source_id": "src_...", "...": "..." },
  "source": { "id": "src_...", "name": "Mock 书站", "compatibility_level": "native", "...": "..." },
  "chapter_count": 6,
  "downloaded_count": 6
}
```

书源被删除后 `source` 为 `null`，书籍本身仍可读。

### `GET /api/v1/books/{book_id}/chapters`

| 参数 | 默认 | 说明 |
|---|---|---|
| `refresh` | false | 是否重新从书源抓取目录 |

```json
{
  "book_id": "bk_...",
  "chapters": [
    { "id": "ch_...", "book_id": "bk_...", "index": 0, "name": "第一章 科学边界",
      "url": "http://...", "is_vip": false, "downloaded": true, "content_hash": "..." }
  ],
  "total": 6
}
```

`refresh=true` 会整体替换目录，但**保留已下载章节的 `downloaded` 与 `content_hash`** ——
重新抓目录不该让已下载的正文「掉线」。

### `GET /api/v1/books/{book_id}/chapters/{chapter_id}`

| 参数 | 默认 | 说明 |
|---|---|---|
| `refresh` | false | 是否强制重新抓取 |

```json
{
  "chapter": { "id": "ch_...", "index": 0, "name": "第一章 科学边界", "downloaded": true, "...": "..." },
  "content": {
    "chapter_id": "ch_...",
    "raw_content": "<div id=\"content\">…</div>",
    "clean_content": "汪淼觉得自己是在做梦。\n\n凌晨一点…",
    "content_hash": "…",
    "fetched_at": "2026-10-02T07:10:33Z"
  }
}
```

优先读本地缓存；未下载或 `refresh=true` 时向书源抓取并入库。

### `POST /api/v1/books/{book_id}/export`

```json
{ "format": "epub", "output_path": null, "start_chapter": 0, "end_chapter": null }
```

```json
{
  "book_id": "bk_...",
  "format": "epub",
  "output_path": "C:\\Users\\you\\.inkflow\\exports\\三体.epub",
  "chapter_count": 6
}
```

只导出**已下载**的章节；所选范围内一章都没有时返回 `EXPORT_FAILED`。
`output_path` 省略时默认写到 `~/.inkflow/exports/<书名>.<扩展名>`。

---

## 书源

### `GET /api/v1/sources`

```json
{ "items": [ /* BookSource[] */ ], "total": 3 }
```

### `POST /api/v1/sources/import`

```json
{ "format": "auto", "content": "name: …", "url": null, "enabled": true }
```

`content` 与 `url` 二选一。`format` 为 `auto` 时按内容特征识别
（有 `bookSourceUrl` → Legado JSON；有 `name`/`url` → 原生 YAML）。

```json
{
  "source": { "id": "src_72b0e86b156f08eb", "name": "Mock 书站", "compatibility_level": "native", "...": "..." },
  "created": true
}
```

**导入是幂等的**：ID 由书源地址派生，同一书源重复导入返回 `created: false` 并更新原记录。

`url` 形式导入同样经过 SSRF 校验，内网地址返回 `403` + `SOURCE_BLOCKED`。

### `PATCH /api/v1/sources/{source_id}`

```json
{ "enabled": false }
```

### `DELETE /api/v1/sources/{source_id}`

| 参数 | 默认 | 说明 |
|---|---|---|
| `purge_books` | false | 是否同时删除该来源下的书籍 |

默认只删书源定义，已入库的书籍保留 —— 用户可能还想继续读已下载的内容。

### `POST /api/v1/sources/{source_id}/test`

```json
{ "kind": "search", "keyword": "三体", "url": null }
```

`kind` 取 `search` / `info` / `toc` / `content`；后三者需要 `url`。

```json
{
  "ok": true,
  "kind": "search",
  "source_id": "src_...",
  "elapsed_ms": 27.7,
  "count": 3,
  "preview": [
    { "name": "三体", "author": "刘慈欣", "book_url": "http://...", "latest_chapter": "第三章 死神永生" }
  ],
  "error": null,
  "debug": {}
}
```

失败时 `ok: false` 且 `error` 带异常类型与消息（不是 500）——
测试接口的职责就是把失败原因告诉用户。

### `GET /api/v1/sources/{source_id}/rules`

返回编译后的规则 AST，用于 Source Debugger。

```json
{
  "source_id": "src_...",
  "source_type": "legado",
  "compatibility_level": "L1",
  "uses_js": false,
  "needs_browser": false,
  "rules": {
    "search.bookList": { "raw": "class.book-item", "mode": "css", "selectors": [".book-item"], "extract": "text", "...": "..." },
    "toc.chapterName": { "raw": "text", "selectors": [], "extract": "text" }
  }
}
```

---

## 任务

### `POST /api/v1/tasks`

```json
{
  "book_id": "bk_...",
  "start_chapter": 0,
  "end_chapter": 5,
  "concurrency": null,
  "output_format": "epub",
  "output_path": null,
  "auto_start": true
}
```

章节区间为**闭区间**；`end_chapter` 省略时下载到最后一章。
返回 `201` + `DownloadTask`。

### `GET /api/v1/tasks`

```json
{ "items": [ /* DownloadTask[] */ ], "total": 5 }
```

### `GET /api/v1/tasks/{task_id}`

```json
{ "task": { "id": "task_...", "status": "COMPLETED", "total": 6, "completed": 6, "failed": 0, "...": "..." }, "book": { "name": "三体", "...": "..." } }
```

### `GET /api/v1/tasks/{task_id}/items`

逐章状态，用于展示失败章节与重试次数。

```json
{
  "task_id": "task_...",
  "items": [
    { "id": "ti_...", "chapter_index": 0, "chapter_name": "第一章 科学边界",
      "status": "SUCCESS", "attempts": 1, "error": null }
  ],
  "total": 6
}
```

### `POST /api/v1/tasks/{task_id}/pause|resume|cancel`

均返回更新后的 `DownloadTask`。

- **pause**：已在途的章节跑完，不再开始新章节。已下载内容全部保留。
- **resume**：跳过已下载章节继续。
- **cancel**：停止任务，已下载内容保留。

对状态不匹配的任务调用会返回 `409` + `TASK_INVALID_STATE`。

---

## 设置

### `GET /api/v1/settings`

返回各配置段的快照（`server` / `download` / `export` / `cache` / `source` / `js` / `browser` / `log`）。

### `PATCH /api/v1/settings`

**只接受白名单字段**，且改动只作用于当前进程，不写回 `config.toml`：

```json
{
  "default_export_format": "epub",
  "download_concurrency": 8,
  "download_timeout": 30,
  "cache_enabled": true,
  "source_allow_private_network": false
}
```

`server.host`、`js.enabled` 这类与安全边界相关的配置**不允许**通过 HTTP 修改 ——
一次误操作就能把本地服务暴露到局域网。请求体里带这些字段会返回 `422`。

---

## 版本管理

API 前缀从第一版就是 `/api/v1`。将来不兼容的改动走 `/api/v2`，
`v1` 保持可用 —— 这是 API-First 最大的价值所在。

---

## 相关文档

- 错误码 → [errors.md](errors.md)
- 进度推送 → [websocket.md](websocket.md)
