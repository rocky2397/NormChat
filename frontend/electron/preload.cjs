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
})
