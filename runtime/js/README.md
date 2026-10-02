# runtime/js —— Legado JS 沙箱运行时

**当前状态：未实现（Milestone 3 的预留位置）。**

这个目录将来放独立于 Python 主进程的 JavaScript 运行时，
用于执行 Legado 书源里的 `@js:` 规则与 `<js>` 标签。

---

## 为什么必须是独立进程

```text
Python Core
      │  JSON-RPC
      ▼
┌─────────────────────┐
│ inkflow-js-runtime   │
│ Node.js sidecar      │
└─────────────────────┘
```

书源里的 JavaScript 是**第三方代码** —— 从网上下载的、可能是别人写的、
可能被篡改的。它绝不能运行在 Python 主进程里：

- Node 的 `child_process` / `fs` 一旦可用，等于把整台机器交出去
- 一个 `while(true)` 就能让整个服务卡死
- 一个内存泄漏就能把下载任务全部拖垮

隔离到独立进程后，最坏情况是「sidecar 崩了」，主服务重启它即可。

---

## 运行时职责

```text
JS 执行          Promise / async
异步请求          HTTP / Cookie / Header
数据处理          JSON / 字符串 / 正则
DOM 操作          HTML 解析与选择
上下文变量        书源运行时的状态传递
```

对外提供 InkFlow 自己的宿主 API：

```javascript
inkflow.http.get(url, options)
inkflow.http.post(url, body, options)
inkflow.dom.parse(html)
inkflow.dom.select(dom, selector)
inkflow.dom.text(node)
inkflow.log(message)
```

再在其上实现 Legado 的兼容 API：

```text
Legado API  →  Compatibility API  →  InkFlow Host API
```

---

## 资源限制（设计目标）

| 限制项 | 目标值 |
|---|---|
| 执行超时 | 10~30s（可配，`config.toml` 的 `[js].timeout`） |
| 内存上限 | 128MB（`[js].max_memory_mb`） |
| 单次执行的最大请求数 | 50（`[js].max_requests`） |
| 单次响应体积上限 | 8MB（`[js].max_response_size`） |
| 最大重定向 | 限制 |
| 最大递归深度 | 限制 |

必须禁止：

```text
✗ 文件系统访问
✗ child_process / shell
✗ native module 加载
✗ 任意系统 API
```

---

## 当前行为

`config.toml` 里的 `[js]` 段已经预留，但 `enabled` 默认为 `false`，
且当前版本**没有**读取这些配置的代码。

遇到含 JavaScript 的书源时，兼容层会抛出明确错误而不是静默降级：

```json
{
  "error": {
    "code": "SOURCE_EXECUTION_ERROR",
    "message": "正文 规则包含 JavaScript，需要 L2 兼容等级（当前版本未实现）",
    "details": { "required_level": "L2", "rule": "@js:…" }
  }
}
```

这样用户能立刻判断：是书源坏了，还是兼容等级不够。

---

## 相关文档

- 兼容等级定义 → [../../docs/source/compatibility-levels.md](../../docs/source/compatibility-levels.md)
- 路线图 → [../../docs/development/roadmap.md](../../docs/development/roadmap.md)
- 安全设计 → [../../docs/development/security.md](../../docs/development/security.md)
