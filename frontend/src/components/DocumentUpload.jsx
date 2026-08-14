import { useCallback, useState } from 'react'

export default function DocumentUpload({ onUpload, disabled = false }) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')

  const handleFiles = useCallback(
    async (files) => {
      const pdfFiles = Array.from(files).filter((file) =>
        file.name.toLowerCase().endsWith('.pdf'),
      )
      if (!pdfFiles.length) {
        setError('Bitte nur PDF-Dateien hochladen.')
        return
      }

      setError('')
      setUploading(true)
      setProgress(0)
      try {
        // One request for the whole batch: the backend runs the
        // project-level reference-enrichment pass once per upload, not
        // once per file.
        await onUpload(pdfFiles, setProgress)
      } catch (err) {
        setError(err.response?.data?.detail || 'Upload fehlgeschlagen.')
      } finally {
        setUploading(false)
        setProgress(0)
      }
    },
    [onUpload],
  )

  return (
    <div className="space-y-2">
      <label
        className={`flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-6 text-center transition ${
          dragging
            ? 'border-slate-700 bg-slate-100'
            : 'border-slate-300 bg-white hover:border-slate-400'
        } ${disabled || uploading ? 'pointer-events-none opacity-60' : ''}`}
        onDragEnter={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={(e) => {
          e.preventDefault()
          setDragging(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          handleFiles(e.dataTransfer.files)
        }}
      >
        <span className="text-sm font-medium text-slate-700">
          PDF-Normen hier ablegen oder auswählen
        </span>
        <span className="mt-1 text-xs text-slate-500">
          DIN, LBO, Eurocode, ÖNORM
        </span>
        <input
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="hidden"
          disabled={disabled || uploading}
          onChange={(e) => {
            handleFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </label>

      {uploading && (
        <div className="space-y-1">
          <div className="h-2 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full bg-slate-800 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-xs text-slate-500">Verarbeitung läuft… {progress}%</p>
        </div>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}
