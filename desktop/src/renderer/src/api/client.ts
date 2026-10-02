/**
 * API 客户端（规划书 §54、§56）。
 *
 *     Renderer → 本模块 → preload → 主进程 → HTTP → InkFlow API
 *
 * 这里**不** import 任何 Python 代码，也不直连数据库 ——
 * Renderer 是纯粹的 API 消费者。
 *
 * 类型定义刻意保持与后端 Pydantic 模型一致（可由 OpenAPI 生成，规划书 §57）。
 */

export interface BackendConnection {
  baseUrl: string
  token: string
  port: number
  host: string
}

export interface SourceRef {
  source_id: string
  source_name: string
  book_id: string
  book_url: string
  latest_chapter: string | null
  score: number
}

export interface SearchItem {
  name: string
  author: string | null
  intro: string | null
  cover_url: string | null
  category: string | null
  status: string | null
  sources: SourceRef[]
  score: number
}

export interface SearchResponse {
  keyword: string
  items: SearchItem[]
  source_errors: Record<string, string>
  total: number
}

export interface Book {
  id: string
  name: string
  author: string | null
  intro: string | null
  cover_url: string | null
  category: string | null
  status: string | null
  source_id: string
  source_book_url: string
  latest_chapter: string | null
  word_count: number | null
}

export interface Chapter {
  id: string
  book_id: string
  index: number
  name: string
  url: string
  is_vip: boolean
  downloaded: boolean
}

export interface DownloadTask {
  id: string
  book_id: string
  status: string
  start_chapter: number
  end_chapter: number
  total: number
  completed: number
  failed: number
  concurrency: number
  output_format: string
  output_path: string
  error: string | null
  created_at: string
}

export interface BookSource {
  id: string
  name: string
  url: string
  enabled: boolean
  source_type: string
  compatibility_level: string
  enabled_search: boolean
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown>; trace_id: string | null }
}

let cached: BackendConnection | null = null

/** 从主进程取后端地址与 token（只取一次）。 */
export async function ensureConnection(): Promise<BackendConnection> {
  if (cached) return cached
  const result = await window.inkflow.getConnection()
  if ('error' in result) throw new Error(result.error)
  cached = result
  return result
}

/** 清空缓存，用于「重试连接」。 */
export function resetConnection(): void {
  cached = null
}

/** 统一的请求封装。 */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const connection = await ensureConnection()
  const response = await fetch(`${connection.baseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${connection.token}`,
      ...(init.headers ?? {})
    }
  })

  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as ApiErrorBody
      message = body.error?.message ?? message
    } catch {
      /* 非 JSON 错误体，保留状态码信息 */
    }
    throw new Error(message)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// ---------------------------------------------------------------- 接口

export const api = {
  health: () => request<{ status: string; version: string }>('/health'),

  search: (keyword: string, limit = 50) =>
    request<SearchResponse>(`/api/v1/search?q=${encodeURIComponent(keyword)}&limit=${limit}`),

  listBooks: (limit = 50, offset = 0) =>
    request<{ items: Book[]; total: number }>(`/api/v1/books?limit=${limit}&offset=${offset}`),

  getBook: (bookId: string) =>
    request<{ book: Book; source: BookSource | null; chapter_count: number; downloaded_count: number }>(
      `/api/v1/books/${bookId}`
    ),

  getChapters: (bookId: string, refresh = false) =>
    request<{ book_id: string; chapters: Chapter[]; total: number }>(
      `/api/v1/books/${bookId}/chapters?refresh=${refresh}`
    ),

  exportBook: (bookId: string, format: string, start = 0, end?: number) =>
    request<{ output_path: string; chapter_count: number }>(`/api/v1/books/${bookId}/export`, {
      method: 'POST',
      body: JSON.stringify({ format, start_chapter: start, end_chapter: end ?? null })
    }),

  listSources: () => request<{ items: BookSource[]; total: number }>('/api/v1/sources'),

  importSource: (content: string) =>
    request<{ source: BookSource; created: boolean }>('/api/v1/sources/import', {
      method: 'POST',
      body: JSON.stringify({ format: 'auto', content, enabled: true })
    }),

  setSourceEnabled: (sourceId: string, enabled: boolean) =>
    request<BookSource>(`/api/v1/sources/${sourceId}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled })
    }),

  deleteSource: (sourceId: string) =>
    request<{ message: string }>(`/api/v1/sources/${sourceId}`, { method: 'DELETE' }),

  testSource: (sourceId: string, kind = 'search', keyword = '测试', url?: string) =>
    request<{ ok: boolean; count: number; elapsed_ms: number; error: string | null; preview: unknown[] }>(
      `/api/v1/sources/${sourceId}/test`,
      { method: 'POST', body: JSON.stringify({ kind, keyword, url: url ?? null }) }
    ),

  listTasks: () => request<{ items: DownloadTask[]; total: number }>('/api/v1/tasks'),

  getTask: (taskId: string) =>
    request<{ task: DownloadTask; book: Book | null }>(`/api/v1/tasks/${taskId}`),

  createTask: (bookId: string, options: { start?: number; end?: number; format?: string } = {}) =>
    request<DownloadTask>('/api/v1/tasks', {
      method: 'POST',
      body: JSON.stringify({
        book_id: bookId,
        start_chapter: options.start ?? 0,
        end_chapter: options.end ?? null,
        output_format: options.format ?? null,
        auto_start: true
      })
    }),

  pauseTask: (taskId: string) =>
    request<DownloadTask>(`/api/v1/tasks/${taskId}/pause`, { method: 'POST' }),

  resumeTask: (taskId: string) =>
    request<DownloadTask>(`/api/v1/tasks/${taskId}/resume`, { method: 'POST' }),

  cancelTask: (taskId: string) =>
    request<DownloadTask>(`/api/v1/tasks/${taskId}/cancel`, { method: 'POST' })
}

/**
 * 订阅任务进度。
 *
 * WebSocket 地址从后端握手信息推导，token 走查询参数
 * （浏览器的 WebSocket API 不支持自定义请求头）。
 */
export async function watchTask(
  taskId: string,
  onEvent: (event: Record<string, unknown>) => void
): Promise<() => void> {
  const connection = await ensureConnection()
  const wsBase = connection.baseUrl.replace(/^http/, 'ws')
  const socket = new WebSocket(`${wsBase}/ws/tasks/${taskId}?token=${connection.token}`)

  socket.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data as string))
    } catch {
      /* 忽略无法解析的帧 */
    }
  }

  return () => socket.close()
}
