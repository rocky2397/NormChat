function truncate(text, maxLength = 180) {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength).trim()}…`
}

export default function SourceCard({ source, onOpen }) {
  return (
    <div className="w-full rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-slate-400 hover:shadow">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">
            {source.norm_reference || source.filename}
          </p>
          <p className="text-xs text-slate-500">{source.filename}</p>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
          S. {source.page_number}
        </span>
      </div>
      <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-slate-700">
        {truncate(source.chunk_text)}
      </p>
      <button
        type="button"
        onClick={() => onOpen(source)}
        className="mt-3 text-xs font-medium text-slate-600 underline-offset-2 transition hover:text-slate-900 hover:underline"
      >
        Im PDF anzeigen →
      </button>
    </div>
  )
}
