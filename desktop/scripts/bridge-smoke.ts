/**
 * 浏览器桥的实机冒烟测试。
 *
 * 为什么单独有这么一个东西：桥跑在 Electron 主进程里，而桌面端整体要起
 * Python 后端、开窗口、建托盘 —— 只为验桥的话太重，也不好放进日常 CI。
 * 这个脚本只做一件事：把桥起起来，自己打自己几发，看协议对不对。
 *
 * 用法（在 desktop/ 下）：
 *
 *     npx esbuild scripts/bridge-smoke.ts --bundle --platform=node --format=cjs \
 *       --external:electron --outfile=scripts/.bridge-smoke.cjs
 *     env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS \
 *       node_modules/.bin/electron scripts/.bridge-smoke.cjs
 *
 * **必须清掉 `ELECTRON_RUN_AS_NODE`** —— 本环境预设了它，Electron 会退化成
 * 纯 Node 跑，`BrowserWindow` 直接不可用。
 */

import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

import { app } from 'electron'

import { startBrowserBridge } from '../src/main/browser-bridge'

const TOKEN = 'smoke-token'

let failures = 0

function check(name: string, ok: boolean, detail = ''): void {
  if (ok) {
    console.log(`  ✓ ${name}`)
  } else {
    failures += 1
    console.log(`  ✗ ${name}${detail ? ` —— ${detail}` : ''}`)
  }
}

/** 一个最小页面服务器：桥要渲染的就是它。 */
function startSite(): Promise<{ url: string; close: () => void }> {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    response.end(
      '<!doctype html><html><head><title>原始标题</title></head>' +
        '<body><p id="c">正文</p></body></html>'
    )
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo
      resolve({ url: `http://127.0.0.1:${port}/`, close: () => server.close() })
    })
  })
}

/**
 * 拿一个**确定没人监听**的端口，用来测「连不上」。
 *
 * 别用 1 这种低位端口 —— Chromium 有一份「不安全端口」黑名单，
 * 那种情况下报的是 `ERR_UNSAFE_PORT`，测的就不是「连接被拒」了。
 */
function closedPortUrl(): Promise<string> {
  const probe = createServer()
  return new Promise((resolve) => {
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address() as AddressInfo
      probe.close(() => resolve(`http://127.0.0.1:${port}/`))
    })
  })
}

async function main(): Promise<void> {
  const site = await startSite()
  const bridge = await startBrowserBridge({ token: TOKEN })
  console.log(`桥已启动：${bridge.url}\n协议检查：`)

  const call = async (
    path: string,
    init: RequestInit = {},
    token = TOKEN
  ): Promise<{ status: number; body: Record<string, unknown> }> => {
    const response = await fetch(`${bridge.url}${path}`, {
      ...init,
      headers: {
        'x-inkflow-token': token,
        'content-type': 'application/json',
        ...(init.headers ?? {})
      }
    })
    const text = await response.text()
    let body: Record<string, unknown> = {}
    try {
      body = JSON.parse(text) as Record<string, unknown>
    } catch {
      body = { raw: text }
    }
    return { status: response.status, body }
  }

  const render = (payload: Record<string, unknown>) =>
    call('/render', { method: 'POST', body: JSON.stringify(payload) })

  const health = await call('/health')
  check('/health 通', health.status === 200 && health.body.ok === true)

  const bad = await call('/health', {}, 'wrong')
  check('token 不对被拒', bad.status === 401, `实际 ${bad.status}`)

  const rendered = await render({ url: site.url, js: null, timeout: 10 })
  const html = String(rendered.body.html ?? '')
  check('/render 拿到 HTML', rendered.body.ok === true && html.includes('正文'))
  check('拿到的是渲染结果', html.includes('<p id="c">'))

  // 关键的一条：脚本要**真的在页面里跑过**。
  // 跑过就会改掉 DOM，而 DOM 变了才会出现在返回的 HTML 里。
  const withJs = await render({
    url: site.url,
    js: "document.body.setAttribute('data-inkflow','ran')",
    timeout: 10
  })
  check('js 真的在页面里跑过', String(withJs.body.html ?? '').includes('data-inkflow="ran"'))

  const cookies = await call('/cookies')
  check('/cookies 返回数组', Array.isArray(cookies.body.cookies))

  const refused = await render({ url: await closedPortUrl(), js: null, timeout: 5 })
  check('连不上时报 ok:false', refused.body.ok === false && refused.status === 200)

  const badBody = await call('/render', { method: 'POST', body: 'not json' })
  check('请求体坏了报 400', badBody.status === 400, `实际 ${badBody.status}`)

  const noUrl = await render({ js: null, timeout: 5 })
  check('缺 url 报 400', noUrl.status === 400, `实际 ${noUrl.status}`)

  await bridge.close()
  site.close()

  console.log(failures === 0 ? '\n全部通过' : `\n${failures} 项失败`)
  app.exit(failures === 0 ? 0 : 1)
}

app.whenReady().then(() => {
  void main().catch((error: unknown) => {
    console.error('冒烟测试自身出错：', error)
    app.exit(2)
  })
})

// Electron 默认「最后一个窗口关掉就退出」。渲染完会销毁隐藏窗口，
// 于是进程会**在检查做到一半时自己退掉** —— 拦掉它，退出由脚本自己决定。
app.on('window-all-closed', () => {
  // 冒烟测试里什么都不做
})
