import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import BUNDESLAENDER from '../constants'
import { createProject, deleteProject, listProjects } from '../api/client'

export default function ProjectList() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [bundesland, setBundesland] = useState('')
  const [error, setError] = useState('')

  async function loadProjects() {
    setLoading(true)
    try {
      const data = await listProjects()
      setProjects(data)
    } catch (err) {
      setError('Projekte konnten nicht geladen werden.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProjects()
  }, [])

  async function handleCreate(event) {
    event.preventDefault()
    if (!name.trim()) return

    setCreating(true)
    setError('')
    try {
      await createProject({
        name: name.trim(),
        bundesland: bundesland || null,
      })
      setName('')
      setBundesland('')
      await loadProjects()
    } catch (err) {
      setError(err.response?.data?.detail || 'Projekt konnte nicht erstellt werden.')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(projectId) {
    if (!window.confirm('Projekt und alle Dokumente wirklich löschen?')) return
    await deleteProject(projectId)
    await loadProjects()
  }

  return (
    <div className="mx-auto min-h-screen max-w-5xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900">NormChat</h1>
        <p className="mt-2 max-w-2xl text-slate-600">
          RAG-gestützte Normensuche für Bauingenieure. Laden Sie Ihre DIN-, LBO- und
          Eurocode-PDFs hoch und finden Sie die relevante Passage mit Quellenangabe.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Projekte</h2>
          {loading ? (
            <p className="mt-4 text-sm text-slate-500">Lade Projekte…</p>
          ) : !projects.length ? (
            <p className="mt-4 text-sm text-slate-500">
              Noch keine Projekte vorhanden. Erstellen Sie das erste Projekt rechts.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {projects.map((project) => (
                <li
                  key={project.id}
                  className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-4"
                >
                  <div>
                    <Link
                      to={`/projects/${project.id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {project.name}
                    </Link>
                    {project.bundesland && (
                      <p className="text-sm text-slate-500">{project.bundesland}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <Link
                      to={`/projects/${project.id}`}
                      className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white"
                    >
                      Öffnen
                    </Link>
                    <button
                      type="button"
                      onClick={() => handleDelete(project.id)}
                      className="text-sm text-red-600"
                    >
                      Löschen
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Neues Projekt</h2>
          <form onSubmit={handleCreate} className="mt-4 space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                Projektname
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="z. B. Klinik Neubau München"
                className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-slate-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                Bundesland (optional)
              </label>
              <select
                value={bundesland}
                onChange={(e) => setBundesland(e.target.value)}
                className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-slate-500"
              >
                <option value="">Kein Bundesland</option>
                {BUNDESLAENDER.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={creating || !name.trim()}
              className="w-full rounded-xl bg-slate-900 px-4 py-3 text-sm font-medium text-white disabled:bg-slate-400"
            >
              {creating ? 'Erstelle…' : 'Projekt anlegen'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
