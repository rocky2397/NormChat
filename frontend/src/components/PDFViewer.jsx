import { documentHighlightedUrl } from '../api/client'

export default function PDFViewer({ documentId, filename, pageNumber = 1, highlightText = '' }) {
  if (!documentId) {
    return (
      <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-sm text-slate-500">
        Wählen Sie eine Quelle aus, um das PDF anzuzeigen.
      </div>
    )
  }

  // The backend bakes a real highlight annotation into a temp copy of the
  // PDF (via PyMuPDF) and serves the full document; #page=N is the standard
  // PDF Open Parameters fragment Chromium's built-in PDF viewer honors for
  // jumping straight to the cited page, with its own zoom/search/print UI.
  const src = `${documentHighlightedUrl(documentId, pageNumber, highlightText)}#page=${pageNumber}`

  return (
    <div className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-3">
        <p className="truncate text-sm font-semibold text-slate-900">{filename}</p>
        <p className="text-xs text-slate-500">Seite {pageNumber}</p>
      </div>
      <iframe
        key={src}
        src={src}
        title={filename}
        className="min-h-0 flex-1 rounded-b-2xl"
      />
    </div>
  )
}
