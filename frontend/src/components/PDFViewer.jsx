import { useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { documentFileUrl } from '../api/client'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

function normalizeText(text) {
  return text.replace(/\s+/g, ' ').trim().toLowerCase()
}

function findHighlightRects(textContent, highlightText) {
  if (!highlightText) return []

  const items = textContent.items.filter((item) => 'str' in item && item.str.trim())
  const normalizedHighlight = normalizeText(highlightText)
  const normalizedItems = items.map((item) => normalizeText(item.str))

  for (let windowSize = Math.min(12, normalizedItems.length); windowSize >= 1; windowSize -= 1) {
    for (let start = 0; start <= normalizedItems.length - windowSize; start += 1) {
      const combined = normalizedItems.slice(start, start + windowSize).join(' ')
      if (
        combined.includes(normalizedHighlight.slice(0, 80)) ||
        normalizedHighlight.includes(combined.slice(0, 80))
      ) {
        return items.slice(start, start + windowSize).map((item) => item.transform)
      }
    }
  }

  const firstWords = normalizedHighlight.split(' ').slice(0, 6).join(' ')
  for (let i = 0; i < normalizedItems.length; i += 1) {
    if (normalizedItems[i].includes(firstWords.split(' ')[0])) {
      return items.slice(i, Math.min(i + 8, items.length)).map((item) => item.transform)
    }
  }

  return []
}

export default function PDFViewer({ documentId, filename, pageNumber = 1, highlightText = '' }) {
  const canvasRef = useRef(null)
  const overlayRef = useRef(null)
  const containerRef = useRef(null)
  const pdfRef = useRef(null)
  const pdfDocIdRef = useRef(null)
  const [currentPage, setCurrentPage] = useState(pageNumber)
  const [totalPages, setTotalPages] = useState(0)
  const [scale, setScale] = useState(1.2)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setCurrentPage(pageNumber)
  }, [pageNumber, documentId])

  useEffect(() => {
    let cancelled = false

    async function loadPdf() {
      if (!documentId) return
      setLoading(true)
      setError('')
      try {
        const loadingTask = pdfjsLib.getDocument(documentFileUrl(documentId))
        const pdf = await loadingTask.promise
        if (cancelled) return
        pdfRef.current = pdf
        pdfDocIdRef.current = documentId
        setTotalPages(pdf.numPages)
      } catch (err) {
        if (!cancelled) {
          setError('PDF konnte nicht geladen werden.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadPdf()
    return () => {
      cancelled = true
    }
  }, [documentId])

  useEffect(() => {
    let cancelled = false

    async function renderPage() {
      const pdf = pdfRef.current
      const canvas = canvasRef.current
      const overlay = overlayRef.current
      if (!pdf || !canvas || !overlay) return
      // pdfRef is a mutable ref, not React state — while a new document is
      // still loading (async), it can still point at the previous PDF. If
      // that stale PDF has fewer pages than the newly requested page,
      // getPage() throws. The loadPdf effect will update totalPages (and
      // this effect's deps) once the right document is actually ready, so
      // it's safe to just wait rather than render against the wrong file.
      if (pdfDocIdRef.current !== documentId) return

      setLoading(true)
      try {
        const page = await pdf.getPage(currentPage)
        if (cancelled) return

        const viewport = page.getViewport({ scale })
        const context = canvas.getContext('2d')
        canvas.width = viewport.width
        canvas.height = viewport.height
        overlay.style.width = `${viewport.width}px`
        overlay.style.height = `${viewport.height}px`
        overlay.innerHTML = ''

        await page.render({ canvasContext: context, viewport }).promise
        if (cancelled) return

        const textContent = await page.getTextContent()
        const transforms = findHighlightRects(textContent, highlightText)

        transforms.forEach((transform) => {
          const [scaleX, , , scaleY, x, y] = transform
          const fontHeight = Math.abs(scaleY)
          const width = Math.abs(scaleX) * 12
          const div = document.createElement('div')
          div.className = 'absolute rounded-sm bg-yellow-300/60'
          div.style.left = `${x}px`
          div.style.top = `${viewport.height - y - fontHeight}px`
          div.style.width = `${Math.max(width, 40)}px`
          div.style.height = `${Math.max(fontHeight, 12)}px`
          overlay.appendChild(div)
        })
      } catch (err) {
        console.error('PDFViewer render error:', err)
        if (!cancelled) setError('Seite konnte nicht gerendert werden.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    renderPage()
    return () => {
      cancelled = true
    }
  }, [currentPage, scale, highlightText, totalPages, documentId])

  if (!documentId) {
    return (
      <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-sm text-slate-500">
        Wählen Sie eine Quelle aus, um das PDF anzuzeigen.
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{filename}</p>
          <p className="text-xs text-slate-500">
            Seite {currentPage} von {totalPages || '–'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setScale((value) => Math.max(0.8, value - 0.2))}
            className="rounded-lg border border-slate-300 px-3 py-1 text-sm"
          >
            −
          </button>
          <span className="text-xs text-slate-500">{Math.round(scale * 100)}%</span>
          <button
            type="button"
            onClick={() => setScale((value) => Math.min(2.4, value + 0.2))}
            className="rounded-lg border border-slate-300 px-3 py-1 text-sm"
          >
            +
          </button>
          <button
            type="button"
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
            className="rounded-lg border border-slate-300 px-3 py-1 text-sm disabled:opacity-40"
          >
            Zurück
          </button>
          <button
            type="button"
            disabled={!totalPages || currentPage >= totalPages}
            onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
            className="rounded-lg border border-slate-300 px-3 py-1 text-sm disabled:opacity-40"
          >
            Weiter
          </button>
        </div>
      </div>

      <div ref={containerRef} className="relative flex-1 overflow-auto bg-slate-100 p-4">
        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
        {loading && <p className="mb-3 text-sm text-slate-500">PDF wird geladen…</p>}
        <div className="relative mx-auto w-fit">
          <canvas ref={canvasRef} className="shadow-lg" />
          <div ref={overlayRef} className="pointer-events-none absolute left-0 top-0" />
        </div>
      </div>
    </div>
  )
}
