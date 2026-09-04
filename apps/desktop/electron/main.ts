import { app, BrowserWindow } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const VITE_DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL

const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend')

let backendProcess: ChildProcess | null = null
let win: BrowserWindow | null = null

function startBackend() {
  backendProcess = spawn(
    'uv',
    ['run', 'uvicorn', 'app.main:app', '--port', '8420', '--reload'],
    { cwd: BACKEND_DIR, shell: true, stdio: 'pipe' },
  )
  backendProcess.stdout?.on('data', (data) => process.stdout.write(data))
  backendProcess.stderr?.on('data', (data) => process.stderr.write(data))
  backendProcess.on('error', (err) => {
    console.error('failed to start backend:', err)
  })
}

function stopBackend() {
  backendProcess?.kill()
  backendProcess = null
}

function createWindow() {
  win = new BrowserWindow({
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL)
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }
}

app.whenReady().then(() => {
  startBackend()
  createWindow()
})

app.on('will-quit', stopBackend)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})
