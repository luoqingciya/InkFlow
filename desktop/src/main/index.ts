/**
 * Electron 主进程（规划书 §33）。
 *
 * 职责严格限定在**系统能力**：窗口、托盘、应用生命周期、后端进程管理、
 * 原生对话框。
 *
 * 主进程**不做**搜索、下载、解析、书源执行 —— 那些都在 Python 后端里。
 * Renderer 也拿不到 Node 权限，只能通过 preload 暴露的白名单接口访问。
 */

import { readFile, stat } from 'node:fs/promises'
import { join } from 'node:path'
import { app, BrowserWindow, Menu, Tray, dialog, ipcMain, shell } from 'electron'

import { BackendProcess, type BackendConnection } from './backend'

const backend = new BackendProcess()
let mainWindow: BrowserWindow | null = null
let tray: Tray | null = null

/** 后端启动失败时的原因；Renderer 会读到它并给出可操作的提示。 */
let backendError: string | null = null

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 900,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#1b1d21',
    title: 'InkFlow',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      // 安全边界：Renderer 不接触 Node，也不允许任意跳转
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true
    }
  })

  window.on('ready-to-show', () => window.show())

  // 外部链接交给系统浏览器，不在应用内开新窗口
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  if (process.env['ELECTRON_RENDERER_URL']) {
    void window.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'))
  }

  window.on('closed', () => {
    mainWindow = null
  })

  return window
}

/**
 * 创建托盘。
 *
 * 托盘创建失败**不能**影响主窗口 —— 某些 Linux 桌面环境没有系统托盘，
 * 某些 Windows 配置会拒绝加载图标。这是典型的「少一个功能，
 * 不能让程序起不来」。
 */
function createTray(): void {
  try {
    const icon = app.isPackaged
      ? join(process.resourcesPath, 'icon.png')
      : join(__dirname, '../../resources/icon.png')

    tray = new Tray(icon)
    tray.setToolTip('InkFlow')
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: '显示主窗口',
          click: () => {
            if (mainWindow) mainWindow.show()
            else mainWindow = createWindow()
          }
        },
        { type: 'separator' },
        { label: '退出', click: () => app.quit() }
      ])
    )
  } catch (error) {
    console.warn('[inkflow] 托盘创建失败，已跳过：', error)
    tray = null
  }
}

/** 注册 IPC 处理器。全部走 `invoke`（请求-响应），不用单向 send。 */
function registerIpc(): void {
  ipcMain.handle('inkflow:connection', (): BackendConnection | { error: string } => {
    if (backendError) return { error: backendError }
    const info = backend.info
    return info ?? { error: '后端尚未就绪' }
  })

  ipcMain.handle('inkflow:app-info', () => ({
    version: app.getVersion(),
    electron: process.versions.electron,
    node: process.versions.node,
    platform: process.platform,
    packaged: app.isPackaged,
    // 数据目录是便携的（默认在程序目录下），UI 需要能告诉用户它在哪
    dataHome: backend.dataHome
  }))

  ipcMain.handle('inkflow:open-path', async (_event, target: string): Promise<string> => {
    // 只允许打开真实存在的路径，避免把任意字符串丢给系统
    return shell.openPath(target)
  })

  ipcMain.handle('inkflow:reveal-path', (_event, target: string): void => {
    shell.showItemInFolder(target)
  })

  ipcMain.handle(
    'inkflow:select-file',
    async (_event, options: { title?: string; filters?: Electron.FileFilter[] }) => {
      const result = await dialog.showOpenDialog({
        title: options?.title ?? '选择书源文件',
        properties: ['openFile'],
        filters: options?.filters ?? [
          { name: '书源文件', extensions: ['json', 'yaml', 'yml'] },
          { name: '全部文件', extensions: ['*'] }
        ]
      })
      return result.canceled ? null : result.filePaths[0]
    }
  )

  ipcMain.handle('inkflow:read-text-file', async (_event, target: string): Promise<string> => {
    // 书源文件不该超过几 MB，设上限避免误选大文件把内存打满
    const MAX_BYTES = 8 * 1024 * 1024
    const info = await stat(target)
    if (info.size > MAX_BYTES) {
      throw new Error(`文件过大（${(info.size / 1024 / 1024).toFixed(1)}MB），上限 8MB`)
    }
    return readFile(target, 'utf-8')
  })

  ipcMain.handle('inkflow:select-directory', async (_event, options: { title?: string }) => {
    const result = await dialog.showOpenDialog({
      title: options?.title ?? '选择目录',
      properties: ['openDirectory', 'createDirectory']
    })
    return result.canceled ? null : result.filePaths[0]
  })
}

app.whenReady().then(async () => {
  registerIpc()

  // 后端启动失败不阻断窗口创建：界面会展示错误与重试入口，
  // 总好过用户面对一个什么都不显示的白屏。
  try {
    const connection = await backend.start({
      cwd: app.isPackaged ? process.resourcesPath : join(__dirname, '../../..')
    })
    console.log(`[inkflow] 后端就绪 ${connection.baseUrl}`)
  } catch (error) {
    backendError = error instanceof Error ? error.message : String(error)
    console.error('[inkflow] 后端启动失败：', backendError)
  }

  mainWindow = createWindow()
  createTray()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

let shuttingDown = false
app.on('before-quit', async (event) => {
  if (shuttingDown) return
  shuttingDown = true
  event.preventDefault()
  await backend.stop()
  app.exit(0)
})
