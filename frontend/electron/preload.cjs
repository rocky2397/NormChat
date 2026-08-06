const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  openPdfWindow: (payload) => {
    ipcRenderer.send('open-pdf-window', payload)
  },
  onUpdateSources: (callback) => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('update-sources', listener)
    return () => ipcRenderer.removeListener('update-sources', listener)
  },
  // Call only after onUpdateSources, so the reply cannot arrive before the
  // listener that is meant to receive it.
  notifyViewerReady: () => {
    ipcRenderer.send('viewer-ready')
  },
})
