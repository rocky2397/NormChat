import { useEffect, useMemo, useState } from 'react'
import PDFViewer from '../components/PDFViewer'

export default function PDFViewerPage() {
  const [sources, setSources] = useState([])
  const [currentIndex, setCurrentIndex] = useState(0)

  function applyUpdate({ sources: nextSources, initialIndex }) {
    setSources(nextSources)
    setCurrentIndex(initialIndex)
  }

  // Citation data arrives after load, not via URL (a full answer's sources
  // easily exceed URL/header size limits) — over Electron IPC when
  // available, otherwise postMessage from the opener window.
  useEffect(() => {
    if (window.electronAPI) {
      const unsubscribe = window.electronAPI.onUpdateSources(applyUpdate)
      // Announce only once the listener exists. This component mounts well
      // after the page loads, because the auth gate holds it back until
      // /api/auth/me returns — so anything pushed at load time was missed.
      window.electronAPI.notifyViewerReady()
      return unsubscribe
    }

    function handleMessage(event) {
      if (event.origin !== window.location.origin) return
      if (event.data?.type !== 'update-sources') return
      applyUpdate(event.data.payload)
    }
    window.addEventListener('message', handleMessage)
    window.opener?.postMessage('normchat-viewer-ready', window.location.origin)
    return () => window.removeEventListener('message', handleMessage)
  }, [])

  const current = sources[currentIndex]

  useEffect(() => {
    if (current?.filename) document.title = current.filename
  }, [current?.filename])

  const goPrev = () => setCurrentIndex((i) => Math.max(0, i - 1))
  const goNext = () => setCurrentIndex((i) => Math.min(sources.length - 1, i + 1))

  useEffect(() => {
    function handleKeyDown(event) {
      // Only fires while focus is on the outer page, not inside the PDF
      // iframe (cross-frame keyboard events don't bubble to the parent) —
      // the Prev/Next buttons are the reliable path, this is a bonus.
      if (event.key === 'ArrowLeft') goPrev()
      if (event.key === 'ArrowRight') goNext()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [sources.length])

  const positionLabel = useMemo(
    () => (sources.length ? `Quelle ${currentIndex + 1} von ${sources.length}` : ''),
    [currentIndex, sources.length],
  )

  if (!current) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-100 text-sm text-slate-500">
        Quellen werden geladen…
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col gap-2 bg-slate-100 p-3">
      <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-2 shadow-sm">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">
            {current.norm_reference || current.filename}
          </p>
          <p className="text-xs text-slate-500">{positionLabel}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={goPrev}
            disabled={currentIndex <= 0}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
            title="Vorherige Quelle (←)"
          >
            ← Vorherige
          </button>
          <button
            type="button"
            onClick={goNext}
            disabled={currentIndex >= sources.length - 1}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
            title="Nächste Quelle (→)"
          >
            Nächste →
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <PDFViewer
          documentId={current.document_id}
          filename={current.filename}
          pageNumber={current.page_number}
          highlightText={current.highlight_snippet || current.chunk_text}
        />
      </div>
    </div>
  )
}
