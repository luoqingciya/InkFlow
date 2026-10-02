# 错误规范

## 统一结构

所有错误响应体固定为：

```json
{
  "error": {
    "code": "SOURCE_TIMEOUT",
    "message": "请求超时或连接失败：https://example.com/search",
    "details": { "url": "https://example.com/search", "attempts": 4 },
    "trace_id": "a1b2c3d4e5f6"
  }
}
```

**客户端按 `code` 分支，不解析 `message`。** `message` 是给人看的，
可能随版本调整措辞；`code` 一旦发布不再改变含义，只允许新增。

`trace_id` 与后端日志一一对应 —— 报问题时带上它就能直接定位。

---

## 错误码表

### 通用

| 码 | HTTP | 含义 |
|---|---|---|
| `INTERNAL_ERROR` | 500 | 未预期的服务端错误（完整堆栈在日志里，响应只给 trace_id） |
| `VALIDATION_ERROR` | 422 | 请求参数校验失败，`details.errors` 里有字段级信息 |
| `UNAUTHORIZED` | 401 | 缺少或无效的 session token |
| `NOT_FOUND` | 404 | 通用资源不存在 |

### 书籍

| 码 | HTTP | 含义 |
|---|---|---|
| `BOOK_NOT_FOUND` | 404 | 书籍不存在 |
| `BOOK_NO_CHAPTERS` | 502 | 该书还没有目录，需先抓取目录 |

### 书源

| 码 | HTTP | 含义 |
|---|---|---|
| `SOURCE_NOT_FOUND` | 404 | 书源不存在 |
| `SOURCE_INVALID` | 502 | 书源结构校验失败 / 格式无法识别 / 无可用解析器 |
| `SOURCE_DISABLED` | 502 | 书源已停用 |
| `SOURCE_TIMEOUT` | 502 | 请求超时或连接失败（重试已耗尽） |
| `SOURCE_EXECUTION_ERROR` | 502 | 规则执行失败（含「需要更高兼容等级」） |
| `SOURCE_BLOCKED` | 403 | URL 被安全策略拒绝（协议不允许 / 内网地址） |

### 搜索

| 码 | HTTP | 含义 |
|---|---|---|
| `SEARCH_FAILED` | 502 | 搜索请求失败 |
| `SEARCH_NO_SOURCE` | 502 | 没有可用书源 |

### 解析

| 码 | HTTP | 含义 |
|---|---|---|
| `CHAPTER_PARSE_FAILED` | 502 | 目录解析失败 / 书源未返回任何章节 |
| `CONTENT_PARSE_FAILED` | 502 | 正文规则未匹配到内容 |
| `RULE_COMPILE_FAILED` | 502 | 规则编译失败 |

### 下载与导出

| 码 | HTTP | 含义 |
|---|---|---|
| `DOWNLOAD_FAILED` | 502 | 下载失败 |
| `EXPORT_FAILED` | 502 | 导出失败（格式不支持 / 没有可导出的内容） |

### 任务

| 码 | HTTP | 含义 |
|---|---|---|
| `TASK_NOT_FOUND` | 404 | 任务不存在 |
| `TASK_CANCELLED` | 409 | 任务已被取消 |
| `TASK_INVALID_STATE` | 409 | 状态转换不合法（如对已完成任务调 pause） |

---

## 具体示例

### 参数校验失败

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数校验失败",
    "details": {
      "errors": [
        { "type": "missing", "loc": ["query", "q"], "msg": "Field required" }
      ]
    },
    "trace_id": "…"
  }
}
```

### 没有可用书源

```json
{
  "error": {
    "code": "SEARCH_NO_SOURCE",
    "message": "没有可用的书源，请先导入并启用书源",
    "details": {},
    "trace_id": "…"
  }
}
```

### 兼容等级不足

```json
{
  "error": {
    "code": "SOURCE_EXECUTION_ERROR",
    "message": "正文 规则包含 JavaScript，需要 L2 兼容等级（当前版本未实现）",
    "details": {
      "source_id": "src_xxx",
      "rule": "@js:result.replace(/广告/g,'')",
      "required_level": "L2"
    },
    "trace_id": "…"
  }
}
```

### SSRF 拦截

```json
{
  "error": {
    "code": "SOURCE_BLOCKED",
    "message": "书源请求被拒绝：127.0.0.1 属于内网 / 回环地址",
    "details": { "url": "http://127.0.0.1:1/source.json", "host": "127.0.0.1" },
    "trace_id": "…"
  }
}
```

### 任务状态不合法

```json
{
  "error": {
    "code": "TASK_INVALID_STATE",
    "message": "只有运行中的任务可以暂停（当前 COMPLETED）",
    "details": { "task_id": "task_xxx", "status": "COMPLETED" },
    "trace_id": "…"
  }
}
```

---

## 客户端处理建议

```python
try:
    result = await client.search("三体")
except ApiError as err:
    if err.code == "SEARCH_NO_SOURCE":
        # 引导用户去导入书源
        ...
    elif err.code in {"SOURCE_TIMEOUT", "SOURCE_EXECUTION_ERROR"}:
        # 单源失败通常已在 source_errors 里体现，这里是全源失败
        ...
    else:
        # 带上 trace_id 报 bug
        log.error("未处理: %s trace=%s", err.code, err.trace_id)
```

CLI 的行为可以作为参考实现：见 `packages/inkflow-cli/src/inkflow_cli/main.py`
的 `_run()` —— 失败时以退出码 1 结束，`--json` 模式下输出同结构的 JSON。

---

## 设计约束

- **不静默降级。** 拿不到结果就报错，不要返回空列表让调用方以为「本来就没有」。
- **不泄漏堆栈。** 未预期异常只返回 `INTERNAL_ERROR` + `trace_id`，堆栈进日志。
- **错误要可操作。** `details` 里给出定位所需的信息（URL、规则原文、书源 ID），
  而不是只说「失败了」。
