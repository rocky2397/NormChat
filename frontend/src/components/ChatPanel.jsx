import { useEffect, useRef, useState } from 'react'
import { sendChatMessage } from '../api/client'
import AnswerText from './AnswerText'
import SourceCard from './SourceCard'

export default function ChatPanel({ projectId, onOpenSource, disabled = false }) {
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)

  useEffect(() => {
    setMessages([])
    setQuestion('')
    setError('')
  }, [projectId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || loading || disabled) return

    setError('')
    setLoading(true)
    setMessages((prev) => [...prev, { role: 'user', content: trimmed }])
    setQuestion('')

    try {
      const response = await sendChatMessage(projectId, trimmed)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: response.answer,
          sources: response.sources,
        },
      ])
    } catch (err) {
      setError(err.response?.data?.detail || 'Anfrage fehlgeschlagen.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <h2 className="text-lg font-semibold text-slate-900">Norm-Assistent</h2>
        <p className="text-sm text-slate-500">
          Fragen Sie Ihre hochgeladenen Normen in natürlicher Sprache.
        </p>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {!messages.length && (
          <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
            Beispiel: „Welche Anforderungen gelten für Brandwände in Fluren
            gemäß DIN 4102?“
          </div>
        )}

        {messages.map((message, index) => (
          <div
            key={`${message.role}-${index}`}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                message.role === 'user'
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-50 text-slate-800'
              }`}
            >
              {message.role === 'assistant' ? (
                <AnswerText text={message.content} />
              ) : (
                <p className="whitespace-pre-wrap">{message.content}</p>
              )}
              {message.sources?.length > 0 && (
                <div className="mt-4 space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Quellen
                  </p>
                  {message.sources.map((source, sourceIndex) => (
                    <SourceCard
                      key={`${source.document_id}-${source.page_number}-${sourceIndex}`}
                      source={source}
                      onOpen={() => onOpenSource(message.sources, sourceIndex)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-500">
            Relevante Passagen werden gesucht…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className="border-t border-slate-200 p-4">
        {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
        <div className="flex gap-2">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Frage zur Norm stellen…"
            disabled={loading || disabled}
            className="flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-slate-500"
          />
          <button
            type="submit"
            disabled={loading || disabled || !question.trim()}
            className="rounded-xl bg-slate-900 px-4 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            Senden
          </button>
        </div>
      </form>
    </div>
  )
}
