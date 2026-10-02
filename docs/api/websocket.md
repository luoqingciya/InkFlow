# 下载进度推送（WebSocket）

## 为什么不用轮询

下载进度是秒级变化的事件流。轮询要么太慢（进度条卡顿），
要么太密（大量无谓请求）。REST 负责「取状态」，WebSocket 负责「推变化」。

---

## 连接

```text
ws://127.0.0.1:<port>/ws/tasks/{task_id}?token=<session_token>
```

**token 走查询参数**，因为浏览器的 WebSocket API 不支持自定义请求头。
后端也接受 `Authorization` 头（非浏览器客户端可用）。

未通过鉴权时服务端以 `4401` 关闭连接；任务不存在时先发一条 `error` 事件再以 `4404` 关闭。

### 不要漏掉开头的事件

任务可能在 WebSocket 连接建立**之前**就跑完了 —— 那时所有进度事件都推给了
空气，客户端只看到一个已经 `COMPLETED` 的快照。

要接住完整事件流，用这个顺序：

```text
POST /api/v1/tasks          {auto_start: false}   → 建任务，停在 PENDING
      ↓
打开 WebSocket              收到 snapshot 初始化进度条
      ↓
POST /api/v1/tasks/{id}/start                     → 现在才开始跑
```

`start` 是幂等的，`auto_start=false` 的任务只能靠它启动
（`resume` 只接受 `PAUSED` 状态）。

---

## 事件类型

连接建立后先收到一条 `snapshot`（当前状态），随后按事件推送。
任务进入终态时服务端主动关闭连接（code `1000`）。

### `snapshot`

连接建立时的当前状态。用「先连后启」的顺序时，这里会是 `PENDING`。

```json
{
  "type": "snapshot",
  "task_id": "task_...",
  "status": "RUNNING",
  "completed": 3,
  "failed": 0,
  "total": 6,
  "percent": 50.0,
  "speed": "1.82 ch/s"
}
```

### `progress`

每完成一个章节推送一次。

```json
{
  "type": "progress",
  "completed": 4,
  "failed": 0,
  "total": 6,
  "current": "第五章 宇宙闪烁",
  "index": 4,
  "percent": 66.7,
  "speed": "2.05 ch/s"
}
```

单章失败时同一事件带 `error` 字段（任务继续，不中断）：

```json
{
  "type": "progress",
  "completed": 4,
  "failed": 1,
  "total": 6,
  "current": "第五章 宇宙闪烁",
  "index": 4,
  "percent": 66.7,
  "speed": "1.71 ch/s",
  "error": "SourceError: 请求超时或连接失败：https://…"
}
```

跳过已下载章节时也会发一条 `progress`，带 `message` 字段：

```json
{ "type": "progress", "completed": 3, "total": 6, "message": "跳过 3 个已下载章节" }
```

失败章节按轮次重试前也会发一条 `progress`，同样带 `message`（HTTP 层与
任务层都有重试，见 [rest-api.md 的「失败重试」](rest-api.md#失败重试)）：

```json
{
  "type": "progress",
  "completed": 4,
  "failed": 2,
  "total": 6,
  "message": "2 个章节失败，1.0s 后重试（第 1/3 轮）"
}
```

> `failed` 是**当前**的失败计数。某章在下一轮重试成功后会从计数里扣掉
> —— 所以这个数字会**减少**，而 `completed` 只增不减。
> 客户端不要把 `failed` 当作单调递增的量来做进度推算。

### `status`

任务状态变化（暂停 / 恢复 / 取消）。

```json
{ "type": "status", "status": "PAUSED" }
```

### `completed`

任务完成（含导出结果）。

```json
{
  "type": "completed",
  "completed": 6,
  "failed": 0,
  "total": 6,
  "output_path": "C:\\Users\\you\\.inkflow\\exports\\三体.epub",
  "status": "COMPLETED"
}
```

### `error`

任务级失败（不是单章失败）。

```json
{ "type": "error", "message": "SourceError: 目录为空", "status": "FAILED" }
```

### `heartbeat`

空闲 20 秒发一次，防止中间设备掐断空闲连接。客户端应忽略。

```json
{ "type": "heartbeat", "task_id": "task_..." }
```

---

## 终止条件

服务端在以下情况主动关闭连接：

| 情况 | 关闭码 |
|---|---|
| 任务进入终态（COMPLETED / FAILED / CANCELLED） | 1000 |
| 客户端主动断开 | —（服务端清理订阅） |
| 任务不存在 | 4404 |
| 鉴权失败 | 4401 |

客户端断开是正常情况，服务端不记错误日志。

---

## 客户端示例

### JavaScript（桌面端）

```typescript
const connection = await window.inkflow.getConnection()
const wsBase = connection.baseUrl.replace(/^http/, 'ws')
const socket = new WebSocket(`${wsBase}/ws/tasks/${taskId}?token=${connection.token}`)

socket.onmessage = (event) => {
  const data = JSON.parse(event.data)
  if (data.type === 'progress') {
    updateProgressBar(data.percent, data.current, data.speed)
  }
  if (data.type === 'completed') {
    showResult(data.output_path)
    socket.close()
  }
}
```

参考实现：`desktop/src/renderer/src/api/client.ts` 的 `watchTask()`。

### Python（CLI）

```python
async for event in client.watch_task(task_id):
    print_progress_event(event)
```

参考实现：`packages/inkflow-cli/src/inkflow_cli/client.py` 的 `watch_task()`。

---

## 可靠性

- **队列满时丢最旧的事件，不阻塞下载器。** 进度是快照型数据，
  落后的事件没有价值，而阻塞下载器会拖慢真正的任务。
- **轮询兜底是必要的。** 桌面端的任务页同时每 5 秒轮询一次 REST ——
  中间设备掐断连接后界面不该卡死。
- **不做断线重连。** 客户端重连即可拿到新的 `snapshot`，
  不需要服务端维护事件历史。
