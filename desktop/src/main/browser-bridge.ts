/**
 * 浏览器桥：让后端借用桌面端的 Chromium（ADR-024）。
 *
 * 后端（Python 进程）要渲染页面，而 Chromium 在主进程里 —— 所以在这里开一个
 * **只监听回环**的小 HTTP 服务，后端通过它请求渲染。
 *
 * 方向与平时相反（平时是桌面端调后端），所以地址由桌面端在 spawn 后端**之前**
 * 通过环境变量传进去，不存在竞态。
 *
 * 协议（与 `packages/inkflow-browser-electron` 对齐）：
 *
 * | 请求 | 请求体 | 响应 |
 * |---|---|---|
 * | `GET /health` | — | `{"ok": true}` |
 * | `POST /render` | `{url, js, timeout}` | `{"ok": true, "html": "..."}` |
 * | `GET /cookies` | — | `{"ok": true, "cookies": [...]}` |
 *
 * 渲染失败返回 **200 + `{ok: false, error}`** —— 桥本身是好的，失败的是这次
 * 渲染。协议层的问题（token 不对、请求体坏了）才用 4xx。
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'

import { BrowserWindow, session } from 'electron'

/** 与后端约定的头名。后端侧常量在 `bridge.py`。 */
const HEADER_TOKEN = 'x-inkflow-token'

/** 请求体上限。桥只收几个字段，超过这个数一定是哪里出错了。 */
const MAX_BODY_BYTES = 64 * 1024

const DEFAULT_TIMEOUT_MS = 30_000

export interface BrowserBridge {
  /** 监听地址，形如 `http://127.0.0.1:53421`。 */
  readonly url: string
  readonly token: string
  close(): Promise<void>
}

export interface BrowserBridgeOptions {
  /** 鉴权 token。由调用方生成，同一个值会写进后端的环境变量。 */
  token: string
}

interface RenderRequest {
  url: string
  js: string | null
  timeoutMs: number
}

/**
 * 启动浏览器桥。
 *
 * 端口由系统分配（`listen(0)`），所以只能这样把实际端口告诉调用方。
 */
export async function startBrowserBridge(options: BrowserBridgeOptions): Promise<BrowserBridge> {
  const { token } = options

  const server = createServer((request, response) => {
    void handle(request, response, token).catch((error: unknown) => {
      // 兜底：处理器自己不该抛，真抛了也别把进程带走
      sendJson(response, 500, { ok: false, error: error instanceof Error ? error.message : String(error) })
    })
  })

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      server.off('error', reject)
      resolve()
    })
  })

  const address = server.address()
  const port = typeof address === 'object' && address !== null ? address.port : 0
  if (!port) {
    server.close()
    throw new Error('浏览器桥没能拿到端口')
  }

  return {
    url: `http://127.0.0.1:${port}`,
    token,
    close: () => closeServer(server)
  }
}

async function handle(
  request: IncomingMessage,
  response: ServerResponse,
  token: string
): Promise<void> {
  // 桥只监听回环，但仍然要 token —— 否则本机任何进程都能借桌面端去抓任意地址。
  if (request.headers[HEADER_TOKEN] !== token) {
    sendJson(response, 401, { ok: false, error: 'token 不匹配' })
    return
  }

  const path = (request.url ?? '').split('?')[0]

  if (path === '/health') {
    sendJson(response, 200, { ok: true })
    return
  }

  if (path === '/cookies') {
    const cookies = await session.defaultSession.cookies.get({})
    sendJson(response, 200, {
      ok: true,
      cookies: cookies.map((cookie) => ({
        name: cookie.name,
        value: cookie.value,
        domain: cookie.domain ?? '',
        path: cookie.path ?? '/'
      }))
    })
    return
  }

  if (path === '/render') {
    if (request.method !== 'POST') {
      sendJson(response, 405, { ok: false, error: '请用 POST' })
      return
    }
    const parsed = await readRenderRequest(request, response)
    if (!parsed) return

    try {
      const html = await render(parsed)
      sendJson(response, 200, { ok: true, html })
    } catch (error) {
      // 渲染失败是**这一次**的失败，不是桥坏了 —— 用 200 + ok:false
      sendJson(response, 200, {
        ok: false,
        error: error instanceof Error ? error.message : String(error)
      })
    }
    return
  }

  sendJson(response, 404, { ok: false, error: `未知路径 ${path}` })
}

