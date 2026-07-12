import { useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import PDFViewer from '../components/PDFViewer'

export default function PDFViewerPage() {
  const { documentId } = useParams()
  const [searchParams] = useSearchParams()
  const pageNumber = Number(searchParams.get('page')) || 1
  const highlightText = searchParams.get('text') || ''
  const filename = searchParams.get('filename') || ''

  useEffect(() => {
    if (filename) document.title = filename
  }, [filename])

  return (
    <div className="h-screen bg-slate-100 p-3">
      <PDFViewer
        documentId={documentId}
        filename={filename}
        pageNumber={pageNumber}
        highlightText={highlightText}
      />
    </div>
  )
}
