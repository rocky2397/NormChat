import { Link } from 'react-router-dom'

export default function ProjectSidebar({
  projects,
  currentProjectId,
  documents,
  onDeleteDocument,
}) {
  return (
    <aside className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-4">
        <Link to="/" className="text-lg font-semibold text-slate-900">
          NormChat
        </Link>
        <p className="mt-1 text-xs text-slate-500">Normen durchsuchen, Quellen im PDF sehen</p>
      </div>

      <div className="border-b border-slate-200 px-4 py-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-800">Projekte</h3>
          <Link
            to="/"
            className="text-xs font-medium text-slate-600 hover:text-slate-900"
          >
            Übersicht
          </Link>
        </div>
        <div className="space-y-1">
          {projects.map((project) => (
            <Link
              key={project.id}
              to={`/projects/${project.id}`}
              className={`block rounded-lg px-3 py-2 text-sm transition ${
                project.id === currentProjectId
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-700 hover:bg-slate-100'
              }`}
            >
              <span className="font-medium">{project.name}</span>
              {project.bundesland && (
                <span
                  className={`mt-0.5 block text-xs ${
                    project.id === currentProjectId ? 'text-slate-300' : 'text-slate-500'
                  }`}
                >
                  {project.bundesland}
                </span>
              )}
            </Link>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">Dokumente</h3>
        {!documents.length ? (
          <p className="text-sm text-slate-500">Noch keine PDFs hochgeladen.</p>
        ) : (
          <ul className="space-y-2">
            {documents.map((document) => (
              <li
                key={document.id}
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <p className="font-medium text-slate-800">{document.filename}</p>
                <p className="text-xs text-slate-500">
                  {document.norm_reference || 'Norm'} · {document.page_count} Seiten ·{' '}
                  {document.chunk_count} Abschnitte
                </p>
                <button
                  type="button"
                  onClick={() => onDeleteDocument(document.id)}
                  className="mt-2 text-xs font-medium text-red-600 hover:text-red-700"
                >
                  Entfernen
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
