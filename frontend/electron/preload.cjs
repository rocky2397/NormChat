const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  openPdfWindow: (documentId, pageNumber, highlightText, filename) => {
    ipcRenderer.send('open-pdf-window', { documentId, pageNumber, highlightText, filename })
  },
})
