/**
 * Preload：主进程与 Renderer 之间唯一的通道（规划书 §55）。
 *
 * 只暴露**有限、具名**的接口。绝不暴露 `require`、`ipcRenderer` 本体或
 * 任意 channel 的发送能力 —— 那等于把 Node 权限交给了页面。
 */

import { contextBridge, ipcRenderer } from 'electron'

export interface BackendConnection {
  baseUrl: string
  token: string
  port: number
  host: string
}

export interface AppInfo {
  version: string
  electron: string
  node: string
  platform: string
  packaged: boolean
  /** 数据目录；后端尚未启动时为 null */
  dataHome: string | null
}

export interface FileDialogOptions {
  title?: string
  filters?: Array<{ name: string; extensions: string[] }>
}

const api = {
  /** 获取后端地址与 session token。后端未就绪时返回 `{ error }`。 */
  getConnection: (): Promise<BackendConnection | { error: string }> =>
    ipcRenderer.invoke('inkflow:connection'),

  /** 应用与运行环境信息。 */
  getAppInfo: (): Promise<AppInfo> => ipcRenderer.invoke('inkflow:app-info'),

  /** 用系统默认程序打开文件 / 目录。返回空字符串表示成功。 */
  openPath: (target: string): Promise<string> => ipcRenderer.invoke('inkflow:open-path', target),

  /** 在文件管理器中定位文件。 */
  revealPath: (target: string): Promise<void> =>
    ipcRenderer.invoke('inkflow:reveal-path', target),

  /** 弹出文件选择对话框，取消时返回 null。 */
  selectFile: (options?: FileDialogOptions): Promise<string | null> =>
    ipcRenderer.invoke('inkflow:select-file', options ?? {}),

  /** 读取文本文件内容。Renderer 没有文件系统权限，只能走这里。 */
  readTextFile: (path: string): Promise<string> =>
    ipcRenderer.invoke('inkflow:read-text-file', path),

  /** 弹出目录选择对话框，取消时返回 null。 */
  selectDirectory: (options?: { title?: string }): Promise<string | null> =>
    ipcRenderer.invoke('inkflow:select-directory', options ?? {})
}

export type InkFlowApi = typeof api

contextBridge.exposeInMainWorld('inkflow', api)
