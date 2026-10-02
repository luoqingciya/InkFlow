/**
 * Python 后端进程管理（规划书 §34、§35）。
 *
 * Desktop **不假设** Python 一定存在：找不到后端时给出明确提示并降级为
 * 「只读模式」，而不是白屏。
 *
 * 握手协议：后端就绪后在 stdout 打印一行
 *
 *     INKFLOW_READY port=53421 token=xxxxx
 *
 * 端口默认由系统分配（配置里 port = 0），所以只能这样拿实际端口。
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createInterface } from 'node:readline'

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

const READY_PREFIX = 'INKFLOW_READY'

/** uv 可执行文件的候选位置。开发机上的安装位置优先于 PATH。 */
const UV_CANDIDATES = [
  process.env.INKFLOW_UV,
  process.platform === 'win32' ? 'D:\\DevEnv\\uv\\uv.exe' : undefined,
  'uv'
].filter((value): value is string => Boolean(value))

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

    const uv = UV_CANDIDATES.find((candidate) => this.canExecute(candidate))
    if (!uv) {
      throw new Error(
        '找不到 uv 可执行文件。请安装 uv，或设置环境变量 INKFLOW_UV 指向它。'
      )
    }

    const args = ['run', 'inkflow-server', '--quiet']
    if (options.port !== undefined) args.push('--port', String(options.port))
    if (options.noToken) args.push('--no-token')

    this.child = spawn(uv, args, {
      cwd: options.cwd ?? process.cwd(),
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe']
    }) as ChildProcessWithoutNullStreams

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

  private canExecute(command: string): boolean {
    if (command.includes('/') || command.includes('\\')) return existsSync(command)
    return true // 交给 PATH 解析
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
