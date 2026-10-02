# 安全设计

## 威胁模型

InkFlow 有三类不可信输入，安全设计围绕它们展开：

| 威胁源 | 风险 | 对应措施 |
|---|---|---|
| **第三方书源** | 恶意规则让程序去访问内网、云 metadata、本机管理接口 | SSRF 防护、协议白名单、资源限额 |
| **本机其他进程 / 网页** | 浏览器里的恶意页面对着 `127.0.0.1:<port>` 发请求 | session token 鉴权、默认只监听回环 |
| **被注入的渲染进程** | 页面脚本拿到 Node 权限后执行任意命令 | contextIsolation、IPC 白名单、CSP |

核心原则：**假设书源是不可信输入。** 它不是「用户自己写的配置」，
而是「从网上下载的、可能是别人写的、可能被篡改的规则」。

---

## 出站请求防护（SSRF）

书源本质上是「让 InkFlow 去请求某个 URL」。没有防护的话，
一个恶意书源就能让程序去访问 `169.254.169.254`（云 metadata）、
`127.0.0.1:6379`（本机 Redis）或局域网设备。

### 两道闸门

```text
1. 协议白名单    只允许 http:// 与 https://
                 拒绝 file:// / data:// / javascript: 等

2. 地址黑名单    拒绝回环、私有、链路本地、保留、组播地址
```

### 域名解析检查

只做字面量检查不够 —— `evil.com` 可以解析到 `127.0.0.1` 绕过。

因此**域名会被解析后校验**，解析结果带缓存（避免每个请求都走一次 DNS），
DNS 查询在线程池里执行以免阻塞事件循环。

覆盖范围：

```text
IPv4 / IPv6 私有段、回环段、链路本地段、保留段、组播段
localhost、*.local、*.internal、*.localhost、*.home.arpa
metadata、metadata.google.internal（云厂商常用别名）
```

### 开关

默认**关闭**内网访问。确实需要时（例如书源指向本地服务、或跑测试）：

```bash
# 环境变量
INKFLOW_SOURCE__ALLOW_PRIVATE_NETWORK=true

# 或 config.toml
[source]
allow_private_network = true
```

这个开关**不允许**通过 HTTP API 修改 —— 它属于安全边界配置。

### 远程导入同样受检

`POST /api/v1/sources/import` 带 `url` 时，同样经过完整校验 ——
否则书源可以把 InkFlow 当成内网探测代理。

---

## 本地 API 防护

### 只监听回环

默认 `host = "127.0.0.1"`。改成 `0.0.0.0` 会把本地下载器暴露到局域网，
配置加载时会发出警告（但不阻断 —— 容器化部署可能确实需要）。

### session token

回环地址不等于安全：本机上**任何**进程都能访问，包括浏览器里的网页。

因此每次启动生成一次性 token：

```text
INKFLOW_READY port=53421 token=<32 字节 URL-safe 随机串>
```

- 通过 ASGI 中间件统一校验，**不是**逐路由加依赖 ——
  漏加一个路由就是一个口子
- 比较用 `hmac.compare_digest`（防时序侧信道）
- 免鉴权路径只有 `/health` 与文档 —— 它们不含用户数据
- token 也写入 `~/.inkflow/server.json`（权限收紧到仅当前用户可读），
  供 CLI 自动发现；服务退出时删除

WebSocket 因浏览器 API 限制只能用查询参数传 token。

---

## 桌面端防护

### Renderer 不接触 Node

```typescript
webPreferences: {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: false,
  webSecurity: true
}
```

主进程与 Renderer 之间只有 preload 暴露的**具名接口**：

```typescript
window.inkflow.getConnection()      // 连接信息
window.inkflow.openPath(path)       // 用系统程序打开
window.inkflow.revealPath(path)     // 文件管理器中定位
window.inkflow.selectFile(options)  // 文件对话框
window.inkflow.readTextFile(path)   // 读取文本文件（限 8MB）
```

绝不暴露 `require`、`ipcRenderer` 本体或任意 channel 的发送能力。

### CSP

渲染页面自带 CSP，限制可连接的地址：

```html
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self'; script-src 'self';
               connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*" />
```

即使页面被注入脚本，也发不出站外请求。

### 外部链接

`setWindowOpenHandler` 把外部链接交给系统浏览器，不在应用内开新窗口。

### 文件读取限额

`readTextFile` 限制 8MB —— 书源文件不该更大，避免误选大文件把内存打满。

---

## 资源限制

书源可以构造出耗尽资源的规则（无限翻页、超大响应、死循环正则）。

| 限制 | 位置 | 默认值 |
|---|---|---|
| 目录分页上限 | `TocSpec.max_pages` | 20（适配器内另有 50 的硬上限） |
| 正文分页上限 | `ContentSpec.max_pages` | 20 |
| 请求超时 | `RequestConfig.timeout` | 20s |
| 重试次数 | `RequestConfig.retry` | 3 |
| 并发上限 | 全局 / 域名 / 书源三级 | 16 / 6 / 3 |
| 请求速率 | 令牌桶 | 2 req/s |
| 连接池 | httpx limits | 64 连接 / 16 keep-alive |

书源配置只能**收紧**这些值，不能放宽全局设置 ——
否则一个写得激进的书源就能把整个进程拖垮。

### 分页死循环

分页循环里同时检查「页数上限」与「下一页是否指回已访问过的 URL」。
规则写错时必须能停下来。

---

## 尚未实现（诚实清单）

| 能力 | 状态 | 风险 |
|---|---|---|
| JS 沙箱 | 未实现（M3） | 当前遇到 `@js:` 规则直接报错，不执行 —— 所以**没有**执行风险，但也用不了这类书源 |
| 浏览器隔离 | 未实现（M4） | 同上 |
| Cookie / 凭据加密存储 | 未实现 | 若将来支持登录，凭据需加密落盘 |
| 请求头注入防护 | 部分 | 书源可自定义请求头，可能被用于构造特殊请求 |
| 出站流量审计 | 未实现 | 无法回答「这个书源访问过哪些域名」 |

**当前的安全姿态是：不执行第三方代码。** 代价是 L2/L3 书源不可用，
但换来的是「书源能造成的最大伤害 = 发起受限的 HTTP 请求」。

---

## 发布前检查清单

- [ ] 逐项审查第三方依赖的许可证与已知漏洞（以 `uv.lock` 为准）
- [ ] 确认 Electron 版本在支持周期内（Electron 的安全更新只覆盖最近几个大版本）
- [ ] 确认打包产物不含 `--no-token` 启动路径
- [ ] 确认 `server.json` 在异常退出后不会残留可用的 token
- [ ] 确认日志不打印 token 与完整 URL 查询串

---

## 相关文档

- 书源兼容等级 → [../source/compatibility-levels.md](../source/compatibility-levels.md)
- 许可证与内容边界 → [licensing.md](licensing.md)
- 架构决策（鉴权、握手、Renderer 隔离） → [../architecture/decisions.md](../architecture/decisions.md)
