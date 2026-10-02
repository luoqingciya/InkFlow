/**
 * Python 后端进程管理（规划书 §34、§35）。
 *
 * 两种运行形态：
 *
 * | 环境 | 后端来源 | 启动方式 |
 * |---|---|---|
 * | 开发 | 仓库源码 | `uv run inkflow-server` |
 * | 打包 | 随安装包分发的单文件可执行程序 | 直接执行 |
 *
 * Desktop **不假设** Python 一定存在：找不到后端时给出明确提示，而不是白屏。
 *
 * 握手协议：后端就绪后在 stdout 打印一行
 *
 *     INKFLOW_READY port=53421 token=xxxxx
 *
 * 端口默认由系统分配（配置里 port = 0），所以只能这样拿实际端口。
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { createInterface } from 'node:readline'

import { app } from 'electron'

export interface BackendConnection {
  baseUrl: string
  token: string
  port: number
  host: string
}

export interface BackendStartOptions {
  /** 就绪超时（毫秒） */
  timeoutMs?: number
  /** 强制指定端口，0 表示自动分配 */
  port?: number
  /** 关闭鉴权（仅本机调试） */
  noToken?: boolean
  /** 工作目录（开发时为仓库根目录） */
  cwd?: string
}

interface LaunchSpec {
  command: string
  args: string[]
  cwd: string
}

const READY_PREFIX = 'INKFLOW_READY'

/** uv 可执行文件的候选位置。开发机上的安装位置优先于 PATH。 */
const UV_CANDIDATES = [
  process.env.INKFLOW_UV,
  process.platform === 'win32' ? 'D:\\DevEnv\\uv\\uv.exe' : undefined,
  'uv'
].filter((value): value is string => Boolean(value))

function isExecutable(command: string): boolean {
  // 含路径分隔符的必须真实存在；裸命令交给 PATH 解析
  if (command.includes('/') || command.includes('\\')) return existsSync(command)
  return true
}

/**
 * 决定启动哪个后端。
 *
 * 打包后必须用随包分发的可执行文件 —— 用户机器上不一定有 Python，
 * 更不一定有 uv。
 */
function resolveLaunch(options: BackendStartOptions): LaunchSpec {
  if (app.isPackaged) {
    const name = process.platform === 'win32' ? 'inkflow-server.exe' : 'inkflow-server'
    const bundled = join(process.resourcesPath, 'backend', name)
    if (!existsSync(bundled)) {
      throw new Error(`安装包缺少后端程序（${bundled}）。这是打包问题，请重新安装或反馈。`)
    }
    // 安装目录通常只读，工作目录换成可写的用户数据目录
    return { command: bundled, args: [], cwd: app.getPath('userData') }
  }

  const uv = UV_CANDIDATES.find(isExecutable)
  if (!uv) {
    throw new Error('找不到 uv 可执行文件。请安装 uv，或设置环境变量 INKFLOW_UV 指向它。')
  }
  return {
    command: uv,
    args: ['run', 'inkflow-server'],
    cwd: options.cwd ?? process.cwd()
  }
}

export class BackendProcess {
  private child: ChildProcessWithoutNullStreams | null = null
  private connection: BackendConnection | null = null
  private stopping = false

  get info(): BackendConnection | null {
    return this.connection
  }

  get isRunning(): boolean {
    return this.child !== null && this.child.exitCode === null
  }

  /**
   * 启动后端并等待握手。
   *
   * @throws 启动失败或超时时抛出，调用方需自行决定是否降级。
   */
  async start(options: BackendStartOptions = {}): Promise<BackendConnection> {
    if (this.connection) return this.connection

    const launch = resolveLaunch(options)
    const args = [...launch.args, '--quiet']
    if (options.port !== undefined) args.push('--port', String(options.port))
    if (options.noToken) args.push('--no-token')

    console.log(`[inkflow-backend] 启动：${launch.command} ${args.join(' ')}`)

    this.child = spawn(launch.command, args, {
      cwd: launch.cwd,
      env: {
        ...process.env,
        // 不缓冲输出，否则握手行要等缓冲区满才吐出来
        PYTHONUNBUFFERED: '1',
        // 本机回环请求不该走系统代理
        NO_PROXY: '127.0.0.1,localhost',
        no_proxy: '127.0.0.1,localhost'
      },
      stdio: ['ignore', 'pipe', 'pipe']
    }) as ChildProcessWithoutNullStreams

    // spawn 失败（可执行文件不存在、无执行权限）会触发 'error'。
    // 不监听的话 Node 会抛未捕获异常，直接带走整个主进程。
    this.child.on('error', (error) => {
      console.error('[inkflow-backend] 进程启动失败：', error)
    })

    this.child.stderr.on('data', (chunk: Buffer) => {
      // 后端日志原样转发，方便在 DevTools 里排查
      console.error('[inkflow-backend]', chunk.toString().trimEnd())
    })

    this.child.on('exit', (code, signal) => {
      if (!this.stopping) {
        console.error(`[inkflow-backend] 进程意外退出 code=${code} signal=${signal}`)
      }
      this.child = null
      this.connection = null
    })

    this.connection = await this.waitForReady(options.timeoutMs ?? 40_000)
    return this.connection
  }

  /** 停止后端。先 SIGTERM，超时后 SIGKILL。 */
  async stop(): Promise<void> {
    const child = this.child
    if (!child || child.exitCode !== null) {
      this.child = null
      this.connection = null
      return
    }

    this.stopping = true
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        child.kill('SIGKILL')
        resolve()
      }, 5_000)

      child.once('exit', () => {
        clearTimeout(timer)
        resolve()
      })
      child.kill('SIGTERM')
    })

    this.child = null
    this.connection = null
    this.stopping = false
  }

  /** 逐行读取 stdout，等待握手行。 */
  private waitForReady(timeoutMs: number): Promise<BackendConnection> {
    const child = this.child
    if (!child) return Promise.reject(new Error('后端进程未启动'))

    return new Promise<BackendConnection>((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup()
        reject(new Error(`后端启动超时（${timeoutMs / 1000}s）。请检查 uv 与依赖是否就绪。`))
      }, timeoutMs)

      const reader = createInterface({ input: child.stdout })

      const onLine = (line: string): void => {
        if (!line.startsWith(READY_PREFIX)) return
        const parsed = parseHandshake(line)
        if (!parsed) return
        cleanup()
        resolve(parsed)
      }

      const onExit = (code: number | null): void => {
        cleanup()
        reject(new Error(`后端进程在就绪前退出（code=${code}）`))
      }

      const cleanup = (): void => {
        clearTimeout(timer)
        reader.off('line', onLine)
        child.off('exit', onExit)
        reader.close()
      }

      reader.on('line', onLine)
      child.once('exit', onExit)
    })
  }
}

/** 解析 `INKFLOW_READY port=… token=…`。 */
export function parseHandshake(line: string): BackendConnection | null {
  const match = /port=(\d+)\s+token=(\S*)/.exec(line)
  if (!match) return null
  const port = Number.parseInt(match[1], 10)
  if (!Number.isFinite(port) || port <= 0) return null
  return {
    host: '127.0.0.1',
    port,
    token: match[2],
    baseUrl: `http://127.0.0.1:${port}`
  }
}
