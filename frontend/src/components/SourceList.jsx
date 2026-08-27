import { useState } from 'react'
import SourceCard from './SourceCard'

// Collapsed by default: a single answer routinely cites a dozen or more
// passages, and expanded they pushed the answer itself off the screen. The
// count stays visible while collapsed so the reader can see how much evidence
// an answer rests on without opening anything.
export default function SourceList({ sources, onOpenSource }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setExpanded((previous) => !previous)}
        aria-expanded={expanded}
        className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500 transition hover:text-slate-800"
      >
        <span aria-hidden="true" className="text-[0.65rem]">
          {expanded ? '▼' : '▶'}
        </span>
        Quellen ({sources.length})
      </button>
      {expanded && (
        <div className="mt-3 space-y-3">
          {sources.map((source, sourceIndex) => (
            <SourceCard
              key={`${source.document_id}-${source.page_number}-${sourceIndex}`}
              source={source}
              onOpen={() => onOpenSource(sources, sourceIndex)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
