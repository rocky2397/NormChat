import { useState } from 'react'
import { submitFeedback } from '../api/client'

const RATINGS = [
  { value: 'good', label: 'Gut' },
  { value: 'mid', label: 'Mittel' },
  { value: 'bad', label: 'Schlecht' },
]

export default function FeedbackWidget({ projectId, question, answer, sources }) {
  const [rating, setRating] = useState(null)
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')

  async function handleRate(value) {
    if (submitting || submitted) return
    setRating(value)
    setShowComment(true)
    setError('')
  }

  async function handleSubmit() {
    if (!rating || submitting) return
    setSubmitting(true)
    setError('')
    try {
      await submitFeedback(projectId, {
        question,
        answer,
        sources,
        rating,
        comment: comment.trim() || null,
      })
      setSubmitted(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Feedback konnte nicht gesendet werden.')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return <p className="mt-3 text-xs text-slate-500">Danke für Ihr Feedback.</p>
  }

  return (
    <div className="mt-4 border-t border-slate-200 pt-3">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-slate-500">Wie war diese Antwort?</span>
        {RATINGS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => handleRate(value)}
            disabled={submitting}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
              rating === value
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-300 text-slate-600 hover:border-slate-500'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {showComment && (
        <div className="mt-2 space-y-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Kommentar (optional)"
            rows={2}
            disabled={submitting}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs outline-none focus:border-slate-500"
          />
          {error && <p className="text-xs text-red-600">{error}</p>}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {submitting ? 'Wird gesendet…' : 'Feedback senden'}
          </button>
        </div>
      )}
    </div>
  )
}
