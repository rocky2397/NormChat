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
let pdfWindow = null
let pdfPayload = null

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

async function openOrUpdatePdfWindow(payload) {
  // Retained so a viewer that announces itself late — or reloads — can be
  // served the current citations without the user clicking again. Citation
  // text for a full answer runs past the ~16KB header limit Node enforces on
  // a query string (a 431 in testing), so it travels over IPC, not the URL.
  pdfPayload = payload

  // Reuse one window across citation clicks — pushing new data over IPC —
  // rather than spawning a new window per click, which was the whole point
  // of the stepper: one place to page through all of an answer's sources.
  if (pdfWindow && !pdfWindow.isDestroyed()) {
    pdfWindow.webContents.send('update-sources', payload)
    pdfWindow.focus()
    return
  }

  pdfWindow = new BrowserWindow({
    width: 1000,
    height: 1100,
    webPreferences: {
      // Required for Chromium's built-in PDF viewer, which the standalone
      // viewer page embeds directly via an <iframe>.
      plugins: true,
      preload: PRELOAD_PATH,
    },
  })
  pdfWindow.on('closed', () => {
    pdfWindow = null
  })

  // The payload is not pushed on 'did-finish-load'. That fires when the page
  // loads, but the viewer route sits behind the auth gate, so React has not
  // mounted the component that listens for it yet — the message was
  // delivered to nobody and the window sat on "Quellen werden geladen…"
  // forever. The renderer now announces itself instead (see 'viewer-ready'),
  // which removes the race rather than narrowing it.

  if (isDev) {
    await pdfWindow.loadURL(`${FRONTEND_DEV_URL}/viewer`)
  } else {
    // Production packaging (static build + routing) hasn't been set up
    // yet — this path is unverified until that lands.
    await pdfWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      hash: '/viewer',
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
    openOrUpdatePdfWindow(payload)
  })

  // The viewer asks for its citations once it is actually listening, which
  // is the only moment the main process can know that. Answering a request
  // cannot lose the message the way pushing on page load did.
  ipcMain.on('viewer-ready', (event) => {
    if (pdfPayload) {
      event.sender.send('update-sources', pdfPayload)
    }
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
