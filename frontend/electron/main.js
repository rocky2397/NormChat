import { app, BrowserWindow, ipcMain } from 'electron'
import { spawn } from 'node:child_process'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const isDev = !app.isPackaged

// The Python venv lives outside the project on internal disk (it can't
// survive on the project's exFAT external drive — see repo history), so
// its path isn't relative to this file the way the backend/frontend are.
const VENV_PYTHON = path.join(os.homedir(), '.venvs/normchat/bin/python3')
const BACKEND_DIR = path.resolve(__dirname, '../../backend')
const BACKEND_PORT = 8000
const FRONTEND_DEV_URL = 'http://localhost:5173'
const PRELOAD_PATH = path.join(__dirname, 'preload.cjs')

let backendProcess = null
let mainWindow = null

function startBackend() {
  backendProcess = spawn(
    VENV_PYTHON,
    ['-m', 'uvicorn', 'main:app', '--port', String(BACKEND_PORT)],
    { cwd: BACKEND_DIR, stdio: 'inherit' },
  )
  backendProcess.on('error', (err) => {
    console.error('Failed to start backend:', err)
  })
}

async function waitForBackend(timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${BACKEND_PORT}/health`)
      if (res.ok) return true
    } catch {
      // backend not up yet, keep polling
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return false
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 1000,
    webPreferences: {
      preload: PRELOAD_PATH,
    },
  })

  if (isDev) {
    await mainWindow.loadURL(FRONTEND_DEV_URL)
  } else {
    await mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }
}

async function createPdfWindow({ documentId, pageNumber, highlightText, filename }) {
  const pdfWindow = new BrowserWindow({
    width: 1000,
    height: 1100,
    webPreferences: {
      // Required for Chromium's built-in PDF viewer, which the standalone
      // viewer page embeds directly via an <iframe>.
      plugins: true,
    },
  })

  const search = new URLSearchParams({
    page: String(pageNumber),
    text: highlightText || '',
    filename: filename || '',
  }).toString()

  if (isDev) {
    await pdfWindow.loadURL(`${FRONTEND_DEV_URL}/documents/${documentId}/viewer?${search}`)
  } else {
    // Production packaging (static build + routing) hasn't been set up
    // yet — this path is unverified until that lands.
    await pdfWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      hash: `/documents/${documentId}/viewer`,
      search,
    })
  }
}

app.whenReady().then(async () => {
  startBackend()
  const backendReady = await waitForBackend()
  if (!backendReady) {
    console.error('Backend did not become ready in time; opening window anyway.')
  }
  await createWindow()

  ipcMain.on('open-pdf-window', (_event, payload) => {
    createPdfWindow(payload)
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backendProcess) backendProcess.kill()
})