async function readRenderRequest(
  request: IncomingMessage,
  response: ServerResponse
): Promise<RenderRequest | null> {
  let raw: string
  try {
    raw = await readBody(request)
  } catch (error) {
    sendJson(response, 413, {
      ok: false,
      error: error instanceof Error ? error.message : '请求体读取失败'
    })
    return null
  }

  let body: Record<string, unknown>
  try {
    body = JSON.parse(raw) as Record<string, unknown>
  } catch {
    sendJson(response, 400, { ok: false, error: '请求体不是合法 JSON' })
    return null
  }

  const url = typeof body.url === 'string' ? body.url.trim() : ''
  if (!url) {
    sendJson(response, 400, { ok: false, error: '缺少 url' })
    return null
  }

  const rawTimeout = Number(body.timeout)
  return {
    url,
    js: typeof body.js === 'string' && body.js ? body.js : null,
    timeoutMs: Number.isFinite(rawTimeout) && rawTimeout > 0 ? rawTimeout * 1000 : DEFAULT_TIMEOUT_MS
  }
}

/**
 * 用隐藏窗口渲染一个页面，返回渲染后的 HTML。
 *
 * **每个请求一个新窗口**：窗口之间互不干扰，并发请求也不会互相踩。
 * 代价是每次多几百毫秒 —— L3 本来就不是热路径，这个代价值得。
 *
 * 窗口用默认 session，所以 Cookie 能跨请求保留（登录态就靠它）。
 */
async function render(request: RenderRequest): Promise<string> {
  const window = new BrowserWindow({
    show: false,
    width: 1280,
    height: 800,
    webPreferences: {
      // 渲染的是**不可信页面**：关掉 Node 集成与预加载，
      // 不给它任何碰到主进程的机会。
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      javascript: true
    }
  })

  try {
    await withTimeout(
      (async () => {
        await window.loadURL(request.url)
        if (request.js) {
          await window.webContents.executeJavaScript(request.js, true)
        }
      })(),
      request.timeoutMs,
      () => window.destroy()
    )

    const html = await window.webContents.executeJavaScript(
      'document.documentElement.outerHTML',
      true
    )
    return typeof html === 'string' ? html : String(html ?? '')
  } finally {
    if (!window.isDestroyed()) window.destroy()
  }
}

/**
 * 给 promise 加超时。
 *
 * `loadURL` 没有超时参数，而一个卡住的页面会让请求永远挂着 ——
 * 后端那边只看到「没响应」，查不出是页面卡住了。
 */
function withTimeout<T>(promise: Promise<T>, ms: number, onTimeout: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      onTimeout()
      reject(new Error(`渲染超时（${Math.round(ms / 1000)}s）`))
    }, ms)

    promise.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (error: unknown) => {
        clearTimeout(timer)
        reject(error instanceof Error ? error : new Error(String(error)))
      }
    )
  })
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0

    request.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > MAX_BODY_BYTES) {
        reject(new Error(`请求体超过 ${MAX_BODY_BYTES} 字节`))
        request.destroy()
        return
      }
      chunks.push(chunk)
    })
    request.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')))
    request.on('error', reject)
  })
}

function sendJson(response: ServerResponse, status: number, payload: unknown): void {
  if (response.writableEnded) return
  const body = JSON.stringify(payload)
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body)
  })
  response.end(body)
}

function closeServer(server: Server): Promise<void> {
  return new Promise<void>((resolve) => {
    server.close(() => resolve())
    // 后端可能还挂着 keep-alive 连接，不等它们自然断开
    server.closeAllConnections?.()
  })
}
